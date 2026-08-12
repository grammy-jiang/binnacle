from __future__ import annotations

import grp
import pwd
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import setup_dev_pi, verify_git_credential_broker
from scripts.verify_git_credential_broker import (
    GitCredentialBrokerVerificationError,
    temporary_verification,
    verify_database,
    verify_paths,
)


def test_credential_units_freeze_a_separate_default_disabled_boundary(
    repo_root: Path,
) -> None:
    service = (repo_root / "deploy/systemd/binnacle-git-credential.service").read_text(
        encoding="utf-8"
    )
    socket = (repo_root / "deploy/systemd/binnacle-git-credential.socket").read_text(
        encoding="utf-8"
    )
    tmpfiles = (repo_root / "deploy/tmpfiles.d/binnacle-git-credential.conf").read_text(
        encoding="utf-8"
    )

    assert {
        "User=binnacle-git-credential",
        "Group=binnacle-git-credential",
        "SupplementaryGroups=binnacle-git-credential-client",
        "ExecStart=/usr/bin/false",
        "Restart=no",
        "ReadWritePaths=/run/binnacle-git-credential/private",
        "ReadWritePaths=/var/lib/binnacle-git-credential/state",
        "PrivateDevices=yes",
        "DevicePolicy=closed",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "ProtectProc=invisible",
        "RestrictAddressFamilies=AF_UNIX",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    } <= set(service.splitlines())
    assert "[Install]" not in service
    assert "/srv/binnacle-dev/repo" not in service
    assert "/var/lib/binnacle-executor" not in service
    assert "/var/lib/binnacle/" not in service

    assert {
        "ListenStream=/run/binnacle-git-credential/broker.sock",
        "Accept=no",
        "SocketUser=binnacle-git-credential",
        "SocketGroup=binnacle-git-credential-client",
        "SocketMode=0660",
        "DirectoryMode=0710",
        "RemoveOnStop=yes",
    } <= set(socket.splitlines())
    assert {
        "d /run/binnacle-git-credential 0710 root binnacle-git-credential-client -",
        "d /run/binnacle-git-credential/private 0700 "
        "binnacle-git-credential binnacle-git-credential -",
        "d /var/lib/binnacle-git-credential 0710 root binnacle-git-credential -",
        "d /var/lib/binnacle-git-credential/state 0700 "
        "binnacle-git-credential binnacle-git-credential -",
    } <= set(tmpfiles.splitlines())


def test_setup_declares_separate_credential_roots_and_assets() -> None:
    assert (
        (Path("/etc/binnacle-git-credential"), 0o750),
        (Path("/var/lib/binnacle-git-credential"), 0o710),
    ) == setup_dev_pi.GIT_CREDENTIAL_ROOT_PATHS
    assert (
        (Path("/var/lib/binnacle-git-credential/state"), 0o700),
    ) == setup_dev_pi.GIT_CREDENTIAL_STATE_PATHS
    assert (
        (Path("/run/binnacle-git-credential"), 0o710),
    ) == setup_dev_pi.GIT_CREDENTIAL_RUNTIME_ROOT_PATHS
    assert (
        (Path("/run/binnacle-git-credential/private"), 0o700),
    ) == setup_dev_pi.GIT_CREDENTIAL_RUNTIME_PRIVATE_PATHS
    assert all("/run/binnacle/" not in str(path) for path, _ in setup_dev_pi.SYSTEM_PATHS)


def test_temporary_credential_verifier_migrates_only_its_store(repo_root: Path) -> None:
    report = temporary_verification(repo_root)

    assert report.revision == "0001_credential_evidence"
    assert report.readiness == "disabled"
    assert report.evidence_generation == 0


def test_credential_verifier_rejects_broad_paths_wrong_name_and_live_authority(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "git-credential-evidence.sqlite3"
    _migrate_credential_database(database, repo_root)
    database.chmod(0o640)
    with pytest.raises(GitCredentialBrokerVerificationError, match="path is unsafe"):
        verify_database(database)

    database.chmod(0o600)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE credential_meta SET readiness='ready'")
    with pytest.raises(GitCredentialBrokerVerificationError, match="promoted"):
        verify_database(database)

    wrong_name = tmp_path / "wrong.sqlite3"
    database.replace(wrong_name)
    with pytest.raises(GitCredentialBrokerVerificationError, match="path is unsafe"):
        verify_database(wrong_name)


def test_credential_verifier_requires_exact_private_directory_modes(tmp_path: Path) -> None:
    state = tmp_path / "state"
    runtime = tmp_path / "runtime"
    state.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    database = state / "git-credential-evidence.sqlite3"
    database.touch(mode=0o600)
    verify_paths(database, runtime)

    runtime.chmod(0o750)
    with pytest.raises(GitCredentialBrokerVerificationError, match="ownership is unsafe"):
        verify_paths(database, runtime)


def test_credential_foundation_verifier_checks_private_default_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ObservedPath:
        def __init__(
            self,
            *,
            uid: int = 0,
            gid: int = 0,
            mode: int = 0,
            directory: bool = False,
            absent: bool = False,
            text: str = "",
        ) -> None:
            kind = stat.S_IFDIR if directory else stat.S_IFREG
            self.metadata = SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=kind | mode)
            self.absent = absent
            self.text = text

        def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
            assert not follow_symlinks
            return self.metadata

        def lstat(self) -> SimpleNamespace:
            if self.absent:
                raise FileNotFoundError
            return self.metadata

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return self.text

    credential_uid = 1302
    credential_gid = 1204
    client_gid = 1205
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_CONFIG_DIRECTORY",
        ObservedPath(uid=0, gid=credential_gid, mode=0o750, directory=True),
    )
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_PERSISTENT_ROOT",
        ObservedPath(uid=0, gid=credential_gid, mode=0o710, directory=True),
    )
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_STATE_DIRECTORY",
        ObservedPath(
            uid=credential_uid,
            gid=credential_gid,
            mode=0o700,
            directory=True,
        ),
    )
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_RUNTIME_ROOT",
        ObservedPath(uid=0, gid=client_gid, mode=0o710, directory=True),
    )
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_RUNTIME_PRIVATE",
        ObservedPath(
            uid=credential_uid,
            gid=credential_gid,
            mode=0o700,
            directory=True,
        ),
    )
    for name in ("_CONFIG_FILE", "_DATABASE", "_SOCKET"):
        monkeypatch.setattr(verify_git_credential_broker, name, ObservedPath(absent=True))
    monkeypatch.setattr(
        verify_git_credential_broker,
        "_TMPFILES",
        ObservedPath(
            uid=0,
            gid=0,
            mode=0o644,
            text=(
                "# Type Path Mode User Group Age Argument\n"
                "d /run/binnacle-git-credential 0710 root "
                "binnacle-git-credential-client -\n"
                "d /run/binnacle-git-credential/private 0700 "
                "binnacle-git-credential binnacle-git-credential -\n"
                "d /var/lib/binnacle-git-credential 0710 root "
                "binnacle-git-credential -\n"
                "d /var/lib/binnacle-git-credential/state 0700 "
                "binnacle-git-credential binnacle-git-credential -\n"
            ),
        ),
    )
    users = {
        "binnacle": pwd.struct_passwd(("binnacle", "x", 1300, 1200, "", "/", "/usr/sbin/nologin")),
        "binnacle-executor": pwd.struct_passwd(
            ("binnacle-executor", "x", 1301, 1202, "", "/", "/usr/sbin/nologin")
        ),
        "binnacle-git-credential": pwd.struct_passwd(
            (
                "binnacle-git-credential",
                "x",
                credential_uid,
                credential_gid,
                "",
                "/",
                "/usr/sbin/nologin",
            )
        ),
    }
    groups = {
        "binnacle-git-credential": grp.struct_group(
            ("binnacle-git-credential", "x", credential_gid, [])
        ),
        "binnacle-git-credential-client": grp.struct_group(
            (
                "binnacle-git-credential-client",
                "x",
                client_gid,
                ["binnacle-executor", "binnacle-git-credential"],
            )
        ),
    }
    monkeypatch.setattr(
        "scripts.verify_git_credential_broker.pwd.getpwnam",
        lambda name: users[name],
    )
    monkeypatch.setattr(
        "scripts.verify_git_credential_broker.grp.getgrnam",
        lambda name: groups[name],
    )
    monkeypatch.setattr("scripts.verify_git_credential_broker.os.geteuid", lambda: credential_uid)
    monkeypatch.setattr("scripts.verify_git_credential_broker.os.getegid", lambda: credential_gid)

    verify_git_credential_broker.verify_default_disabled_foundation()


def _migrate_credential_database(database: Path, repo_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(repo_root / "alembic-git-credential.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_git_credential"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")

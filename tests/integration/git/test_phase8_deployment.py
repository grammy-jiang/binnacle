from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from scripts import setup_dev_pi
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
    with sqlite3.connect(database) as connection:
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


def _migrate_credential_database(database: Path, repo_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(repo_root / "alembic-git-credential.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_git_credential"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")

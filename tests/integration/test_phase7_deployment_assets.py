"""Static and isolated checks for the default-disabled Phase 7 deployment."""

from __future__ import annotations

import grp
import os
import pwd
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from scripts import setup_dev_pi, verify_dev_pi
from scripts.verify_execution_supervisor import (
    ExecutorVerificationError,
    verify_executor_database,
)
from tests.phase7_support import migrate_executor_database


def test_executor_units_and_tmpfiles_freeze_the_disabled_boundary(repo_root: Path) -> None:
    service = (repo_root / "deploy/systemd/binnacle-executor.service").read_text(encoding="utf-8")
    socket = (repo_root / "deploy/systemd/binnacle-executor.socket").read_text(encoding="utf-8")
    tmpfiles = (repo_root / "deploy/tmpfiles.d/binnacle-executor.conf").read_text(encoding="utf-8")

    assert {
        "User=binnacle-executor",
        "Group=binnacle-executor",
        "SupplementaryGroups=binnacle-dev binnacle-executor-client",
        "PrivateDevices=yes",
        "DevicePolicy=closed",
        "ProtectProc=invisible",
        "RestrictAddressFamilies=AF_UNIX",
        "ReadWritePaths=/run/binnacle-executor/private",
        "ReadWritePaths=/var/lib/binnacle-executor/state",
        "ReadWritePaths=/var/lib/binnacle-executor/output",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    } <= set(service.splitlines())
    assert "ProcSubset=pid" not in service
    assert "[Install]" not in service
    assert {
        "ListenStream=/run/binnacle-executor/supervisor.sock",
        "Accept=no",
        "SocketUser=binnacle-executor",
        "SocketGroup=binnacle-executor-client",
        "SocketMode=0660",
        "DirectoryMode=0710",
        "RemoveOnStop=yes",
    } <= set(socket.splitlines())
    assert {
        "d /run/binnacle-executor 0710 root binnacle-executor-client -",
        "d /run/binnacle-executor/private 0700 binnacle-executor binnacle-executor -",
    } <= set(tmpfiles.splitlines())


def test_setup_grants_both_services_runtime_parent_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = setup_dev_pi.SetupPlan(
        checks=(setup_dev_pi.Check("repository", "pass", "reviewed"),),
        actions=("bounded",),
    )
    groups = {
        "binnacle": grp.struct_group(("binnacle", "x", 1200, [])),
        "binnacle-dev": grp.struct_group(("binnacle-dev", "x", 1201, [])),
        "binnacle-executor": grp.struct_group(("binnacle-executor", "x", 1202, [])),
        "binnacle-executor-client": grp.struct_group(("binnacle-executor-client", "x", 1203, [])),
    }
    users = {
        "binnacle": pwd.struct_passwd(("binnacle", "x", 1300, 1200, "", "/", "/usr/sbin/nologin")),
        "binnacle-executor": pwd.struct_passwd(
            ("binnacle-executor", "x", 1301, 1202, "", "/", "/usr/sbin/nologin")
        ),
    }
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(setup_dev_pi, "build_setup_plan", lambda _repo: plan)
    monkeypatch.setattr("scripts.setup_dev_pi.os.geteuid", lambda: 0)
    monkeypatch.setattr(setup_dev_pi, "_ensure_group", lambda _name: None)
    monkeypatch.setattr(setup_dev_pi, "_ensure_user", lambda _user, _group: None)
    monkeypatch.setattr("scripts.setup_dev_pi.grp.getgrnam", lambda name: groups[name])
    monkeypatch.setattr("scripts.setup_dev_pi.pwd.getpwnam", lambda name: users[name])
    monkeypatch.setattr(setup_dev_pi, "_ensure_protected_directory", lambda *_a, **_k: None)
    monkeypatch.setattr(setup_dev_pi, "_atomic_install", lambda *_a, **_k: None)

    def record(command: list[str], *, check: bool) -> None:
        assert check
        commands.append(tuple(command))

    monkeypatch.setattr("scripts.setup_dev_pi.subprocess.run", record)

    setup_dev_pi.apply_setup(tmp_path, enable=False)

    expected_groups = "binnacle-dev,binnacle-executor-client"
    assert ("usermod", "--append", "--groups", expected_groups, "binnacle") in commands
    assert (
        "usermod",
        "--append",
        "--groups",
        expected_groups,
        "binnacle-executor",
    ) in commands
    assert not any(command[:2] == ("systemctl", "enable") for command in commands)


@pytest.mark.parametrize("readiness", ("recovering", "integrity_failed"))
def test_executor_verifier_rejects_failure_or_incomplete_readiness(
    tmp_path: Path,
    repo_root: Path,
    readiness: str,
) -> None:
    database = tmp_path / "executor-state.sqlite3"
    migrate_executor_database(database, repo_root)
    database.chmod(0o600)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE executor_meta SET readiness=? WHERE id=1", (readiness,))

    with pytest.raises(ExecutorVerificationError, match="identity or integrity"):
        verify_executor_database(database)


def test_executor_verifier_rejects_broad_or_foreign_database_file(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "executor-state.sqlite3"
    migrate_executor_database(database, repo_root)
    database.chmod(0o640)

    with pytest.raises(ExecutorVerificationError, match="path is unsafe"):
        verify_executor_database(database)

    database.chmod(0o600)
    assert database.stat().st_uid == os.geteuid()
    assert verify_executor_database(database).readiness == "uninitialized"


def test_executor_migration_rejects_repository_relative_database(repo_root: Path) -> None:
    config = Config(repo_root / "alembic-executor.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_executor"))
    config.attributes["database_url"] = "sqlite:///executor-state.sqlite3"

    with pytest.raises(RuntimeError, match="absolute SQLite"):
        command.upgrade(config, "head")


def test_deployment_verifier_checks_effective_executor_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ObservedPath:
        def __init__(
            self,
            value: str,
            *,
            uid: int,
            gid: int,
            mode: int,
            directory: bool,
            text: str = "",
        ) -> None:
            self.value = value
            kind = stat.S_IFDIR if directory else stat.S_IFREG
            self.metadata = SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=kind | mode)
            self.text = text

        def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
            assert not follow_symlinks
            return self.metadata

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return self.text

        def __str__(self) -> str:
            return self.value

    executor_uid = 1301
    executor_gid = 1202
    client_gid = 1203
    directory_facts = {
        "EXECUTOR_PERSISTENT_ROOT": ("/var/lib/binnacle-executor", 0, executor_gid, 0o710),
        "EXECUTOR_STATE_DIRECTORY": (
            "/var/lib/binnacle-executor/state",
            executor_uid,
            executor_gid,
            0o700,
        ),
        "EXECUTOR_OUTPUT_DIRECTORY": (
            "/var/lib/binnacle-executor/output",
            executor_uid,
            executor_gid,
            0o700,
        ),
        "EXECUTOR_CONFIG_DIRECTORY": ("/etc/binnacle-executor", 0, executor_gid, 0o750),
        "EXECUTOR_RUNTIME_ROOT": ("/run/binnacle-executor", 0, client_gid, 0o710),
        "EXECUTOR_RUNTIME_PRIVATE": (
            "/run/binnacle-executor/private",
            executor_uid,
            executor_gid,
            0o700,
        ),
    }
    for name, (value, uid, gid, mode) in directory_facts.items():
        monkeypatch.setattr(
            verify_dev_pi,
            name,
            ObservedPath(value, uid=uid, gid=gid, mode=mode, directory=True),
        )
    monkeypatch.setattr(
        verify_dev_pi,
        "EXECUTOR_CONFIG_FILE",
        ObservedPath(
            "/etc/binnacle-executor/executor.toml",
            uid=0,
            gid=executor_gid,
            mode=0o640,
            directory=False,
        ),
    )
    monkeypatch.setattr(
        verify_dev_pi,
        "EXECUTOR_TMPFILES_PATH",
        ObservedPath(
            "/etc/tmpfiles.d/binnacle-executor.conf",
            uid=0,
            gid=0,
            mode=0o644,
            directory=False,
            text=(
                "# Type Path Mode User Group Age Argument\n"
                "d /run/binnacle-executor 0710 root binnacle-executor-client -\n"
                "d /run/binnacle-executor/private 0700 "
                "binnacle-executor binnacle-executor -\n"
            ),
        ),
    )
    monkeypatch.setattr(
        verify_dev_pi,
        "EXECUTOR_SOCKET_PATH",
        ObservedPath(
            "/run/binnacle-executor/supervisor.sock",
            uid=executor_uid,
            gid=client_gid,
            mode=0o660,
            directory=False,
        ),
    )
    users = {
        "binnacle": pwd.struct_passwd(("binnacle", "x", 1300, 1200, "", "/", "/usr/sbin/nologin")),
        "binnacle-executor": pwd.struct_passwd(
            ("binnacle-executor", "x", executor_uid, executor_gid, "", "/", "/usr/sbin/nologin")
        ),
    }
    groups = {
        "binnacle": grp.struct_group(("binnacle", "x", 1200, [])),
        "binnacle-executor": grp.struct_group(("binnacle-executor", "x", executor_gid, [])),
        "binnacle-executor-client": grp.struct_group(
            ("binnacle-executor-client", "x", client_gid, ["binnacle", "binnacle-executor"])
        ),
    }
    monkeypatch.setattr("scripts.verify_dev_pi.pwd.getpwnam", lambda name: users[name])
    monkeypatch.setattr("scripts.verify_dev_pi.grp.getgrnam", lambda name: groups[name])

    def properties(names: tuple[str, ...], *, service_name: str) -> dict[str, str]:
        if service_name == verify_dev_pi.EXECUTOR_SERVICE_NAME:
            values = {
                "ActiveState": "inactive",
                "UnitFileState": "static",
                "FragmentPath": "/etc/systemd/system/binnacle-executor.service",
                "DropInPaths": "",
                "User": "binnacle-executor",
                "Group": "binnacle-executor",
                "SupplementaryGroups": "binnacle-dev binnacle-executor-client",
                "ReadWritePaths": " ".join(
                    sorted(verify_dev_pi.EXPECTED_EXECUTOR_READ_WRITE_PATHS)
                ),
                "ProtectSystem": "strict",
                "NoNewPrivileges": "yes",
                "PrivateDevices": "yes",
                "DevicePolicy": "closed",
                "ProtectProc": "invisible",
                "ProcSubset": "all",
                "RestrictAddressFamilies": "AF_UNIX",
                "CapabilityBoundingSet": "",
                "AmbientCapabilities": "",
                "KillMode": "control-group",
                "SendSIGKILL": "yes",
                "Delegate": "no",
            }
        else:
            values = {
                "ActiveState": "inactive",
                "UnitFileState": "disabled",
                "FragmentPath": "/etc/systemd/system/binnacle-executor.socket",
                "DropInPaths": "",
                "Listen": "Stream=/run/binnacle-executor/supervisor.sock",
                "SocketUser": "binnacle-executor",
                "SocketGroup": "binnacle-executor-client",
                "SocketMode": "0660",
                "DirectoryMode": "0710",
                "RemoveOnStop": "yes",
            }
        assert set(names) == set(values)
        return values

    monkeypatch.setattr(verify_dev_pi, "_systemd_properties", properties)

    checks = verify_dev_pi._executor_foundation_checks()

    assert checks and all(check.status == "pass" for check in checks)

from __future__ import annotations

import grp
import os
import pwd
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from scripts import setup_dev_pi, verify_dev_pi

from binnacle.privileged_broker import verify_cli


def test_privileged_units_and_tmpfiles_freeze_root_boundary(repo_root: Path) -> None:
    service = (repo_root / "deploy/systemd/binnacle-privileged.service").read_text(encoding="utf-8")
    socket = (repo_root / "deploy/systemd/binnacle-privileged.socket").read_text(encoding="utf-8")
    tmpfiles = (repo_root / "deploy/tmpfiles.d/binnacle-privileged.conf").read_text(
        encoding="utf-8"
    )

    assert {
        "User=root",
        "Group=root",
        "WorkingDirectory=/var/empty",
        "ExecStart=/opt/binnacle-privileged/bin/binnacle-privileged-broker "
        "--config /etc/binnacle-privileged/broker.toml",
        "ConditionPathExists=/opt/binnacle-privileged/artifact-manifest.json",
        "ReadWritePaths=/run/binnacle-privileged",
        "ReadWritePaths=/var/lib/binnacle-privileged",
        "InaccessiblePaths=/srv/binnacle-dev/repo",
        "NoNewPrivileges=yes",
        "PrivateDevices=yes",
        "DevicePolicy=closed",
        "ProtectSystem=strict",
        "RestrictAddressFamilies=AF_UNIX",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    } <= set(service.splitlines())
    assert "PartOf=binnacle-dev.service" not in service
    assert {
        "ListenStream=/run/binnacle-privileged/broker.sock",
        "Accept=no",
        "SocketUser=root",
        "SocketGroup=binnacle-privileged-client",
        "SocketMode=0660",
        "DirectoryMode=0750",
        "RemoveOnStop=yes",
    } <= set(socket.splitlines())
    assert {
        "d /run/binnacle-privileged 0750 root binnacle-privileged-client -",
        "d /var/lib/binnacle-privileged 0700 root root -",
        "d /etc/binnacle-privileged 0700 root root -",
        "d /opt/binnacle-privileged 0755 root root -",
        "d /srv/binnacle-runtime 0750 root binnacle -",
        "d /srv/binnacle-runtime/slots 0750 root binnacle -",
        "d /srv/binnacle-runtime/.staging 0700 root root -",
    } <= set(tmpfiles.splitlines())


def test_setup_declares_separate_privileged_roots_and_assets(repo_root: Path) -> None:
    assert (
        (Path("/etc/binnacle-privileged"), 0o700),
        (Path("/var/lib/binnacle-privileged"), 0o700),
        (Path("/opt/binnacle-privileged"), 0o755),
    ) == setup_dev_pi.PRIVILEGED_ROOT_PATHS
    assert ((Path("/run/binnacle-privileged"), 0o750),) == setup_dev_pi.PRIVILEGED_RUNTIME_PATHS
    assert (
        (Path("/srv/binnacle-runtime"), 0o750),
        (Path("/srv/binnacle-runtime/slots"), 0o750),
    ) == setup_dev_pi.RUNTIME_SLOT_ROOT_PATHS
    assert ((Path("/srv/binnacle-runtime/.staging"), 0o700),) == (
        setup_dev_pi.RUNTIME_SLOT_PRIVATE_PATHS
    )
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'binnacle-privileged-broker = "binnacle.privileged_broker.__main__:main"' in pyproject


def _write(path: Path, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    path.chmod(mode)


def _install_foundation_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[pwd.struct_passwd, grp.struct_group, grp.struct_group]:
    config = tmp_path / "etc/binnacle-privileged"
    persistent = tmp_path / "var/lib/binnacle-privileged"
    runtime = tmp_path / "run/binnacle-privileged"
    install = tmp_path / "opt/binnacle-privileged"
    runtime_slots = tmp_path / "srv/binnacle-runtime"
    slot_directory = runtime_slots / "slots"
    slot_staging = runtime_slots / ".staging"
    for path, mode in (
        (config, 0o700),
        (persistent, 0o700),
        (runtime, 0o750),
        (install, 0o755),
        (runtime_slots, 0o750),
        (slot_directory, 0o750),
        (slot_staging, 0o700),
    ):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    original_stat = Path.stat
    root_owned_paths = (config, persistent, install, tmp_path / "etc/tmpfiles.d")

    def stat_with_runtime_group(
        path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        observed = original_stat(path, follow_symlinks=follow_symlinks)
        if path == runtime:
            fields = list(observed)
            fields[4] = 0
            fields[5] = 1202
            return os.stat_result(fields)
        if path in {runtime_slots, slot_directory}:
            fields = list(observed)
            fields[4] = 0
            fields[5] = 1201
            return os.stat_result(fields)
        if path == slot_staging:
            fields = list(observed)
            fields[4] = 0
            fields[5] = 0
            return os.stat_result(fields)
        if not any(path == root or path.is_relative_to(root) for root in root_owned_paths):
            return observed
        fields = list(observed)
        fields[4] = 0
        fields[5] = 0
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", stat_with_runtime_group)
    config_file = config / "broker.toml"
    database = persistent / "evidence.db"
    executable = install / "bin/binnacle-privileged-broker"
    verify_executable = install / "bin/binnacle-privileged-verify"
    artifact_manifest = install / "artifact-manifest.json"
    tmpfiles = tmp_path / "etc/tmpfiles.d/binnacle-privileged.conf"
    _write(config_file, 0o600)
    _write(database, 0o600)
    _write(executable, 0o755)
    _write(verify_executable, 0o755)
    _write(artifact_manifest, 0o644)
    _write(tmpfiles, 0o644)
    tmpfiles.write_text(
        "# Type Path Mode User Group Age Argument\n"
        "d /run/binnacle-privileged 0750 root binnacle-privileged-client -\n"
        "d /var/lib/binnacle-privileged 0700 root root -\n"
        "d /etc/binnacle-privileged 0700 root root -\n"
        "d /opt/binnacle-privileged 0755 root root -\n"
        "d /srv/binnacle-runtime 0750 root binnacle -\n"
        "d /srv/binnacle-runtime/slots 0750 root binnacle -\n"
        "d /srv/binnacle-runtime/.staging 0700 root root -\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_CONFIG_DIRECTORY", config)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_CONFIG_FILE", config_file)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_PERSISTENT_ROOT", persistent)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_DATABASE", database)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_RUNTIME_ROOT", runtime)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_SOCKET_PATH", runtime / "broker.sock")
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_INSTALL_ROOT", install)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_EXECUTABLE", executable)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_VERIFY_EXECUTABLE", verify_executable)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_ARTIFACT_MANIFEST", artifact_manifest)
    monkeypatch.setattr(verify_dev_pi, "PRIVILEGED_TMPFILES_PATH", tmpfiles)
    monkeypatch.setattr(verify_dev_pi, "RUNTIME_SLOT_ROOT", runtime_slots)
    monkeypatch.setattr(verify_dev_pi, "RUNTIME_SLOT_DIRECTORY", slot_directory)
    monkeypatch.setattr(verify_dev_pi, "RUNTIME_SLOT_STAGING", slot_staging)
    monkeypatch.setattr(
        verify_dev_pi,
        "EXPECTED_PRIVILEGED_READ_WRITE_PATHS",
        frozenset({str(runtime), str(persistent)}),
    )
    application = pwd.struct_passwd(("binnacle", "x", 1200, 1201, "", "/", "/bin/false"))
    application_group = grp.struct_group(("binnacle", "x", 1201, []))
    client_group = grp.struct_group(("binnacle-privileged-client", "x", 1202, ["binnacle"]))
    return application, application_group, client_group


def test_full_verifier_checks_default_disabled_privileged_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    application, application_group, client_group = _install_foundation_paths(monkeypatch, tmp_path)
    groups = {
        "binnacle": application_group,
        "binnacle-privileged-client": client_group,
    }
    monkeypatch.setattr("scripts.verify_dev_pi.pwd.getpwnam", lambda name: application)
    monkeypatch.setattr("scripts.verify_dev_pi.pwd.getpwall", lambda: [application])
    monkeypatch.setattr("scripts.verify_dev_pi.grp.getgrnam", lambda name: groups[name])
    monkeypatch.setattr("scripts.verify_dev_pi.grp.getgrall", lambda: list(groups.values()))

    def properties(_names: tuple[str, ...], *, service_name: str) -> dict[str, str]:
        if service_name == "binnacle-privileged.service":
            return {
                "ActiveState": "inactive",
                "UnitFileState": "static",
                "FragmentPath": "/etc/systemd/system/binnacle-privileged.service",
                "DropInPaths": "",
                "User": "root",
                "Group": "root",
                "SupplementaryGroups": "",
                "WorkingDirectory": "/var/empty",
                "ExecStart": f"{{ path={verify_dev_pi.PRIVILEGED_EXECUTABLE} ; argv[]=... "
                f"{verify_dev_pi.PRIVILEGED_CONFIG_FILE} }}",
                "ReadWritePaths": " ".join(verify_dev_pi.EXPECTED_PRIVILEGED_READ_WRITE_PATHS),
                "InaccessiblePaths": " ".join(verify_dev_pi.EXPECTED_PRIVILEGED_INACCESSIBLE_PATHS),
                "ProtectSystem": "strict",
                "NoNewPrivileges": "yes",
                "PrivateDevices": "yes",
                "DevicePolicy": "closed",
                "ProtectProc": "invisible",
                "RestrictAddressFamilies": "AF_UNIX",
                "CapabilityBoundingSet": "",
                "AmbientCapabilities": "",
                "KillMode": "control-group",
                "SendSIGKILL": "yes",
                "Delegate": "no",
            }
        return {
            "ActiveState": "inactive",
            "UnitFileState": "disabled",
            "FragmentPath": "/etc/systemd/system/binnacle-privileged.socket",
            "DropInPaths": "",
            "Listen": f"Stream={verify_dev_pi.PRIVILEGED_SOCKET_PATH}",
            "SocketUser": "root",
            "SocketGroup": "binnacle-privileged-client",
            "SocketMode": "0660",
            "DirectoryMode": "0750",
            "RemoveOnStop": "yes",
        }

    monkeypatch.setattr(verify_dev_pi, "_systemd_properties", properties)

    checks = {check.name: check for check in verify_dev_pi._privileged_foundation_checks()}

    assert checks["privileged-identities"].status == "pass"
    assert checks["privileged-roots"].status == "pass"
    assert checks["privileged-default-disabled"].status == "pass"

    rogue = pwd.struct_passwd(("rogue", "x", 1300, 1300, "", "/", "/bin/false"))
    contaminated = grp.struct_group(
        (client_group.gr_name, "x", client_group.gr_gid, ["binnacle", "rogue"])
    )
    groups["binnacle-privileged-client"] = contaminated
    monkeypatch.setattr("scripts.verify_dev_pi.pwd.getpwall", lambda: [application, rogue])
    monkeypatch.setattr("scripts.verify_dev_pi.grp.getgrall", lambda: list(groups.values()))

    contaminated_checks = {
        check.name: check for check in verify_dev_pi._privileged_foundation_checks()
    }
    assert contaminated_checks["privileged-identities"].status == "fail"


def test_installed_privileged_verifier_reads_exact_root_owned_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo_root: Path,
) -> None:
    state = tmp_path / "privileged-state"
    state.mkdir(mode=0o700)
    database = state / "evidence.db"
    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")
    database.chmod(0o600)
    original_lstat = Path.lstat

    def lstat_as_root(path: Path) -> os.stat_result:
        observed = original_lstat(path)
        if path not in {state, database}:
            return observed
        fields = list(observed)
        fields[4] = 0
        fields[5] = 0
        return os.stat_result(fields)

    monkeypatch.setattr(verify_cli, "_DATABASE_PATH", database)
    monkeypatch.setattr("binnacle.privileged_broker.verify_cli.os.geteuid", lambda: 0)
    monkeypatch.setattr("binnacle.privileged_broker.verify_cli.os.getegid", lambda: 0)
    monkeypatch.setattr(Path, "lstat", lstat_as_root)

    report = verify_cli.verify_installed_database(database)
    verify_cli.require_installed_default_disabled(report)

    assert report.readiness == "disabled"
    assert report.evidence_generation == 0

    database.chmod(0o640)
    with pytest.raises(verify_cli.InstalledPrivilegedVerificationError, match="unsafe"):
        verify_cli.verify_installed_database(database)

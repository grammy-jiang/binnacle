from pathlib import Path

from binnacle import deployment_platform
from binnacle.runtime_path_contracts import RuntimePaths
from binnacle.runtime_paths_linux import resolve_runtime_paths


def test_linux_runtime_paths_prefer_xdg_runtime_dir():
    paths = resolve_runtime_paths({"XDG_RUNTIME_DIR": "/tmp/g4-xdg"}, uid=999)

    assert paths == RuntimePaths(
        binnacle_runtime_dir=Path("/tmp/g4-xdg/binnacle"),
        jobs_socket=Path("/tmp/g4-xdg/binnacle/jobs.sock"),
    )


def test_linux_runtime_paths_fall_back_to_run_user_uid():
    paths = resolve_runtime_paths({}, uid=4242)

    assert paths == RuntimePaths(
        binnacle_runtime_dir=Path("/run/user/4242/binnacle"),
        jobs_socket=Path("/run/user/4242/binnacle/jobs.sock"),
    )


def test_linux_runtime_paths_do_not_mutate_supplied_environment():
    env = {"XDG_RUNTIME_DIR": "/run/custom", "KEEP": "yes"}
    before = dict(env)

    resolve_runtime_paths(env, uid=123)

    assert env == before


def test_default_platform_factory_selects_linux_runtime_paths(monkeypatch):
    expected = RuntimePaths(
        Path("/tmp/runtime/binnacle"), Path("/tmp/runtime/binnacle/jobs.sock")
    )
    monkeypatch.setattr(
        "binnacle.runtime_paths_linux.resolve_runtime_paths",
        lambda: expected,
    )

    assert deployment_platform.create_runtime_paths() == expected


def test_default_platform_factories_construct_linux_adapters(tmp_path):
    from binnacle.deployment_platform import (
        create_linux_provisioner,
        create_service_controller,
        create_service_inspector,
        create_service_log_source,
    )
    from binnacle.service_journal import JournalServiceLogSource
    from binnacle.service_provisioning_linux import LinuxServiceProvisioner
    from binnacle.service_systemd import SystemdUserServices

    log_source = create_service_log_source(command_timeout_s=12.5)
    assert isinstance(log_source, JournalServiceLogSource)
    assert log_source.command_timeout_s == 12.5

    assert isinstance(create_service_inspector(), SystemdUserServices)
    assert isinstance(create_service_controller(), SystemdUserServices)

    provisioner = create_linux_provisioner(
        unit_dir=tmp_path / "units",
        backup_dir=tmp_path / "backups",
    )
    assert isinstance(provisioner, LinuxServiceProvisioner)
    assert provisioner.unit_dir == tmp_path / "units"
    assert provisioner.backup_dir == tmp_path / "backups"

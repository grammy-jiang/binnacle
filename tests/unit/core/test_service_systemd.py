import subprocess

import pytest

from binnacle import service_systemd
from binnacle.service_lifecycle_contracts import ManagedServiceStatus
from binnacle.service_systemd import SystemdUserServices


def completed(argv, stdout="", rc=0):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")


@pytest.mark.parametrize(
    "state", ["active", "inactive", "failed", "activating", "deactivating"]
)
def test_status_preserves_exact_nonempty_state_and_properties(monkeypatch, state):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "is-active" in argv:
            return completed(argv, state + "\n", 0 if state == "active" else 3)
        return completed(argv, "MainPID=42\nNRestarts=3\n")

    monkeypatch.setattr(service_systemd.subprocess, "run", run)

    status = SystemdUserServices().status("demo.service")

    assert status == ManagedServiceStatus(state, main_pid=42, restart_count=3)
    assert calls[0] == ["systemctl", "--user", "is-active", "demo.service"]
    assert calls[1] == [
        "systemctl",
        "--user",
        "show",
        "demo.service",
        "-p",
        "MainPID",
        "-p",
        "NRestarts",
    ]


def test_status_uses_unknown_for_empty_state_and_none_for_invalid_values(monkeypatch):
    responses = iter(
        [
            completed([], "\n", 4),
            completed([], "MainPID=?\nNRestarts=n/a\n"),
        ]
    )
    monkeypatch.setattr(
        service_systemd.subprocess, "run", lambda *a, **k: next(responses)
    )

    assert SystemdUserServices().status("demo.service") == ManagedServiceStatus(
        "unknown", main_pid=None, restart_count=None
    )


def test_main_process_environment_queries_are_semantic(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    env = proc / "42" / "environ"
    env.parent.mkdir(parents=True)
    env.write_bytes(b"PATH=/usr/bin:/bin\0BINNACLE_MANAGED_DEPLOYMENT=1\0")
    monkeypatch.setattr(service_systemd, "_PROC_ROOT", proc)

    services = SystemdUserServices()
    monkeypatch.setattr(
        services,
        "status",
        lambda unit: ManagedServiceStatus("active", main_pid=42, restart_count=0),
    )

    assert services.main_process_path("demo.service") == "/usr/bin:/bin"
    assert (
        services.main_process_has_environment(
            "demo.service", "BINNACLE_MANAGED_DEPLOYMENT", "1"
        )
        is True
    )
    assert services.main_process_has_environment("demo.service", "OTHER", "x") is False


def test_main_process_environment_is_none_when_inactive_or_unreadable(
    tmp_path, monkeypatch
):
    proc = tmp_path / "proc"
    monkeypatch.setattr(service_systemd, "_PROC_ROOT", proc)
    services = SystemdUserServices()

    monkeypatch.setattr(
        services,
        "status",
        lambda unit: ManagedServiceStatus("inactive", main_pid=None, restart_count=0),
    )
    assert services.main_process_path("demo.service") is None

    monkeypatch.setattr(
        services,
        "status",
        lambda unit: ManagedServiceStatus("active", main_pid=99, restart_count=0),
    )
    assert services.main_process_path("demo.service") is None
    assert (
        services.main_process_has_environment(
            "demo.service", "BINNACLE_MANAGED_DEPLOYMENT", "1"
        )
        is None
    )


def test_rss_kb_keeps_current_cgroup_procfs_accounting(tmp_path, monkeypatch):
    cgroup = tmp_path / "cgroup"
    proc = tmp_path / "proc"
    scope = cgroup / "user.slice" / "demo.service"
    scope.mkdir(parents=True)
    (scope / "cgroup.procs").write_text("10\n11\n")
    for pid, rss in (("10", 123), ("11", 456)):
        status = proc / pid / "status"
        status.parent.mkdir(parents=True)
        status.write_text(f"Name: x\nVmRSS:\t{rss} kB\n")

    monkeypatch.setattr(service_systemd, "_CGROUP_FS", cgroup)
    monkeypatch.setattr(service_systemd, "_PROC_ROOT", proc)
    services = SystemdUserServices()
    monkeypatch.setattr(
        services, "_show_value", lambda service, prop, **kw: "/user.slice/demo.service"
    )

    assert services.rss_kb("demo.service") == 579.0


def test_started_at_epoch_keeps_systemd_timestamp_and_date_conversion(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return completed(argv, "1791240123.125\n")

    services = SystemdUserServices()
    monkeypatch.setattr(
        services,
        "_show_value",
        lambda service, prop, **kw: "Tue 2026-10-06 09:42:03.125000 AEDT",
    )
    monkeypatch.setattr(service_systemd.subprocess, "run", run)

    assert services.started_at_epoch("demo.service") == 1791240123.125
    assert calls == [
        (
            [
                "date",
                "-d",
                "Tue 2026-10-06 09:42:03.125000 AEDT",
                "+%s.%N",
            ],
            {
                "capture_output": True,
                "text": True,
                "check": False,
                "timeout": 10.0,
            },
        )
    ]

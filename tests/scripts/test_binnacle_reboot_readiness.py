"""Boot preparedness and reboot admission are separate read-only decisions."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from scripts import check_binnacle_reboot_readiness as probe


def make_plist(tmp_path, *, label="com.binnacle.mcp", **overrides):
    payload = {
        "Label": label,
        "ProgramArguments": ["/usr/bin/true"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "Umask": 0o077,
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    path = tmp_path / (label + ".plist")
    path.write_bytes(plistlib.dumps(payload))
    return path


def test_plist_boot_requirements_allow_existing_executable(tmp_path):
    path = make_plist(tmp_path)
    assert probe._mac_plist_ok(path, label="com.binnacle.mcp", expected_uid=os.getuid())


@pytest.mark.parametrize(
    "overrides",
    [
        {"Label": "com.other"},
        {"RunAtLoad": False},
        {"KeepAlive": False},
        {"Umask": None},
        {"Umask": 0o022},
        {"ProgramArguments": []},
        {"ProgramArguments": ["relative/python"]},
        {"ProgramArguments": ["/does/not/exist"]},
        {"ProgramArguments": [""]},
    ],
)
def test_plist_rejects_missing_safe_reboot_properties(tmp_path, overrides):
    path = make_plist(tmp_path, **overrides)
    assert not probe._mac_plist_ok(
        path, label="com.binnacle.mcp", expected_uid=os.getuid()
    )


def test_plist_refuses_unexpected_ownership_permissions_and_invalid_content(
    tmp_path,
):
    path = make_plist(tmp_path)
    assert not probe._mac_plist_ok(path, label="com.binnacle.mcp", expected_uid=-1)
    path.chmod(0o666)
    assert not probe._mac_plist_ok(
        path, label="com.binnacle.mcp", expected_uid=os.getuid()
    )
    path.chmod(0o600)
    path.write_text("not a plist")
    assert not probe._mac_plist_ok(
        path, label="com.binnacle.mcp", expected_uid=os.getuid()
    )
    path.unlink()
    assert not probe._mac_plist_ok(
        path, label="com.binnacle.mcp", expected_uid=os.getuid()
    )


def test_mac_boot_checks_require_all_five_services(monkeypatch, tmp_path):
    looked_up = []

    def has_plist(path, *, label):
        looked_up.append((path, label))
        return True

    def run(argv):
        return "state = running\n" if argv[0] == "/bin/launchctl" else None

    monkeypatch.setattr(probe, "_mac_plist_ok", has_plist)
    monkeypatch.setattr(probe, "_run", run)
    checks = probe._mac_boot_checks(root=tmp_path)
    assert len(checks) == 10
    assert all(checks.values())
    assert len(looked_up) == 5


def test_mac_missing_or_stopped_service_blocks_boot(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "_mac_plist_ok", lambda *a, **kw: True)
    monkeypatch.setattr(probe, "_run", lambda argv: None)
    assert not all(probe._mac_boot_checks(root=tmp_path).values())


def test_linux_requires_linger_and_one_watchdog_type(monkeypatch):
    seen = []

    def run(argv):
        seen.append(argv)
        if argv[0] == "loginctl":
            return "Linger=yes\n"
        if argv[0] == "systemctl":
            return "enabled\n" if argv[2] == "is-enabled" else "active\n"
        return None

    monkeypatch.setattr(probe, "_run", run)
    result = probe._linux_boot_checks()
    assert len(result) == 11
    assert all(result.values())
    assert not any("service-watchdog.service" in str(x) for x in seen)
    assert any("binnacle-watchdog.service" in str(x) for x in seen)


def test_linux_sextant_uses_service_watchdog(monkeypatch):
    def run(argv):
        if argv[0] == "loginctl":
            return "Linger=yes"
        if "binnacle-watchdog.service" in argv:
            return None
        return "enabled" if argv[2] == "is-enabled" else "active"

    monkeypatch.setattr(probe, "_run", run)
    checks = probe._linux_boot_checks()
    assert checks["service-watchdog.enabled"]
    assert checks["service-watchdog.active"]
    assert "watchdog.enabled" not in checks


def test_linux_bad_linger_and_inactive_service_block(monkeypatch):
    monkeypatch.setattr(probe, "_run", lambda argv: None)
    checks = probe._linux_boot_checks()
    assert not any(checks.values())


def test_dev_process_scan_uses_only_command_basename(monkeypatch):
    monkeypatch.setattr(
        probe,
        "_run",
        lambda argv: (
            "/usr/bin/python3\n/Users/user/.local/bin/claude\n"
            "codex\n/opt/app/pytest\n/usr/bin/sleep\n"
        ),
    )
    assert probe._developer_processes() == 3


def test_dev_process_scan_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(probe, "_run", lambda argv: None)
    assert probe._developer_processes() is None


@pytest.mark.parametrize("kind", [OSError, subprocess.TimeoutExpired])
def test_fixed_command_errors_are_unknown(monkeypatch, kind):
    def bad(*args, **kwargs):
        if kind is subprocess.TimeoutExpired:
            raise kind(args[0], 5)
        raise kind("unavailable")

    monkeypatch.setattr(probe.subprocess, "run", bad)
    assert probe._run(["ps", "-A", "-o", "comm="]) is None


def test_nonzero_exit_is_unverified(monkeypatch):
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "maybe", ""),
    )
    assert probe._run(["systemctl", "--user", "is-active", "unit"]) is None


def test_job_activity_calls_platform_resolver(monkeypatch, tmp_path):
    from binnacle import config
    from binnacle.companions import service_watchdog_safety

    seen = []
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(dir=tmp_path)),
    )
    monkeypatch.setattr(
        service_watchdog_safety,
        "current_job_activity",
        lambda root, host: seen.append((root, host)) or 2,
    )
    assert probe._job_activity("darwin") == 2
    assert seen == [(tmp_path, "darwin")]


def test_failed_job_activity_is_unknown(monkeypatch):
    from binnacle import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )
    assert probe._job_activity("linux") is None


@pytest.mark.parametrize(
    "activity,dev_processes,blockers",
    [
        (0, 0, ()),
        (1, 0, ("jobs_still_active",)),
        (None, 0, ("job_activity_unknown",)),
        (0, 1, ("other_development_processes_running",)),
        (0, None, ("developer_process_scan_unavailable",)),
        (4, 5, ("jobs_still_active", "other_development_processes_running")),
    ],
)
def test_reboot_admission_fails_closed(monkeypatch, activity, dev_processes, blockers):
    monkeypatch.setattr(probe, "_mac_boot_checks", lambda: {"mcp": True})
    monkeypatch.setattr(probe, "_job_activity", lambda host: activity)
    monkeypatch.setattr(probe, "_developer_processes", lambda: dev_processes)
    got = probe.inspect(system="Darwin")
    assert got.boot_ready is True
    assert got.blocker_reasons == blockers
    assert got.reboot_now_candidate is (not blockers)


def test_linux_static_boot_bad_even_when_no_jobs(monkeypatch):
    monkeypatch.setattr(probe, "_linux_boot_checks", lambda: {"lingering": False})
    monkeypatch.setattr(probe, "_job_activity", lambda host: 0)
    monkeypatch.setattr(probe, "_developer_processes", lambda: 0)
    result = probe.inspect(system="Linux")
    assert not result.boot_ready and not result.reboot_now_candidate


def test_unknown_host_not_promoted_to_automatic_reboot():
    report = probe.inspect(system="UnsupportedOS")
    assert not report.boot_ready
    assert "unknown_host" in report.blocker_reasons


def test_main_prints_json_and_exits_blocked(monkeypatch, capsys):
    monkeypatch.setattr(
        probe,
        "inspect",
        lambda: probe.Readiness("darwin", {"mcp": True}, ("jobs_still_active",)),
    )
    assert probe.main(["--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["boot_ready"]
    assert not report["reboot_now_candidate"]
    assert report["blocker_reasons"] == ["jobs_still_active"]
    assert "static" in report["warning"]


def test_main_readable_and_can_return_candidate(monkeypatch, capsys):
    monkeypatch.setattr(
        probe, "inspect", lambda: probe.Readiness("linux", {"boot": True}, ())
    )
    assert probe.main([]) == 0
    result = capsys.readouterr().out
    assert "boot_ready=True" in result
    assert "not a command to reboot" in result

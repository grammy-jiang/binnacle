"""Lifecycle-boundary checks used by the MCP mode restart gate."""

import subprocess

from binnacle import doctor_jobs


def fake_systemctl(state: str, pid: str = "42"):
    def run(*args: str, **kwargs):
        if args[:1] == ("is-active",):
            return subprocess.CompletedProcess(args, 0, state + "\n", "")
        if args[:2] == ("show", "mcp.service"):
            return subprocess.CompletedProcess(args, 0, pid + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    return run


def test_inactive_server_has_no_embedded_jobs_to_protect():
    assert doctor_jobs.server_uses_manager(
        "mcp.service", run=fake_systemctl("inactive"), environ=lambda pid: None
    )


def test_running_managed_server_is_detected_from_live_environment():
    assert doctor_jobs.server_uses_manager(
        "mcp.service",
        run=fake_systemctl("active"),
        environ=lambda pid: b"PATH=/bin\0BINNACLE_MANAGED_DEPLOYMENT=1\0",
    )


def test_old_running_server_stays_embedded_during_first_upgrade():
    assert not doctor_jobs.server_uses_manager(
        "mcp.service",
        run=fake_systemctl("active"),
        environ=lambda pid: b"PATH=/bin\0",
    )


def test_unreadable_or_invalid_main_pid_fails_safe():
    assert not doctor_jobs.server_uses_manager(
        "mcp.service", run=fake_systemctl("active", "?"), environ=lambda pid: b""
    )
    assert not doctor_jobs.server_uses_manager(
        "mcp.service", run=fake_systemctl("active"), environ=lambda pid: None
    )

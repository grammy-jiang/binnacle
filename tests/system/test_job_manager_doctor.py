"""Diagnostics for the durable command-owner service."""

import subprocess
from pathlib import Path

from binnacle import job_client
from binnacle.job_manager_doctor import check_job_manager


def fake_systemctl(state: str, restarts: str = "0"):
    def run(*args: str, **kwargs):
        if args[:1] == ("is-active",):
            return subprocess.CompletedProcess(args, 0, state + "\n", "")
        if args[:2] == ("show", "jobs.service") and "NRestarts" in args:
            return subprocess.CompletedProcess(args, 0, restarts + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    return run


def test_job_manager_active_socket_ok(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        run=fake_systemctl("active"),
        ping=lambda path: {
            "owner_instance_id": "abcdef1234567890",
            "package_version": "1.0.0",
            "revision": "abcdef123456",
        },
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "ok", "ok"]
    assert "owner=abcdef123456" in checks[-1].detail
    assert "package=1.0.0" in checks[-1].detail
    assert "revision=abcdef123456" in checks[-1].detail


def test_job_manager_missing_runtime_provenance_warns(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        run=fake_systemctl("active"),
        ping=lambda path: {
            "owner_instance_id": "abcdef1234567890",
            "package_version": "1.0.0",
        },
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "ok", "warn"]
    assert "revision=?" in checks[-1].detail
    assert "quiet moment" in checks[-1].hint


def test_job_manager_inactive_fails(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        run=fake_systemctl("inactive"),
    )
    assert active is None and checks[0].status == "fail"


def test_job_manager_restarts_warn_and_dead_socket_fails(tmp_path):
    def dead(path: Path):
        raise job_client.JobManagerError("connection refused")

    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        run=fake_systemctl("active", "2"),
        ping=dead,
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "warn", "fail"]

"""Diagnostics for the durable command-owner service."""

from pathlib import Path

from binnacle.diagnostics.job_manager_doctor import check_job_manager
from binnacle.features.commands import job_client
from binnacle.platform.contracts.service_lifecycle_contracts import ManagedServiceStatus
from tests.service_fakes import FakeServiceInspector


def inspector(state: str, restarts: int | None = 0) -> FakeServiceInspector:
    return FakeServiceInspector(
        statuses={
            "jobs.service": ManagedServiceStatus(
                state,
                main_pid=42 if state == "active" else None,
                restart_count=restarts,
            )
        }
    )


def test_job_manager_active_socket_ok(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        inspector=inspector("active"),
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


def test_job_manager_revision_mismatch_warns(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        inspector=inspector("active"),
        ping=lambda path: {
            "owner_instance_id": "abcdef1234567890",
            "package_version": "1.0.0",
            "revision": "oldrev123456",
        },
        expected_revision="newrev123456",
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "ok", "warn"]
    assert "revision=oldrev123456" in checks[-1].detail
    assert "differs from checkout newrev123456" in checks[-1].hint
    assert "only when no jobs are running" in checks[-1].hint


def test_job_manager_matching_revision_is_ok(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        inspector=inspector("active"),
        ping=lambda path: {
            "owner_instance_id": "abcdef1234567890",
            "package_version": "1.0.0",
            "revision": "same12345678",
        },
        expected_revision="same12345678",
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "ok", "ok"]


def test_job_manager_missing_runtime_provenance_warns(tmp_path):
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        inspector=inspector("active"),
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
        inspector=inspector("inactive"),
    )
    assert active is None and checks[0].status == "fail"


def test_job_manager_restarts_warn_and_dead_socket_fails(tmp_path):
    def dead(path: Path):
        raise job_client.JobManagerError("connection refused")

    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "jobs.sock",
        inspector=inspector("active", 2),
        ping=dead,
    )
    assert active == "jobs.service"
    assert [c.status for c in checks] == ["ok", "warn", "fail"]


def test_legacy_module_identity_and_ping_default():
    import importlib

    from binnacle.diagnostics import job_manager_doctor as owned

    assert importlib.import_module("binnacle.diagnostics.job_manager_doctor") is owned
    assert owned.check_job_manager.__defaults__[1] is job_client.ping

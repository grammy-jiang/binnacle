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


def test_darwin_doctor_uses_authenticated_platform_client(monkeypatch, tmp_path):
    from binnacle.platform import composition

    calls = []

    class Authenticated:
        def ping(self, path):
            calls.append(path)
            return {
                "owner_instance_id": "verified-owner",
                "package_version": "1.0.1",
                "revision": "r6w3",
                "unrecorded_exits": 3,
                "oldest_unrecorded_age_s": 8.5,
            }

    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    monkeypatch.setattr(composition, "create_job_client", Authenticated)
    sock = tmp_path / "manager.sock"
    checks, active = check_job_manager(
        "jobs.service",
        sock,
        inspector=inspector("active"),
        expected_revision="r6w3",
    )
    assert active == "jobs.service"
    assert calls == [sock]
    queued = [c for c in checks if "queued but not yet durable" in c.detail]
    assert len(queued) == 1 and queued[0].status == "warn"


def test_darwin_authenticated_ping_failure_returns_a_failing_check(
    monkeypatch, tmp_path
):
    from binnacle.platform import composition
    from binnacle.platform.darwin.job_manager_client import DarwinJobManagerError

    class Authenticated:
        def ping(self, path):
            raise DarwinJobManagerError("authentication failed")

    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    monkeypatch.setattr(composition, "create_job_client", Authenticated)
    checks, active = check_job_manager(
        "jobs.service",
        tmp_path / "manager.sock",
        inspector=inspector("active"),
    )
    assert active == "jobs.service"
    assert checks[-1].status == "fail"
    assert "not responding" in checks[-1].detail


def test_manager_reported_python_is_checked_even_with_healthy_frontend(tmp_path):
    checks, _ = check_job_manager(
        "jobs.service",
        tmp_path / "socket",
        inspector=inspector("active"),
        ping=lambda path: {
            "owner_instance_id": "owner",
            "package_version": "1.0.1",
            "revision": "abc",
            "manager_python_version": "3.12",
            "manager_waitid_available": False,
        },
        expected_revision="abc",
    )
    owner_python = [c for c in checks if c.group == "jobs-python"]
    assert len(owner_python) == 1 and owner_python[0].status == "fail"
    assert "3.12" in owner_python[0].detail


def test_manager_reported_supported_python_is_verified(tmp_path):
    checks, _ = check_job_manager(
        "jobs.service",
        tmp_path / "socket",
        inspector=inspector("active"),
        ping=lambda path: {
            "owner_instance_id": "owner",
            "package_version": "1.0.1",
            "revision": "abc",
            "manager_python_version": "3.13",
            "manager_waitid_available": True,
        },
        expected_revision="abc",
    )
    owner_python = [c for c in checks if c.group == "jobs-python"]
    assert len(owner_python) == 1 and owner_python[0].status == "ok"

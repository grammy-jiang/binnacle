"""Lifecycle-boundary checks used by the MCP mode restart gate."""

from binnacle import doctor_jobs
from binnacle.platform.contracts.service_lifecycle_contracts import ManagedServiceStatus
from tests.service_fakes import FakeServiceInspector


def inspector(
    state: str,
    *,
    pid: int | None = 42,
    managed: bool | None = None,
) -> FakeServiceInspector:
    return FakeServiceInspector(
        statuses={"mcp.service": ManagedServiceStatus(state, main_pid=pid)},
        environment_matches={
            ("mcp.service", "BINNACLE_MANAGED_DEPLOYMENT", "1"): managed
        },
    )


def test_inactive_server_has_no_embedded_jobs_to_protect():
    assert doctor_jobs.server_uses_manager(
        "mcp.service", inspector=inspector("inactive", managed=None)
    )


def test_running_managed_server_is_detected_from_live_environment():
    assert doctor_jobs.server_uses_manager(
        "mcp.service", inspector=inspector("active", managed=True)
    )


def test_old_running_server_stays_embedded_during_first_upgrade():
    assert not doctor_jobs.server_uses_manager(
        "mcp.service", inspector=inspector("active", managed=False)
    )


def test_unreadable_or_invalid_main_pid_fails_safe():
    assert not doctor_jobs.server_uses_manager(
        "mcp.service", inspector=inspector("active", pid=None, managed=None)
    )
    assert not doctor_jobs.server_uses_manager(
        "mcp.service", inspector=inspector("active", managed=None)
    )


def test_busy_reasons_with_no_jobs_and_no_calls_is_empty(tmp_path):
    assert (
        doctor_jobs.server_busy_reasons(
            "mcp.service", tmp_path / "missing", fetch=lambda unit, window: ""
        )
        == []
    )


def test_legacy_doctor_jobs_alias_preserves_default_reader_identity():
    import importlib

    from binnacle.diagnostics import doctor_jobs as owned

    assert doctor_jobs is owned
    assert importlib.import_module("binnacle.doctor_jobs") is owned
    assert importlib.import_module("binnacle.diagnostics.doctor_jobs") is owned
    assert (
        doctor_jobs.server_busy_reasons.__kwdefaults__["state_reader"]
        is doctor_jobs._job_state_safe
    )

"""Issue #30 advisory recovery decisions cannot enable real service operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from binnacle.platform.darwin.log_maintenance_recovery_policy import (
    RecoveryAssessment,
    RecoveryReadings,
    assess_recovery,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceTransactionJournal,
)
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    PRODUCER,
    TARGET,
    advance_to,
    begin,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def snapshot(root: Path, phase: str):
    with MaintenanceTransactionJournal(root) as tx:
        result = begin(tx)
        return result if phase == "intent" else advance_to(tx, phase)


def fully_matching(**overrides) -> RecoveryReadings:
    opts = {
        "authenticated": True,
        "target": TARGET,
        "producer_alive": True,
        "producer_pid": 230,
        "producer_generation": PRODUCER,
        "source_dev": 89,
        "source_ino": 901,
        "watchdog_paused": True,
        "guardian_ready": True,
        "mcp_inflight": 0,
        "jobs_running": 0,
        "jobs_unknown": 0,
        "source_writable_fds": 0,
    }
    opts.update(overrides)
    return RecoveryReadings(**cast(Any, opts))


def test_absent_or_corrupt_unknown_never_results_in_action() -> None:
    result = assess_recovery(None)
    assert result.status == "unverifiable"
    assert result.transaction_nonce is None
    assert result.risks == ("journal_missing_or_untrusted",)
    assert result.manual_review_required
    assert not result.production_authorized
    assert not result.autonomous_restart_allowed


def test_preadmission_phase_requires_manual_review_without_service_stop(
    root: Path,
) -> None:
    result = assess_recovery(snapshot(root, "intent"))
    assert result.status == "pre_stop_manual_review"
    assert result.risks == ("observation_not_authenticated",)
    assert result.production_authorized is False


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("j7_locked", "pre_stop_manual_review"),
        ("watchdog_acked", "pre_stop_manual_review"),
        ("mcp_drained", "pre_stop_manual_review"),
        ("jobs_drained", "pre_stop_manual_review"),
        ("guardian_armed", "possible_outage_manual_review"),
        ("producer_stopped", "possible_outage_manual_review"),
        ("writer_fds_closed", "possible_outage_manual_review"),
        ("canonical_verified", "possible_outage_manual_review"),
        ("raw_pruned", "possible_outage_manual_review"),
        ("producer_restored", "possible_outage_manual_review"),
        ("complete", "completion_record_manual_review"),
    ],
)
def test_all_phases_are_manual_only(tmp_path: Path, phase: str, expected: str) -> None:
    root = tmp_path / ("txn-" + NONCE)
    root.mkdir(mode=0o700)
    result = assess_recovery(snapshot(root, phase), fully_matching())
    assert result.status == expected
    assert result.manual_review_required
    assert not result.production_authorized
    assert not result.autonomous_restart_allowed
    if phase == "guardian_armed":
        assert "producer_may_be_offline" in result.risks
    if phase == "complete":
        assert "producer_may_be_offline" not in result.risks


def test_even_all_matching_authenticated_readings_cannot_authorize_recovery(
    root: Path,
) -> None:
    decision = assess_recovery(snapshot(root, "guardian_armed"), fully_matching())
    assert decision.status == "possible_outage_manual_review"
    assert decision.risks == (
        "journal_incomplete",
        "controller_terminated_before_completion",
        "producer_may_be_offline",
    )
    assert not decision.production_authorized
    assert not decision.autonomous_restart_allowed


@pytest.mark.parametrize(
    ("change", "must_contain"),
    [
        ({"producer_alive": False}, "producer_absent_observed"),
        ({"producer_pid": 231}, "producer_incarnation_changed"),
        ({"producer_generation": "d" * 32}, "producer_generation_changed"),
        ({"target": "system/com.binnacle.jobs"}, "producer_identity_unverifiable"),
        ({"producer_pid": None}, "producer_identity_unverifiable"),
        ({"producer_alive": None}, "producer_identity_unverifiable"),
        ({"producer_generation": None}, "producer_identity_unverifiable"),
        ({"source_dev": 123}, "source_inode_changed"),
        ({"source_ino": 123}, "source_inode_changed"),
        ({"source_dev": None}, "source_inode_unverifiable"),
        ({"source_ino": None}, "source_inode_unverifiable"),
        ({"watchdog_paused": False}, "watchdog_pause_unverified"),
        ({"watchdog_paused": None}, "watchdog_pause_unverified"),
        ({"guardian_ready": False}, "guardian_readiness_unverified"),
        ({"guardian_ready": None}, "guardian_readiness_unverified"),
        ({"mcp_inflight": 1}, "mcp_calls_active"),
        ({"mcp_inflight": None}, "mcp_activity_unverified"),
        ({"jobs_running": 3}, "jobs_running"),
        ({"jobs_running": None}, "jobs_activity_unverified"),
        ({"jobs_unknown": 1}, "jobs_unknown"),
        ({"jobs_unknown": None}, "jobs_activity_unverified"),
        ({"source_writable_fds": 1}, "source_writable_fds_open"),
        ({"source_writable_fds": None}, "source_writers_unverified"),
    ],
)
def test_incomplete_or_mismatched_readings_raise_manual_risks(
    tmp_path: Path, change: dict, must_contain: str
) -> None:
    root = tmp_path / ("txn-" + NONCE)
    root.mkdir(mode=0o700)
    report = assess_recovery(
        snapshot(root, "producer_stopped"), fully_matching(**change)
    )
    assert must_contain in report.risks
    assert report.production_authorized is False


@pytest.mark.parametrize(
    "replaced",
    [
        False,
        None,
    ],
)
def test_readings_without_authentication_are_never_positive_witness(
    root: Path, replaced: bool | None
) -> None:
    value = snapshot(root, "producer_stopped")
    report = assess_recovery(value, fully_matching(authenticated=replaced))
    assert report.risks[-1] == "observation_not_authenticated"
    assert not report.production_authorized


def test_combined_active_jobs_and_open_source_writers_report_distinct_risks(
    root: Path,
) -> None:
    value = snapshot(root, "raw_pruned")
    report = assess_recovery(
        value,
        fully_matching(
            jobs_running=1,
            jobs_unknown=2,
            source_writable_fds=3,
            mcp_inflight=1,
            guardian_ready=False,
        ),
    )
    assert "jobs_running" in report.risks
    assert "jobs_unknown" in report.risks
    assert "source_writable_fds_open" in report.risks
    assert "mcp_calls_active" in report.risks
    assert "guardian_readiness_unverified" in report.risks
    assert len(report.risks) == len(set(report.risks))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("producer_pid", 0),
        ("producer_pid", -5),
        ("producer_pid", True),
        ("producer_pid", "5"),
        ("source_dev", 0),
        ("source_ino", True),
        ("mcp_inflight", -1),
        ("mcp_inflight", True),
        ("jobs_running", -1),
        ("jobs_running", True),
        ("jobs_unknown", -1),
        ("jobs_unknown", False),
        ("source_writable_fds", -1),
        ("source_writable_fds", 3.5),
        ("producer_generation", "A" * 32),
        ("producer_generation", "not-a-token"),
        ("producer_generation", False),
        ("authenticated", "yes"),
        ("producer_alive", 1),
        ("guardian_ready", 1),
        ("watchdog_paused", "true"),
    ],
)
def test_malformed_readings_rejected_before_policy(field: str, bad: object) -> None:
    with pytest.raises(ValueError):
        fully_matching(**{field: bad})


def test_constructor_forbids_fake_permission_flags() -> None:
    for field, bad in (
        ("production_authorized", True),
        ("autonomous_restart_allowed", True),
        ("manual_review_required", False),
    ):
        with pytest.raises(ValueError, match="cannot authorize"):
            RecoveryAssessment(
                NONCE,
                "intent",
                "pre_stop_manual_review",
                ("observation_not_authenticated",),
                **{field: bad},
            )

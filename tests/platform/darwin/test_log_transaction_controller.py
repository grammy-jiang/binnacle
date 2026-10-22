"""Issue #30: the reusable coordinator drives actual isolated components.

No service control, real log or installed Mac file is used. All writers,
Jobs, watchdog and guardian processes belong to the disposable test root.
"""

from __future__ import annotations

import bz2
import sys
import time
from pathlib import Path

import pytest

from binnacle.companions.darwin_log_transaction_controller import (
    ControllerRefused,
    StepReceipt,
    run_maintenance_transaction,
)
from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceJournalRefused,
    MaintenanceTransactionJournal,
)
from tests.issue30_controller_real_components import (
    TestControllerExecutor as FixtureExecutor,
)
from tests.issue30_full_transaction_fixture import (
    _guardian_outcome,
    setup_fixture,
)

NONCE = "a" * 32
CTRL_GEN = "b" * 32
RAW = "mcp.stderr.log.0"


@pytest.fixture
def scenario(tmp_path: Path):
    if sys.platform != "linux":
        pytest.skip("real isolated controller writer/guardian uses Linux proc")
    root = tmp_path / ("issue30-fixture-e2e-" + NONCE)
    setup_fixture(root)
    executor = FixtureExecutor(root)
    try:
        yield root, executor
    finally:
        executor.close()


def run(scenario, **updates):
    root, executor = scenario
    args = {
        "j7_root": root / "j7-state",
        "watchdog_root": root / "watchdog",
        "journal": MaintenanceTransactionJournal(root / ("txn-" + NONCE)),
        "archive_root": root / "private-logs",
        "raw_name": RAW,
        "executor": executor,
        "nonce": NONCE,
        "controller_generation": CTRL_GEN,
        "min_free_bytes": 0,
    }
    args.update(updates)
    return run_maintenance_transaction(**args)


def snapshot(root: Path):
    return inspect_unowned_transaction(root / ("txn-" + NONCE))


def snapshot_when_fixture_lease_released(root: Path, *, timeout_s: float = 2):
    """Wait for a cooperative synthetic guardian to release its short lease.

    The real observer remains strictly nonblocking. Retry only its exact
    existing-owner refusal for a bounded period; a permanently held lease
    still fails, and no journal lock is broken or forcefully released.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return snapshot(root)
        except MaintenanceJournalRefused as exc:
            if str(exc) != "existing controller still owns the journal lease":
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def assert_no_archive_mutation(root: Path) -> None:
    raw = root / "private-logs" / RAW
    assert raw.read_bytes() == b"e2e-fixture-generation raw\n"
    assert not (root / "private-logs" / (RAW + ".bz2")).exists()


def test_complete_transaction_uses_real_components_and_durable_journal(
    scenario,
) -> None:
    root, actor = scenario
    result = run(scenario)
    assert result.phase == "complete"
    assert not result.production_authorized
    assert actor.writer.original is not None
    assert actor.writer.original.poll() == 0
    assert actor.writer.active is not None
    assert actor.writer.active.poll() is None
    assert not (root / "private-logs" / RAW).exists()
    assert bz2.decompress((root / "private-logs" / (RAW + ".bz2")).read_bytes()) == (
        b"e2e-fixture-generation raw\n"
    )
    # An independently running synthetic guardian can briefly hold the
    # journal lock even after the successful controller has returned.
    # Observe its completed, non-authorizing outcome before claiming an
    # unowned snapshot. This never changes the production nonblocking reader.
    assert _guardian_outcome(root) == "not-needed"
    report = snapshot_when_fixture_lease_released(root)
    assert report.phase == "complete"
    assert report.revision == 11
    assert len(report.receipts) == 11
    assert not report.production_authorized
    assert not report.producer_may_be_stopped
    assert actor.events.index("watchdog") < actor.events.index("mcp")
    assert actor.events.index("mcp") < actor.events.index("jobs")
    assert actor.events.index("jobs") < actor.events.index("guardian")
    assert actor.events.index("guardian") < actor.events.index("stop")
    assert actor.events.index("stop") < actor.events.index("fd")
    assert actor.events.index("fd") < actor.events.index("restore")
    assert actor.events.index("restore") < actor.events.index("mcp_resumed")
    assert actor.events.index("mcp_resumed") < actor.events.index("jobs_release")
    assert actor.gate.snapshot().pause_nonce is None
    accepted = actor.gate.admit()
    actor.gate.release(accepted)
    assert not (root / "manager-pause" / "request.json").exists()
    assert not (root / "watchdog" / "request.json").exists()


@pytest.mark.parametrize(
    ("stage", "phase"),
    [
        ("watchdog", "j7_locked"),
        ("mcp", "watchdog_acked"),
        ("jobs", "mcp_drained"),
        ("guardian", "jobs_drained"),
    ],
)
def test_prebootout_refusal_preserves_raw_and_old_writer(
    scenario, stage: str, phase: str
) -> None:
    root, actor = scenario
    actor.failure = stage
    with pytest.raises(RuntimeError, match="fixture rejected"):
        run(scenario)
    assert_no_archive_mutation(root)
    assert actor.writer.original is not None
    assert actor.writer.original.poll() is None
    assert actor.writer.active is None
    assert snapshot(root).phase == phase
    assert not (root / "watchdog" / "request.json").exists()


def test_unknown_bootout_leaves_independent_guardian_armed_without_duplicate(
    scenario,
) -> None:
    root, actor = scenario
    actor.failure = "stop"  # fails BEFORE the test-owned writer is stopped
    with pytest.raises(RuntimeError, match="fixture rejected step stop"):
        run(scenario)
    assert_no_archive_mutation(root)
    observed = snapshot_when_fixture_lease_released(root)
    assert observed.phase == "guardian_armed"
    assert observed.producer_may_be_stopped
    assert actor.writer.original is not None
    assert actor.writer.original.poll() is None
    assert actor.writer.active is None
    assert "restore" not in actor.events  # UNKNOWN != confirmed safe to start
    assert _guardian_outcome(root) == "original-still-live"


def test_unknown_stop_after_child_exits_does_not_adopt_old_journal(
    scenario,
) -> None:
    root, actor = scenario
    actor.failure = "stopped"  # after old worker exited, before stopped receipt
    with pytest.raises(RuntimeError, match="fixture rejected step stopped"):
        run(scenario)
    assert_no_archive_mutation(root)
    assert snapshot_when_fixture_lease_released(root).phase == "guardian_armed"
    assert "restore" not in actor.events
    assert _guardian_outcome(root) == "restarted"
    assert (root / "private-logs/mcp.stderr.log").is_file()


def test_failure_after_confirmed_stop_restores_writer_before_releasing_barriers(
    scenario,
) -> None:
    root, actor = scenario
    actor.failure = "fd"
    with pytest.raises(RuntimeError, match="fixture rejected step fd"):
        run(scenario)
    assert_no_archive_mutation(root)
    assert snapshot_when_fixture_lease_released(root).phase == "producer_stopped"
    assert actor.restored
    assert actor.writer.active is not None
    assert actor.writer.active.poll() is None
    assert actor.events.count("restore") == 1
    assert "jobs_release" in actor.events
    assert not (root / "watchdog/request.json").exists()


def test_restore_refusal_after_valid_prune_leaves_recovery_guardian(
    scenario,
) -> None:
    root, actor = scenario
    actor.failure = "restore"
    with pytest.raises(RuntimeError, match="fixture rejected step restore"):
        run(scenario)
    assert not (root / "private-logs" / RAW).exists()
    assert bz2.decompress((root / "private-logs" / (RAW + ".bz2")).read_bytes()) == (
        b"e2e-fixture-generation raw\n"
    )
    assert snapshot_when_fixture_lease_released(root).phase == "raw_pruned"
    assert actor.writer.active is None
    assert actor.events.count("restore") == 1  # no unsafe bootstrap retry
    assert _guardian_outcome(root) == "restarted"


def test_forged_untyped_mcp_drain_receipt_does_not_stop_writer(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    monkeypatch.setattr(
        actor,
        "fence_mcp",
        lambda nonce: StepReceipt(nonce, "f" * 64),
    )
    with pytest.raises(ControllerRefused, match="quiet-window"):
        run(scenario)
    assert snapshot(root).phase == "watchdog_acked"
    assert_no_archive_mutation(root)
    assert actor.writer.original is not None
    assert actor.writer.original.poll() is None


def test_forged_untyped_jobs_drain_receipt_does_not_stop_writer(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    monkeypatch.setattr(
        actor,
        "fence_jobs",
        lambda nonce: StepReceipt(nonce, "f" * 64),
    )
    with pytest.raises(ControllerRefused, match="quiet-window"):
        run(scenario)
    assert snapshot(root).phase == "mcp_drained"
    assert_no_archive_mutation(root)


@pytest.mark.parametrize(
    "changes",
    [
        {"nonce": "invalid"},
        {"nonce": "A" * 32},
        {"controller_generation": "invalid"},
        {"controller_generation": NONCE},
        {"raw_name": "/private/var/log/system.log"},
        {"min_free_bytes": -1},
        {"watchdog_timeout_s": 0},
        {"j7_root": Path("relative")},
    ],
)
def test_untrusted_control_input_never_enters_j7_or_modifies_log(
    scenario, changes: dict
) -> None:
    root, actor = scenario
    with pytest.raises(ControllerRefused):
        run(scenario, **changes)
    assert_no_archive_mutation(root)
    assert actor.writer.original is not None
    assert actor.writer.original.poll() is None
    assert actor.events == []


def test_new_source_generation_cannot_be_finalized_again(
    scenario,
) -> None:
    root, actor = scenario
    result = run(scenario)
    assert result.phase == "complete"
    with pytest.raises(FileNotFoundError):
        run(scenario)
    assert not (root / "private-logs" / RAW).exists()
    assert actor.writer.active is not None
    assert actor.writer.active.poll() is None


def test_lost_durable_restored_phase_ack_cannot_double_bootstrap(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    journal = MaintenanceTransactionJournal(root / ("txn-" + NONCE))
    actual_advance = journal.advance
    attempts = [0]

    def interrupted_receipt(**arguments):
        if arguments["phase"] == "producer_restored":
            attempts[0] += 1
            raise RuntimeError("synthetic journal directory fsync uncertainty")
        return actual_advance(**arguments)

    monkeypatch.setattr(journal, "advance", interrupted_receipt)
    with pytest.raises(RuntimeError, match="fsync uncertainty"):
        run(scenario, journal=journal)
    assert attempts == [1]
    assert actor.events.count("restore") == 1
    assert actor.events.count("mcp_resumed") == 1
    assert actor.writer.active is not None
    assert actor.writer.active.poll() is None
    assert actor.gate.snapshot().pause_nonce is None
    assert snapshot_when_fixture_lease_released(root).phase == "raw_pruned"
    assert not (root / "private-logs" / RAW).exists()
    assert not (root / "watchdog/request.json").exists()


def test_mcp_reopen_failure_holds_guardian_and_other_admission_barriers(
    scenario,
) -> None:
    root, actor = scenario
    actor.failure = "mcp_resumed"
    with pytest.raises(RuntimeError, match="fixture rejected step mcp_resumed"):
        run(scenario)
    assert actor.writer.active is not None
    assert actor.writer.active.poll() is None
    assert actor.events.count("restore") == 1
    assert actor.events.count("mcp_resumed") == 1
    observed = snapshot_when_fixture_lease_released(root)
    assert observed.phase == "raw_pruned"
    assert observed.needs_external_recovery
    assert not (root / "guardian-disarm").exists()
    assert (root / "manager-pause/request.json").exists()
    assert (root / "watchdog/request.json").exists()
    assert actor.gate.snapshot().pause_nonce == NONCE


def test_wrong_mcp_resumption_receipt_cannot_grant_complete(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario

    def forged_resume(nonce: str) -> StepReceipt:
        return StepReceipt("c" * 32, "f" * 64)

    monkeypatch.setattr(actor, "verify_mcp_resumed", forged_resume)
    with pytest.raises(ControllerRefused, match="unowned"):
        run(scenario)
    assert actor.events.count("restore") == 1
    # This fixture's guardian can briefly hold the journal after the
    # controller refuses; wait for an actual unowned observation, not a
    # controller lock bypass or a second inconsistent snapshot.
    observed = snapshot_when_fixture_lease_released(root)
    assert observed.phase == "raw_pruned"
    assert observed.production_authorized is False
    assert not (root / "guardian-disarm").exists()


def test_activity_in_mcp_prevents_any_bootout(
    scenario,
) -> None:
    root, actor = scenario
    ticket = actor.gate.admit()
    try:
        with pytest.raises(ControllerRefused, match="active or unknown"):
            run(scenario)
        assert snapshot(root).phase == "watchdog_acked"
        assert "stop" not in actor.events
        assert_no_archive_mutation(root)
    finally:
        actor.gate.release(ticket)


def test_running_job_prevents_writer_stop_under_private_manager_ack(
    scenario,
) -> None:
    from tests.platform.darwin.test_job_manager_maintenance_fence import _launch

    root, actor = scenario
    assert isinstance(_launch(actor.manager, root), str)
    with pytest.raises(ControllerRefused, match="active or unknown"):
        run(scenario)
    assert snapshot(root).phase == "mcp_drained"
    assert "stop" not in actor.events
    assert_no_archive_mutation(root)


def test_busy_j7_lock_refuses_without_stopping_writer(
    scenario,
) -> None:
    from binnacle.companions.darwin_log_j7_interlocks import (
        J7InterlockBusy,
        J7Interlocks,
    )

    root, actor = scenario
    with J7Interlocks(root / "j7-state") as blocker:
        blocker.verify()
        with pytest.raises(J7InterlockBusy):
            run(scenario)
    assert snapshot(root).phase == "intent"
    assert actor.events == []
    assert_no_archive_mutation(root)

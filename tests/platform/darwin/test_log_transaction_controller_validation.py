"""Issue #30 controller negative authority and journal refusal tests.

The same Linux-only disposable writer/guardian fixture is imported from the
main transaction suite. There are no installed launchd interactions.
"""

from __future__ import annotations

import pytest

from binnacle.companions.darwin_log_transaction_controller import (
    ControllerRefused,
    StepReceipt,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceTransactionJournal,
)
from tests.issue30_full_transaction_fixture import _guardian_outcome
from tests.platform.darwin import test_log_transaction_controller as base

# Re-export the shared fixture explicitly: pytest discovers module-level
# fixture objects, whereas Ruff correctly removes otherwise-unused imports.
scenario = base.scenario

from tests.platform.darwin.test_log_transaction_controller import (
    NONCE,
    RAW,
    assert_no_archive_mutation,
    run,
    snapshot,
)


def test_structural_evidence_validation_never_grants_write_or_restart_permission():
    from binnacle.companions.darwin_log_archive_finalize import FinalizedArchive
    from binnacle.companions.darwin_log_transaction_controller import (
        GuardianReceipt,
        ProducerPin,
        QuiescenceReceipt,
        TransactionResult,
    )

    with pytest.raises(ControllerRefused, match="pinned producer"):
        ProducerPin("system/com.binnacle.mcp", 0, "c" * 32, 2, 3)
    with pytest.raises(ControllerRefused, match="malformed"):
        StepReceipt(NONCE, "WRONG-CHECKSUM")
    with pytest.raises(ControllerRefused, match="guardian readiness"):
        GuardianReceipt(NONCE, "f" * 64, pid=0)
    with pytest.raises(ControllerRefused, match="active or unknown"):
        QuiescenceReceipt(NONCE, "f" * 64, in_flight=0, unknown=1)
    archive = FinalizedArchive(
        RAW, RAW + ".bz2", "system/com.binnacle.mcp", 1, "f" * 64, False
    )
    with pytest.raises(ValueError, match="never grants"):
        TransactionResult(NONCE, archive, "complete", production_authorized=True)
    with pytest.raises(ValueError, match="never grants"):
        TransactionResult(NONCE, archive, "raw_pruned")


def test_unexpected_unpinned_executor_identity_is_rejected_before_io(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    monkeypatch.setattr(actor, "pin", lambda: object())
    with pytest.raises(ControllerRefused, match="producer identity"):
        run(scenario)
    assert_no_archive_mutation(root)
    assert actor.events == []


def test_watchdog_ack_must_match_pinned_generation(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    monkeypatch.setattr(actor, "witness_watchdog", lambda nonce: 999999)
    with pytest.raises(ControllerRefused, match="watchdog incarnation"):
        run(scenario)
    assert snapshot(root).phase == "j7_locked"
    assert_no_archive_mutation(root)
    assert not (root / "watchdog/request.json").exists()


def test_false_ready_guardian_receipt_cannot_stop_writer(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    monkeypatch.setattr(
        actor, "arm_guardian", lambda nonce, producer: StepReceipt(nonce, "f" * 64)
    )
    with pytest.raises(ControllerRefused, match="guardian not ready"):
        run(scenario)
    assert snapshot(root).phase == "jobs_drained"
    assert_no_archive_mutation(root)
    assert actor.writer.original is not None and actor.writer.original.poll() is None


def test_journal_owner_mismatch_before_first_step_cannot_start_maintenance(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    root, actor = scenario
    journal = MaintenanceTransactionJournal(root / ("txn-" + NONCE))
    original = journal.begin

    def foreign_begin(**kw):
        return replace(original(**kw), target="system/com.binnacle.jobs")

    monkeypatch.setattr(journal, "begin", foreign_begin)
    with pytest.raises(ControllerRefused, match="journal owner changed"):
        run(scenario, journal=journal)
    assert snapshot(root).phase == "intent"
    assert_no_archive_mutation(root)
    assert actor.events == []


def test_journal_unacknowledged_phase_refuses_any_further_steps(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    root, actor = scenario
    journal = MaintenanceTransactionJournal(root / ("txn-" + NONCE))
    original = journal.advance

    def ambiguous(**kw):
        state = original(**kw)
        return replace(state, phase="intent")

    monkeypatch.setattr(journal, "advance", ambiguous)
    with pytest.raises(ControllerRefused, match="durable milestone"):
        run(scenario, journal=journal)
    assert snapshot(root).phase == "j7_locked"
    assert_no_archive_mutation(root)
    assert actor.events == []


def test_confirmed_stop_with_failed_immediate_restoration_keeps_guardian(
    scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, actor = scenario
    actor.failure = "restore"

    def abort_fd(_pin):
        raise RuntimeError("synthetic FD witness unexpectedly unavailable")

    monkeypatch.setattr(actor, "prove_writers_closed", abort_fd)
    with pytest.raises(RuntimeError, match="FD witness"):
        run(scenario)
    assert actor.events.count("restore") == 1
    assert snapshot(root).phase == "producer_stopped"
    assert_no_archive_mutation(root)
    assert _guardian_outcome(root) == "restarted"

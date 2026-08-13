"""Replacement-application routing for retained Phase 9 restart operations."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from tests.phase4_support import NOW, intent, owner
from tests.phase9_support import SHA_C, binding_snapshot

from binnacle.application.privileged_reconciliation import (
    PrivilegedRestartAuditClosure,
    PrivilegedRestartReconciler,
    PrivilegedRestartReconciliationError,
    RestartAcceptedAuditClosure,
    RestartNoAcceptAuditClosure,
)
from binnacle.domain.audit import AuditAppendResult, AuditTail
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    new_received_operation,
    transition,
)
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    BrokerServiceRestartOutcome,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
)
from binnacle.domain.privileged_restart import (
    PrivilegedOperationState,
    ServiceRestartAcceptedClosureRequest,
)
from binnacle.ports.audit import AuditJournal, AuditObligation, AuditObligationStore
from binnacle.ports.privileged import (
    PrivilegedApplicationRepository,
    PrivilegedBrokerPort,
    PrivilegedBrokerUnavailable,
)


def _operation() -> OperationSnapshot:
    return new_received_operation(
        owner=owner(),
        intent=intent(),
        operation_id="operation:fixture",
        now=NOW,
    )


def _authorised_operation() -> OperationSnapshot:
    received = _operation()
    return transition(
        received,
        TransitionRequest(
            expected_state_version=received.state_version,
            to_state=OperationState.AUTHORISED,
            effect_knowledge=EffectKnowledge.NONE,
            reason_code="policy_allowed",
            occurred_at=NOW,
        ),
    )


def _running_operation() -> OperationSnapshot:
    authorised = _authorised_operation()
    return transition(
        authorised,
        TransitionRequest(
            expected_state_version=authorised.state_version,
            to_state=OperationState.RUNNING,
            effect_knowledge=EffectKnowledge.NONE,
            reason_code="privileged_dispatch_committed",
            occurred_at=NOW,
        ),
    )


def _terminal_snapshot(
    outcome: BrokerRestartOutcome = BrokerRestartOutcome.CANDIDATE_READY,
) -> BrokerBindingSnapshot:
    accepted = binding_snapshot()
    selected = {
        BrokerRestartOutcome.CANDIDATE_READY: "candidate-slot",
        BrokerRestartOutcome.ROLLBACK_READY: "lkg-slot",
        BrokerRestartOutcome.NO_SUBEFFECT: None,
        BrokerRestartOutcome.FAILED: "lkg-slot",
    }[outcome]
    return replace(
        accepted,
        identity=replace(
            accepted.identity,
            action=PrivilegedAction.CONTROLLED_RESTART,
        ),
        evidence_generation=8,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=(
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            if outcome is BrokerRestartOutcome.NO_SUBEFFECT
            else PrivilegedEffectKnowledge.KNOWN_EFFECT
        ),
        result_evidence_sha256=SHA_C,
        accepted_at=NOW,
        closed_at=NOW,
        restart_checkpoint_sha256=SHA_C,
        restart_checkpoint_state=BrokerRestartCheckpointState.TERMINAL,
        restart_outcome=outcome,
        candidate_slot_id="candidate-slot",
        lkg_slot_id="lkg-slot",
        selected_runtime_slot_id=selected,
    )


def _terminal_service_snapshot(
    *,
    outcome: BrokerServiceRestartOutcome = BrokerServiceRestartOutcome.SERVICE_READY,
) -> BrokerBindingSnapshot:
    accepted = binding_snapshot()
    return replace(
        accepted,
        identity=replace(
            accepted.identity,
            action=PrivilegedAction.SERVICE_RESTART,
        ),
        evidence_generation=3,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=(
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            if outcome is BrokerServiceRestartOutcome.NO_SUBEFFECT
            else PrivilegedEffectKnowledge.KNOWN_EFFECT
        ),
        result_evidence_sha256=SHA_C,
        accepted_at=NOW,
        closed_at=NOW,
        service_restart_outcome=outcome,
        service_readiness_evidence_sha256=(
            None if outcome is BrokerServiceRestartOutcome.NO_SUBEFFECT else SHA_C
        ),
    )


def _dependencies(
    *,
    retained: bool = True,
    retained_state: PrivilegedOperationState = PrivilegedOperationState.DISPATCHED,
    snapshot: BrokerBindingSnapshot | None = None,
    broker_error: Exception | None = None,
    promotion_error: Exception | None = None,
    audit_closure: RestartNoAcceptAuditClosure | None = None,
    accepted_audit_closure: RestartAcceptedAuditClosure | None = None,
) -> tuple[
    PrivilegedRestartReconciler,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    record_snapshot = AsyncMock()
    close_before_dispatch = AsyncMock()
    close_no_accept = AsyncMock()
    close_accepted = AsyncMock()
    repository = cast(
        PrivilegedApplicationRepository,
        SimpleNamespace(
            get_restart=AsyncMock(
                return_value=(
                    SimpleNamespace(
                        operation_id="operation:fixture",
                        state=retained_state,
                        broker_acceptance_state=BrokerAcceptanceState.UNRESOLVED,
                    )
                    if retained
                    else None
                )
            ),
            record_broker_snapshot=record_snapshot,
            close_restart_before_dispatch=close_before_dispatch,
            close_restart_no_accept=close_no_accept,
            close_restart_accepted=close_accepted,
            close_service_restart_accepted=close_accepted,
        ),
    )
    broker_get = AsyncMock(return_value=snapshot)
    if broker_error is not None:
        broker_get.side_effect = broker_error
    promoted_snapshot = (
        replace(
            snapshot,
            lkg_promotion_audit_sha256=SHA_C,
            lkg_promotion_evidence_sha256=SHA_C,
            lkg_promoted_at=NOW,
        )
        if snapshot is not None and snapshot.restart_outcome is BrokerRestartOutcome.CANDIDATE_READY
        else snapshot
    )
    promote_lkg = AsyncMock(return_value=promoted_snapshot)
    if promotion_error is not None:
        promote_lkg.side_effect = promotion_error
    broker = cast(
        PrivilegedBrokerPort,
        SimpleNamespace(get=broker_get, promote_restart_lkg=promote_lkg),
    )
    return (
        PrivilegedRestartReconciler(
            repository=repository,
            broker=broker,
            no_accept_audit_closure=audit_closure,
            accepted_audit_closure=accepted_audit_closure,
            clock=lambda: NOW,
        ),
        record_snapshot,
        broker_get,
        close_before_dispatch,
        close_no_accept,
        close_accepted,
    )


@pytest.mark.anyio
async def test_non_privileged_operation_falls_through_to_other_reconcilers() -> None:
    reconciler, record, broker_get, close_before, close_no_accept, close_accepted = _dependencies(
        retained=False
    )

    assert await reconciler.reconcile(_operation()) is None
    broker_get.assert_not_awaited()
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()
    close_accepted.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_or_unavailable_broker_keeps_restart_recovery_closed() -> None:
    operation = _running_operation()
    missing, missing_record, _, missing_before, missing_close, missing_accepted = _dependencies(
        snapshot=None
    )
    (
        unavailable,
        unavailable_record,
        _,
        unavailable_before,
        unavailable_close,
        unavailable_accepted,
    ) = _dependencies(broker_error=PrivilegedBrokerUnavailable("broker unavailable"))

    assert await missing.reconcile(operation) is operation
    assert await unavailable.reconcile(operation) is operation
    missing_record.assert_not_awaited()
    unavailable_record.assert_not_awaited()
    missing_before.assert_not_awaited()
    unavailable_before.assert_not_awaited()
    missing_close.assert_not_awaited()
    unavailable_close.assert_not_awaited()
    missing_accepted.assert_not_awaited()
    unavailable_accepted.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "broker_error",
    (None, PrivilegedBrokerUnavailable("broker unavailable")),
)
async def test_pre_dispatch_restart_closes_without_broker_evidence(
    broker_error: Exception | None,
) -> None:
    operation = _authorised_operation()
    closed_operation = transition(
        operation,
        TransitionRequest(
            expected_state_version=operation.state_version,
            to_state=OperationState.FAILED,
            effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
            reason_code="restart_before_dispatch",
            error=OperationError(
                "reconciliation_unavailable",
                "Authorised operation did not reach the durable dispatch marker.",
            ),
            occurred_at=NOW,
        ),
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=None,
        broker_error=broker_error,
        retained_state=PrivilegedOperationState.PREPARED,
    )
    close_before.return_value = (closed_operation, object(), object())

    assert await reconciler.reconcile(operation) is closed_operation
    close_before.assert_awaited_once_with(operation.operation_id, closed_at=NOW)
    record.assert_not_awaited()
    close_no_accept.assert_not_awaited()
    close_accepted.assert_not_awaited()


@pytest.mark.anyio
async def test_exact_accepted_snapshot_is_recorded_without_generic_closure() -> None:
    operation = _running_operation()
    snapshot = binding_snapshot()
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=snapshot
    )

    assert await reconciler.reconcile(operation) is operation
    record.assert_awaited_once_with(snapshot, reconciled_at=NOW)
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()
    close_accepted.assert_not_awaited()
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_no_accept_snapshot_waits_for_atomic_terminal_closure() -> None:
    operation = _running_operation()
    accepted = binding_snapshot()
    sealed = replace(
        accepted,
        acceptance_state=BrokerAcceptanceState.SEALED_NO_ACCEPT,
        acceptance_evidence_sha256=SHA_C,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT,
        result_evidence_sha256=SHA_C,
        accepted_at=None,
        sealed_at=NOW,
        closed_at=NOW,
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=sealed
    )

    assert await reconciler.reconcile(operation) is operation
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()
    close_accepted.assert_not_awaited()


@pytest.mark.anyio
async def test_no_accept_snapshot_closes_only_after_durable_audit_evidence() -> None:
    operation = _running_operation()
    accepted = binding_snapshot()
    sealed = replace(
        accepted,
        acceptance_state=BrokerAcceptanceState.SEALED_NO_ACCEPT,
        acceptance_evidence_sha256=SHA_C,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT,
        result_evidence_sha256=SHA_C,
        accepted_at=None,
        sealed_at=NOW,
        closed_at=NOW,
    )
    closed_operation = replace(
        operation,
        state=operation.state,
    )
    audit_record = AsyncMock(return_value=SHA_C)
    audit_closure = cast(
        RestartNoAcceptAuditClosure,
        SimpleNamespace(record_no_accept=audit_record),
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=sealed,
        audit_closure=audit_closure,
    )
    close_no_accept.return_value = (closed_operation, object(), object())

    assert await reconciler.reconcile(operation) is closed_operation
    audit_record.assert_awaited_once_with(operation, sealed)
    assert close_no_accept.await_args is not None
    request = close_no_accept.await_args.args[0]
    assert request.snapshot is sealed
    assert request.audit_closure_evidence_sha256 == SHA_C
    assert request.closed_at == NOW
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_accepted.assert_not_awaited()


@pytest.mark.anyio
async def test_accepted_terminal_snapshot_closes_only_after_exact_audit_evidence() -> None:
    operation = _running_operation()
    terminal = _terminal_snapshot()
    closed_operation = replace(operation, state=operation.state)
    audit_record = AsyncMock(return_value=SHA_C)
    audit_closure = cast(
        RestartAcceptedAuditClosure,
        SimpleNamespace(record_accepted=audit_record),
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=terminal,
        accepted_audit_closure=audit_closure,
    )
    close_accepted.return_value = (closed_operation, object(), object())

    assert await reconciler.reconcile(operation) is closed_operation
    audit_record.assert_awaited_once_with(operation, terminal)
    assert close_accepted.await_args is not None
    request = close_accepted.await_args.args[0]
    assert request.snapshot is not terminal
    assert request.snapshot.lkg_promotion_audit_sha256 == SHA_C
    assert request.snapshot.lkg_promotion_evidence_sha256 == SHA_C
    assert request.snapshot.lkg_promoted_at == NOW
    assert request.audit_closure_evidence_sha256 == SHA_C
    assert request.closed_at == NOW
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()


@pytest.mark.anyio
async def test_accepted_service_restart_uses_checkpoint_free_terminal_closure() -> None:
    operation = _running_operation()
    terminal = _terminal_service_snapshot()
    closed_operation = replace(operation, state=operation.state)
    audit_record = AsyncMock(return_value=SHA_C)
    audit_closure = cast(
        RestartAcceptedAuditClosure,
        SimpleNamespace(record_accepted=audit_record),
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=terminal,
        accepted_audit_closure=audit_closure,
    )
    close_accepted.return_value = (closed_operation, object(), object())

    assert await reconciler.reconcile(operation) is closed_operation
    audit_record.assert_awaited_once_with(operation, terminal)
    assert close_accepted.await_args is not None
    request = close_accepted.await_args.args[0]
    assert isinstance(request, ServiceRestartAcceptedClosureRequest)
    assert request.snapshot is terminal
    assert request.audit_closure_evidence_sha256 == SHA_C
    assert request.closed_at == NOW
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()


@pytest.mark.anyio
async def test_candidate_ready_keeps_authority_closed_when_promotion_is_unavailable() -> None:
    operation = _running_operation()
    terminal = _terminal_snapshot()
    audit_record = AsyncMock(return_value=SHA_C)
    audit_closure = cast(
        RestartAcceptedAuditClosure,
        SimpleNamespace(record_accepted=audit_record),
    )
    reconciler, record, _, close_before, close_no_accept, close_accepted = _dependencies(
        snapshot=terminal,
        promotion_error=PrivilegedBrokerUnavailable("promotion unavailable"),
        accepted_audit_closure=audit_closure,
    )

    assert await reconciler.reconcile(operation) is operation
    audit_record.assert_awaited_once_with(operation, terminal)
    record.assert_not_awaited()
    close_before.assert_not_awaited()
    close_no_accept.assert_not_awaited()
    close_accepted.assert_not_awaited()


@pytest.mark.anyio
async def test_rollback_ready_closes_without_lkg_promotion() -> None:
    operation = _running_operation()
    terminal = _terminal_snapshot(BrokerRestartOutcome.ROLLBACK_READY)
    closed_operation = replace(operation, state=operation.state)
    audit_record = AsyncMock(return_value=SHA_C)
    audit_closure = cast(
        RestartAcceptedAuditClosure,
        SimpleNamespace(record_accepted=audit_record),
    )
    reconciler, _, _, _, _, close_accepted = _dependencies(
        snapshot=terminal,
        promotion_error=AssertionError("rollback must not promote"),
        accepted_audit_closure=audit_closure,
    )
    close_accepted.return_value = (closed_operation, object(), object())

    assert await reconciler.reconcile(operation) is closed_operation
    assert close_accepted.await_args is not None
    assert close_accepted.await_args.args[0].snapshot is terminal


@pytest.mark.anyio
async def test_audit_closure_appends_then_reuses_exact_terminal_evidence() -> None:
    operation = _running_operation()
    snapshot = _terminal_snapshot()
    append = AsyncMock(
        return_value=AuditAppendResult(
            sequence=2,
            event_hash=SHA_C,
            canonical_bytes=b"audit-fixture",
        )
    )
    find = AsyncMock(return_value=None)
    emergency = AsyncMock()
    journal = cast(
        AuditJournal,
        SimpleNamespace(
            tail=AuditTail(2, SHA_C),
            append=append,
            append_emergency=emergency,
            find_operation_state_evidence=find,
        ),
    )
    scan = AsyncMock(return_value=())
    obligations = cast(AuditObligationStore, SimpleNamespace(scan=scan))
    update_tail = AsyncMock()
    latch = AsyncMock()
    closure = PrivilegedRestartAuditClosure(
        audit=journal,
        obligations=obligations,
        store=SimpleNamespace(
            update_audit_tail_cache=update_tail,
            latch_audit_failure=latch,
        ),
        closure_health=AsyncMock(return_value=True),
        clock=lambda: NOW,
        monotonic_ns=lambda: 123,
    )

    assert await closure.record_accepted(operation, snapshot) == SHA_C
    assert append.await_args is not None
    draft = append.await_args.args[0]
    assert draft.payload == {
        "kind": "operation.state_changed",
        "old_state": "running",
        "new_state": "succeeded",
        "state_version": operation.state_version + 1,
        "effect_knowledge": "known_effect",
        "result_digest": SHA_C,
        "reason_code": "privileged_candidate_ready",
    }
    assert {item["name"] for item in draft.safe_facts} == {
        "privileged_ticket_sha256",
        "broker_acceptance_evidence_sha256",
        "restart_checkpoint_sha256",
        "restart_outcome",
        "selected_runtime_slot_id",
        "service_restart_outcome",
        "service_readiness_evidence_sha256",
    }
    update_tail.assert_awaited_once_with(AuditTail(2, SHA_C))
    emergency.assert_not_awaited()
    latch.assert_not_awaited()

    find.return_value = SHA_C
    assert await closure.record_accepted(operation, snapshot) == SHA_C
    append.assert_awaited_once()
    assert update_tail.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcome", "new_state", "effect_knowledge", "reason_code"),
    (
        (
            BrokerServiceRestartOutcome.SERVICE_READY,
            "succeeded",
            "known_effect",
            "privileged_service_ready",
        ),
        (
            BrokerServiceRestartOutcome.NO_SUBEFFECT,
            "failed",
            "known_no_effect",
            "privileged_effect_not_started",
        ),
        (
            BrokerServiceRestartOutcome.FAILED,
            "failed",
            "known_effect",
            "privileged_service_restart_failed",
        ),
    ),
)
async def test_audit_closure_records_terminal_service_restart_without_checkpoint(
    outcome: BrokerServiceRestartOutcome,
    new_state: str,
    effect_knowledge: str,
    reason_code: str,
) -> None:
    operation = _running_operation()
    snapshot = _terminal_service_snapshot(outcome=outcome)
    append = AsyncMock(
        return_value=AuditAppendResult(
            sequence=2,
            event_hash=SHA_C,
            canonical_bytes=b"audit-fixture",
        )
    )
    journal = cast(
        AuditJournal,
        SimpleNamespace(
            tail=AuditTail(2, SHA_C),
            append=append,
            append_emergency=AsyncMock(),
            find_operation_state_evidence=AsyncMock(return_value=None),
        ),
    )
    closure = PrivilegedRestartAuditClosure(
        audit=journal,
        obligations=cast(AuditObligationStore, SimpleNamespace(scan=AsyncMock(return_value=()))),
        store=SimpleNamespace(
            update_audit_tail_cache=AsyncMock(),
            latch_audit_failure=AsyncMock(),
        ),
        closure_health=AsyncMock(return_value=True),
        clock=lambda: NOW,
        monotonic_ns=lambda: 123,
    )

    assert await closure.record_accepted(operation, snapshot) == SHA_C
    assert append.await_args is not None
    assert append.await_args.args[0].payload == {
        "kind": "operation.state_changed",
        "old_state": "running",
        "new_state": new_state,
        "state_version": operation.state_version + 1,
        "effect_knowledge": effect_knowledge,
        "result_digest": SHA_C,
        "reason_code": reason_code,
    }


@pytest.mark.anyio
async def test_audit_closure_retains_fence_when_health_or_append_is_unavailable() -> None:
    operation = _running_operation()
    snapshot = _terminal_snapshot(BrokerRestartOutcome.ROLLBACK_READY)
    append = AsyncMock(side_effect=OSError("journal unavailable"))
    emergency = AsyncMock()
    journal = cast(
        AuditJournal,
        SimpleNamespace(
            tail=AuditTail(0, None),
            append=append,
            append_emergency=emergency,
            find_operation_state_evidence=AsyncMock(return_value=None),
        ),
    )
    obligation_scan = AsyncMock(
        return_value=(AuditObligation("1", "obl-fixture", operation.operation_id, 3),)
    )
    obligations = cast(
        AuditObligationStore,
        SimpleNamespace(scan=obligation_scan),
    )
    latch = AsyncMock()
    closure = PrivilegedRestartAuditClosure(
        audit=journal,
        obligations=obligations,
        store=SimpleNamespace(
            update_audit_tail_cache=AsyncMock(),
            latch_audit_failure=latch,
        ),
        closure_health=AsyncMock(return_value=True),
        clock=lambda: NOW,
    )

    with pytest.raises(PrivilegedRestartReconciliationError, match="recovery"):
        await closure.record_accepted(operation, snapshot)
    append.assert_not_awaited()

    obligation_scan.return_value = ()
    with pytest.raises(PrivilegedRestartReconciliationError, match="persisted"):
        await closure.record_accepted(operation, snapshot)
    latch.assert_awaited_once_with("privileged_restart_audit_unavailable")
    emergency.assert_awaited_once()

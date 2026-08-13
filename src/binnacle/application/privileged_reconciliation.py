"""Conservative replacement-application reconciliation for Phase 9 restarts."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol

from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.idempotency import owner_digest
from binnacle.domain.operation import EffectKnowledge, OperationSnapshot, OperationState
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartOutcome,
    PrivilegedEffectKnowledge,
)
from binnacle.domain.privileged_restart import (
    PrivilegedOperationState,
    RestartAcceptedClosureRequest,
    RestartNoAcceptClosureRequest,
)
from binnacle.ports.audit import AuditJournal, AuditObligationStore
from binnacle.ports.privileged import (
    PrivilegedApplicationRepository,
    PrivilegedBrokerPort,
    PrivilegedBrokerUnavailable,
)


class PrivilegedRestartReconciliationError(RuntimeError):
    """Retained application and broker restart evidence cannot be reconciled safely."""


class RestartNoAcceptAuditClosure(Protocol):
    """Idempotently retain/reuse audit closure for a broker-proven no-accept result."""

    async def record_no_accept(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
    ) -> str: ...


class RestartAcceptedAuditClosure(Protocol):
    """Idempotently retain/reuse audit closure for accepted terminal broker truth."""

    async def record_accepted(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
    ) -> str: ...


class RestartAuditStateStore(Protocol):
    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def latch_audit_failure(self, reason: str) -> int: ...


class PrivilegedRestartAuditClosure:
    """Append exact terminal lifecycle truth before releasing restart authority."""

    def __init__(
        self,
        *,
        audit: AuditJournal,
        obligations: AuditObligationStore,
        store: RestartAuditStateStore,
        closure_health: Callable[[], Awaitable[bool]],
        clock: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._audit = audit
        self._obligations = obligations
        self._store = store
        self._closure_health = closure_health
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._locks: dict[str, asyncio.Lock] = {}

    async def record_no_accept(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
    ) -> str:
        if (
            snapshot.acceptance_state is not BrokerAcceptanceState.SEALED_NO_ACCEPT
            or snapshot.execution_state is not BrokerExecutionState.TERMINAL
            or snapshot.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
        ):
            raise PrivilegedRestartReconciliationError(
                "no-accept audit closure received different broker truth"
            )
        return await self._record(
            operation,
            snapshot,
            final_state=OperationState.FAILED,
            effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
            reason_code="privileged_no_accept_proven",
        )

    async def record_accepted(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
    ) -> str:
        final_state, effect_knowledge, reason_code = self._accepted_outcome(snapshot)
        return await self._record(
            operation,
            snapshot,
            final_state=final_state,
            effect_knowledge=effect_knowledge,
            reason_code=reason_code,
        )

    async def _record(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
        *,
        final_state: OperationState,
        effect_knowledge: EffectKnowledge,
        reason_code: str,
    ) -> str:
        if operation.operation_id != snapshot.identity.operation_id:
            raise PrivilegedRestartReconciliationError(
                "restart audit operation and broker identity differ"
            )
        if snapshot.result_evidence_sha256 is None:
            raise PrivilegedRestartReconciliationError(
                "restart audit closure lacks broker result evidence"
            )
        lock = self._locks.setdefault(operation.operation_id, asyncio.Lock())
        async with lock:
            if not await self._closure_health() or await self._obligations.scan():
                raise PrivilegedRestartReconciliationError("restart audit recovery is not closed")
            state_version = operation.state_version + 1
            existing = await self._audit.find_operation_state_evidence(
                operation_id=operation.operation_id,
                state_version=state_version,
                state=final_state.value,
                effect_knowledge=effect_knowledge.value,
            )
            if existing is not None:
                await self._cache_tail_or_latch()
                return existing
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise PrivilegedRestartReconciliationError("restart audit closure clock is naive")
            draft = AuditEventDraft(
                event_id=f"event_{secrets.token_hex(16)}",
                recorded_at=now,
                monotonic_ns=self._monotonic_ns(),
                severity="notice",
                source="binnacle_system",
                controller_id_digest=owner_digest(operation.owner),
                operation_id=operation.operation_id,
                correlation_ids=(snapshot.identity.ticket_id,),
                payload={
                    "kind": "operation.state_changed",
                    "old_state": operation.state.value,
                    "new_state": final_state.value,
                    "state_version": state_version,
                    "effect_knowledge": effect_knowledge.value,
                    "result_digest": snapshot.result_evidence_sha256,
                    "reason_code": reason_code,
                },
                safe_facts=(
                    {
                        "name": "privileged_ticket_sha256",
                        "value": snapshot.identity.ticket_sha256,
                        "classification": "restricted-result",
                    },
                    {
                        "name": "broker_acceptance_evidence_sha256",
                        "value": snapshot.acceptance_evidence_sha256,
                        "classification": "restricted-result",
                    },
                    {
                        "name": "restart_checkpoint_sha256",
                        "value": snapshot.restart_checkpoint_sha256,
                        "classification": "restricted-result",
                    },
                    {
                        "name": "restart_outcome",
                        "value": (
                            None
                            if snapshot.restart_outcome is None
                            else snapshot.restart_outcome.value
                        ),
                        "classification": "normal-result",
                    },
                    {
                        "name": "selected_runtime_slot_id",
                        "value": snapshot.selected_runtime_slot_id,
                        "classification": "restricted-result",
                    },
                ),
            )
            try:
                result = await self._audit.append(draft)
                await self._store.update_audit_tail_cache(
                    AuditTail(result.sequence, result.event_hash)
                )
            except Exception as exc:
                await self._latch_failure()
                with suppress(Exception):
                    await self._audit.append_emergency(
                        reason_code="privileged_restart_audit_unavailable",
                        operation_id=operation.operation_id,
                        source_event_id=draft.event_id,
                    )
                raise PrivilegedRestartReconciliationError(
                    "restart audit closure could not be persisted"
                ) from exc
            return result.event_hash

    async def _cache_tail_or_latch(self) -> None:
        try:
            await self._store.update_audit_tail_cache(self._audit.tail)
        except Exception as exc:
            await self._latch_failure()
            raise PrivilegedRestartReconciliationError(
                "restart audit tail cache could not be persisted"
            ) from exc

    async def _latch_failure(self) -> None:
        with suppress(Exception):
            await self._store.latch_audit_failure("privileged_restart_audit_unavailable")

    @staticmethod
    def _accepted_outcome(
        snapshot: BrokerBindingSnapshot,
    ) -> tuple[OperationState, EffectKnowledge, str]:
        if (
            snapshot.acceptance_state is not BrokerAcceptanceState.ACCEPTED
            or snapshot.execution_state is not BrokerExecutionState.TERMINAL
        ):
            raise PrivilegedRestartReconciliationError(
                "accepted audit closure received open broker truth"
            )
        mapping = {
            BrokerRestartOutcome.CANDIDATE_READY: (
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_candidate_ready",
            ),
            BrokerRestartOutcome.ROLLBACK_READY: (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_restart_rolled_back",
            ),
            BrokerRestartOutcome.NO_SUBEFFECT: (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_NO_EFFECT,
                "privileged_effect_not_started",
            ),
            BrokerRestartOutcome.FAILED: (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_restart_failed",
            ),
        }
        outcome = snapshot.restart_outcome
        if outcome is None:
            raise PrivilegedRestartReconciliationError(
                "accepted audit closure lacks terminal checkpoint truth"
            )
        try:
            return mapping[outcome]
        except KeyError as exc:
            raise PrivilegedRestartReconciliationError(
                "accepted audit closure lacks terminal checkpoint truth"
            ) from exc


class PrivilegedRestartReconciler:
    """Route retained restart operations away from generic no-effect recovery.

    Accepted broker observations deliberately leave the Phase 4 operation and Phase 6
    fence open. A sealed no-accept result closes them only after an explicit audit
    closure dependency returns retained evidence. Without that dependency, broker
    absence, an empty lookup, and no-accept all remain recovery-closed.
    """

    def __init__(
        self,
        *,
        repository: PrivilegedApplicationRepository,
        broker: PrivilegedBrokerPort,
        no_accept_audit_closure: RestartNoAcceptAuditClosure | None = None,
        accepted_audit_closure: RestartAcceptedAuditClosure | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._broker = broker
        self._no_accept_audit_closure = no_accept_audit_closure
        self._accepted_audit_closure = accepted_audit_closure
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None:
        retained = await self._repository.get_restart(operation.operation_id)
        if retained is None:
            return None
        if retained.operation_id != operation.operation_id:
            raise PrivilegedRestartReconciliationError(
                "restart repository returned a foreign operation"
            )
        before_dispatch = (
            operation.state is OperationState.AUTHORISED
            and retained.state is PrivilegedOperationState.PREPARED
            and retained.broker_acceptance_state is BrokerAcceptanceState.UNRESOLVED
        )
        try:
            snapshot = await self._broker.get(operation.operation_id)
        except PrivilegedBrokerUnavailable:
            if before_dispatch:
                return await self._close_before_dispatch(operation.operation_id)
            return operation
        if snapshot is None:
            if before_dispatch:
                return await self._close_before_dispatch(operation.operation_id)
            return operation
        if snapshot.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
            if self._no_accept_audit_closure is None:
                return operation
            audit_evidence_sha256 = await self._no_accept_audit_closure.record_no_accept(
                operation,
                snapshot,
            )
            closed, _, _ = await self._repository.close_restart_no_accept(
                RestartNoAcceptClosureRequest(
                    snapshot=snapshot,
                    audit_closure_evidence_sha256=audit_evidence_sha256,
                    closed_at=self._clock(),
                )
            )
            return closed
        if snapshot.execution_state is BrokerExecutionState.TERMINAL:
            if self._accepted_audit_closure is None:
                await self._repository.record_broker_snapshot(
                    snapshot,
                    reconciled_at=self._clock(),
                )
                return operation
            audit_evidence_sha256 = await self._accepted_audit_closure.record_accepted(
                operation,
                snapshot,
            )
            if snapshot.restart_outcome is BrokerRestartOutcome.CANDIDATE_READY:
                try:
                    snapshot = await self._broker.promote_restart_lkg(
                        operation.operation_id,
                        audit_closure_evidence_sha256=audit_evidence_sha256,
                        promoted_at=self._clock(),
                    )
                except PrivilegedBrokerUnavailable:
                    # The durable audit event is idempotent.  Keep the application
                    # reservation/fence closed until the broker can bind it to the
                    # protected LKG transition and return that exact evidence.
                    return operation
            closed, _, _ = await self._repository.close_restart_accepted(
                RestartAcceptedClosureRequest(
                    snapshot=snapshot,
                    audit_closure_evidence_sha256=audit_evidence_sha256,
                    closed_at=self._clock(),
                )
            )
            return closed
        await self._repository.record_broker_snapshot(
            snapshot,
            reconciled_at=self._clock(),
        )
        return operation

    async def _close_before_dispatch(self, operation_id: str) -> OperationSnapshot:
        closed, _, _ = await self._repository.close_restart_before_dispatch(
            operation_id,
            closed_at=self._clock(),
        )
        return closed

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
        return ()


__all__ = [
    "PrivilegedRestartAuditClosure",
    "PrivilegedRestartReconciler",
    "PrivilegedRestartReconciliationError",
    "RestartAcceptedAuditClosure",
    "RestartAuditStateStore",
    "RestartNoAcceptAuditClosure",
]

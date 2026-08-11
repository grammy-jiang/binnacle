"""Restart-safe Phase 6 session and workspace domain closure."""

from __future__ import annotations

import secrets
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol

from binnacle.application.development_session import SessionActivationClosure
from binnacle.application.workspace import WorkspaceMutationClosure
from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.idempotency import owner_digest
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    Terminality,
    TransitionRequest,
)
from binnacle.ports.audit import AuditJournal, AuditObligationStore
from binnacle.ports.development_session import DevelopmentSessionRepository
from binnacle.ports.operation_store import OperationStore
from binnacle.ports.workspace import WorkspaceRepository


class Phase6ReconciliationError(RuntimeError):
    """Retained Phase 6 authority cannot yet be closed truthfully."""


class Phase6ClosureHealth(Protocol):
    async def __call__(self) -> bool: ...


class Phase6ReconciliationStore(OperationStore, Protocol):
    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def latch_audit_failure(self, reason_code: str) -> int: ...

    async def get_transition_audit_context(
        self,
        operation_id: str,
        state_version: int,
    ) -> tuple[OperationState, str] | None: ...


class Phase6OperationReconciler:
    """Reconcile exact activation/fence truth before either workspace mode opens."""

    def __init__(
        self,
        *,
        operations: Phase6ReconciliationStore,
        sessions: DevelopmentSessionRepository,
        workspaces: WorkspaceRepository,
        session_closure: SessionActivationClosure,
        workspace_closure: WorkspaceMutationClosure,
        audit: AuditJournal,
        obligations: AuditObligationStore,
        closure_health: Phase6ClosureHealth,
    ) -> None:
        self._operations = operations
        self._sessions = sessions
        self._workspaces = workspaces
        self._session_closure = session_closure
        self._workspace_closure = workspace_closure
        self._audit = audit
        self._obligations = obligations
        self._closure_health = closure_health

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None:
        if await self._sessions.get_by_begin_operation(operation.operation_id) is not None:
            return await self._reconcile_session(operation)
        if await self._workspaces.get_operation(operation.operation_id) is not None:
            return await self._reconcile_workspace(operation)
        return None

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
        reconciled: list[OperationSnapshot] = []
        reconciled.extend(await self._reconcile_session_closure_pages())
        reconciled.extend(await self._reconcile_workspace_closure_pages())
        return tuple(reconciled)

    async def _reconcile_session(self, operation: OperationSnapshot) -> OperationSnapshot:
        session = await self._sessions.get_by_begin_operation(operation.operation_id)
        if session is None:
            raise Phase6ReconciliationError("session reconciliation projection disappeared")
        if operation.state is OperationState.AUTHORISED:
            await self._require_runtime_ready(operation)
            operation = await self._transition_with_audit(
                operation,
                to_state=OperationState.FAILED,
                effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                reason_code="restart_before_dispatch",
                error=OperationError(
                    "reconciliation_unavailable",
                    "Session activation did not reach the durable dispatch marker.",
                ),
            )
        elif operation.state in {OperationState.RUNNING, OperationState.UNCERTAIN}:
            if (
                session.activation_effect_reference is not None
                and session.activation_effect_reference_sha256 is not None
            ):
                # This exact retained domain receipt is the effect truth needed by
                # AuditRecoveryService to close a surviving post-effect obligation.
                # Persist it even while global admission remains latched; closure
                # below still requires the marker/generation recovery to finish.
                operation = await self._transition_with_audit(
                    operation,
                    to_state=OperationState.SUCCEEDED,
                    effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
                    reason_code="session_activation_reconciled",
                    effect_reference=session.activation_effect_reference,
                    effect_reference_digest=session.activation_effect_reference_sha256,
                )
            else:
                await self._require_runtime_ready(operation)
                if operation.state is OperationState.RUNNING:
                    operation = await self._transition_with_audit(
                        operation,
                        to_state=OperationState.UNCERTAIN,
                        effect_knowledge=EffectKnowledge.UNCERTAIN,
                        reason_code="session_activation_receipt_unavailable",
                        error=OperationError(
                            "operation_uncertain",
                            "Session activation start cannot be proven after restart.",
                            "reconcile",
                        ),
                    )
        if self._is_closable(operation):
            await self._require_closure_evidence(operation)
            return await self._session_closure.close_retained(operation)
        return operation

    async def _reconcile_workspace(self, operation: OperationSnapshot) -> OperationSnapshot:
        if operation.state is OperationState.AUTHORISED:
            await self._require_runtime_ready(operation)
            operation = await self._transition_with_audit(
                operation,
                to_state=OperationState.FAILED,
                effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                reason_code="restart_before_dispatch",
                error=OperationError(
                    "reconciliation_unavailable",
                    "Workspace mutation did not reach the durable dispatch marker.",
                ),
            )
        elif (
            operation.state is OperationState.RUNNING
            and operation.effect_knowledge is EffectKnowledge.NONE
        ):
            await self._require_runtime_ready(operation)
            operation = await self._transition_with_audit(
                operation,
                to_state=OperationState.UNCERTAIN,
                effect_knowledge=EffectKnowledge.UNCERTAIN,
                reason_code="workspace_effect_receipt_unavailable",
                error=OperationError(
                    "operation_uncertain",
                    "Workspace effect truth is unavailable after restart.",
                    "reconcile",
                ),
            )
        if self._is_closable(operation):
            await self._require_closure_evidence(operation)
            return await self._workspace_closure.close_retained(operation)
        return operation

    async def _reconcile_session_closure_pages(self) -> tuple[OperationSnapshot, ...]:
        reconciled: list[OperationSnapshot] = []
        after_created_at: datetime | None = None
        after_session_id: str | None = None
        while True:
            page = await self._sessions.list_activation_closures(
                limit=100,
                after_created_at=after_created_at,
                after_session_id=after_session_id,
            )
            for session in page:
                operation = await self._operations.get_operation(session.begin_operation_id)
                if operation is None:
                    raise Phase6ReconciliationError("session operation lifecycle is unavailable")
                if self._is_closable(operation):
                    await self._require_closure_evidence(operation)
                    reconciled.append(await self._session_closure.close_retained(operation))
            if len(page) < 100:
                break
            last = page[-1]
            after_created_at = last.created_at
            after_session_id = last.session_id
        return tuple(reconciled)

    async def _reconcile_workspace_closure_pages(self) -> tuple[OperationSnapshot, ...]:
        reconciled: list[OperationSnapshot] = []
        after_created_at: datetime | None = None
        after_operation_id: str | None = None
        while True:
            page = await self._workspaces.list_operations_for_closure(
                limit=100,
                after_created_at=after_created_at,
                after_operation_id=after_operation_id,
            )
            for record in page:
                operation = await self._operations.get_operation(record.operation_id)
                if operation is None:
                    raise Phase6ReconciliationError("workspace operation lifecycle is unavailable")
                if self._is_closable(operation):
                    await self._require_closure_evidence(operation)
                    reconciled.append(await self._workspace_closure.close_retained(operation))
            if len(page) < 100:
                break
            last = page[-1]
            after_created_at = last.created_at
            after_operation_id = last.operation_id
        return tuple(reconciled)

    async def _transition_with_audit(
        self,
        operation: OperationSnapshot,
        *,
        to_state: OperationState,
        effect_knowledge: EffectKnowledge,
        reason_code: str,
        error: OperationError | None = None,
        effect_reference: str | None = None,
        effect_reference_digest: str | None = None,
    ) -> OperationSnapshot:
        transitioned = await self._operations.transition(
            operation.operation_id,
            TransitionRequest(
                expected_state_version=operation.state_version,
                to_state=to_state,
                effect_knowledge=effect_knowledge,
                reason_code=reason_code,
                error=error,
                effect_reference=effect_reference,
                effect_reference_digest=effect_reference_digest,
                occurred_at=datetime.now(UTC),
            ),
        )
        await self._ensure_state_audit(
            transitioned,
            old_state=operation.state,
            reason_code=reason_code,
        )
        return transitioned

    async def _ensure_state_audit(
        self,
        operation: OperationSnapshot,
        *,
        old_state: OperationState | None = None,
        reason_code: str | None = None,
    ) -> None:
        existing = await self._audit.find_operation_state_evidence(
            operation_id=operation.operation_id,
            state_version=operation.state_version,
            state=operation.state.value,
            effect_knowledge=operation.effect_knowledge.value,
        )
        if existing is not None:
            return
        if old_state is None or reason_code is None:
            context = await self._operations.get_transition_audit_context(
                operation.operation_id,
                operation.state_version,
            )
            if context is None:
                raise Phase6ReconciliationError(
                    "Phase 6 operation transition audit context is unavailable"
                )
            old_state, reason_code = context
        draft = AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="notice",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            payload={
                "kind": "operation.state_changed",
                "old_state": old_state.value,
                "new_state": operation.state.value,
                "state_version": operation.state_version,
                "effect_knowledge": operation.effect_knowledge.value,
                "result_digest": operation.effect_reference_digest,
                "reason_code": reason_code,
            },
        )
        try:
            result = await self._audit.append(draft)
            await self._operations.update_audit_tail_cache(
                AuditTail(result.sequence, result.event_hash)
            )
        except Exception as exc:
            with suppress(Exception):
                await self._operations.latch_audit_failure("phase6_restart_audit_unavailable")
            with suppress(Exception):
                await self._audit.append_emergency(
                    reason_code="phase6_restart_audit_unavailable",
                    operation_id=operation.operation_id,
                    source_event_id=draft.event_id,
                )
            raise Phase6ReconciliationError(
                "Phase 6 restart audit evidence could not be persisted"
            ) from exc

    async def _require_runtime_ready(self, operation: OperationSnapshot) -> None:
        if any(
            marker.operation_id == operation.operation_id
            for marker in await self._obligations.scan()
        ):
            raise Phase6ReconciliationError("Phase 6 audit obligation remains open")
        if not await self._closure_health():
            raise Phase6ReconciliationError("Phase 6 audit recovery health is unavailable")

    async def _require_closure_evidence(self, operation: OperationSnapshot) -> None:
        await self._require_runtime_ready(operation)
        evidence = await self._audit.find_operation_state_evidence(
            operation_id=operation.operation_id,
            state_version=operation.state_version,
            state=operation.state.value,
            effect_knowledge=operation.effect_knowledge.value,
        )
        if evidence is None:
            await self._ensure_state_audit(operation)
            evidence = await self._audit.find_operation_state_evidence(
                operation_id=operation.operation_id,
                state_version=operation.state_version,
                state=operation.state.value,
                effect_knowledge=operation.effect_knowledge.value,
            )
        if evidence is None:
            raise Phase6ReconciliationError("Phase 6 operation audit evidence is unavailable")

    @staticmethod
    def _is_closable(operation: OperationSnapshot) -> bool:
        return operation.terminality is Terminality.TERMINAL and operation.effect_knowledge in {
            EffectKnowledge.KNOWN_EFFECT,
            EffectKnowledge.KNOWN_NO_EFFECT,
        }


__all__ = [
    "Phase6ClosureHealth",
    "Phase6OperationReconciler",
    "Phase6ReconciliationError",
    "Phase6ReconciliationStore",
]

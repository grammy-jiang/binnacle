"""Conservative fresh-process operation and audit-obligation reconciliation."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from binnacle.application.boundary import ConsequentialBoundaryGate
from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.ports.audit import (
    AuditJournal,
    AuditObligation,
    AuditObligationRecovery,
    AuditObligationStore,
)
from binnacle.ports.effect import EffectReconciler, EffectReference
from binnacle.ports.operation_store import OperationStore, ReconciliationCursor


class ReconciliationStore(OperationStore, Protocol):
    async def latch_audit_failure(self, reason_code: str) -> int: ...

    async def audit_failure_state(self) -> tuple[bool, int, int]: ...

    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def clear_audit_failure(self, generation: int, evidence_sha256: str) -> None: ...


class SpecializedOperationReconciler(Protocol):
    """Optional phase-specific closure before generic lifecycle fallback."""

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None: ...

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]: ...


class CompositeSpecializedOperationReconciler:
    """Route disjoint operation families without allowing one fallback to shadow another."""

    def __init__(self, *reconcilers: SpecializedOperationReconciler) -> None:
        if not reconcilers:
            raise ValueError("at least one specialized reconciler is required")
        self._reconcilers = reconcilers

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None:
        for reconciler in self._reconcilers:
            result = await reconciler.reconcile(operation)
            if result is not None:
                return result
        return None

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
        results: list[OperationSnapshot] = []
        for reconciler in self._reconcilers:
            results.extend(await reconciler.reconcile_terminal_closures())
        return tuple(results)


@dataclass(frozen=True, slots=True)
class AuditObligationClosure:
    obligation_id: str
    effect_outcome: str
    evidence_sha256: str


def audit_closure_evidence_digest(
    *,
    generation: int,
    marker: AuditObligation,
    operation: OperationSnapshot,
    effect_outcome: str,
) -> str:
    """Bind operator closure evidence to the retained durable effect truth."""

    values = (
        str(generation),
        marker.obligation_id,
        marker.operation_id,
        str(marker.running_state_version),
        operation.state.value,
        str(operation.state_version),
        operation.effect_knowledge.value,
        operation.effect_reference_digest or "none",
        effect_outcome,
    )
    return hashlib.sha256(
        b"binnacle.audit-obligation-closure.v1\0" + "\0".join(values).encode()
    ).hexdigest()


class AuditRecoveryService:
    """Explicit exact-generation closure; normal startup never calls this service."""

    def __init__(
        self,
        *,
        store: ReconciliationStore,
        obligations: AuditObligationStore,
        audit: AuditJournal,
    ) -> None:
        self._store = store
        self._obligations = obligations
        self._audit = audit

    async def recover(
        self, *, generation: int, closures: tuple[AuditObligationClosure, ...]
    ) -> str:
        latched, active_generation, recovered_generation = await self._store.audit_failure_state()
        if generation != active_generation:
            raise RuntimeError("audit recovery generation mismatch")
        markers = await self._obligations.scan()
        existing_recovery = await self._audit.find_generation_recovery(generation)
        if not latched:
            if recovered_generation == generation and existing_recovery is not None and not markers:
                return existing_recovery
            raise RuntimeError("audit recovery generation mismatch")
        if recovered_generation >= generation:
            raise RuntimeError("audit recovery generation mismatch")
        if existing_recovery is not None:
            if markers:
                raise RuntimeError("exact-generation recovery conflicts with surviving obligations")
            await self._store.clear_audit_failure(generation, existing_recovery)
            return existing_recovery

        by_id = {item.obligation_id: item for item in markers}
        supplied = {item.obligation_id: item for item in closures}
        recovered = {
            item.obligation_id: item
            for item in await self._audit.list_obligation_recoveries(generation)
        }
        missing = set(by_id) - set(supplied) - set(recovered)
        unexpected = set(supplied) - set(by_id) - set(recovered)
        if len(supplied) != len(closures) or missing or unexpected:
            raise RuntimeError("closures must match every surviving obligation exactly")

        for recovery in recovered.values():
            closure = supplied.get(recovery.obligation_id)
            if closure is not None and (
                closure.effect_outcome != recovery.effect_outcome
                or closure.evidence_sha256 != recovery.evidence_sha256
            ):
                raise RuntimeError("audit obligation recovery evidence conflicts")
            marker = by_id.get(recovery.obligation_id) or AuditObligation(
                schema_version="1",
                obligation_id=recovery.obligation_id,
                operation_id=recovery.operation_id,
                running_state_version=recovery.running_state_version,
            )
            self._validate_recovery_binding(marker, recovery)
            await self._validate_closure_truth(
                generation=generation,
                marker=marker,
                effect_outcome=recovery.effect_outcome,
                evidence_sha256=recovery.evidence_sha256,
            )

        for marker in markers:
            prior = recovered.get(marker.obligation_id)
            if prior is not None:
                await self._obligations.remove(marker.obligation_id)
                continue
            closure = supplied[marker.obligation_id]
            await self._validate_closure_truth(
                generation=generation,
                marker=marker,
                effect_outcome=closure.effect_outcome,
                evidence_sha256=closure.evidence_sha256,
            )
            result = await self._audit.append(
                AuditEventDraft(
                    event_id=f"event_{secrets.token_hex(16)}",
                    recorded_at=datetime.now(UTC),
                    monotonic_ns=time.monotonic_ns(),
                    severity="notice",
                    source="local_owner",
                    operation_id=marker.operation_id,
                    correlation_ids=(marker.obligation_id,),
                    payload={
                        "kind": "recovery.completed",
                        "phase": "audit_obligation_closure",
                        "remaining_effects_verified": True,
                        "result_digest": closure.evidence_sha256,
                        "reason_code": closure.effect_outcome,
                    },
                    safe_facts=(
                        {
                            "name": "running_state_version",
                            "value": marker.running_state_version,
                            "classification": "normal-result",
                        },
                        {
                            "name": "audit_failure_generation",
                            "value": generation,
                            "classification": "restricted-result",
                        },
                    ),
                )
            )
            await self._store.update_audit_tail_cache(AuditTail(result.sequence, result.event_hash))
            await self._obligations.remove(marker.obligation_id)
        if await self._obligations.scan():
            raise RuntimeError("audit obligations remain after explicit closure")

        durable_closures = await self._audit.list_obligation_recoveries(generation)
        verification_hash = await self._audit.find_generation_verification(generation)
        if verification_hash is None:
            verification = await self._audit.append(self._verification_event(generation))
            await self._store.update_audit_tail_cache(
                AuditTail(verification.sequence, verification.event_hash)
            )
            verification_hash = verification.event_hash
        recovery_digest = hashlib.sha256(
            b"binnacle.audit-recovery-batch.v1\0"
            + str(generation).encode()
            + b"\0"
            + "\0".join(item.event_hash for item in durable_closures).encode()
            + b"\0"
            + verification_hash.encode()
        ).hexdigest()
        completed = await self._audit.append(
            self._generation_recovery_event(
                generation=generation,
                recoveries=durable_closures,
                recovery_digest=recovery_digest,
            )
        )
        await self._store.update_audit_tail_cache(
            AuditTail(completed.sequence, completed.event_hash)
        )
        await self._store.clear_audit_failure(generation, completed.event_hash)
        return completed.event_hash

    @staticmethod
    def _validate_recovery_binding(
        marker: AuditObligation, recovery: AuditObligationRecovery
    ) -> None:
        if (
            marker.operation_id != recovery.operation_id
            or marker.running_state_version != recovery.running_state_version
        ):
            raise RuntimeError("audit obligation recovery evidence conflicts")

    async def _validate_closure_truth(
        self,
        *,
        generation: int,
        marker: AuditObligation,
        effect_outcome: str,
        evidence_sha256: str,
    ) -> None:
        outcome_knowledge = {
            "known_no_effect": EffectKnowledge.KNOWN_NO_EFFECT,
            "known_effect": EffectKnowledge.KNOWN_EFFECT,
            "partial": EffectKnowledge.PARTIAL,
        }
        try:
            digest_valid = (
                len(evidence_sha256) == 64
                and int(evidence_sha256, 16) >= 0
                and evidence_sha256 == evidence_sha256.casefold()
            )
        except ValueError:
            digest_valid = False
        if effect_outcome not in outcome_knowledge or not digest_valid:
            raise RuntimeError("audit obligation closure evidence is invalid")
        operation = await self._store.get_operation(marker.operation_id)
        if operation is None:
            raise RuntimeError("audit obligation operation truth is unavailable")
        if operation.effect_knowledge is not outcome_knowledge[effect_outcome]:
            raise RuntimeError("audit obligation outcome contradicts durable operation truth")
        matched_event = await self._audit.find_obligation_evidence(
            obligation_id=marker.obligation_id,
            operation_id=marker.operation_id,
            running_state_version=marker.running_state_version,
        )
        expected_evidence = matched_event or audit_closure_evidence_digest(
            generation=generation,
            marker=marker,
            operation=operation,
            effect_outcome=effect_outcome,
        )
        if evidence_sha256 != expected_evidence:
            raise RuntimeError("audit obligation evidence is not bound to durable truth")

    def _verification_event(self, generation: int) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="notice",
            source="local_owner",
            payload={
                "kind": "audit.verification_passed",
                "segment_first_sequence": 1 if self._audit.tail.sequence else None,
                "segment_last_sequence": self._audit.tail.sequence,
                "event_count": self._audit.tail.sequence,
                "byte_count": 0,
                "segment_or_checkpoint_digest": self._audit.tail.event_hash,
                "external_receipt_digest": None,
                "previous_checkpoint_digest": None,
                "reason_code": "exact_generation_recovered",
            },
            safe_facts=(
                {
                    "name": "audit_failure_generation",
                    "value": generation,
                    "classification": "restricted-result",
                },
            ),
        )

    @staticmethod
    def _generation_recovery_event(
        *,
        generation: int,
        recoveries: tuple[AuditObligationRecovery, ...],
        recovery_digest: str,
    ) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="notice",
            source="local_owner",
            correlation_ids=tuple(item.obligation_id for item in recoveries),
            payload={
                "kind": "recovery.completed",
                "phase": "audit_failure_generation",
                "remaining_effects_verified": True,
                "result_digest": recovery_digest,
                "reason_code": "audit_failure_recovered",
            },
            safe_facts=(
                {
                    "name": "audit_failure_generation",
                    "value": generation,
                    "classification": "restricted-result",
                },
                {
                    "name": "audit_obligation_count",
                    "value": len(recoveries),
                    "classification": "normal-result",
                },
            ),
        )


class OperationReconciler:
    def __init__(
        self,
        *,
        store: ReconciliationStore,
        obligations: AuditObligationStore,
        gate: ConsequentialBoundaryGate,
        effect_reconciler: EffectReconciler | None = None,
        specialized_reconciler: SpecializedOperationReconciler | None = None,
    ) -> None:
        self._store = store
        self._obligations = obligations
        self._gate = gate
        self._effect_reconciler = effect_reconciler
        self._specialized_reconciler = specialized_reconciler

    async def reconcile_startup(
        self, *, open_when_healthy: bool = True
    ) -> tuple[OperationSnapshot, ...]:
        await self._gate.close()
        obligations = await self._obligations.scan()
        if obligations:
            await self._store.latch_audit_failure("surviving_audit_obligation")
        reconciled: list[OperationSnapshot] = []
        cursor: ReconciliationCursor | None = None
        while True:
            page = await self._store.list_reconcilable(limit=100, after=cursor)
            for operation in page:
                reconciled.append(await self._reconcile(operation))
            if len(page) < 100:
                break
            last = page[-1]
            cursor = ReconciliationCursor(last.created_at, last.operation_id)
        if self._specialized_reconciler is not None:
            reconciled.extend(await self._specialized_reconciler.reconcile_terminal_closures())
        latched, generation, recovered = await self._store.audit_failure_state()
        if open_when_healthy and not obligations and not latched and generation == recovered:
            await self._gate.open()
        return tuple(reconciled)

    async def _reconcile(self, operation: OperationSnapshot) -> OperationSnapshot:
        if self._specialized_reconciler is not None:
            specialized = await self._specialized_reconciler.reconcile(operation)
            if specialized is not None:
                return specialized
        if operation.state is OperationState.RECEIVED:
            existing = await self._store.get_policy_decision(operation.operation_id)
            decision = existing or self._recovery_decision(operation)
            return await self._store.reject_received_on_restart(operation.operation_id, decision)
        if operation.state is OperationState.AUTHORISED:
            return await self._store.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.FAILED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code="restart_before_dispatch",
                    error=OperationError(
                        "reconciliation_unavailable",
                        "Authorised operation did not reach the durable dispatch marker.",
                    ),
                ),
            )
        if operation.state is OperationState.UNCERTAIN:
            if operation.effect_reference and operation.effect_reference_digest:
                return await self._reconcile_reference(operation)
            return operation
        if operation.state in {
            OperationState.RUNNING,
            OperationState.PAUSED,
            OperationState.CANCELLING,
        }:
            if operation.effect_reference and operation.effect_reference_digest:
                return await self._reconcile_reference(operation)
            if operation.state is OperationState.RUNNING:
                return await self._store.transition(
                    operation.operation_id,
                    TransitionRequest(
                        expected_state_version=operation.state_version,
                        to_state=OperationState.UNCERTAIN,
                        effect_knowledge=EffectKnowledge.UNCERTAIN,
                        reason_code="restart_missing_effect_receipt",
                        error=OperationError(
                            "operation_uncertain",
                            "Dispatch was attempted but its effect cannot be proven.",
                            "reconcile",
                        ),
                    ),
                )
            return await self._store.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.UNCERTAIN,
                    effect_knowledge=EffectKnowledge.UNCERTAIN,
                    reason_code="restart_reconciliation_unavailable",
                    error=OperationError(
                        "reconciliation_unavailable",
                        "Effect reference is unavailable after restart.",
                        "reconcile",
                    ),
                ),
            )
        return operation

    async def _reconcile_reference(self, operation: OperationSnapshot) -> OperationSnapshot:
        if self._effect_reconciler is None:
            if operation.state is OperationState.UNCERTAIN:
                return operation
            return await self._store.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.UNCERTAIN,
                    effect_knowledge=EffectKnowledge.UNCERTAIN,
                    reason_code="effect_reconciler_unavailable",
                    error=OperationError(
                        "reconciliation_unavailable",
                        "No effect reconciler is available.",
                        "reconcile",
                    ),
                ),
            )
        assert operation.effect_reference is not None
        assert operation.effect_reference_digest is not None
        observation = await self._effect_reconciler.reconcile(
            EffectReference(
                operation.operation_id,
                operation.effect_reference,
                operation.effect_reference_digest,
            )
        )
        error = None
        if observation.state in {OperationState.FAILED, OperationState.UNCERTAIN}:
            error = OperationError(
                "operation_uncertain"
                if observation.state is OperationState.UNCERTAIN
                else "effect_failed",
                "Effect reconciler reported a non-success outcome.",
                "reconcile" if observation.state is OperationState.UNCERTAIN else "none",
            )
        return await self._store.transition(
            operation.operation_id,
            TransitionRequest(
                expected_state_version=operation.state_version,
                to_state=observation.state,
                effect_knowledge=observation.effect_knowledge,
                reason_code=observation.reason_code,
                error=error,
            ),
        )

    @staticmethod
    def _recovery_decision(operation: OperationSnapshot) -> PolicyDecision:
        facts = hashlib.sha256(
            b"binnacle.restart-before-admission.v1\0" + operation.operation_id.encode()
        ).hexdigest()
        return PolicyDecision(
            policy_decision_id=f"policy_{secrets.token_hex(16)}",
            operation_id=operation.operation_id,
            policy_id="bootstrap-recovery-policy",
            policy_version="1.0.0",
            decision=PolicyDecisionValue.DENY,
            reason_codes=("restart_before_admission",),
            input_facts_sha256=facts,
            runtime_policy_sha256=facts,
            decided_at=datetime.now(UTC),
        )

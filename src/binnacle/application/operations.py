"""Durable consequential-operation admission and synthetic dispatch coordinator."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from binnacle.application.boundary import (
    BoundaryGateError,
    ConsequentialBoundaryGate,
    DispatchHandoffGate,
    FinalBoundaryService,
)
from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.idempotency import IdempotencyOutcome, owner_digest
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationOwner,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecisionValue, PolicyRequest
from binnacle.ports.audit import AuditJournal, AuditObligation, AuditObligationStore
from binnacle.ports.boundary import OperationBoundaryCheck
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectBoundary,
    EffectRequest,
    EffectStartReceipt,
)
from binnacle.ports.operation_store import (
    CreateOrFindRequest,
    CreateOrFindResult,
    OperationStore,
)
from binnacle.ports.policy import PolicyEngine


class KernelOperationStore(OperationStore, Protocol):
    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def latch_audit_failure(self, reason_code: str) -> int: ...


class RequiredAuditError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CoordinatedOperationRequest:
    admission: CreateOrFindRequest
    required_scope_digest: str | None
    normalized_target_digest: str
    boundary_predicates: Mapping[str, str | bool | int | None]
    effect_type: str
    protected_effect_arguments: Mapping[str, object]


class OperationCoordinator:
    def __init__(
        self,
        *,
        store: KernelOperationStore,
        policy: PolicyEngine,
        audit: AuditJournal,
        obligations: AuditObligationStore,
        handoff_gate: DispatchHandoffGate,
        consequential_gate: ConsequentialBoundaryGate,
        final_boundary: FinalBoundaryService,
        effect_boundary: EffectBoundary,
    ) -> None:
        self._store = store
        self._policy = policy
        self._audit = audit
        self._obligations = obligations
        self._handoff_gate = handoff_gate
        self._consequential_gate = consequential_gate
        self._final_boundary = final_boundary
        self._effect_boundary = effect_boundary

    async def execute(self, request: CoordinatedOperationRequest) -> CreateOrFindResult:
        admitted = await self._store.create_or_find(request.admission)
        if admitted.outcome is not IdempotencyOutcome.CREATED or admitted.operation is None:
            return admitted
        operation = admitted.operation
        await self._required_audit(
            self._state_event(
                operation,
                old_state=None,
                reason_code="operation_received",
                idempotency_digest=request.admission.key.digest_sha256,
            )
        )
        policy_request = PolicyRequest(
            operation_id=operation.operation_id,
            owner=operation.owner,
            intent=operation.intent,
            required_scope_digest=request.required_scope_digest,
            normalized_target_digest=request.normalized_target_digest,
        )
        decision = await self._policy.evaluate(policy_request)
        await self._store.store_policy_decision(decision)
        if decision.decision is PolicyDecisionValue.DENY:
            rejected = await self._store.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.REJECTED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code=decision.reason_codes[0],
                    error=OperationError("policy_rejected", "Bootstrap policy rejected operation."),
                ),
            )
            await self._required_audit(
                self._policy_event(rejected, decision.allowed, decision.reason_codes[0])
            )
            await self._required_audit(
                self._state_event(
                    rejected, old_state=OperationState.RECEIVED.value, reason_code="policy_rejected"
                )
            )
            return CreateOrFindResult(IdempotencyOutcome.CREATED, rejected)

        authorised = await self._store.transition(
            operation.operation_id,
            TransitionRequest(
                expected_state_version=operation.state_version,
                to_state=OperationState.AUTHORISED,
                effect_knowledge=EffectKnowledge.NONE,
                reason_code="policy_allowed",
            ),
        )
        try:
            await self._required_audit(self._policy_event(authorised, True, "policy_allowed"))
            await self._required_audit(
                self._state_event(
                    authorised,
                    old_state=OperationState.RECEIVED.value,
                    reason_code="operation_authorised",
                )
            )
        except RequiredAuditError:
            failed = await self._fail_known_no_effect(
                authorised, code="audit_unavailable", reason="authorization_audit_failed"
            )
            return CreateOrFindResult(IdempotencyOutcome.CREATED, failed)

        running = await self._store.transition(
            authorised.operation_id,
            TransitionRequest(
                expected_state_version=authorised.state_version,
                to_state=OperationState.RUNNING,
                effect_knowledge=EffectKnowledge.NONE,
                reason_code="dispatch_attempt_recorded",
            ),
        )
        try:
            await self._required_audit(
                self._state_event(
                    running,
                    old_state=OperationState.AUTHORISED.value,
                    reason_code="dispatch_attempt_recorded",
                )
            )
            await self._required_audit(
                self._effect_event(
                    running,
                    kind="effect.intent_recorded",
                    effect_type=request.effect_type,
                    target_digest=request.normalized_target_digest,
                    effect_knowledge=EffectKnowledge.NONE,
                    reason_code="effect_intent_recorded",
                )
            )
        except RequiredAuditError:
            failed = await self._fail_known_no_effect(
                running, code="audit_unavailable", reason="effect_intent_audit_failed"
            )
            return CreateOrFindResult(IdempotencyOutcome.CREATED, failed)

        result = await self._dispatch(request, running)
        return CreateOrFindResult(IdempotencyOutcome.CREATED, result)

    async def _dispatch(
        self, request: CoordinatedOperationRequest, running: OperationSnapshot
    ) -> OperationSnapshot:
        async with self._handoff_gate.hold(running.operation_id):
            permit = await self._consequential_gate.acquire()
            current = await self._store.get_operation(running.operation_id)
            if current is None:
                await self._consequential_gate.release(permit)
                raise RuntimeError("operation disappeared before boundary revalidation")
            check = OperationBoundaryCheck(
                operation_id=current.operation_id,
                expected_state_version=current.state_version,
                predicates=request.boundary_predicates,
            )
            boundary = await self._final_boundary.verify(snapshot=current, check=check)
            if not boundary.allowed:
                await self._consequential_gate.release(permit)
                latest = await self._store.get_operation(current.operation_id)
                if latest is None:
                    raise RuntimeError("operation disappeared after boundary rejection")
                if (
                    latest.state is not OperationState.RUNNING
                    or latest.state_version != current.state_version
                ):
                    return latest
                failed = await self._fail_known_no_effect(
                    latest,
                    code="boundary_revalidation_failed",
                    reason=boundary.reason_code,
                )
                await self._required_audit(
                    self._state_event(
                        failed,
                        old_state=OperationState.RUNNING.value,
                        reason_code=boundary.reason_code,
                    )
                )
                return failed
            obligation = AuditObligation(
                schema_version="1",
                obligation_id=f"obl_{secrets.token_hex(16)}",
                operation_id=current.operation_id,
                running_state_version=current.state_version,
            )
            try:
                await self._obligations.publish(obligation)
            except Exception as exc:
                await self._consequential_gate.trip("audit_obligation_publish_failed")
                await self._latch_failure("audit_obligation_publish_failed")
                await self._consequential_gate.release(permit)
                raise RequiredAuditError("audit obligation could not be made durable") from exc
            effect_request = EffectRequest(
                operation_id=current.operation_id,
                running_state_version=current.state_version,
                effect_type=request.effect_type,
                protected_arguments=request.protected_effect_arguments,
            )
            try:
                receipt = await self._consequential_gate.call_start(
                    permit, self._effect_boundary, effect_request
                )
            except BoundaryGateError:
                await self._consequential_gate.release(permit)
                return current
            except Exception:  # noqa: BLE001 - any lost adapter response is uncertain.
                try:
                    uncertain = await self._store.transition(
                        current.operation_id,
                        TransitionRequest(
                            expected_state_version=current.state_version,
                            to_state=OperationState.UNCERTAIN,
                            effect_knowledge=EffectKnowledge.UNCERTAIN,
                            reason_code="effect_start_response_lost",
                            error=OperationError(
                                "operation_uncertain",
                                "Effect dispatch may have crossed the boundary; "
                                "reconcile before retry.",
                                "reconcile",
                            ),
                        ),
                    )
                except Exception:
                    await self._consequential_gate.complete_start(permit)
                    await self._consequential_gate.trip("effect_receipt_classification_failed")
                    await self._latch_failure("effect_receipt_classification_failed")
                    raise
                await self._consequential_gate.complete_start(permit)
                await self._finish_obligation_audit(
                    obligation,
                    self._effect_event(
                        uncertain,
                        kind="effect.uncertain",
                        effect_type=request.effect_type,
                        target_digest=request.normalized_target_digest,
                        effect_knowledge=EffectKnowledge.UNCERTAIN,
                        reason_code="effect_start_response_lost",
                        obligation_id=obligation.obligation_id,
                        obligation_state_version=obligation.running_state_version,
                    ),
                )
                await self._required_audit(
                    self._state_event(
                        uncertain,
                        old_state=OperationState.RUNNING.value,
                        reason_code="effect_start_response_lost",
                    )
                )
                return uncertain
            try:
                classified = await self._classify_receipt(current, receipt)
            except Exception:
                await self._consequential_gate.complete_start(permit)
                await self._consequential_gate.trip("effect_receipt_classification_failed")
                await self._latch_failure("effect_receipt_classification_failed")
                raise
            await self._consequential_gate.complete_start(permit)
            post_event = self._effect_event(
                classified,
                kind=self._receipt_event_kind(receipt),
                effect_type=request.effect_type,
                target_digest=request.normalized_target_digest,
                effect_knowledge=classified.effect_knowledge,
                reason_code=receipt.reason_code,
                obligation_id=obligation.obligation_id,
                obligation_state_version=obligation.running_state_version,
            )
            await self._finish_obligation_audit(obligation, post_event)
            if classified.state_version != running.state_version:
                await self._required_audit(
                    self._state_event(
                        classified,
                        old_state=OperationState.RUNNING.value,
                        reason_code=receipt.reason_code,
                    )
                )
            return classified

    async def _classify_receipt(
        self, running: OperationSnapshot, receipt: EffectStartReceipt
    ) -> OperationSnapshot:
        current = await self._store.get_operation(running.operation_id)
        if current is None:
            raise RuntimeError("operation disappeared after effect receipt")
        reference_digest = receipt.reference_digest
        if receipt.reference is not None and reference_digest is None:
            reference_digest = hashlib.sha256(
                b"binnacle.effect-reference.v1\0" + receipt.reference.encode()
            ).hexdigest()
        if receipt.terminal_state is None:
            return await self._store.record_effect_start(
                current.operation_id,
                expected_state_version=current.state_version,
                effect_knowledge=receipt.effect_knowledge,
                effect_reference=receipt.reference,
                effect_reference_digest=reference_digest,
            )
        error: OperationError | None = None
        if receipt.terminal_state is OperationState.FAILED:
            error = OperationError(receipt.reason_code, "Effect boundary reported failure.")
        elif receipt.terminal_state is OperationState.UNCERTAIN:
            error = OperationError(
                "operation_uncertain",
                "Effect outcome is uncertain; reconcile before retry.",
                "reconcile",
            )
        return await self._store.transition(
            current.operation_id,
            TransitionRequest(
                expected_state_version=current.state_version,
                to_state=receipt.terminal_state,
                effect_knowledge=receipt.effect_knowledge,
                reason_code=receipt.reason_code,
                error=error,
                effect_reference=receipt.reference,
                effect_reference_digest=reference_digest,
            ),
        )

    async def _finish_obligation_audit(
        self, obligation: AuditObligation, event: AuditEventDraft
    ) -> None:
        try:
            await self._required_audit(event)
        except RequiredAuditError:
            return
        try:
            await self._obligations.remove(obligation.obligation_id)
        except Exception as exc:
            await self._consequential_gate.trip("audit_obligation_cleanup_failed")
            await self._latch_failure("audit_obligation_cleanup_failed")
            raise RequiredAuditError("audit obligation cleanup was not durable") from exc

    async def _required_audit(self, draft: AuditEventDraft) -> None:
        try:
            result = await self._audit.append(draft)
            await self._store.update_audit_tail_cache(AuditTail(result.sequence, result.event_hash))
        except Exception as exc:
            await self._consequential_gate.trip("audit_unavailable")
            await self._latch_failure("audit_unavailable")
            raise RequiredAuditError("required audit persistence failed") from exc

    async def _latch_failure(self, reason: str) -> None:
        try:
            await self._store.latch_audit_failure(reason)
        except Exception:  # noqa: BLE001 - gate remains closed if durable latch also fails.
            # The in-memory gate remains tripped and a durable obligation, when published,
            # remains the independent restart-visible recovery marker.
            return

    async def _fail_known_no_effect(
        self, snapshot: OperationSnapshot, *, code: str, reason: str
    ) -> OperationSnapshot:
        latest = await self._store.get_operation(snapshot.operation_id)
        if latest is None:
            raise RuntimeError("operation disappeared during failure classification")
        if latest.state_version != snapshot.state_version or latest.state is not snapshot.state:
            return latest
        return await self._store.transition(
            latest.operation_id,
            TransitionRequest(
                expected_state_version=latest.state_version,
                to_state=OperationState.FAILED,
                effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                reason_code=reason,
                error=OperationError(code, "Consequential boundary was not crossed."),
            ),
        )

    @staticmethod
    def _receipt_event_kind(receipt: EffectStartReceipt) -> str:
        if receipt.crossing is BoundaryCrossing.UNCERTAIN:
            return "effect.uncertain"
        if receipt.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED:
            return "effect.failed"
        return "effect.observed" if receipt.terminal_state else "effect.started"

    @staticmethod
    def _state_event(
        operation: OperationSnapshot,
        *,
        old_state: str | None,
        reason_code: str,
        idempotency_digest: str | None = None,
    ) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="info",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            idempotency_digest=idempotency_digest,
            payload={
                "kind": "operation.state_changed",
                "old_state": old_state,
                "new_state": operation.state.value,
                "state_version": operation.state_version,
                "effect_knowledge": operation.effect_knowledge.value,
                "result_digest": None,
                "reason_code": reason_code,
            },
        )

    @staticmethod
    def _policy_event(
        operation: OperationSnapshot, allowed: bool, reason_code: str
    ) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="info" if allowed else "warning",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            payload={
                "kind": "policy.decision",
                "decision": "allowed" if allowed else "rejected",
                "rule_id": "bootstrap-policy",
                "reason_code": reason_code,
                "normalized_target_digest": operation.intent.request_fingerprint_sha256,
                "resource_digests": [],
            },
        )

    @staticmethod
    def _effect_event(
        operation: OperationSnapshot,
        *,
        kind: str,
        effect_type: str,
        target_digest: str,
        effect_knowledge: EffectKnowledge,
        reason_code: str,
        obligation_id: str | None = None,
        obligation_state_version: int | None = None,
    ) -> AuditEventDraft:
        safe_facts: tuple[Mapping[str, object], ...] = ()
        correlations: tuple[str, ...] = ()
        if obligation_id is not None:
            correlations = (obligation_id,)
            safe_facts = (
                {
                    "name": "running_state_version",
                    "value": obligation_state_version,
                    "classification": "normal-result",
                },
            )
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="warning" if kind in {"effect.failed", "effect.uncertain"} else "info",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            correlation_ids=correlations,
            safe_facts=safe_facts,
            payload={
                "kind": kind,
                "effect_type": effect_type,
                "target_digest": target_digest,
                "payload_digest": None,
                "actual_destination_digest": None,
                "credential_audience_digest": None,
                "bytes": 0,
                "items": 0,
                "effect_knowledge": effect_knowledge.value,
                "reason_code": reason_code,
            },
        )


class OperationService:
    """Internal-only operation status and cancellation use cases."""

    def __init__(self, store: OperationStore, handoff_gate: DispatchHandoffGate) -> None:
        self._store = store
        self._handoff_gate = handoff_gate

    async def get_operation(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot:
        operation = await self._store.get_operation(operation_id)
        if operation is None:
            raise RuntimeError("operation_not_found")
        if (
            operation.owner.controller_id != owner.controller_id
            or operation.owner.controller_epoch != owner.controller_epoch
        ):
            raise RuntimeError("operation_owner_mismatch")
        return operation

    async def request_cancel(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot:
        async with self._handoff_gate.hold(operation_id):
            operation = await self.get_operation(operation_id, owner)
            if operation.state is OperationState.AUTHORISED:
                return await self._store.transition(
                    operation_id,
                    TransitionRequest(
                        expected_state_version=operation.state_version,
                        to_state=OperationState.CANCELLED,
                        effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                        reason_code="cancelled_before_dispatch",
                    ),
                )
            if operation.state in {
                OperationState.RUNNING,
                OperationState.PAUSED,
            }:
                return await self._store.transition(
                    operation_id,
                    TransitionRequest(
                        expected_state_version=operation.state_version,
                        to_state=OperationState.CANCELLING,
                        effect_knowledge=operation.effect_knowledge,
                        reason_code="cancellation_requested",
                    ),
                )
            raise RuntimeError("cancellation_not_supported")

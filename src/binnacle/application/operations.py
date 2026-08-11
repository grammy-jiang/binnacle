"""Durable consequential-operation admission and synthetic dispatch coordinator."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from binnacle.application.boundary import (
    BoundaryGateError,
    ConsequentialBoundaryGate,
    ConsequentialPermit,
    DispatchHandoffGate,
    FinalBoundaryService,
    PermitState,
)
from binnacle.application.trusted_time import TrustedTimeGuard
from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.idempotency import (
    IdempotencyKeyMode,
    IdempotencyOutcome,
    owner_digest,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationOwner,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue, PolicyRequest
from binnacle.domain.trusted_time import DeadlineStatus
from binnacle.ports.audit import AuditJournal, AuditObligation, AuditObligationStore
from binnacle.ports.boundary import (
    BoundaryDisposition,
    OperationBoundaryCheck,
    PreparedStateCheck,
    PreparedStateVerifier,
)
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectBoundary,
    EffectRequest,
    EffectStartReceipt,
    validate_effect_start_receipt,
)
from binnacle.ports.operation_store import (
    CreateOrFindRequest,
    CreateOrFindResult,
    OperationStore,
    PreparedExecutionAdmission,
)
from binnacle.ports.policy import PolicyEngine


class KernelOperationStore(OperationStore, Protocol):
    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def latch_audit_failure(self, reason_code: str) -> int: ...


class RequiredAuditError(RuntimeError):
    pass


class OperationAuthoriser(Protocol):
    async def authorise(
        self,
        *,
        operation: OperationSnapshot,
        decision: PolicyDecision,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot: ...


@dataclass(frozen=True, slots=True)
class CoordinatedOperationRequest:
    admission: CreateOrFindRequest
    required_scope_digest: str | None
    normalized_target_digest: str
    boundary_predicates: Mapping[str, str | bool | int | None]
    effect_type: str
    protected_effect_arguments: Mapping[str, object]
    prepared_state_facts: Mapping[str, str] | None = None
    prepared_execution: PreparedExecutionAdmission | None = None


class _DefaultOperationAuthoriser:
    def __init__(self, store: KernelOperationStore) -> None:
        self._store = store

    async def authorise(
        self,
        *,
        operation: OperationSnapshot,
        decision: PolicyDecision,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        del request
        await self._store.store_policy_decision(decision)
        return await self._store.transition(
            operation.operation_id,
            TransitionRequest(
                expected_state_version=operation.state_version,
                to_state=OperationState.AUTHORISED,
                effect_knowledge=EffectKnowledge.NONE,
                reason_code="policy_allowed",
            ),
        )


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
        trusted_time_guard: TrustedTimeGuard | None = None,
        prepared_state_verifier: PreparedStateVerifier | None = None,
        authoriser: OperationAuthoriser | None = None,
    ) -> None:
        self._store = store
        self._policy = policy
        self._audit = audit
        self._obligations = obligations
        self._handoff_gate = handoff_gate
        self._consequential_gate = consequential_gate
        self._final_boundary = final_boundary
        self._effect_boundary = effect_boundary
        self._trusted_time_guard = trusted_time_guard
        self._prepared_state_verifier = prepared_state_verifier
        self._authoriser = authoriser or _DefaultOperationAuthoriser(store)

    async def execute(self, request: CoordinatedOperationRequest) -> CreateOrFindResult:
        admitted = await self._create_or_find(request)
        if admitted.outcome is not IdempotencyOutcome.CREATED or admitted.operation is None:
            await self._audit_idempotency_outcome(request, admitted)
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
        if decision.decision is PolicyDecisionValue.DENY:
            await self._store.store_policy_decision(decision)
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

        prepared_allowed = True
        prepared_reason = "prepared_state_not_applicable"
        if request.prepared_execution is not None:
            prepared_allowed, prepared_reason = await self._prepared_revalidation(
                request,
                operation_id=operation.operation_id,
            )
        if not prepared_allowed:
            await self._store.store_policy_decision(decision)
            rejected = await self._store.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.REJECTED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code=prepared_reason,
                    error=OperationError(
                        prepared_reason,
                        "Prepared state changed before post-policy admission.",
                    ),
                ),
            )
            await self._required_audit(self._policy_event(rejected, True, "policy_allowed"))
            await self._required_audit(
                self._state_event(
                    rejected,
                    old_state=OperationState.RECEIVED.value,
                    reason_code=prepared_reason,
                )
            )
            return CreateOrFindResult(IdempotencyOutcome.CREATED, rejected)

        authorised = await self._authoriser.authorise(
            operation=operation,
            decision=decision,
            request=request,
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
            try:
                current = await self._store.get_operation(running.operation_id)
                if current is None:
                    raise RuntimeError("operation disappeared before boundary revalidation")
                prepared_allowed, prepared_reason = await self._prepared_revalidation(
                    request,
                    operation_id=current.operation_id,
                )
                if not prepared_allowed:
                    await self._consequential_gate.release(permit)
                    failed = await self._fail_known_no_effect(
                        current,
                        code=prepared_reason,
                        reason=prepared_reason,
                    )
                    await self._required_audit(
                        self._state_event(
                            failed,
                            old_state=OperationState.RUNNING.value,
                            reason_code=prepared_reason,
                        )
                    )
                    return failed
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
                    code = (
                        boundary.reason_code
                        if boundary.disposition is BoundaryDisposition.KNOWN_NO_EFFECT
                        else "boundary_revalidation_failed"
                    )
                    failed = await self._fail_known_no_effect(
                        latest,
                        code=code,
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
                task = asyncio.create_task(
                    self._run_committed_dispatch(
                        request=request,
                        running=running,
                        current=current,
                        permit=permit,
                        obligation=obligation,
                        effect_request=effect_request,
                    )
                )
                cancelled = False
                while True:
                    try:
                        result = await asyncio.shield(task)
                        break
                    except asyncio.CancelledError:
                        cancelled = True
                        if task.done():
                            result = task.result()
                            break
                if cancelled:
                    raise asyncio.CancelledError
                return result
            finally:
                if permit.state is PermitState.PRE_START:
                    await self._consequential_gate.release(permit)

    async def _run_committed_dispatch(
        self,
        *,
        request: CoordinatedOperationRequest,
        running: OperationSnapshot,
        current: OperationSnapshot,
        permit: ConsequentialPermit,
        obligation: AuditObligation,
        effect_request: EffectRequest,
    ) -> OperationSnapshot:
        try:
            receipt = await self._consequential_gate.call_start(
                permit, self._effect_boundary, effect_request
            )
        except BoundaryGateError:
            if permit.state is PermitState.START_COMMITTED:
                # The adapter may itself raise BoundaryGateError. Once call_start has
                # committed the permit, that exception is a lost response and can never
                # be treated as proof that the effect boundary was not crossed.
                return await self._classify_lost_start_response(
                    request=request,
                    current=current,
                    permit=permit,
                    obligation=obligation,
                )
            await self._consequential_gate.release(permit)
            failed = await self._fail_known_no_effect(
                current,
                code="audit_unavailable",
                reason="consequential_permit_revoked",
            )
            await self._finish_obligation_audit(
                obligation,
                self._effect_event(
                    failed,
                    kind="effect.failed",
                    effect_type=request.effect_type,
                    target_digest=request.normalized_target_digest,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code="consequential_permit_revoked",
                    obligation_id=obligation.obligation_id,
                    obligation_state_version=obligation.running_state_version,
                ),
            )
            await self._required_audit(
                self._state_event(
                    failed,
                    old_state=OperationState.RUNNING.value,
                    reason_code="consequential_permit_revoked",
                )
            )
            return failed
        except (Exception, asyncio.CancelledError):  # noqa: BLE001
            return await self._classify_lost_start_response(
                request=request,
                current=current,
                permit=permit,
                obligation=obligation,
            )
        try:
            classified = await self._classify_receipt(current, receipt)
        except (Exception, asyncio.CancelledError):
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

    async def _classify_lost_start_response(
        self,
        *,
        request: CoordinatedOperationRequest,
        current: OperationSnapshot,
        permit: ConsequentialPermit,
        obligation: AuditObligation,
    ) -> OperationSnapshot:
        """Persist uncertainty for every exception after start is committed."""

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
                        "Effect dispatch may have crossed the boundary; reconcile before retry.",
                        "reconcile",
                    ),
                ),
            )
        except (Exception, asyncio.CancelledError):
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

    async def _classify_receipt(
        self, running: OperationSnapshot, receipt: EffectStartReceipt
    ) -> OperationSnapshot:
        validate_effect_start_receipt(receipt)
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

    async def _admission_with_prepared_revalidation(
        self, request: CoordinatedOperationRequest
    ) -> CreateOrFindRequest:
        if request.admission.key.mode is not IdempotencyKeyMode.PREPARED_EXECUTION_NONCE:
            return request.admission
        allowed, reason, digest = await self._prepared_revalidation_details(
            request,
            operation_id=None,
        )
        status = DeadlineStatus.VALID
        if reason == IdempotencyOutcome.PREPARED_EXPIRED.value:
            status = DeadlineStatus.EXPIRED
        elif not allowed and reason == IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE.value:
            status = DeadlineStatus.UNAVAILABLE
        return replace(
            request.admission,
            prepared_deadline_status=status,
            verified_prepared_state_binding_sha256=digest,
        )

    async def _create_or_find(self, request: CoordinatedOperationRequest) -> CreateOrFindResult:
        prepared = request.prepared_execution
        if prepared is None:
            admission = await self._admission_with_prepared_revalidation(request)
            return await self._store.create_or_find(admission)
        if prepared.caller != request.admission:
            raise ValueError("prepared caller admission does not match coordinated request")
        retained = await self._store.find_existing(request.admission)
        if retained is not None:
            return retained
        allowed, reason, digest = await self._prepared_revalidation_details(
            request,
            operation_id=None,
        )
        status = DeadlineStatus.VALID
        if reason == IdempotencyOutcome.PREPARED_EXPIRED.value:
            status = DeadlineStatus.EXPIRED
        elif not allowed and reason == IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE.value:
            status = DeadlineStatus.UNAVAILABLE
        caller = replace(
            request.admission,
            prepared_state_binding_sha256=digest,
            prepared_deadline_status=status,
            verified_prepared_state_binding_sha256=digest,
        )
        return await self._store.create_or_find_prepared(
            PreparedExecutionAdmission(caller=caller, prepared_key=prepared.prepared_key)
        )

    async def _prepared_revalidation(
        self,
        request: CoordinatedOperationRequest,
        *,
        operation_id: str,
    ) -> tuple[bool, str]:
        if (
            request.prepared_execution is None
            and request.admission.key.mode is not IdempotencyKeyMode.PREPARED_EXECUTION_NONCE
        ):
            return True, "prepared_state_not_applicable"
        allowed, reason, _ = await self._prepared_revalidation_details(
            request,
            operation_id=operation_id,
        )
        return allowed, reason

    async def _prepared_revalidation_details(
        self,
        request: CoordinatedOperationRequest,
        *,
        operation_id: str | None,
    ) -> tuple[bool, str, str | None]:
        admission = request.admission
        if request.prepared_execution is not None:
            admission = replace(admission, key=request.prepared_execution.prepared_key)
        retained = await self._store.get_prepared_execution(admission)
        if retained is None:
            return False, IdempotencyOutcome.PREPARED_MISMATCH.value, None
        if self._trusted_time_guard is None:
            return False, IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE.value, None
        deadline = await self._trusted_time_guard.evaluate(
            expires_at=retained.prepared_expires_at,
            registered_boot_id_digest=retained.registered_boot_id_digest,
            monotonic_deadline_ns=retained.monotonic_deadline_ns,
        )
        if deadline.status is DeadlineStatus.EXPIRED:
            return False, IdempotencyOutcome.PREPARED_EXPIRED.value, None
        if deadline.status is not DeadlineStatus.VALID:
            return False, IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE.value, None
        if self._prepared_state_verifier is None or request.prepared_state_facts is None:
            return False, IdempotencyOutcome.PREPARED_MISMATCH.value, None
        try:
            digest = await self._prepared_state_verifier.current_state_digest(
                PreparedStateCheck(
                    operation_id=operation_id,
                    prepared_operation_id=retained.prepared_operation_id,
                    protected_facts=request.prepared_state_facts,
                )
            )
        except Exception:  # noqa: BLE001 - state-verifier failure is fail closed.
            return False, IdempotencyOutcome.PREPARED_MISMATCH.value, None
        if digest != retained.prepared_state_binding_sha256:
            return False, IdempotencyOutcome.PREPARED_MISMATCH.value, digest
        return True, "prepared_state_verified", digest

    async def _audit_idempotency_outcome(
        self,
        request: CoordinatedOperationRequest,
        result: CreateOrFindResult,
    ) -> None:
        audited = {
            IdempotencyOutcome.CONFLICT,
            IdempotencyOutcome.OWNER_MISMATCH,
            IdempotencyOutcome.KEY_RETIRED,
            IdempotencyOutcome.PREPARED_MISMATCH,
        }
        if result.outcome not in audited:
            return
        retained = None
        if result.outcome in {
            IdempotencyOutcome.CONFLICT,
            IdempotencyOutcome.PREPARED_MISMATCH,
        }:
            retained = await self._store.get_idempotency_conflict_operation(request.admission)
        if retained is not None:
            await self._required_audit(
                self._idempotency_conflict_event(
                    retained,
                    reason_code=result.outcome.value,
                    idempotency_digest=request.admission.key.digest_sha256,
                )
            )
            return
        await self._required_audit(
            self._preoperation_idempotency_rejection_event(
                request,
                reason_code=result.outcome.value,
            )
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
            with suppress(Exception):
                await self._audit.append_emergency(
                    reason_code="audit_unavailable",
                    operation_id=draft.operation_id,
                    source_event_id=draft.event_id,
                )
            raise RequiredAuditError("required audit persistence failed") from exc

    async def record_required_audit(self, draft: AuditEventDraft) -> None:
        """Append one schema-valid operation-owned audit fact through the kernel gate."""

        await self._required_audit(draft)

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
    def _idempotency_conflict_event(
        operation: OperationSnapshot,
        *,
        reason_code: str,
        idempotency_digest: str,
    ) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="warning",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            idempotency_digest=idempotency_digest,
            payload={
                "kind": "operation.idempotency_conflict",
                "old_state": operation.state.value,
                "new_state": operation.state.value,
                "state_version": operation.state_version,
                "effect_knowledge": operation.effect_knowledge.value,
                "result_digest": None,
                "reason_code": reason_code,
            },
        )

    @staticmethod
    def _preoperation_idempotency_rejection_event(
        request: CoordinatedOperationRequest,
        *,
        reason_code: str,
    ) -> AuditEventDraft:
        return AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="warning",
            source="binnacle_system",
            controller_id_digest=owner_digest(request.admission.owner),
            operation_id=None,
            idempotency_digest=request.admission.key.digest_sha256,
            payload={
                "kind": "policy.decision",
                "decision": "rejected",
                "rule_id": "idempotency-boundary",
                "reason_code": reason_code,
                "normalized_target_digest": request.normalized_target_digest,
                "resource_digests": [],
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

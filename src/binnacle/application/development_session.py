"""Session-authority linearization for Phase 6 content and mutation admission."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from binnacle.application.operations import CoordinatedOperationRequest, OperationAuthorityError
from binnacle.application.workspace_coordination import ContentReadGuard
from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionError,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    SessionAuthorityFacts,
    SessionIneffectiveReason,
    evaluate_pending_activation_authority,
    evaluate_session_authority,
    new_pending_session,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    Terminality,
)
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.workspace import ContentReadPermit, validate_sha256
from binnacle.ports.boundary import BoundaryCheckResult, OperationBoundaryCheck
from binnacle.ports.development_session import (
    DevelopmentSessionRepository,
    SessionAuthorisationRequest,
)
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectRequest,
    EffectStartReceipt,
)


class DevelopmentSessionAuthorityError(OperationAuthorityError):
    """The current session cannot grant the requested bounded authority."""


SessionReader = Callable[[str], Awaitable[DevelopmentSessionSnapshot | None]]
AuthorityFactsReader = Callable[[DevelopmentSessionSnapshot], Awaitable[SessionAuthorityFacts]]
AuthorityReducer = Callable[[DevelopmentSessionSnapshot], Awaitable[DevelopmentSessionSnapshot]]


@dataclass(frozen=True, slots=True)
class SessionStartGuard:
    snapshot: DevelopmentSessionSnapshot
    facts: SessionAuthorityFacts


@dataclass(frozen=True, slots=True)
class SessionReservationRequest:
    operation: OperationSnapshot
    session_id: str
    workspace_id: str
    workspace_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    policy_version: str
    contract_profile_sha256: str
    objective_sha256: str
    expires_at: datetime
    trusted_time_generation: int
    activation_boot_id_digest: str
    monotonic_deadline_ns: int
    now: datetime


SessionReservationReader = Callable[
    [OperationSnapshot, CoordinatedOperationRequest],
    Awaitable[SessionReservationRequest],
]
SessionClosureVerifier = Callable[
    [OperationSnapshot, DevelopmentSessionSnapshot],
    Awaitable[bool],
]


class DevelopmentSessionAuthorityGate:
    """Serialize authority admission and reduction for exact durable sessions."""

    def __init__(
        self,
        *,
        session_reader: SessionReader,
        facts_reader: AuthorityFactsReader,
    ) -> None:
        self._session_reader = session_reader
        self._facts_reader = facts_reader
        self._registry_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    async def admit_content_read(
        self,
        *,
        session_id: str,
        workspace_id: str,
        request_sha256: str,
        content_guard: ContentReadGuard,
    ) -> ContentReadPermit:
        """Mint one ephemeral permit while the caller still owns CONTENT_READ."""

        validate_sha256(request_sha256, name="request_sha256")
        if content_guard.released or content_guard.workspace_id != workspace_id:
            raise DevelopmentSessionAuthorityError("content guard is stale or foreign")
        lock = await self._lock_for(session_id)
        async with lock:
            snapshot, _facts = await self._require_effective(session_id, workspace_id)
            return ContentReadPermit(
                permit_id=f"permit_{secrets.token_hex(12)}",
                session_id=snapshot.session_id,
                session_state_version=snapshot.state_version,
                workspace_id=snapshot.workspace_id,
                workspace_profile_sha256=snapshot.workspace_profile_sha256,
                root_identity_sha256=snapshot.workspace_root_identity_sha256,
                mount_identity_sha256=snapshot.workspace_mount_identity_sha256,
                request_sha256=request_sha256,
                content_guard_epoch=content_guard.epoch,
            )

    @asynccontextmanager
    async def hold_member_start(
        self,
        *,
        session_id: str,
        workspace_id: str,
    ) -> AsyncIterator[SessionStartGuard]:
        """Hold the session gate through the caller's immediate effect classification."""

        lock = await self._lock_for(session_id)
        async with lock:
            snapshot, facts = await self._require_effective(session_id, workspace_id)
            yield SessionStartGuard(snapshot, facts)

    @asynccontextmanager
    async def hold_activation_start(
        self,
        *,
        session_id: str,
        begin_operation_id: str,
        expected_state_version: int,
    ) -> AsyncIterator[DevelopmentSessionSnapshot]:
        """Hold exact PENDING authority state around the Phase 4 process gate."""

        lock = await self._lock_for(session_id)
        async with lock:
            snapshot = await self._session_reader(session_id)
            if snapshot is None:
                raise DevelopmentSessionAuthorityError("development session is unavailable")
            if (
                snapshot.state is not DevelopmentSessionState.PENDING
                or snapshot.begin_operation_id != begin_operation_id
                or snapshot.state_version != expected_state_version
            ):
                raise DevelopmentSessionAuthorityError("pending session activation is stale")
            facts = await self._facts_reader(snapshot)
            effectiveness = evaluate_pending_activation_authority(snapshot, facts)
            if not effectiveness.effective:
                reason = effectiveness.reason or SessionIneffectiveReason.KERNEL_UNAVAILABLE
                raise DevelopmentSessionAuthorityError(reason.value)
            yield snapshot

    async def mutate_authority(
        self,
        *,
        session_id: str,
        mutator: AuthorityReducer,
    ) -> DevelopmentSessionSnapshot:
        """Serialize every durable session mutation with member/activation admission."""

        lock = await self._lock_for(session_id)
        async with lock:
            snapshot = await self._session_reader(session_id)
            if snapshot is None:
                raise DevelopmentSessionAuthorityError("development session is unavailable")
            return await mutator(snapshot)

    async def reduce_authority(
        self,
        *,
        session_id: str,
        reducer: AuthorityReducer,
    ) -> DevelopmentSessionSnapshot:
        """Run one durable authority-reducing transition under the same gate."""

        return await self.mutate_authority(session_id=session_id, mutator=reducer)

    async def _require_effective(
        self,
        session_id: str,
        workspace_id: str,
    ) -> tuple[DevelopmentSessionSnapshot, SessionAuthorityFacts]:
        snapshot = await self._session_reader(session_id)
        if snapshot is None or snapshot.workspace_id != workspace_id:
            raise DevelopmentSessionAuthorityError("development session is unavailable")
        facts = await self._facts_reader(snapshot)
        effectiveness = evaluate_session_authority(snapshot, facts)
        if not effectiveness.effective:
            reason = "development_session_not_effective"
            if effectiveness.reason is not None:
                reason = effectiveness.reason.value
            raise DevelopmentSessionAuthorityError(reason)
        return snapshot, facts

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        if not session_id:
            raise DevelopmentSessionAuthorityError("session_id is required")
        async with self._registry_lock:
            return self._locks.setdefault(session_id, asyncio.Lock())


class DevelopmentSessionService:
    """Durable session reservation/closure operations used by a future activation."""

    def __init__(
        self,
        *,
        repository: DevelopmentSessionRepository,
        authority_gate: DevelopmentSessionAuthorityGate,
    ) -> None:
        self._repository = repository
        self._authority_gate = authority_gate

    async def close_activation(
        self,
        *,
        operation: OperationSnapshot,
        closed_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        if (
            operation.state is not OperationState.SUCCEEDED
            or operation.effect_knowledge is not EffectKnowledge.KNOWN_EFFECT
            or operation.effect_reference is None
            or operation.effect_reference_digest is None
        ):
            raise DevelopmentSessionError("activation operation lacks exact known-effect proof")
        session = await self._repository.get_by_begin_operation(operation.operation_id)
        if session is None:
            raise DevelopmentSessionError("activation closure evidence is inconsistent")

        async def close_exact(
            current: DevelopmentSessionSnapshot,
        ) -> DevelopmentSessionSnapshot:
            if (
                current.begin_operation_id != operation.operation_id
                or current.state is DevelopmentSessionState.PENDING
                or current.activation_closure is not ActivationClosure.PENDING
                or current.activation_effect_reference != operation.effect_reference
                or current.activation_effect_reference_sha256 != operation.effect_reference_digest
            ):
                raise DevelopmentSessionError("activation closure evidence is inconsistent")
            return await self._repository.complete_activation(
                session_id=current.session_id,
                expected_state_version=current.state_version,
                closed_at=closed_at,
            )

        return await self._authority_gate.mutate_authority(
            session_id=session.session_id,
            mutator=close_exact,
        )

    async def close_no_effect_activation(
        self,
        *,
        operation: OperationSnapshot,
        closed_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        """Durably close a terminal never-started activation after exact audit proof."""

        if (
            operation.terminality is not Terminality.TERMINAL
            or operation.effect_knowledge is not EffectKnowledge.KNOWN_NO_EFFECT
            or operation.effect_reference is not None
            or operation.effect_reference_digest is not None
        ):
            raise DevelopmentSessionError("activation operation lacks exact no-effect proof")
        session = await self._repository.get_by_begin_operation(operation.operation_id)
        if session is None:
            raise DevelopmentSessionError("activation closure evidence is inconsistent")

        async def close_exact(
            current: DevelopmentSessionSnapshot,
        ) -> DevelopmentSessionSnapshot:
            if (
                current.begin_operation_id != operation.operation_id
                or current.state
                not in {
                    DevelopmentSessionState.ENDED,
                    DevelopmentSessionState.EXPIRED,
                    DevelopmentSessionState.REVOKED,
                }
                or current.started_at is not None
                or current.activation_closure is not ActivationClosure.PENDING
                or current.activation_effect_reference is not None
                or current.activation_effect_reference_sha256 is not None
            ):
                raise DevelopmentSessionError("no-effect activation closure is inconsistent")
            return await self._repository.complete_activation(
                session_id=current.session_id,
                expected_state_version=current.state_version,
                closed_at=closed_at,
            )

        return await self._authority_gate.mutate_authority(
            session_id=session.session_id,
            mutator=close_exact,
        )

    async def reduce_authority(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        target: DevelopmentSessionState,
        reason: str,
        terminal_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        async def reduce_exact(
            snapshot: DevelopmentSessionSnapshot,
        ) -> DevelopmentSessionSnapshot:
            if snapshot.state_version != expected_state_version:
                raise DevelopmentSessionError("session reduction state version is stale")
            return await self._repository.reduce(
                session_id=session_id,
                expected_state_version=expected_state_version,
                target=target,
                reason=reason,
                terminal_at=terminal_at,
            )

        return await self._authority_gate.reduce_authority(
            session_id=session_id,
            reducer=reduce_exact,
        )


class SessionBeginAuthoriser:
    """Commit policy, AUTHORISED lifecycle, and one PENDING slot atomically."""

    def __init__(
        self,
        *,
        repository: DevelopmentSessionRepository,
        reservation_reader: SessionReservationReader,
    ) -> None:
        self._repository = repository
        self._reservation_reader = reservation_reader

    async def authorise(
        self,
        *,
        operation: OperationSnapshot,
        decision: PolicyDecision,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        reservation = await self._reservation_reader(operation, request)
        if reservation.operation != operation or operation.state is not OperationState.RECEIVED:
            raise DevelopmentSessionError("session reservation operation is stale")
        pending = _pending_snapshot(reservation)
        authorised, retained = await self._repository.authorise_begin(
            SessionAuthorisationRequest(
                operation=operation,
                decision=decision,
                snapshot=pending,
                required_scope_digest=request.required_scope_digest,
                normalized_target_digest=request.normalized_target_digest,
                authorised_at=reservation.now,
            )
        )
        if (
            authorised.state is not OperationState.AUTHORISED
            or retained.begin_operation_id != authorised.operation_id
            or retained.state is not DevelopmentSessionState.PENDING
        ):
            raise DevelopmentSessionError("session authorisation returned contradictory state")
        return authorised


class SessionActivationClosure:
    """Close or revoke the pending authority row only after required audit proof."""

    def __init__(
        self,
        *,
        service: DevelopmentSessionService,
        repository: DevelopmentSessionRepository,
        closure_verifier: SessionClosureVerifier,
    ) -> None:
        self._service = service
        self._repository = repository
        self._closure_verifier = closure_verifier

    async def close(
        self,
        *,
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        del request
        return await self.close_retained(operation)

    async def close_retained(self, operation: OperationSnapshot) -> OperationSnapshot:
        """Close one retained activation without reconstructing caller input."""

        session = await self._repository.get_by_begin_operation(operation.operation_id)
        if session is None:
            raise DevelopmentSessionError("activation session closure is missing")
        if not await self._closure_verifier(operation, session):
            return operation
        if (
            operation.state is OperationState.SUCCEEDED
            and operation.effect_knowledge is EffectKnowledge.KNOWN_EFFECT
        ):
            if (
                session.state is not DevelopmentSessionState.PENDING
                and session.activation_closure is ActivationClosure.COMPLETE
                and session.activation_effect_reference == operation.effect_reference
                and session.activation_effect_reference_sha256 == operation.effect_reference_digest
            ):
                return operation
            await self._service.close_activation(
                operation=operation,
                closed_at=operation.terminal_at or operation.updated_at,
            )
            return operation
        if (
            operation.terminality is Terminality.TERMINAL
            and operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
        ):
            if (
                session.state
                in {
                    DevelopmentSessionState.ENDED,
                    DevelopmentSessionState.EXPIRED,
                    DevelopmentSessionState.REVOKED,
                }
                and session.started_at is None
                and session.activation_effect_reference is None
                and session.activation_effect_reference_sha256 is None
                and session.activation_closure is ActivationClosure.COMPLETE
            ):
                return operation
            if (
                session.state
                in {
                    DevelopmentSessionState.ENDED,
                    DevelopmentSessionState.EXPIRED,
                    DevelopmentSessionState.REVOKED,
                }
                and session.started_at is None
                and session.activation_effect_reference is None
                and session.activation_effect_reference_sha256 is None
                and session.activation_closure is ActivationClosure.PENDING
            ):
                await self._service.close_no_effect_activation(
                    operation=operation,
                    closed_at=operation.terminal_at or operation.updated_at,
                )
                return operation
            if session.state is not DevelopmentSessionState.PENDING:
                raise DevelopmentSessionError(
                    "known-no-effect activation contradicts retained session state"
                )
            reduced = await self._service.reduce_authority(
                session_id=session.session_id,
                expected_state_version=session.state_version,
                target=DevelopmentSessionState.REVOKED,
                reason="activation_known_no_effect",
                terminal_at=operation.terminal_at or operation.updated_at,
            )
            if reduced.activation_closure is not ActivationClosure.PENDING:
                raise DevelopmentSessionError("no-effect activation closure changed unexpectedly")
            await self._service.close_no_effect_activation(
                operation=operation,
                closed_at=operation.terminal_at or operation.updated_at,
            )
        return operation


def _pending_snapshot(request: SessionReservationRequest) -> DevelopmentSessionSnapshot:
    operation = request.operation
    if operation.state is not OperationState.RECEIVED:
        raise DevelopmentSessionError("session reservation requires a received operation")
    return new_pending_session(
        session_id=request.session_id,
        begin_operation_id=operation.operation_id,
        controller_id=operation.owner.controller_id,
        controller_epoch=operation.owner.controller_epoch,
        device_id=operation.intent.device_id,
        device_epoch=operation.intent.device_epoch,
        workspace_id=request.workspace_id,
        workspace_profile_sha256=request.workspace_profile_sha256,
        workspace_root_identity_sha256=request.workspace_root_identity_sha256,
        workspace_mount_identity_sha256=request.workspace_mount_identity_sha256,
        policy_version=request.policy_version,
        contract_profile_sha256=request.contract_profile_sha256,
        objective_sha256=request.objective_sha256,
        expires_at=request.expires_at,
        trusted_time_generation=request.trusted_time_generation,
        activation_boot_id_digest=request.activation_boot_id_digest,
        monotonic_deadline_ns=request.monotonic_deadline_ns,
        now=request.now,
    )


class SessionActivationBoundaryVerifier:
    """Re-read exact pending authority and accepted trusted time at final OP-BOUNDARY."""

    def __init__(
        self,
        *,
        repository: DevelopmentSessionRepository,
        facts_reader: AuthorityFactsReader,
    ) -> None:
        self._repository = repository
        self._facts_reader = facts_reader

    async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult:
        session = await self._repository.get_by_begin_operation(request.operation_id)
        if session is None:
            return BoundaryCheckResult(False, "session_activation_missing")
        predicates = request.predicates
        if (
            predicates.get("session_id") != session.session_id
            or predicates.get("session_state_version") != session.state_version
            or predicates.get("controller_id") != session.controller_id
            or predicates.get("controller_epoch") != session.controller_epoch
            or predicates.get("device_id") != session.device_id
            or predicates.get("device_epoch") != session.device_epoch
            or predicates.get("workspace_id") != session.workspace_id
            or predicates.get("workspace_profile_sha256") != session.workspace_profile_sha256
            or predicates.get("workspace_root_identity_sha256")
            != session.workspace_root_identity_sha256
            or predicates.get("workspace_mount_identity_sha256")
            != session.workspace_mount_identity_sha256
            or predicates.get("policy_version") != session.policy_version
            or predicates.get("contract_profile_sha256") != session.contract_profile_sha256
            or predicates.get("trusted_time_generation") != session.trusted_time_generation
            or predicates.get("activation_boot_id_digest") != session.activation_boot_id_digest
            or predicates.get("monotonic_deadline_ns") != session.monotonic_deadline_ns
        ):
            return BoundaryCheckResult(False, "session_activation_binding_mismatch")
        facts = await self._facts_reader(session)
        effectiveness = evaluate_pending_activation_authority(session, facts)
        if not effectiveness.effective:
            reason = effectiveness.reason or SessionIneffectiveReason.KERNEL_UNAVAILABLE
            return BoundaryCheckResult(False, reason.value)
        return BoundaryCheckResult(True, "session_activation_verified")


class SessionActivationEffectBoundary:
    """The sole narrow PENDING -> ACTIVE effect boundary."""

    def __init__(
        self,
        repository: DevelopmentSessionRepository,
        *,
        facts_reader: AuthorityFactsReader,
    ) -> None:
        self._repository = repository
        self._facts_reader = facts_reader

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        if request.effect_type != "development_session_activate":
            return _activation_not_started("session_activation_effect_type_unavailable")
        session_id = request.protected_arguments.get("session_id")
        expected_version = request.protected_arguments.get("expected_state_version")
        if (
            not isinstance(session_id, str)
            or not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
        ):
            return _activation_not_started("session_activation_arguments_invalid")
        current = await self._repository.get_by_begin_operation(request.operation_id)
        if (
            current is None
            or current.session_id != session_id
            or current.state is not DevelopmentSessionState.PENDING
            or current.state_version != expected_version
        ):
            return _activation_not_started("session_activation_state_stale")
        facts = await self._facts_reader(current)
        effectiveness = evaluate_pending_activation_authority(current, facts)
        if not effectiveness.effective:
            reason = effectiveness.reason or SessionIneffectiveReason.KERNEL_UNAVAILABLE
            return _activation_not_started(reason.value)
        session_digest = hashlib.sha256(
            b"binnacle.session-activation.v1\0" + session_id.encode("utf-8")
        ).hexdigest()
        reference = f"session_activation:{session_digest}:{expected_version + 1}"
        reference_sha256 = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        activated = await self._repository.activate(
            session_id=session_id,
            expected_state_version=expected_version,
            effect_reference=reference,
            effect_reference_sha256=reference_sha256,
            started_at=facts.wall_time,
        )
        if (
            activated.state is not DevelopmentSessionState.ACTIVE
            or activated.activation_effect_reference != reference
        ):
            raise DevelopmentSessionError("activation repository returned contradictory state")
        return EffectStartReceipt(
            crossing=BoundaryCrossing.CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference=reference,
            reference_digest=reference_sha256,
            terminal_state=OperationState.SUCCEEDED,
            reason_code="development_session_activated",
        )


class SessionActivationDispatchAuthority:
    """Hold the persisted session gate between handoff and process-wide gate."""

    def __init__(
        self,
        *,
        repository: DevelopmentSessionRepository,
        authority_gate: DevelopmentSessionAuthorityGate,
    ) -> None:
        self._repository = repository
        self._authority_gate = authority_gate

    @asynccontextmanager
    async def hold(
        self,
        *,
        operation: OperationSnapshot,
        request: object,
    ) -> AsyncIterator[None]:
        del request
        session = await self._repository.get_by_begin_operation(operation.operation_id)
        if session is None:
            raise DevelopmentSessionAuthorityError("activation session is unavailable")
        async with self._authority_gate.hold_activation_start(
            session_id=session.session_id,
            begin_operation_id=operation.operation_id,
            expected_state_version=session.state_version,
        ):
            yield


def _activation_not_started(reason_code: str) -> EffectStartReceipt:
    return EffectStartReceipt(
        crossing=BoundaryCrossing.DEFINITELY_NOT_CROSSED,
        effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
        terminal_state=OperationState.FAILED,
        reason_code=reason_code,
    )


__all__ = [
    "AuthorityFactsReader",
    "AuthorityReducer",
    "DevelopmentSessionAuthorityError",
    "DevelopmentSessionAuthorityGate",
    "DevelopmentSessionService",
    "SessionActivationBoundaryVerifier",
    "SessionActivationClosure",
    "SessionActivationDispatchAuthority",
    "SessionActivationEffectBoundary",
    "SessionBeginAuthoriser",
    "SessionClosureVerifier",
    "SessionReader",
    "SessionReservationReader",
    "SessionReservationRequest",
    "SessionStartGuard",
]

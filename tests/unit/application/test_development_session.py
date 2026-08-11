from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.phase4_support import intent, owner

from binnacle.application.development_session import (
    DevelopmentSessionAuthorityError,
    DevelopmentSessionAuthorityGate,
    DevelopmentSessionService,
    SessionActivationBoundaryVerifier,
    SessionActivationClosure,
    SessionActivationDispatchAuthority,
    SessionActivationEffectBoundary,
    SessionBeginAuthoriser,
    SessionReservationRequest,
)
from binnacle.application.operations import CoordinatedOperationRequest
from binnacle.application.workspace_coordination import ContentReadGuard
from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionError,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    SessionAuthorityFacts,
    activate_session,
    complete_activation,
    new_pending_session,
    reduce_session,
)
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    new_received_operation,
    transition,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.ports.boundary import OperationBoundaryCheck
from binnacle.ports.development_session import SessionAuthorisationRequest
from binnacle.ports.effect import BoundaryCrossing, EffectRequest
from binnacle.ports.operation_store import CreateOrFindRequest

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
DIGEST = "a" * 64


class MemorySessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, DevelopmentSessionSnapshot] = {}

    async def authorise_begin(
        self, request: SessionAuthorisationRequest
    ) -> tuple[OperationSnapshot, DevelopmentSessionSnapshot]:
        authorised = transition(
            request.operation,
            TransitionRequest(
                request.operation.state_version,
                OperationState.AUTHORISED,
                EffectKnowledge.NONE,
                "policy_allowed",
                occurred_at=request.authorised_at,
            ),
        )
        self.sessions[request.snapshot.session_id] = request.snapshot
        return authorised, request.snapshot

    async def get_session(self, session_id: str) -> DevelopmentSessionSnapshot | None:
        return self.sessions.get(session_id)

    async def require_session(self, session_id: str) -> DevelopmentSessionSnapshot:
        return self.sessions[session_id]

    async def get_by_begin_operation(
        self, begin_operation_id: str
    ) -> DevelopmentSessionSnapshot | None:
        return next(
            (
                item
                for item in self.sessions.values()
                if item.begin_operation_id == begin_operation_id
            ),
            None,
        )

    async def activate(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        effect_reference: str,
        effect_reference_sha256: str,
        started_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        result = activate_session(
            self.sessions[session_id],
            expected_state_version=expected_state_version,
            effect_reference=effect_reference,
            effect_reference_sha256=effect_reference_sha256,
            now=started_at,
        )
        self.sessions[session_id] = result
        return result

    async def complete_activation(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        closed_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        del closed_at
        result = complete_activation(
            self.sessions[session_id], expected_state_version=expected_state_version
        )
        self.sessions[session_id] = result
        return result

    async def reduce(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        target: DevelopmentSessionState,
        reason: str,
        terminal_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        result = reduce_session(
            self.sessions[session_id],
            expected_state_version=expected_state_version,
            target=target,
            reason=reason,
            now=terminal_at,
        )
        self.sessions[session_id] = result
        return result

    async def list_live(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]:
        del after_created_at, after_session_id
        return tuple(self.sessions.values())[:limit]

    async def list_activation_closures(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]:
        del after_created_at, after_session_id
        return tuple(
            item
            for item in self.sessions.values()
            if item.activation_closure is ActivationClosure.PENDING
        )[:limit]

    async def verify_integrity(self) -> None:
        return None


def _session(*, closed: bool = True) -> DevelopmentSessionSnapshot:
    pending = new_pending_session(
        session_id="dev_session",
        begin_operation_id="op_begin",
        controller_id="controller",
        controller_epoch=1,
        device_id="device",
        device_epoch=1,
        workspace_id="workspace",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        objective_sha256=DIGEST,
        expires_at=NOW + timedelta(hours=1),
        trusted_time_generation=1,
        activation_boot_id_digest=DIGEST,
        monotonic_deadline_ns=10_000,
        now=NOW,
    )
    active = activate_session(
        pending,
        expected_state_version=1,
        effect_reference="activation_ref",
        effect_reference_sha256=DIGEST,
        now=NOW + timedelta(seconds=1),
    )
    return complete_activation(active, expected_state_version=2) if closed else active


def _facts() -> SessionAuthorityFacts:
    return SessionAuthorityFacts(
        controller_id="controller",
        controller_epoch=1,
        device_id="device",
        device_epoch=1,
        workspace_id="workspace",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        wall_time=NOW + timedelta(minutes=1),
        wall_time_trusted=True,
        trusted_time_generation=1,
        boot_id_digest=DIGEST,
        monotonic_ns=1_000,
        kernel_consequential_ready=True,
    )


async def _facts_reader(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
    return replace(
        _facts(),
        controller_id=snapshot.controller_id,
        controller_epoch=snapshot.controller_epoch,
        device_id=snapshot.device_id,
        device_epoch=snapshot.device_epoch,
        workspace_id=snapshot.workspace_id,
        workspace_profile_sha256=snapshot.workspace_profile_sha256,
        workspace_root_identity_sha256=snapshot.workspace_root_identity_sha256,
        workspace_mount_identity_sha256=snapshot.workspace_mount_identity_sha256,
        policy_version=snapshot.policy_version,
        contract_profile_sha256=snapshot.contract_profile_sha256,
        trusted_time_generation=snapshot.trusted_time_generation,
        boot_id_digest=snapshot.activation_boot_id_digest,
    )


@pytest.mark.anyio
async def test_content_permit_requires_live_guard_and_fresh_effective_session() -> None:
    current = _session()

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return current if session_id == current.session_id else None

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        del snapshot
        return _facts()

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=facts)
    guard = ContentReadGuard("content_guard", "workspace", 7)
    permit = await gate.admit_content_read(
        session_id="dev_session",
        workspace_id="workspace",
        request_sha256=DIGEST,
        content_guard=guard,
    )
    assert permit.content_guard_epoch == 7
    assert permit.session_state_version == current.state_version

    guard.released = True
    with pytest.raises(DevelopmentSessionAuthorityError, match="stale"):
        await gate.admit_content_read(
            session_id="dev_session",
            workspace_id="workspace",
            request_sha256=DIGEST,
            content_guard=guard,
        )


@pytest.mark.anyio
async def test_incomplete_activation_never_admits_content_or_member_start() -> None:
    current = _session(closed=False)

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        del session_id
        return current

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        del snapshot
        return _facts()

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=facts)
    with pytest.raises(DevelopmentSessionAuthorityError, match="activation_incomplete"):
        async with gate.hold_member_start(session_id="dev_session", workspace_id="workspace"):
            raise AssertionError("unreachable")


@pytest.mark.anyio
async def test_member_start_and_reduction_are_binary_on_one_session_gate() -> None:
    current = _session()
    member_entered = asyncio.Event()
    member_continue = asyncio.Event()
    reduction_ran = asyncio.Event()

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        del session_id
        return current

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        del snapshot
        return _facts()

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=facts)

    async def member() -> None:
        async with gate.hold_member_start(session_id="dev_session", workspace_id="workspace"):
            member_entered.set()
            await member_continue.wait()

    async def reducer(snapshot: DevelopmentSessionSnapshot) -> DevelopmentSessionSnapshot:
        nonlocal current
        current = reduce_session(
            snapshot,
            expected_state_version=snapshot.state_version,
            target=DevelopmentSessionState.ENDED,
            reason="owner_end",
            now=NOW + timedelta(minutes=2),
        )
        reduction_ran.set()
        return current

    member_task = asyncio.create_task(member())
    await member_entered.wait()
    reduction_task = asyncio.create_task(
        gate.reduce_authority(session_id="dev_session", reducer=reducer)
    )
    await asyncio.sleep(0)
    assert not reduction_ran.is_set()
    member_continue.set()
    await member_task
    await reduction_task
    assert reduction_ran.is_set()
    with pytest.raises(DevelopmentSessionAuthorityError, match="not_active"):
        async with gate.hold_member_start(session_id="dev_session", workspace_id="workspace"):
            raise AssertionError("unreachable")


@pytest.mark.anyio
async def test_activation_guard_requires_exact_pending_self() -> None:
    current = new_pending_session(
        session_id="dev_pending",
        begin_operation_id="op_begin",
        controller_id="controller",
        controller_epoch=1,
        device_id="device",
        device_epoch=1,
        workspace_id="workspace",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        objective_sha256=DIGEST,
        expires_at=NOW + timedelta(hours=1),
        trusted_time_generation=1,
        activation_boot_id_digest=DIGEST,
        monotonic_deadline_ns=10_000,
        now=NOW,
    )

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        del session_id
        return current

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        del snapshot
        return replace(_facts(), workspace_id="workspace")

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=facts)
    async with gate.hold_activation_start(
        session_id="dev_pending",
        begin_operation_id="op_begin",
        expected_state_version=1,
    ) as observed:
        assert observed is current
    with pytest.raises(DevelopmentSessionAuthorityError, match="stale"):
        async with gate.hold_activation_start(
            session_id="dev_pending",
            begin_operation_id="op_other",
            expected_state_version=1,
        ):
            raise AssertionError("unreachable")


def _received_begin_operation() -> OperationSnapshot:
    return new_received_operation(
        owner=owner(),
        intent=intent(),
        operation_id="op_begin",
        now=NOW,
    )


def _decision(operation: OperationSnapshot) -> PolicyDecision:
    return PolicyDecision(
        "decision_session",
        operation.operation_id,
        "bootstrap-policy",
        "1.0.0",
        PolicyDecisionValue.ALLOW,
        ("policy_allowed",),
        "b" * 64,
        "c" * 64,
        NOW,
    )


def _coordinated(operation: OperationSnapshot) -> CoordinatedOperationRequest:
    return CoordinatedOperationRequest(
        admission=CreateOrFindRequest(
            key=validate_and_digest_key("1" * 64, IdempotencyKeyMode.CALLER_KEY),
            owner=operation.owner,
            intent=operation.intent,
            tool_name="internal.development_session_begin",
            contract_version="1.0.0",
        ),
        required_scope_digest="d" * 64,
        normalized_target_digest="e" * 64,
        boundary_predicates={},
        effect_type="development_session_activate",
        protected_effect_arguments={},
    )


@pytest.mark.anyio
async def test_session_activation_effect_and_closure_require_exact_operation_truth() -> None:
    repository = MemorySessionRepository()

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return await repository.get_session(session_id)

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        del snapshot
        return _facts()

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=facts)
    service = DevelopmentSessionService(repository=repository, authority_gate=gate)
    received = _received_begin_operation()

    async def reservation(
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> SessionReservationRequest:
        del request
        return SessionReservationRequest(
            operation=operation,
            session_id="dev_reserved",
            workspace_id="workspace",
            workspace_profile_sha256=DIGEST,
            workspace_root_identity_sha256=DIGEST,
            workspace_mount_identity_sha256=DIGEST,
            policy_version="policy-v1",
            contract_profile_sha256=DIGEST,
            objective_sha256=DIGEST,
            expires_at=NOW + timedelta(hours=1),
            trusted_time_generation=1,
            activation_boot_id_digest=DIGEST,
            monotonic_deadline_ns=10_000,
            now=NOW,
        )

    authorised = await SessionBeginAuthoriser(
        repository=repository,
        reservation_reader=reservation,
    ).authorise(
        operation=received,
        decision=_decision(received),
        request=_coordinated(received),
    )
    pending = await repository.require_session("dev_reserved")
    boundary = SessionActivationEffectBoundary(repository, facts_reader=_facts_reader)
    receipt = await boundary.start(
        EffectRequest(
            "op_begin",
            3,
            "development_session_activate",
            {
                "session_id": pending.session_id,
                "expected_state_version": pending.state_version,
                "started_at": NOW + timedelta(seconds=1),
            },
        )
    )
    assert receipt.crossing is BoundaryCrossing.CROSSED
    assert receipt.reference is not None
    assert receipt.reference_digest is not None
    active = await repository.require_session(pending.session_id)
    assert active.state is DevelopmentSessionState.ACTIVE
    assert active.activation_closure.value == "pending"
    assert active.started_at == (await _facts_reader(pending)).wall_time

    running = transition(
        authorised,
        TransitionRequest(
            2,
            OperationState.RUNNING,
            EffectKnowledge.NONE,
            "dispatch",
            occurred_at=NOW,
        ),
    )
    succeeded = transition(
        running,
        TransitionRequest(
            3,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "activated",
            effect_reference=receipt.reference,
            effect_reference_digest=receipt.reference_digest,
            occurred_at=NOW + timedelta(seconds=1),
        ),
    )

    async def closure_verified(
        operation: OperationSnapshot,
        session: DevelopmentSessionSnapshot,
    ) -> bool:
        return operation is succeeded and session.session_id == pending.session_id

    result = await SessionActivationClosure(
        service=service,
        repository=repository,
        closure_verifier=closure_verified,
    ).close(operation=succeeded, request=_coordinated(received))
    assert result is succeeded
    closed = await repository.require_session(pending.session_id)
    assert closed.activation_closure.value == "complete"
    repeated = await SessionActivationClosure(
        service=service,
        repository=repository,
        closure_verifier=closure_verified,
    ).close(operation=succeeded, request=_coordinated(received))
    assert repeated is succeeded


def _activation_predicates(session: DevelopmentSessionSnapshot) -> dict[str, str | int]:
    return {
        "session_id": session.session_id,
        "session_state_version": session.state_version,
        "controller_id": session.controller_id,
        "controller_epoch": session.controller_epoch,
        "device_id": session.device_id,
        "device_epoch": session.device_epoch,
        "workspace_id": session.workspace_id,
        "workspace_profile_sha256": session.workspace_profile_sha256,
        "workspace_root_identity_sha256": session.workspace_root_identity_sha256,
        "workspace_mount_identity_sha256": session.workspace_mount_identity_sha256,
        "policy_version": session.policy_version,
        "contract_profile_sha256": session.contract_profile_sha256,
        "trusted_time_generation": session.trusted_time_generation,
        "activation_boot_id_digest": session.activation_boot_id_digest,
        "monotonic_deadline_ns": session.monotonic_deadline_ns,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ({"controller_epoch": 2}, "controller_identity_mismatch"),
        ({"device_epoch": 2}, "device_identity_mismatch"),
        ({"workspace_profile_sha256": "0" * 64}, "workspace_profile_mismatch"),
        ({"workspace_root_identity_sha256": "0" * 64}, "workspace_root_identity_mismatch"),
        ({"workspace_mount_identity_sha256": "0" * 64}, "workspace_mount_identity_mismatch"),
        ({"policy_version": "policy-v2"}, "policy_identity_mismatch"),
        ({"contract_profile_sha256": "0" * 64}, "contract_profile_mismatch"),
        ({"trusted_time_generation": 2}, "trusted_time_unavailable"),
        ({"wall_time_trusted": False}, "trusted_time_unavailable"),
        ({"wall_time": NOW + timedelta(hours=2)}, "development_session_expired"),
        ({"kernel_consequential_ready": False}, "kernel_unavailable"),
    ],
)
async def test_activation_revalidates_every_current_authority_fact_before_start(
    drift: dict[str, object],
    reason: str,
) -> None:
    repository = MemorySessionRepository()
    received, _authorised, pending = await _reserve_pending(
        repository,
        session_id=f"dev_drift_{reason}",
    )
    facts = replace(await _facts_reader(pending), **drift)  # type: ignore[arg-type]

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return await repository.get_session(session_id)

    async def current_facts(_snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return facts

    gate = DevelopmentSessionAuthorityGate(
        session_reader=read,
        facts_reader=current_facts,
    )
    with pytest.raises(DevelopmentSessionAuthorityError, match=reason):
        async with gate.hold_activation_start(
            session_id=pending.session_id,
            begin_operation_id=received.operation_id,
            expected_state_version=pending.state_version,
        ):
            pytest.fail("stale authority must not enter the activation suffix")

    verifier = SessionActivationBoundaryVerifier(
        repository=repository,
        facts_reader=current_facts,
    )
    decision = await verifier.verify(
        OperationBoundaryCheck(
            received.operation_id,
            3,
            _activation_predicates(pending),
        )
    )
    assert not decision.allowed
    assert decision.reason_code == reason

    receipt = await SessionActivationEffectBoundary(
        repository,
        facts_reader=current_facts,
    ).start(
        EffectRequest(
            received.operation_id,
            3,
            "development_session_activate",
            {
                "session_id": pending.session_id,
                "expected_state_version": pending.state_version,
                "started_at": pending.created_at,
            },
        )
    )
    assert receipt.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED
    assert receipt.reason_code == reason
    assert (await repository.require_session(pending.session_id)).state is (
        DevelopmentSessionState.PENDING
    )


@pytest.mark.anyio
async def test_activation_closure_converges_after_authority_reduction_wins() -> None:
    repository = MemorySessionRepository()
    received, authorised, pending = await _reserve_pending(
        repository,
        session_id="dev_reduce_before_closure",
    )

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return await repository.get_session(session_id)

    gate = DevelopmentSessionAuthorityGate(session_reader=read, facts_reader=_facts_reader)
    service = DevelopmentSessionService(repository=repository, authority_gate=gate)
    receipt = await SessionActivationEffectBoundary(
        repository,
        facts_reader=_facts_reader,
    ).start(
        EffectRequest(
            received.operation_id,
            3,
            "development_session_activate",
            {
                "session_id": pending.session_id,
                "expected_state_version": pending.state_version,
            },
        )
    )
    running = transition(
        authorised,
        TransitionRequest(
            authorised.state_version,
            OperationState.RUNNING,
            EffectKnowledge.NONE,
            "dispatch",
            occurred_at=NOW,
        ),
    )
    succeeded = transition(
        running,
        TransitionRequest(
            running.state_version,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "activated",
            effect_reference=receipt.reference,
            effect_reference_digest=receipt.reference_digest,
            occurred_at=NOW + timedelta(minutes=1),
        ),
    )
    active = await repository.require_session(pending.session_id)
    ended = await service.reduce_authority(
        session_id=active.session_id,
        expected_state_version=active.state_version,
        target=DevelopmentSessionState.ENDED,
        reason="owner_end",
        terminal_at=NOW + timedelta(minutes=2),
    )
    assert ended.activation_closure is ActivationClosure.PENDING

    async def closure_verified(
        _operation: OperationSnapshot,
        _session: DevelopmentSessionSnapshot,
    ) -> bool:
        return True

    await SessionActivationClosure(
        service=service,
        repository=repository,
        closure_verifier=closure_verified,
    ).close_retained(succeeded)
    retained = await repository.require_session(pending.session_id)
    assert retained.state is DevelopmentSessionState.ENDED
    assert retained.activation_closure is ActivationClosure.COMPLETE


@pytest.mark.anyio
async def test_activation_boundary_rejects_foreign_or_malformed_request_without_effect() -> None:
    repository = MemorySessionRepository()
    boundary = SessionActivationEffectBoundary(repository, facts_reader=_facts_reader)
    malformed = await boundary.start(
        EffectRequest("op_unknown", 3, "development_session_activate", {})
    )
    assert malformed.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED
    wrong_type = await boundary.start(EffectRequest("op_unknown", 3, "workspace_write", {}))
    assert wrong_type.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED


@pytest.mark.anyio
async def test_session_gate_rejects_missing_foreign_and_unnamed_authority() -> None:
    async def missing(_session_id: str) -> DevelopmentSessionSnapshot | None:
        return None

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return await _facts_reader(snapshot)

    missing_gate = DevelopmentSessionAuthorityGate(session_reader=missing, facts_reader=facts)
    with pytest.raises(DevelopmentSessionAuthorityError, match="unavailable"):
        async with missing_gate.hold_activation_start(
            session_id="dev_missing",
            begin_operation_id="op_begin",
            expected_state_version=1,
        ):
            pytest.fail("missing session must not enter")
    with pytest.raises(DevelopmentSessionAuthorityError, match="unavailable"):
        await missing_gate.reduce_authority(
            session_id="dev_missing",
            reducer=lambda snapshot: _identity_session(snapshot),
        )
    with pytest.raises(DevelopmentSessionAuthorityError, match="session_id is required"):
        async with missing_gate.hold_member_start(session_id="", workspace_id="workspace"):
            pytest.fail("empty session identity must not enter")

    current = _session()

    async def present(_session_id: str) -> DevelopmentSessionSnapshot | None:
        return current

    foreign_gate = DevelopmentSessionAuthorityGate(session_reader=present, facts_reader=facts)
    with pytest.raises(DevelopmentSessionAuthorityError, match="unavailable"):
        async with foreign_gate.hold_member_start(
            session_id=current.session_id,
            workspace_id="other-workspace",
        ):
            pytest.fail("foreign workspace must not enter")

    async def unavailable_facts(_snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return replace(_facts(), kernel_consequential_ready=False)

    unavailable_gate = DevelopmentSessionAuthorityGate(
        session_reader=present,
        facts_reader=unavailable_facts,
    )
    with pytest.raises(DevelopmentSessionAuthorityError, match="kernel_unavailable"):
        async with unavailable_gate.hold_member_start(
            session_id=current.session_id,
            workspace_id=current.workspace_id,
        ):
            pytest.fail("ineffective session must not enter")


async def _identity_session(
    snapshot: DevelopmentSessionSnapshot,
) -> DevelopmentSessionSnapshot:
    return snapshot


async def _reserve_pending(
    repository: MemorySessionRepository,
    *,
    session_id: str,
) -> tuple[OperationSnapshot, OperationSnapshot, DevelopmentSessionSnapshot]:
    received = _received_begin_operation()

    async def reservation(
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> SessionReservationRequest:
        del request
        return SessionReservationRequest(
            operation=operation,
            session_id=session_id,
            workspace_id="workspace",
            workspace_profile_sha256=DIGEST,
            workspace_root_identity_sha256=DIGEST,
            workspace_mount_identity_sha256=DIGEST,
            policy_version="policy-v1",
            contract_profile_sha256=DIGEST,
            objective_sha256=DIGEST,
            expires_at=NOW + timedelta(hours=1),
            trusted_time_generation=1,
            activation_boot_id_digest=DIGEST,
            monotonic_deadline_ns=10_000,
            now=NOW,
        )

    authorised = await SessionBeginAuthoriser(
        repository=repository,
        reservation_reader=reservation,
    ).authorise(
        operation=received,
        decision=_decision(received),
        request=_coordinated(received),
    )
    return received, authorised, await repository.require_session(session_id)


@pytest.mark.anyio
async def test_activation_known_no_effect_revokes_once_and_retains_audit_block() -> None:
    repository = MemorySessionRepository()
    received, authorised, pending = await _reserve_pending(
        repository,
        session_id="dev_no_effect",
    )

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return await repository.get_session(session_id)

    async def facts(_snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return _facts()

    service = DevelopmentSessionService(
        repository=repository,
        authority_gate=DevelopmentSessionAuthorityGate(
            session_reader=read,
            facts_reader=facts,
        ),
    )
    running = transition(
        authorised,
        TransitionRequest(
            authorised.state_version,
            OperationState.RUNNING,
            EffectKnowledge.NONE,
            "dispatch",
            occurred_at=NOW,
        ),
    )
    failed = transition(
        running,
        TransitionRequest(
            running.state_version,
            OperationState.FAILED,
            EffectKnowledge.KNOWN_NO_EFFECT,
            "not_started",
            error=OperationError("not_started", "Activation did not start."),
            occurred_at=NOW + timedelta(seconds=1),
        ),
    )
    audit_closed = False

    async def closure_verified(
        _operation: OperationSnapshot,
        _session: DevelopmentSessionSnapshot,
    ) -> bool:
        return audit_closed

    closure = SessionActivationClosure(
        service=service,
        repository=repository,
        closure_verifier=closure_verified,
    )
    assert await closure.close(operation=failed, request=_coordinated(received)) is failed
    assert (
        await repository.require_session(pending.session_id)
    ).state is DevelopmentSessionState.PENDING
    audit_closed = True
    assert await closure.close(operation=failed, request=_coordinated(received)) is failed
    revoked = await repository.require_session(pending.session_id)
    assert revoked.state is DevelopmentSessionState.REVOKED
    assert await closure.close(operation=failed, request=_coordinated(received)) is failed


@pytest.mark.anyio
async def test_activation_helpers_fail_closed_on_missing_stale_or_contradictory_state() -> None:
    repository = MemorySessionRepository()
    received, _authorised, pending = await _reserve_pending(
        repository,
        session_id="dev_boundary_failures",
    )
    boundary = SessionActivationEffectBoundary(repository, facts_reader=_facts_reader)
    stale = await boundary.start(
        EffectRequest(
            received.operation_id,
            3,
            "development_session_activate",
            {
                "session_id": pending.session_id,
                "expected_state_version": 99,
                "started_at": NOW + timedelta(seconds=1),
            },
        )
    )
    assert stale.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED
    assert stale.reason_code == "session_activation_state_stale"

    async def read(session_id: str) -> DevelopmentSessionSnapshot | None:
        return await repository.get_session(session_id)

    async def facts(snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return await _facts_reader(snapshot)

    authority_gate = DevelopmentSessionAuthorityGate(
        session_reader=read,
        facts_reader=facts,
    )
    dispatch = SessionActivationDispatchAuthority(
        repository=repository,
        authority_gate=authority_gate,
    )
    async with dispatch.hold(operation=received, request=object()):
        pass
    with pytest.raises(DevelopmentSessionAuthorityError, match="unavailable"):
        async with dispatch.hold(
            operation=replace(received, operation_id="op_missing"),
            request=object(),
        ):
            pytest.fail("missing activation must not enter")

    malformed = transition(
        received,
        TransitionRequest(
            received.state_version,
            OperationState.AUTHORISED,
            EffectKnowledge.NONE,
            "policy_allowed",
            occurred_at=NOW,
        ),
    )

    async def stale_reservation(
        _operation: OperationSnapshot,
        _request: CoordinatedOperationRequest,
    ) -> SessionReservationRequest:
        return SessionReservationRequest(
            operation=malformed,
            session_id="dev_stale",
            workspace_id="workspace",
            workspace_profile_sha256=DIGEST,
            workspace_root_identity_sha256=DIGEST,
            workspace_mount_identity_sha256=DIGEST,
            policy_version="policy-v1",
            contract_profile_sha256=DIGEST,
            objective_sha256=DIGEST,
            expires_at=NOW + timedelta(hours=1),
            trusted_time_generation=1,
            activation_boot_id_digest=DIGEST,
            monotonic_deadline_ns=10_000,
            now=NOW,
        )

    with pytest.raises(DevelopmentSessionError, match="reservation operation is stale"):
        await SessionBeginAuthoriser(
            repository=repository,
            reservation_reader=stale_reservation,
        ).authorise(
            operation=received,
            decision=_decision(received),
            request=_coordinated(received),
        )

    async def verified(
        _operation: OperationSnapshot,
        _session: DevelopmentSessionSnapshot,
    ) -> bool:
        return True

    missing_closure = SessionActivationClosure(
        service=DevelopmentSessionService(
            repository=repository,
            authority_gate=authority_gate,
        ),
        repository=repository,
        closure_verifier=verified,
    )
    with pytest.raises(DevelopmentSessionError, match="closure is missing"):
        await missing_closure.close(
            operation=replace(received, operation_id="op_missing"),
            request=_coordinated(received),
        )

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import pytest
from tests.phase4_support import NOW, intent, owner

from binnacle.adapters.workspace.reconcile import (
    Phase6ClosureHealth,
    Phase6OperationReconciler,
    Phase6ReconciliationError,
    Phase6ReconciliationStore,
)
from binnacle.application.development_session import (
    DevelopmentSessionAuthorityGate,
    DevelopmentSessionService,
    SessionActivationClosure,
)
from binnacle.application.reconciliation import CompositeSpecializedOperationReconciler
from binnacle.application.workspace import WorkspaceMutationClosure
from binnacle.domain.audit import AuditAppendResult, AuditEventDraft, AuditTail
from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    SessionAuthorityFacts,
    activate_session,
    complete_activation,
    new_pending_session,
    reduce_session,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    new_received_operation,
    transition,
)
from binnacle.domain.workspace import (
    WorkspaceFence,
    WorkspaceMutationKind,
    WorkspaceObjectKind,
)
from binnacle.ports.audit import AuditJournal, AuditObligation, AuditObligationStore
from binnacle.ports.development_session import DevelopmentSessionRepository
from binnacle.ports.workspace import WorkspaceOperationRecord, WorkspaceRepository

DIGEST = "a" * 64


class MemoryOperations:
    def __init__(self, *operations: OperationSnapshot) -> None:
        self.operations = {item.operation_id: item for item in operations}
        self.audit_contexts: dict[tuple[str, int], tuple[OperationState, str]] = {}
        self.tail = AuditTail(0, None)
        self.latched = False

    async def get_operation(self, operation_id: str) -> OperationSnapshot | None:
        return self.operations.get(operation_id)

    async def transition(
        self,
        operation_id: str,
        request: TransitionRequest,
    ) -> OperationSnapshot:
        current = self.operations[operation_id]
        desired = transition(current, request)
        self.operations[operation_id] = desired
        self.audit_contexts[(operation_id, desired.state_version)] = (
            current.state,
            request.reason_code,
        )
        return desired

    async def get_transition_audit_context(
        self,
        operation_id: str,
        state_version: int,
    ) -> tuple[OperationState, str] | None:
        return self.audit_contexts.get((operation_id, state_version))

    async def update_audit_tail_cache(self, tail: AuditTail) -> None:
        self.tail = tail

    async def latch_audit_failure(self, reason_code: str) -> int:
        del reason_code
        self.latched = True
        return 1


class MemorySessions:
    def __init__(self, session: DevelopmentSessionSnapshot) -> None:
        self.session = session

    async def get_session(self, session_id: str) -> DevelopmentSessionSnapshot | None:
        return self.session if session_id == self.session.session_id else None

    async def get_by_begin_operation(
        self, begin_operation_id: str
    ) -> DevelopmentSessionSnapshot | None:
        return self.session if begin_operation_id == self.session.begin_operation_id else None

    async def complete_activation(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        closed_at: object,
    ) -> DevelopmentSessionSnapshot:
        del closed_at
        assert session_id == self.session.session_id
        self.session = complete_activation(
            self.session,
            expected_state_version=expected_state_version,
        )
        return self.session

    async def reduce(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        target: DevelopmentSessionState,
        reason: str,
        terminal_at: object,
    ) -> DevelopmentSessionSnapshot:
        assert session_id == self.session.session_id
        self.session = reduce_session(
            self.session,
            expected_state_version=expected_state_version,
            target=target,
            reason=reason,
            now=cast("datetime", terminal_at),
        )
        return self.session

    async def list_activation_closures(
        self,
        *,
        limit: int,
        after_created_at: object = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]:
        del limit, after_created_at
        if (
            after_session_id is not None
            or self.session.activation_closure is ActivationClosure.COMPLETE
            or (
                self.session.state is not DevelopmentSessionState.PENDING
                and self.session.activation_effect_reference is None
            )
        ):
            return ()
        return (self.session,)


class MemoryWorkspaces:
    def __init__(self, record: WorkspaceOperationRecord | None = None) -> None:
        self.record = record
        self.fence = WorkspaceFence(
            "workspace",
            2,
            None if record is None else record.operation_id,
            None if record is None else "workspace_create",
        )

    async def get_operation(self, operation_id: str) -> WorkspaceOperationRecord | None:
        return (
            self.record
            if self.record is not None and operation_id == self.record.operation_id
            else None
        )

    async def get_fence(self, workspace_id: str) -> WorkspaceFence:
        assert workspace_id == self.fence.workspace_id
        return self.fence

    async def release_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        released_at: object,
    ) -> WorkspaceFence:
        del released_at
        assert workspace_id == self.fence.workspace_id
        assert expected_version == self.fence.fence_version
        assert operation_id == self.fence.active_operation_id
        self.fence = WorkspaceFence(workspace_id, expected_version + 1, None, None)
        return self.fence

    async def list_operations_for_closure(
        self,
        *,
        limit: int,
        after_created_at: object = None,
        after_operation_id: str | None = None,
    ) -> tuple[WorkspaceOperationRecord, ...]:
        del limit, after_created_at
        if self.record is None or after_operation_id is not None:
            return ()
        if self.fence.active_operation_id != self.record.operation_id:
            return ()
        return (self.record,)


class MemoryAudit:
    def __init__(self, *, fail_append: bool = False) -> None:
        self._tail = AuditTail(0, None)
        self.evidence: set[tuple[str, int, str, str]] = set()
        self.fail_append = fail_append
        self.emergency_count = 0

    @property
    def tail(self) -> AuditTail:
        return self._tail

    async def append(self, draft: AuditEventDraft) -> AuditAppendResult:
        if self.fail_append:
            raise OSError("injected audit append failure")
        sequence = self._tail.sequence + 1
        digest = f"{sequence:064x}"
        self._tail = AuditTail(sequence, digest)
        assert draft.operation_id is not None
        self.evidence.add(
            (
                draft.operation_id,
                cast(int, draft.payload["state_version"]),
                str(draft.payload["new_state"]),
                str(draft.payload["effect_knowledge"]),
            )
        )
        return AuditAppendResult(sequence, digest, b"event")

    async def append_emergency(self, **_kwargs: object) -> None:
        self.emergency_count += 1

    async def find_operation_state_evidence(
        self,
        *,
        operation_id: str,
        state_version: int,
        state: str,
        effect_knowledge: str,
    ) -> str | None:
        key = (operation_id, state_version, state, effect_knowledge)
        return DIGEST if key in self.evidence else None


class MemoryObligations:
    def __init__(self, *markers: AuditObligation) -> None:
        self.markers = tuple(markers)

    async def scan(self) -> tuple[AuditObligation, ...]:
        return self.markers


def _running(operation_id: str, contract: str) -> OperationSnapshot:
    authorised = _authorised(operation_id, contract)
    return transition(
        authorised,
        TransitionRequest(2, OperationState.RUNNING, EffectKnowledge.NONE, "dispatch"),
    )


def _authorised(operation_id: str, contract: str) -> OperationSnapshot:
    received = new_received_operation(
        owner=owner(),
        intent=replace(intent(), operation_contract=contract, tool_name=contract),
        operation_id=operation_id,
        now=NOW,
    )
    return transition(
        received,
        TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "policy_allowed"),
    )


def _active_session(operation_id: str) -> DevelopmentSessionSnapshot:
    return activate_session(
        _pending_session(operation_id),
        expected_state_version=1,
        effect_reference="session_activation:fixture:2",
        effect_reference_sha256=DIGEST,
        now=NOW + timedelta(seconds=1),
    )


def _pending_session(operation_id: str) -> DevelopmentSessionSnapshot:
    return new_pending_session(
        session_id="dev_restart",
        begin_operation_id=operation_id,
        controller_id=owner().controller_id,
        controller_epoch=1,
        device_id="device-fixture",
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


def _workspace_record(operation_id: str) -> WorkspaceOperationRecord:
    return WorkspaceOperationRecord(
        operation_id,
        "dev_restart",
        "workspace",
        WorkspaceMutationKind.CREATE,
        WorkspaceObjectKind.REGULAR_FILE,
        None,
        "1" * 64,
        None,
        None,
        None,
        DIGEST,
        "2" * 64,
        1,
        "3" * 64,
        "staging",
        "4" * 64,
        "linux-v1",
        NOW,
        NOW,
    )


async def _facts(session: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
    return SessionAuthorityFacts(
        session.controller_id,
        session.controller_epoch,
        session.device_id,
        session.device_epoch,
        session.workspace_id,
        session.workspace_profile_sha256,
        session.workspace_root_identity_sha256,
        session.workspace_mount_identity_sha256,
        session.policy_version,
        session.contract_profile_sha256,
        NOW + timedelta(minutes=1),
        True,
        1,
        DIGEST,
        1_000,
        True,
    )


def _reconciler(
    *,
    operation: OperationSnapshot,
    sessions: MemorySessions,
    workspaces: MemoryWorkspaces,
    audit: MemoryAudit,
    obligations: MemoryObligations,
    closure_health: Phase6ClosureHealth | None = None,
) -> tuple[Phase6OperationReconciler, MemoryOperations]:
    operations = MemoryOperations(operation)
    session_repository = cast(DevelopmentSessionRepository, sessions)
    workspace_repository = cast(WorkspaceRepository, workspaces)
    gate = DevelopmentSessionAuthorityGate(
        session_reader=sessions.get_session,
        facts_reader=_facts,
    )
    service = DevelopmentSessionService(
        repository=session_repository,
        authority_gate=gate,
    )

    async def session_verified(
        _operation: OperationSnapshot,
        _session: DevelopmentSessionSnapshot,
    ) -> bool:
        return True

    async def workspace_verified(
        _operation: OperationSnapshot,
        _record: WorkspaceOperationRecord,
    ) -> bool:
        return True

    reconciler = Phase6OperationReconciler(
        operations=cast(Phase6ReconciliationStore, operations),
        sessions=session_repository,
        workspaces=workspace_repository,
        session_closure=SessionActivationClosure(
            service=service,
            repository=session_repository,
            closure_verifier=session_verified,
        ),
        workspace_closure=WorkspaceMutationClosure(
            repository=workspace_repository,
            release_verifier=workspace_verified,
        ),
        audit=cast(AuditJournal, audit),
        obligations=cast(AuditObligationStore, obligations),
        closure_health=closure_health or _healthy,
    )
    return reconciler, operations


async def _healthy() -> bool:
    return True


@pytest.mark.anyio
async def test_restart_reconciles_activation_reference_then_completes_closure() -> None:
    running = _running("op_session_restart", "development_session_begin")
    sessions = MemorySessions(_active_session(running.operation_id))
    audit = MemoryAudit()
    reconciler, operations = _reconciler(
        operation=running,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=audit,
        obligations=MemoryObligations(),
    )

    result = await reconciler.reconcile(running)
    assert result is not None
    assert result.state is OperationState.SUCCEEDED
    assert result.effect_knowledge is EffectKnowledge.KNOWN_EFFECT
    assert result.effect_reference == sessions.session.activation_effect_reference
    assert sessions.session.activation_closure is ActivationClosure.COMPLETE
    assert operations.tail.sequence == 1
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_restart_releases_only_audited_terminal_workspace_fence() -> None:
    running = _running("op_workspace_restart", "workspace_create")
    succeeded = transition(
        running,
        TransitionRequest(
            running.state_version,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "workspace_effect_verified",
            effect_reference="workspace:receipt",
            effect_reference_digest=DIGEST,
        ),
    )
    record = _workspace_record(succeeded.operation_id)
    workspaces = MemoryWorkspaces(record)
    audit = MemoryAudit()
    audit.evidence.add(
        (
            succeeded.operation_id,
            succeeded.state_version,
            succeeded.state.value,
            succeeded.effect_knowledge.value,
        )
    )
    reconciler, _operations = _reconciler(
        operation=succeeded,
        sessions=MemorySessions(
            complete_activation(
                _active_session("op_other_session"),
                expected_state_version=2,
            )
        ),
        workspaces=workspaces,
        audit=audit,
        obligations=MemoryObligations(),
    )

    assert await reconciler.reconcile_terminal_closures() == (succeeded,)
    assert workspaces.fence.active_operation_id is None


@pytest.mark.anyio
async def test_exact_activation_truth_precedes_obligation_recovery_and_closure() -> None:
    running = _running("op_session_obligation", "development_session_begin")
    sessions = MemorySessions(_active_session(running.operation_id))
    marker = AuditObligation("1", "obl_fixture", running.operation_id, running.state_version)
    audit = MemoryAudit()
    obligations = MemoryObligations(marker)
    reconciler, operations = _reconciler(
        operation=running,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=audit,
        obligations=obligations,
    )

    with pytest.raises(Phase6ReconciliationError, match="obligation"):
        await reconciler.reconcile(running)
    classified = operations.operations[running.operation_id]
    assert classified.state is OperationState.SUCCEEDED
    assert classified.effect_knowledge is EffectKnowledge.KNOWN_EFFECT
    assert classified.effect_reference == sessions.session.activation_effect_reference
    assert sessions.session.activation_closure is ActivationClosure.PENDING

    # Exact-generation recovery validates this durable known-effect truth before
    # removing the marker.  Model that completed owner action, then prove the next
    # restart closes the retained authority exactly once.
    obligations.markers = ()
    assert await reconciler.reconcile_terminal_closures() == (classified,)
    closed_session = await sessions.get_session(sessions.session.session_id)
    assert closed_session is not None
    assert closed_session.activation_closure is ActivationClosure.COMPLETE
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_restart_authorised_session_is_audited_no_effect_and_revoked() -> None:
    authorised = _authorised("op_session_authorised", "development_session_begin")
    sessions = MemorySessions(_pending_session(authorised.operation_id))
    reconciler, _operations = _reconciler(
        operation=authorised,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )

    result = await reconciler.reconcile(authorised)
    assert result is not None
    assert result.state is OperationState.FAILED
    assert result.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
    assert sessions.session.state is DevelopmentSessionState.REVOKED


@pytest.mark.anyio
async def test_restart_running_session_without_receipt_stays_uncertain_and_reserved() -> None:
    running = _running("op_session_uncertain", "development_session_begin")
    sessions = MemorySessions(_pending_session(running.operation_id))
    reconciler, _operations = _reconciler(
        operation=running,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )

    result = await reconciler.reconcile(running)
    assert result is not None
    assert result.state is OperationState.UNCERTAIN
    assert result.effect_knowledge is EffectKnowledge.UNCERTAIN
    assert sessions.session.state is DevelopmentSessionState.PENDING


@pytest.mark.anyio
async def test_restart_authorised_workspace_is_closed_without_effect() -> None:
    authorised = _authorised("op_workspace_authorised", "workspace_create")
    workspaces = MemoryWorkspaces(_workspace_record(authorised.operation_id))
    reconciler, _operations = _reconciler(
        operation=authorised,
        sessions=MemorySessions(
            complete_activation(_active_session("op_other"), expected_state_version=2)
        ),
        workspaces=workspaces,
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )

    result = await reconciler.reconcile(authorised)
    assert result is not None
    assert result.state is OperationState.FAILED
    assert result.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
    assert workspaces.fence.active_operation_id is None


@pytest.mark.anyio
async def test_restart_running_workspace_retains_fence_when_receipt_is_unknown() -> None:
    running = _running("op_workspace_uncertain", "workspace_create")
    workspaces = MemoryWorkspaces(_workspace_record(running.operation_id))
    reconciler, _operations = _reconciler(
        operation=running,
        sessions=MemorySessions(
            complete_activation(_active_session("op_other"), expected_state_version=2)
        ),
        workspaces=workspaces,
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )

    result = await reconciler.reconcile(running)
    assert result is not None
    assert result.state is OperationState.UNCERTAIN
    assert result.effect_knowledge is EffectKnowledge.UNCERTAIN
    assert workspaces.fence.active_operation_id == running.operation_id


@pytest.mark.anyio
async def test_terminal_session_closure_scan_is_idempotent() -> None:
    running = _running("op_session_terminal", "development_session_begin")
    active = _active_session(running.operation_id)
    succeeded = transition(
        running,
        TransitionRequest(
            running.state_version,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "activated",
            effect_reference=active.activation_effect_reference,
            effect_reference_digest=active.activation_effect_reference_sha256,
        ),
    )
    sessions = MemorySessions(active)
    audit = MemoryAudit()
    audit.evidence.add(
        (
            succeeded.operation_id,
            succeeded.state_version,
            succeeded.state.value,
            succeeded.effect_knowledge.value,
        )
    )
    reconciler, _operations = _reconciler(
        operation=succeeded,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=audit,
        obligations=MemoryObligations(),
    )

    assert await reconciler.reconcile_terminal_closures() == (succeeded,)
    assert sessions.session.activation_closure is ActivationClosure.COMPLETE
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_unknown_family_and_missing_terminal_evidence_fail_closed() -> None:
    running = _running("op_unowned", "synthetic.effect")
    reconciler, _operations = _reconciler(
        operation=running,
        sessions=MemorySessions(
            complete_activation(_active_session("op_other"), expected_state_version=2)
        ),
        workspaces=MemoryWorkspaces(),
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )
    assert await reconciler.reconcile(running) is None

    succeeded = transition(
        _running("op_missing_evidence", "workspace_create"),
        TransitionRequest(
            3,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "effect",
            effect_reference="workspace:receipt",
            effect_reference_digest=DIGEST,
        ),
    )
    workspaces = MemoryWorkspaces(_workspace_record(succeeded.operation_id))
    missing, _operations = _reconciler(
        operation=succeeded,
        sessions=MemorySessions(
            complete_activation(_active_session("op_other"), expected_state_version=2)
        ),
        workspaces=workspaces,
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
    )
    with pytest.raises(Phase6ReconciliationError, match="audit context"):
        await missing.reconcile_terminal_closures()
    assert workspaces.fence.active_operation_id == succeeded.operation_id


@pytest.mark.anyio
async def test_restart_audit_failure_latches_and_retains_authority() -> None:
    authorised = _authorised("op_audit_failure", "development_session_begin")
    sessions = MemorySessions(_pending_session(authorised.operation_id))
    audit = MemoryAudit(fail_append=True)
    reconciler, operations = _reconciler(
        operation=authorised,
        sessions=sessions,
        workspaces=MemoryWorkspaces(),
        audit=audit,
        obligations=MemoryObligations(),
    )

    with pytest.raises(Phase6ReconciliationError, match="could not be persisted"):
        await reconciler.reconcile(authorised)
    assert operations.latched
    assert audit.emergency_count == 1
    assert sessions.session.state is DevelopmentSessionState.PENDING

    # Model the explicit generation recovery that makes the main journal healthy
    # again.  The terminal-closure retry must reconstruct the exact missing state
    # event from durable transition history before releasing authority.
    operations.latched = False
    audit.fail_append = False
    failed = operations.operations[authorised.operation_id]
    assert await reconciler.reconcile_terminal_closures() == (failed,)
    revoked_session = await sessions.get_session(sessions.session.session_id)
    assert revoked_session is not None
    assert revoked_session.state is DevelopmentSessionState.REVOKED
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_restart_health_failure_retains_authorised_workspace_fence() -> None:
    authorised = _authorised("op_health_failure", "workspace_create")
    workspaces = MemoryWorkspaces(_workspace_record(authorised.operation_id))

    async def unhealthy() -> bool:
        return False

    reconciler, operations = _reconciler(
        operation=authorised,
        sessions=MemorySessions(
            complete_activation(_active_session("op_other"), expected_state_version=2)
        ),
        workspaces=workspaces,
        audit=MemoryAudit(),
        obligations=MemoryObligations(),
        closure_health=unhealthy,
    )

    with pytest.raises(Phase6ReconciliationError, match="health"):
        await reconciler.reconcile(authorised)
    assert operations.operations[authorised.operation_id] == authorised
    assert workspaces.fence.active_operation_id == authorised.operation_id


@pytest.mark.anyio
async def test_composite_reconciler_routes_once_and_aggregates_terminal_closures() -> None:
    operation = _running("op_composite", "workspace_create")
    fallback = _authorised("op_fallback", "workspace_create")

    class StubReconciler:
        def __init__(
            self,
            result: OperationSnapshot | None,
            closures: tuple[OperationSnapshot, ...],
        ) -> None:
            self.result = result
            self.closures = closures
            self.calls = 0

        async def reconcile(self, _operation: OperationSnapshot) -> OperationSnapshot | None:
            self.calls += 1
            return self.result

        async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
            return self.closures

    first = StubReconciler(None, (fallback,))
    second = StubReconciler(operation, (operation,))
    composite = CompositeSpecializedOperationReconciler(first, second)

    assert await composite.reconcile(operation) == operation
    assert first.calls == 1
    assert second.calls == 1
    assert await composite.reconcile_terminal_closures() == (fallback, operation)

    with pytest.raises(ValueError, match="at least one"):
        CompositeSpecializedOperationReconciler()

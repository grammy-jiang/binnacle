"""Phase 6 durable registration, session-slot, and mutation-fence tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.phase4_support import NOW, intent, operation_runtime, owner

from binnacle.adapters.sqlite.development_session import (
    DevelopmentSessionSlotBusy,
    DevelopmentSessionStoreError,
    SqliteDevelopmentSessionRepository,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.adapters.sqlite.workspace import SqliteWorkspaceRepository, WorkspaceStoreError
from binnacle.adapters.verification import KernelVerificationError, verify_database_read_only
from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionError,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    new_pending_session,
)
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.domain.workspace import WorkspaceMutationKind, WorkspaceObjectKind
from binnacle.ports.development_session import SessionAuthorisationRequest
from binnacle.ports.operation_store import CreateOrFindRequest
from binnacle.ports.workspace import (
    RegisteredWorkspaceSnapshot,
    WorkspaceAuthorisationRequest,
    WorkspaceOperationRecord,
)


def _registration() -> RegisteredWorkspaceSnapshot:
    return RegisteredWorkspaceSnapshot(
        workspace_id="workspace-fixture",
        profile_sha256="1" * 64,
        root_identity_sha256="2" * 64,
        mount_identity_sha256="3" * 64,
        root_device=8,
        root_inode=9,
        mount_id=10,
        mount_device=8,
        filesystem_type="ext4",
        owner_uid=1000,
        owner_gid=1000,
        mode=0o750,
        primitive_profile_version="linux-workspace-v1",
        registration_version=1,
        registered_at=NOW,
        updated_at=NOW,
    )


async def _operation(store: SqliteOperationStore, *, key_byte: str, fingerprint: str) -> str:
    return (
        await _operation_snapshot(store, key_byte=key_byte, fingerprint=fingerprint)
    ).operation_id


async def _operation_snapshot(
    store: SqliteOperationStore,
    *,
    key_byte: str,
    fingerprint: str,
    contract: str = "synthetic.effect",
    target_identity_sha256: str = "d" * 64,
) -> OperationSnapshot:
    operation_intent = replace(
        intent(fingerprint=fingerprint * 64),
        operation_contract=contract,
        tool_name=contract,
        target_identity_sha256=target_identity_sha256,
    )
    result = await store.create_or_find(
        CreateOrFindRequest(
            validate_and_digest_key(key_byte * 64, IdempotencyKeyMode.CALLER_KEY),
            owner(),
            operation_intent,
            contract,
            "1.0.0",
        )
    )
    assert result.operation is not None
    return result.operation


def _pending(
    begin_operation_id: str,
    *,
    session_id: str,
    now: datetime = NOW,
) -> DevelopmentSessionSnapshot:
    return new_pending_session(
        session_id=session_id,
        begin_operation_id=begin_operation_id,
        controller_id="controller-fixture",
        controller_epoch=1,
        device_id="device-fixture",
        device_epoch=1,
        workspace_id="workspace-fixture",
        workspace_profile_sha256="1" * 64,
        workspace_root_identity_sha256="2" * 64,
        workspace_mount_identity_sha256="3" * 64,
        policy_version="policy-v1",
        contract_profile_sha256="4" * 64,
        objective_sha256="5" * 64,
        expires_at=now + timedelta(hours=1),
        trusted_time_generation=1,
        activation_boot_id_digest="6" * 64,
        monotonic_deadline_ns=3_600_000_000_000,
        now=now,
    )


def _session_authorisation_request(
    operation: OperationSnapshot,
    *,
    session_id: str,
    decision_id: str,
    snapshot: DevelopmentSessionSnapshot | None = None,
) -> SessionAuthorisationRequest:
    authorised_at = operation.created_at
    pending = snapshot or _pending(
        operation.operation_id,
        session_id=session_id,
        now=authorised_at,
    )
    return SessionAuthorisationRequest(
        operation=operation,
        decision=PolicyDecision(
            policy_decision_id=decision_id,
            operation_id=operation.operation_id,
            policy_id="session-policy",
            policy_version="policy-v1",
            decision=PolicyDecisionValue.ALLOW,
            reason_codes=("session_allowed",),
            input_facts_sha256="7" * 64,
            runtime_policy_sha256="8" * 64,
            decided_at=authorised_at,
        ),
        snapshot=pending,
        required_scope_digest="9" * 64,
        normalized_target_digest="d" * 64,
        authorised_at=authorised_at,
    )


async def _authorise_pending_session(
    sessions: SqliteDevelopmentSessionRepository,
    operations: SqliteOperationStore,
    *,
    key_byte: str,
    session_id: str,
) -> tuple[OperationSnapshot, DevelopmentSessionSnapshot]:
    operation = await _operation_snapshot(
        operations,
        key_byte=key_byte,
        fingerprint=key_byte,
        contract="development_session_begin",
    )
    return await sessions.authorise_begin(
        _session_authorisation_request(
            operation,
            session_id=session_id,
            decision_id=f"policy-{session_id}",
        )
    )


async def _active_session(
    sessions: SqliteDevelopmentSessionRepository,
    operations: SqliteOperationStore,
    *,
    key_byte: str,
    session_id: str,
) -> DevelopmentSessionSnapshot:
    authorised, pending = await _authorise_pending_session(
        sessions,
        operations,
        key_byte=key_byte,
        session_id=session_id,
    )
    running = await operations.transition(
        authorised.operation_id,
        TransitionRequest(
            authorised.state_version,
            OperationState.RUNNING,
            EffectKnowledge.NONE,
            "dispatch_attempt_recorded",
            occurred_at=pending.created_at + timedelta(milliseconds=500),
        ),
    )
    reference = f"activation-{session_id}"
    reference_sha256 = "7" * 64
    active = await sessions.activate(
        session_id=session_id,
        expected_state_version=1,
        effect_reference=reference,
        effect_reference_sha256=reference_sha256,
        started_at=pending.created_at + timedelta(seconds=1),
    )
    await operations.transition(
        running.operation_id,
        TransitionRequest(
            running.state_version,
            OperationState.SUCCEEDED,
            EffectKnowledge.KNOWN_EFFECT,
            "development_session_activated",
            effect_reference=reference,
            effect_reference_digest=reference_sha256,
            occurred_at=pending.created_at + timedelta(seconds=1),
        ),
    )
    return await sessions.complete_activation(
        session_id=session_id,
        expected_state_version=active.state_version,
        closed_at=pending.created_at + timedelta(seconds=2),
    )


def _mutation_record(
    operation_id: str,
    session_id: str,
    *,
    now: datetime = NOW + timedelta(seconds=3),
) -> WorkspaceOperationRecord:
    return WorkspaceOperationRecord(
        operation_id=operation_id,
        session_id=session_id,
        workspace_id="workspace-fixture",
        mutation_kind=WorkspaceMutationKind.CREATE,
        object_kind=WorkspaceObjectKind.REGULAR_FILE,
        source_path_sha256=None,
        target_path_sha256="8" * 64,
        expected_object_sha256=None,
        expected_content_sha256=None,
        expected_link_count=None,
        expected_mount_identity_sha256="3" * 64,
        proposed_content_sha256="9" * 64,
        proposed_byte_count=12,
        state_binding_sha256="a" * 64,
        staging_reference=f"staging-{operation_id}",
        staging_reference_sha256="0" * 64,
        primitive_profile_version="linux-workspace-v1",
        created_at=now,
        updated_at=now,
    )


def _authorisation_request(
    operation: OperationSnapshot,
    session_id: str,
    *,
    decision_id: str,
    record: WorkspaceOperationRecord | None = None,
) -> WorkspaceAuthorisationRequest:
    authorised_at = operation.created_at + timedelta(seconds=3)
    return WorkspaceAuthorisationRequest(
        operation=operation,
        decision=PolicyDecision(
            policy_decision_id=decision_id,
            operation_id=operation.operation_id,
            policy_id="workspace-policy",
            policy_version="policy-v1",
            decision=PolicyDecisionValue.ALLOW,
            reason_codes=("workspace_allowed",),
            input_facts_sha256="b" * 64,
            runtime_policy_sha256="c" * 64,
            decided_at=operation.created_at + timedelta(seconds=2),
        ),
        record=record or _mutation_record(operation.operation_id, session_id, now=authorised_at),
        expected_fence_version=1,
        required_scope_digest="e" * 64,
        normalized_target_digest="f" * 64,
        authorised_at=authorised_at,
    )


@pytest.mark.anyio
async def test_registration_and_fence_are_atomic_immutable_and_versioned(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        repository = SqliteWorkspaceRepository(runtime)
        registration = _registration()
        assert await repository.register_workspace(registration) == registration
        assert await repository.register_workspace(registration) == registration
        assert await repository.get_registration(registration.workspace_id) == registration
        assert await repository.get_registration("workspace-missing") is None
        assert await repository.require_registration(registration.workspace_id) == registration
        with pytest.raises(WorkspaceStoreError, match="workspace is missing"):
            await repository.require_registration("workspace-missing")
        with pytest.raises(WorkspaceStoreError, match="fence is missing"):
            await repository.get_fence("workspace-missing")
        assert await repository.get_fence(registration.workspace_id) == type(
            await repository.get_fence(registration.workspace_id)
        )("workspace-fixture", 1, None, None)

        with pytest.raises(WorkspaceStoreError, match="conflicts"):
            await repository.register_workspace(
                replace(registration, root_identity_sha256="9" * 64)
            )

        operation_id = await _operation(operations, key_byte="a", fingerprint="a")
        with pytest.raises(WorkspaceStoreError, match="owner is invalid"):
            await repository.acquire_fence(
                workspace_id=registration.workspace_id,
                expected_version=1,
                operation_id="op_missing",
                contract="workspace.create",
                acquired_at=NOW,
            )
        acquired = await repository.acquire_fence(
            workspace_id=registration.workspace_id,
            expected_version=1,
            operation_id=operation_id,
            contract="workspace.create",
            acquired_at=NOW,
        )
        assert acquired.fence_version == 2
        assert acquired.active_operation_id == operation_id
        with pytest.raises(WorkspaceStoreError, match="busy or stale"):
            await repository.acquire_fence(
                workspace_id=registration.workspace_id,
                expected_version=1,
                operation_id=operation_id,
                contract="workspace.create",
                acquired_at=NOW,
            )
        with pytest.raises(WorkspaceStoreError, match="owner/version changed"):
            await repository.release_fence(
                workspace_id=registration.workspace_id,
                expected_version=2,
                operation_id="op_foreign",
                released_at=NOW + timedelta(seconds=1),
            )
        released = await repository.release_fence(
            workspace_id=registration.workspace_id,
            expected_version=2,
            operation_id=operation_id,
            released_at=NOW + timedelta(seconds=1),
        )
        assert released.fence_version == 3
        assert released.active_operation_id is None
        await repository.verify_integrity()

        conflicting = replace(
            registration,
            workspace_id="workspace-other",
            registered_at=NOW + timedelta(seconds=2),
            updated_at=NOW + timedelta(seconds=2),
        )
        with pytest.raises(WorkspaceStoreError, match="inserted exactly once"):
            await repository.register_workspace(conflicting)


@pytest.mark.anyio
async def test_concurrent_distinct_begins_create_exactly_one_live_slot(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        first_operation = await _operation_snapshot(
            operations,
            key_byte="b",
            fingerprint="b",
            contract="development_session_begin",
        )
        second_operation = await _operation_snapshot(
            operations,
            key_byte="c",
            fingerprint="c",
            contract="development_session_begin",
        )
        candidates = (
            _session_authorisation_request(
                first_operation,
                session_id="dev_first",
                decision_id="policy-dev-first",
            ),
            _session_authorisation_request(
                second_operation,
                session_id="dev_second",
                decision_id="policy-dev-second",
            ),
        )

        results = await asyncio.gather(
            *(sessions.authorise_begin(candidate) for candidate in candidates),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(isinstance(result, DevelopmentSessionSlotBusy) for result in results) == 1
        retained = await sessions.list_live(limit=10)
        assert len(retained) == 1
        assert await sessions.get_session(retained[0].session_id) == retained[0]
        assert await sessions.require_session(retained[0].session_id) == retained[0]
        assert await sessions.get_session("dev_missing") is None
        with pytest.raises(DevelopmentSessionStoreError, match="session is missing"):
            await sessions.require_session("dev_missing")
        assert await sessions.get_by_begin_operation(retained[0].begin_operation_id) == retained[0]
        assert await sessions.get_by_begin_operation("op_missing") is None
        for candidate in candidates:
            operation = await operations.get_operation(candidate.operation.operation_id)
            assert operation is not None
            won = operation.operation_id == retained[0].begin_operation_id
            assert operation.state is (
                OperationState.AUTHORISED if won else OperationState.RECEIVED
            )
            assert (await operations.get_policy_decision(operation.operation_id) is not None) is won
            assert (
                await sessions.get_by_begin_operation(operation.operation_id) is not None
            ) is won
        with pytest.raises(DevelopmentSessionStoreError, match="limit"):
            await sessions.list_live(limit=0)
        with pytest.raises(DevelopmentSessionStoreError, match="cursor"):
            await sessions.list_live(limit=1, after_created_at=NOW)
        assert (
            await sessions.list_live(
                limit=1,
                after_created_at=retained[0].created_at,
                after_session_id=retained[0].session_id,
            )
            == ()
        )
        await sessions.verify_integrity()


@pytest.mark.anyio
async def test_session_authorisation_rolls_back_on_constraint_failure(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())

        existing = await _operation_snapshot(
            operations,
            key_byte="0",
            fingerprint="0",
        )
        await operations.store_policy_decision(
            PolicyDecision(
                policy_decision_id="policy-duplicate-primary-key",
                operation_id=existing.operation_id,
                policy_id="existing-policy",
                policy_version="policy-v1",
                decision=PolicyDecisionValue.ALLOW,
                reason_codes=("existing",),
                input_facts_sha256="1" * 64,
                runtime_policy_sha256="2" * 64,
                decided_at=NOW,
            )
        )
        candidate = await _operation_snapshot(
            operations,
            key_byte="1",
            fingerprint="1",
            contract="development_session_begin",
        )
        request = _session_authorisation_request(
            candidate,
            session_id="dev_constraint_rollback",
            decision_id="policy-duplicate-primary-key",
        )

        with pytest.raises(DevelopmentSessionStoreError, match="durable constraints"):
            await sessions.authorise_begin(request)

        retained = await operations.get_operation(candidate.operation_id)
        assert retained is not None and retained.state is OperationState.RECEIVED
        assert await operations.get_policy_decision(candidate.operation_id) is None
        assert await sessions.get_session(request.snapshot.session_id) is None


@pytest.mark.anyio
async def test_session_closure_reduction_and_workspace_operation_round_trip(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        authorised, pending = await _authorise_pending_session(
            sessions,
            operations,
            key_byte="d",
            session_id="dev_lifecycle",
        )
        assert authorised.state is OperationState.AUTHORISED
        assert await operations.get_policy_decision(authorised.operation_id) == PolicyDecision(
            policy_decision_id="policy-dev_lifecycle",
            operation_id=authorised.operation_id,
            policy_id="session-policy",
            policy_version="policy-v1",
            decision=PolicyDecisionValue.ALLOW,
            reason_codes=("session_allowed",),
            input_facts_sha256="7" * 64,
            runtime_policy_sha256="8" * 64,
            decided_at=pending.created_at,
        )
        async with runtime.session_factory() as database_session:
            projection = (
                await database_session.execute(
                    text(
                        "SELECT required_scope_digest,normalized_target_digest "
                        "FROM policy_decisions WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": authorised.operation_id},
                )
            ).one()
            transition = (
                await database_session.execute(
                    text(
                        "SELECT from_state,to_state,effect_knowledge,reason_code "
                        "FROM operation_transitions "
                        "WHERE operation_id=:operation_id AND state_version=2"
                    ),
                    {"operation_id": authorised.operation_id},
                )
            ).one()
        assert tuple(projection) == ("9" * 64, "d" * 64)
        assert tuple(transition) == ("received", "authorised", "none", "policy_allowed")

        active = await sessions.activate(
            session_id=pending.session_id,
            expected_state_version=1,
            effect_reference="activation-fixture",
            effect_reference_sha256="7" * 64,
            started_at=pending.created_at + timedelta(seconds=1),
        )
        assert active.state is DevelopmentSessionState.ACTIVE
        assert active.activation_closure is ActivationClosure.PENDING
        closed = await sessions.complete_activation(
            session_id=active.session_id,
            expected_state_version=2,
            closed_at=pending.created_at + timedelta(seconds=2),
        )
        assert closed.activation_closure is ActivationClosure.COMPLETE
        assert closed.state_version == 3

        ended = await sessions.reduce(
            session_id=closed.session_id,
            expected_state_version=3,
            target=DevelopmentSessionState.ENDED,
            reason="owner-ended",
            terminal_at=pending.created_at + timedelta(seconds=4),
        )
        assert ended.state is DevelopmentSessionState.ENDED
        assert await sessions.list_live(limit=10) == ()
        with pytest.raises(DevelopmentSessionError):
            await sessions.reduce(
                session_id=ended.session_id,
                expected_state_version=4,
                target=DevelopmentSessionState.REVOKED,
                reason="invalid-second-reduction",
                terminal_at=pending.created_at + timedelta(seconds=5),
            )
        with pytest.raises(DevelopmentSessionStoreError, match="not exact"):
            await sessions.authorise_begin(
                _session_authorisation_request(
                    authorised,
                    session_id="dev_reused_begin_operation",
                    decision_id="policy-reused-begin",
                )
            )


@pytest.mark.anyio
async def test_terminal_activation_closure_is_monotonic_and_exact_in_sqlite(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        authorised, pending = await _authorise_pending_session(
            sessions,
            operations,
            key_byte="a",
            session_id="dev_terminal_before_closure",
        )
        running = await operations.transition(
            authorised.operation_id,
            TransitionRequest(
                authorised.state_version,
                OperationState.RUNNING,
                EffectKnowledge.NONE,
                "dispatch_attempt_recorded",
                occurred_at=pending.created_at + timedelta(seconds=1),
            ),
        )
        reference = "activation-terminal-before-closure"
        reference_digest = "7" * 64
        active = await sessions.activate(
            session_id=pending.session_id,
            expected_state_version=pending.state_version,
            effect_reference=reference,
            effect_reference_sha256=reference_digest,
            started_at=pending.created_at + timedelta(seconds=2),
        )
        succeeded = await operations.transition(
            running.operation_id,
            TransitionRequest(
                running.state_version,
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "development_session_activated",
                effect_reference=reference,
                effect_reference_digest=reference_digest,
                occurred_at=pending.created_at + timedelta(seconds=3),
            ),
        )
        assert await operations.get_transition_audit_context(
            succeeded.operation_id,
            succeeded.state_version,
        ) == (OperationState.RUNNING, "development_session_activated")
        ended = await sessions.reduce(
            session_id=active.session_id,
            expected_state_version=active.state_version,
            target=DevelopmentSessionState.ENDED,
            reason="owner_end_won",
            terminal_at=pending.created_at + timedelta(seconds=5),
        )

        closed = await sessions.complete_activation(
            session_id=ended.session_id,
            expected_state_version=ended.state_version,
            closed_at=succeeded.terminal_at or succeeded.updated_at,
        )

        assert closed.state is DevelopmentSessionState.ENDED
        assert closed.activation_closure is ActivationClosure.COMPLETE
        assert closed.state_version == ended.state_version + 1
        assert closed.terminal_at == ended.terminal_at
        await sessions.verify_integrity()

        async with runtime.engine.connect() as connection:
            with pytest.raises(IntegrityError, match="authority is immutable"):
                await connection.execute(
                    text(
                        "UPDATE development_sessions SET terminal_reason='tampered' "
                        "WHERE session_id='dev_terminal_before_closure'"
                    )
                )
            await connection.rollback()


@pytest.mark.anyio
async def test_activation_closure_scan_excludes_terminal_never_started_history(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        for key_byte, target in (
            ("1", DevelopmentSessionState.ENDED),
            ("2", DevelopmentSessionState.EXPIRED),
            ("3", DevelopmentSessionState.REVOKED),
        ):
            authorised, pending = await _authorise_pending_session(
                sessions,
                operations,
                key_byte=key_byte,
                session_id=f"dev_historical_{target.value}",
            )
            await sessions.reduce(
                session_id=pending.session_id,
                expected_state_version=pending.state_version,
                target=target,
                reason=f"{target.value}_before_start",
                terminal_at=pending.created_at + timedelta(seconds=1),
            )
            await operations.transition(
                authorised.operation_id,
                TransitionRequest(
                    authorised.state_version,
                    OperationState.FAILED,
                    EffectKnowledge.KNOWN_NO_EFFECT,
                    "activation_authority_unavailable",
                    error=OperationError(
                        "authority_unavailable",
                        "Activation authority was reduced before dispatch.",
                    ),
                    occurred_at=pending.created_at + timedelta(seconds=2),
                ),
            )

        _authorised, actionable = await _authorise_pending_session(
            sessions,
            operations,
            key_byte="4",
            session_id="dev_actionable_pending",
        )
        page = await sessions.list_activation_closures(limit=1)

        assert tuple(item.session_id for item in page) == (actionable.session_id,)
        assert (
            await sessions.list_activation_closures(
                limit=1,
                after_created_at=page[-1].created_at,
                after_session_id=page[-1].session_id,
            )
            == ()
        )
        await sessions.verify_integrity()


@pytest.mark.anyio
async def test_mutation_authorisation_commits_policy_binding_fence_and_transition(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        session = await _active_session(
            sessions, operations, key_byte="3", session_id="dev_authorise"
        )
        operation = await _operation_snapshot(
            operations,
            key_byte="4",
            fingerprint="4",
            contract="workspace_create",
            target_identity_sha256="f" * 64,
        )
        request = _authorisation_request(
            operation, session.session_id, decision_id="policy-workspace-authorise"
        )

        authorised, fence = await workspaces.authorise_mutation(request)
        assert authorised.state is OperationState.AUTHORISED
        assert authorised.state_version == 2
        assert fence.active_operation_id == operation.operation_id
        assert fence.active_contract == "workspace_create"
        assert await workspaces.get_operation(operation.operation_id) == request.record
        assert await workspaces.get_operation("op_missing") is None
        assert await workspaces.list_operations(limit=10) == (request.record,)
        with pytest.raises(WorkspaceStoreError, match="limit"):
            await workspaces.list_operations(limit=0)
        with pytest.raises(WorkspaceStoreError, match="cursor"):
            await workspaces.list_operations(limit=1, after_created_at=request.record.created_at)
        assert (
            await workspaces.list_operations(
                limit=1,
                after_created_at=request.record.created_at,
                after_operation_id=request.record.operation_id,
            )
            == ()
        )
        assert await operations.get_operation(operation.operation_id) == authorised
        assert await operations.get_policy_decision(operation.operation_id) == request.decision
        async with runtime.session_factory() as database_session:
            policy_projection = (
                await database_session.execute(
                    text(
                        "SELECT required_scope_digest, normalized_target_digest "
                        "FROM policy_decisions WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            ).one()
            transition_count = int(
                (
                    await database_session.execute(
                        text(
                            "SELECT COUNT(*) FROM operation_transitions "
                            "WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": operation.operation_id},
                    )
                ).scalar_one()
            )
        assert tuple(policy_projection) == ("e" * 64, "f" * 64)
        assert transition_count == 2
        await workspaces.verify_integrity()

        with pytest.raises(WorkspaceStoreError, match="stale"):
            await workspaces.authorise_mutation(request)
        assert await workspaces.get_fence("workspace-fixture") == fence


@pytest.mark.anyio
async def test_concurrent_mutation_authorisations_have_one_fence_winner(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        session = await _active_session(
            sessions, operations, key_byte="5", session_id="dev_mutation_race"
        )
        candidates: tuple[OperationSnapshot, ...] = tuple(
            await asyncio.gather(
                *(
                    _operation_snapshot(
                        operations,
                        key_byte=key,
                        fingerprint=key,
                        contract="workspace_create",
                        target_identity_sha256="f" * 64,
                    )
                    for key in ("6", "7")
                )
            )
        )
        requests = tuple(
            _authorisation_request(
                operation,
                session.session_id,
                decision_id=f"policy-race-{index}",
            )
            for index, operation in enumerate(candidates)
        )
        results = await asyncio.gather(
            *(workspaces.authorise_mutation(request) for request in requests),
            return_exceptions=True,
        )
        assert sum(isinstance(result, tuple) for result in results) == 1
        assert sum(isinstance(result, WorkspaceStoreError) for result in results) == 1

        fence = await workspaces.get_fence("workspace-fixture")
        assert fence.active_operation_id is not None
        for request in requests:
            retained = await operations.get_operation(request.operation.operation_id)
            assert retained is not None
            won = request.operation.operation_id == fence.active_operation_id
            assert retained.state is (OperationState.AUTHORISED if won else OperationState.RECEIVED)
            assert (await workspaces.get_operation(retained.operation_id) is not None) is won
            assert (await operations.get_policy_decision(retained.operation_id) is not None) is won


@pytest.mark.anyio
async def test_mutation_authorisation_rolls_back_every_projection_on_constraint_failure(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        session = await _active_session(
            sessions, operations, key_byte="8", session_id="dev_authorise_rollback"
        )
        operation = await _operation_snapshot(
            operations,
            key_byte="9",
            fingerprint="9",
            contract="workspace_create",
            target_identity_sha256="f" * 64,
        )
        normal = _authorisation_request(
            operation, session.session_id, decision_id="policy-rollback"
        )
        denied = replace(
            normal,
            decision=replace(normal.decision, decision=PolicyDecisionValue.DENY),
        )
        with pytest.raises(WorkspaceStoreError, match="policy or operation"):
            await workspaces.authorise_mutation(denied)

        invalid = replace(
            normal,
            record=replace(normal.record, proposed_byte_count=4_194_305),
        )
        with pytest.raises(WorkspaceStoreError, match="durable constraints"):
            await workspaces.authorise_mutation(invalid)
        retained = await operations.get_operation(operation.operation_id)
        assert retained is not None and retained.state is OperationState.RECEIVED
        assert await operations.get_policy_decision(operation.operation_id) is None
        assert await workspaces.get_operation(operation.operation_id) is None
        assert (await workspaces.get_fence("workspace-fixture")).active_operation_id is None


@pytest.mark.anyio
async def test_repository_transition_errors_and_integrity_mismatches_fail_closed(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        begin_operation = await _operation_snapshot(
            operations,
            key_byte="2",
            fingerprint="2",
            contract="development_session_begin",
        )
        pending = _pending(
            begin_operation.operation_id,
            session_id="dev_error_paths",
            now=begin_operation.created_at,
        )

        active_value = replace(
            pending,
            state=DevelopmentSessionState.ACTIVE,
            state_version=2,
            started_at=pending.created_at + timedelta(seconds=1),
            activation_effect_reference="activation-fixture",
            activation_effect_reference_sha256="7" * 64,
        )
        with pytest.raises(DevelopmentSessionStoreError, match="not exact"):
            await sessions.authorise_begin(
                _session_authorisation_request(
                    begin_operation,
                    session_id=active_value.session_id,
                    decision_id="policy-invalid-active",
                    snapshot=active_value,
                )
            )
        with pytest.raises(DevelopmentSessionStoreError, match="session is missing"):
            await sessions.activate(
                session_id="dev_missing",
                expected_state_version=1,
                effect_reference="activation-fixture",
                effect_reference_sha256="7" * 64,
                started_at=pending.created_at + timedelta(seconds=1),
            )

        await sessions.authorise_begin(
            _session_authorisation_request(
                begin_operation,
                session_id=pending.session_id,
                decision_id="policy-error-paths",
                snapshot=pending,
            )
        )
        with pytest.raises(DevelopmentSessionError, match="version is stale"):
            await sessions.activate(
                session_id=pending.session_id,
                expected_state_version=2,
                effect_reference="activation-fixture",
                effect_reference_sha256="7" * 64,
                started_at=pending.created_at + timedelta(seconds=1),
            )
        with pytest.raises(DevelopmentSessionError, match="only an activated"):
            await sessions.complete_activation(
                session_id=pending.session_id,
                expected_state_version=1,
                closed_at=pending.created_at + timedelta(seconds=1),
            )
        with pytest.raises(DevelopmentSessionError, match="target is not terminal"):
            await sessions.reduce(
                session_id=pending.session_id,
                expected_state_version=1,
                target=DevelopmentSessionState.ACTIVE,
                reason="invalid-target",
                terminal_at=pending.created_at + timedelta(seconds=1),
            )

        async with runtime.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE development_sessions SET workspace_profile_sha256=:digest "
                    "WHERE session_id=:session_id"
                ),
                {"digest": "f" * 64, "session_id": pending.session_id},
            )
        with pytest.raises(DevelopmentSessionStoreError, match="integrity"):
            await sessions.verify_integrity()

        async with runtime.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE development_sessions SET workspace_profile_sha256=:digest "
                    "WHERE session_id=:session_id"
                ),
                {"digest": "1" * 64, "session_id": pending.session_id},
            )
            await connection.execute(
                text("DELETE FROM workspace_mutation_fences WHERE workspace_id='workspace-fixture'")
            )
        with pytest.raises(WorkspaceStoreError, match="integrity"):
            await workspaces.verify_integrity()


@pytest.mark.anyio
async def test_database_constraints_reject_noncanonical_workspace_operation_shape(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        _authorised, pending = await _authorise_pending_session(
            sessions,
            operations,
            key_byte="f",
            session_id="dev_invalid_shape",
        )
        write_operation_id = await _operation(operations, key_byte="1", fingerprint="1")
        create_operation_id = await _operation(operations, key_byte="2", fingerprint="2")
        directory_operation_id = await _operation(operations, key_byte="3", fingerprint="3")
        assert pending.session_id == "dev_invalid_shape"
        async with runtime.engine.connect() as connection:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO workspace_operations "
                        "(operation_id,session_id,workspace_id,mutation_kind,object_kind,"
                        "source_path_sha256,target_path_sha256,expected_object_sha256,"
                        "expected_content_sha256,expected_link_count,"
                        "expected_mount_identity_sha256,proposed_content_sha256,"
                        "proposed_byte_count,state_binding_sha256,staging_reference,"
                        "staging_reference_sha256,primitive_profile_version,created_at,updated_at) "
                        "VALUES (:operation_id,'dev_invalid_shape','workspace-fixture','write',"
                        "'regular_file',:source,NULL,:expected,:content,1,:mount,:proposed,1,"
                        ":binding,NULL,NULL,'linux-workspace-v1',CURRENT_TIMESTAMP,"
                        "CURRENT_TIMESTAMP)"
                    ),
                    {
                        "operation_id": write_operation_id,
                        "source": "1" * 64,
                        "expected": "2" * 64,
                        "content": "3" * 64,
                        "mount": "3" * 64,
                        "proposed": "4" * 64,
                        "binding": "5" * 64,
                    },
                )
            await connection.rollback()

        async with runtime.engine.connect() as connection:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO workspace_operations "
                        "(operation_id,session_id,workspace_id,mutation_kind,object_kind,"
                        "source_path_sha256,target_path_sha256,expected_object_sha256,"
                        "expected_content_sha256,expected_link_count,"
                        "expected_mount_identity_sha256,proposed_content_sha256,"
                        "proposed_byte_count,state_binding_sha256,staging_reference,"
                        "staging_reference_sha256,primitive_profile_version,created_at,updated_at) "
                        "VALUES (:operation_id,'dev_invalid_shape','workspace-fixture','create',"
                        "'regular_file',NULL,:target,NULL,NULL,NULL,:mount,:proposed,1,"
                        ":binding,NULL,NULL,'linux-workspace-v1',CURRENT_TIMESTAMP,"
                        "CURRENT_TIMESTAMP)"
                    ),
                    {
                        "operation_id": create_operation_id,
                        "target": "1" * 64,
                        "mount": "3" * 64,
                        "proposed": "4" * 64,
                        "binding": "5" * 64,
                    },
                )
            await connection.rollback()

        async with runtime.engine.connect() as connection:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO workspace_operations "
                        "(operation_id,session_id,workspace_id,mutation_kind,object_kind,"
                        "source_path_sha256,target_path_sha256,expected_object_sha256,"
                        "expected_content_sha256,expected_link_count,"
                        "expected_mount_identity_sha256,proposed_content_sha256,"
                        "proposed_byte_count,state_binding_sha256,staging_reference,"
                        "staging_reference_sha256,primitive_profile_version,created_at,updated_at) "
                        "VALUES (:operation_id,'dev_invalid_shape','workspace-fixture','create',"
                        "'directory',NULL,:target,NULL,NULL,NULL,:mount,NULL,NULL,:binding,"
                        ":staging,:staging_digest,'linux-workspace-v1',CURRENT_TIMESTAMP,"
                        "CURRENT_TIMESTAMP)"
                    ),
                    {
                        "operation_id": directory_operation_id,
                        "target": "1" * 64,
                        "mount": "3" * 64,
                        "binding": "5" * 64,
                        "staging": "unexpected-directory-staging",
                        "staging_digest": "6" * 64,
                    },
                )
            await connection.rollback()


@pytest.mark.anyio
async def test_repository_and_read_only_verifier_reject_nonatomic_session_metadata(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        begin = await _operation_snapshot(
            operations,
            key_byte="e",
            fingerprint="e",
            contract="development_session_begin",
        )
        pending = _pending(
            begin.operation_id,
            session_id="dev_raw_session_metadata",
            now=begin.created_at,
        )
        async with runtime.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO development_sessions "
                    "(session_id,begin_operation_id,state,state_version,activation_closure,"
                    "activation_closure_version,controller_id,controller_epoch,device_id,"
                    "device_epoch,workspace_id,workspace_profile_sha256,"
                    "workspace_root_identity_sha256,workspace_mount_identity_sha256,"
                    "policy_version,contract_profile_sha256,objective_sha256,created_at,"
                    "updated_at,expires_at,trusted_time_generation,activation_boot_id_digest,"
                    "monotonic_deadline_ns,started_at,terminal_at,terminal_reason,"
                    "activation_effect_reference,activation_effect_reference_sha256) "
                    "VALUES (:session_id,:begin_operation_id,'pending',1,'pending',1,"
                    ":controller_id,:controller_epoch,:device_id,:device_epoch,:workspace_id,"
                    ":profile,:root_identity,:mount_identity,:policy_version,:contract_profile,"
                    ":objective,:created_at,:created_at,:expires_at,:time_generation,:boot_id,"
                    ":monotonic_deadline,NULL,NULL,NULL,NULL,NULL)"
                ),
                {
                    "session_id": pending.session_id,
                    "begin_operation_id": pending.begin_operation_id,
                    "controller_id": pending.controller_id,
                    "controller_epoch": pending.controller_epoch,
                    "device_id": pending.device_id,
                    "device_epoch": pending.device_epoch,
                    "workspace_id": pending.workspace_id,
                    "profile": pending.workspace_profile_sha256,
                    "root_identity": pending.workspace_root_identity_sha256,
                    "mount_identity": pending.workspace_mount_identity_sha256,
                    "policy_version": pending.policy_version,
                    "contract_profile": pending.contract_profile_sha256,
                    "objective": pending.objective_sha256,
                    "created_at": pending.created_at.isoformat(sep=" "),
                    "expires_at": pending.expires_at.isoformat(sep=" "),
                    "time_generation": pending.trusted_time_generation,
                    "boot_id": pending.activation_boot_id_digest,
                    "monotonic_deadline": pending.monotonic_deadline_ns,
                },
            )
        with pytest.raises(DevelopmentSessionStoreError, match="integrity"):
            await sessions.verify_integrity()

    with pytest.raises(KernelVerificationError, match="development session provenance"):
        verify_database_read_only(
            database_path=tmp_path / "state/binnacle.db",
            runtime_directory=tmp_path / "run",
            busy_timeout_ms=5_000,
            wal_autocheckpoint_pages=1_000,
        )


@pytest.mark.anyio
async def test_repository_and_read_only_verifier_reject_nonatomic_workspace_metadata(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        await _authorise_pending_session(
            sessions,
            operations,
            key_byte="a",
            session_id="dev_raw_workspace_metadata",
        )
        mutation = await _operation_snapshot(
            operations,
            key_byte="b",
            fingerprint="3",
            contract="workspace_create",
            target_identity_sha256="f" * 64,
        )
        async with runtime.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO workspace_operations "
                    "(operation_id,session_id,workspace_id,mutation_kind,object_kind,"
                    "source_path_sha256,target_path_sha256,expected_object_sha256,"
                    "expected_content_sha256,expected_link_count,"
                    "expected_mount_identity_sha256,proposed_content_sha256,"
                    "proposed_byte_count,state_binding_sha256,staging_reference,"
                    "staging_reference_sha256,primitive_profile_version,created_at,updated_at) "
                    "VALUES (:operation_id,'dev_raw_workspace_metadata','workspace-fixture',"
                    "'create','regular_file',NULL,:target,NULL,NULL,NULL,:mount,:proposed,1,"
                    ":binding,:staging,:staging_digest,'linux-workspace-v1',CURRENT_TIMESTAMP,"
                    "CURRENT_TIMESTAMP)"
                ),
                {
                    "operation_id": mutation.operation_id,
                    "target": "1" * 64,
                    "mount": "3" * 64,
                    "proposed": "4" * 64,
                    "binding": "5" * 64,
                    "staging": "staging-raw-metadata",
                    "staging_digest": "6" * 64,
                },
            )
        with pytest.raises(WorkspaceStoreError, match="integrity"):
            await workspaces.verify_integrity()

    with pytest.raises(KernelVerificationError, match="workspace operation provenance"):
        verify_database_read_only(
            database_path=tmp_path / "state/binnacle.db",
            runtime_directory=tmp_path / "run",
            busy_timeout_ms=5_000,
            wal_autocheckpoint_pages=1_000,
        )


@pytest.mark.anyio
async def test_verifiers_reject_activation_without_exact_phase4_effect_truth(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        authorised, pending = await _authorise_pending_session(
            sessions,
            operations,
            key_byte="c",
            session_id="dev_invented_activation",
        )
        active = await sessions.activate(
            session_id=pending.session_id,
            expected_state_version=pending.state_version,
            effect_reference="invented-activation",
            effect_reference_sha256="7" * 64,
            started_at=pending.created_at + timedelta(seconds=1),
        )
        await sessions.complete_activation(
            session_id=active.session_id,
            expected_state_version=active.state_version,
            closed_at=pending.created_at + timedelta(seconds=2),
        )
        assert authorised.state is OperationState.AUTHORISED
        with pytest.raises(DevelopmentSessionStoreError, match="integrity"):
            await sessions.verify_integrity()

    with pytest.raises(KernelVerificationError, match="development session provenance"):
        verify_database_read_only(
            database_path=tmp_path / "state/binnacle.db",
            runtime_directory=tmp_path / "run",
            busy_timeout_ms=5_000,
            wal_autocheckpoint_pages=1_000,
        )


@pytest.mark.anyio
async def test_verifiers_reject_foreign_or_contract_mismatched_fence_owner(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        workspaces = SqliteWorkspaceRepository(runtime)
        sessions = SqliteDevelopmentSessionRepository(runtime)
        await workspaces.register_workspace(_registration())
        session = await _active_session(
            sessions,
            operations,
            key_byte="d",
            session_id="dev_fence_integrity",
        )
        operation = await _operation_snapshot(
            operations,
            key_byte="e",
            fingerprint="e",
            contract="workspace_create",
            target_identity_sha256="f" * 64,
        )
        request = _authorisation_request(
            operation,
            session.session_id,
            decision_id="policy-fence-integrity",
        )
        await workspaces.authorise_mutation(request)
        async with runtime.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE workspace_mutation_fences SET active_contract='workspace_write' "
                    "WHERE workspace_id='workspace-fixture'"
                )
            )
        with pytest.raises(WorkspaceStoreError, match="integrity"):
            await workspaces.verify_integrity()

    with pytest.raises(KernelVerificationError, match="workspace fence owner"):
        verify_database_read_only(
            database_path=tmp_path / "state/binnacle.db",
            runtime_directory=tmp_path / "run",
            busy_timeout_ms=5_000,
            wal_autocheckpoint_pages=1_000,
        )

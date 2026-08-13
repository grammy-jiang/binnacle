"""Atomic Phase 9 restart admission and Phase 6 fence ownership tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from tests.phase4_support import NOW, operation_runtime, owner

from binnacle.adapters.sqlite.development_session import SqliteDevelopmentSessionRepository
from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.adapters.sqlite.privileged import (
    PrivilegedApplicationStoreError,
    SqlitePrivilegedApplicationRepository,
)
from binnacle.adapters.sqlite.workspace import SqliteWorkspaceRepository
from binnacle.domain.development_session import new_pending_session
from binnacle.domain.idempotency import IdempotencyKeyMode, owner_digest, validate_and_digest_key
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationIntent,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedMaximumEffect,
    PrivilegedTicket,
)
from binnacle.domain.privileged_restart import (
    PrivilegedOperationState,
    PrivilegedPreparationState,
    PrivilegedReservationState,
    PrivilegedRestartPreparation,
    RestartAuthorisationRequest,
)
from binnacle.ports.development_session import SessionAuthorisationRequest
from binnacle.ports.operation_store import CreateOrFindRequest
from binnacle.ports.workspace import RegisteredWorkspaceSnapshot

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
PROOF = "signed-proof-value-with-sufficient-length"


async def _received_operation(
    operations: SqliteOperationStore,
    *,
    key: str,
    contract: str,
    target_sha256: str,
    request_sha256: str = SHA_C,
) -> OperationSnapshot:
    request = CreateOrFindRequest(
        validate_and_digest_key(key * 64, IdempotencyKeyMode.CALLER_KEY),
        owner(),
        OperationIntent(
            operation_contract=contract,
            operation_contract_version="v1",
            request_fingerprint_sha256=request_sha256,
            device_id="device-fixture",
            device_epoch=1,
            runtime_build_sha256=SHA_D,
            runtime_config_sha256=SHA_E,
            tool_name=contract,
            tool_contract_version="v1",
            target_identity_sha256=target_sha256,
            maximum_effect_sha256=SHA_A,
        ),
        contract,
        "v1",
    )
    result = await operations.create_or_find(request)
    assert result.operation is not None
    return result.operation


async def _active_session(runtime: DatabaseRuntime, operations: SqliteOperationStore) -> None:
    workspaces = SqliteWorkspaceRepository(runtime)
    sessions = SqliteDevelopmentSessionRepository(runtime)
    await workspaces.register_workspace(
        RegisteredWorkspaceSnapshot(
            workspace_id="workspace-fixture",
            profile_sha256=SHA_A,
            root_identity_sha256=SHA_B,
            mount_identity_sha256=SHA_C,
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
    )
    begin = await _received_operation(
        operations,
        key="1",
        contract="development_session_begin",
        target_sha256=SHA_A,
    )
    pending = new_pending_session(
        session_id="session-fixture",
        begin_operation_id=begin.operation_id,
        controller_id="controller-fixture",
        controller_epoch=1,
        device_id="device-fixture",
        device_epoch=1,
        workspace_id="workspace-fixture",
        workspace_profile_sha256=SHA_A,
        workspace_root_identity_sha256=SHA_B,
        workspace_mount_identity_sha256=SHA_C,
        policy_version="policy-v1",
        contract_profile_sha256=SHA_D,
        objective_sha256=SHA_E,
        expires_at=NOW + timedelta(hours=2),
        trusted_time_generation=1,
        activation_boot_id_digest=SHA_A,
        monotonic_deadline_ns=3_600_000_000_000,
        now=NOW,
    )
    decision = PolicyDecision(
        policy_decision_id="policy-session",
        operation_id=begin.operation_id,
        policy_id="workspace-policy",
        policy_version="policy-v1",
        decision=PolicyDecisionValue.ALLOW,
        reason_codes=(),
        input_facts_sha256=SHA_A,
        runtime_policy_sha256=SHA_B,
        decided_at=NOW,
    )
    authorised, inserted = await sessions.authorise_begin(
        SessionAuthorisationRequest(
            operation=begin,
            snapshot=pending,
            decision=decision,
            required_scope_digest=None,
            normalized_target_digest=SHA_A,
            authorised_at=NOW,
        )
    )
    active = await sessions.activate(
        session_id=inserted.session_id,
        expected_state_version=inserted.state_version,
        effect_reference="activation-fixture",
        effect_reference_sha256=SHA_C,
        started_at=NOW,
    )
    await sessions.complete_activation(
        session_id=active.session_id,
        expected_state_version=active.state_version,
        closed_at=NOW,
    )
    assert authorised.state is OperationState.AUTHORISED


def _preparation(
    *,
    prepare_operation_id: str,
    nonce: str = "1" * 64,
    suffix: str = "first",
) -> PrivilegedRestartPreparation:
    nonce_sha256 = hashlib.sha256(bytes.fromhex(nonce)).hexdigest()
    return PrivilegedRestartPreparation(
        prepare_operation_id=prepare_operation_id,
        session_id="session-fixture",
        workspace_id="workspace-fixture",
        action=PrivilegedAction.CONTROLLED_RESTART,
        target_profile_id="service-profile",
        target_profile_sha256=SHA_B,
        maximum_effect=PrivilegedMaximumEffect.CONTROLLED_RESTART,
        normalized_request_sha256=SHA_C,
        current_state_binding_sha256=SHA_A,
        prepared_evidence_sha256=_digest(f"prepared:{suffix}"),
        execution_nonce_sha256=nonce_sha256,
        service_profile_sha256=SHA_B,
        candidate_verification_reference="verification-fixture",
        candidate_verification_sha256=SHA_C,
        candidate_slot_id="candidate-slot",
        lkg_slot_id="lkg-slot",
        schema_heads_sha256=SHA_A,
        runtime_layout_sha256=SHA_B,
        deployed_peer_set_sha256=SHA_C,
        state=PrivilegedPreparationState.AVAILABLE,
        consumed_by_operation_id=None,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        consumed_at=None,
        updated_at=NOW,
    )


def _decision(operation_id: str) -> PolicyDecision:
    return PolicyDecision(
        policy_decision_id=f"policy-{operation_id}",
        operation_id=operation_id,
        policy_id="privileged-policy",
        policy_version="policy-v1",
        decision=PolicyDecisionValue.ALLOW,
        reason_codes=(),
        input_facts_sha256=SHA_A,
        runtime_policy_sha256=SHA_E,
        decided_at=NOW + timedelta(seconds=1),
    )


def _ticket(
    operation: OperationSnapshot,
    preparation: PrivilegedRestartPreparation,
    *,
    nonce: str = "1" * 64,
    ticket_id: str = "ticket-fixture",
) -> PrivilegedTicket:
    return PrivilegedTicket(
        operation_id=operation.operation_id,
        ticket_id=ticket_id,
        nonce=nonce,
        controller_identity_sha256=owner_digest(operation.owner),
        device_id="device-fixture",
        device_epoch=1,
        operation_contract="binnacle_restart",
        operation_contract_version="v1",
        broker_profile_id="privileged-broker",
        broker_profile_version="v1",
        broker_profile_sha256=SHA_D,
        action=PrivilegedAction.CONTROLLED_RESTART,
        target_profile_id=preparation.target_profile_id,
        target_profile_sha256=preparation.target_profile_sha256,
        request_fingerprint_sha256=SHA_C,
        maximum_effect=PrivilegedMaximumEffect.CONTROLLED_RESTART,
        current_state_binding_sha256=preparation.current_state_binding_sha256,
        policy_evidence_reference=f"policy-{operation.operation_id}",
        policy_evidence_sha256=SHA_E,
        application_build_sha256=SHA_D,
        application_config_sha256=SHA_E,
        application_policy_sha256=SHA_E,
        operation_specific_evidence_sha256=preparation.prepared_evidence_sha256,
        issued_at=NOW + timedelta(seconds=2),
        expires_at=NOW + timedelta(minutes=2),
        integrity_algorithm="ed25519",
        integrity_proof=PROOF,
    )


def _broker_snapshot(
    ticket: PrivilegedTicket,
    *,
    execution_state: BrokerExecutionState = BrokerExecutionState.ACCEPTED_PRE_EFFECT,
    effect_knowledge: PrivilegedEffectKnowledge = PrivilegedEffectKnowledge.NONE,
    result_evidence_sha256: str | None = None,
) -> BrokerBindingSnapshot:
    return BrokerBindingSnapshot(
        identity=ticket.routing_identity,
        acceptance_state=BrokerAcceptanceState.ACCEPTED,
        evidence_generation=1,
        acceptance_evidence_sha256=_digest("broker-accepted"),
        execution_state=execution_state,
        effect_knowledge=effect_knowledge,
        result_evidence_sha256=result_evidence_sha256,
        accepted_at=ticket.issued_at + timedelta(milliseconds=100),
        sealed_at=None,
        closed_at=(
            ticket.issued_at + timedelta(milliseconds=200)
            if execution_state is BrokerExecutionState.TERMINAL
            else None
        ),
        last_reconciled_at=None,
    )


@pytest.mark.anyio
async def test_restart_admission_atomically_binds_policy_fence_ticket_and_reservation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        await _active_session(runtime, operations)
        prepare_operation = await _received_operation(
            operations,
            key="2",
            contract="privileged_prepare",
            target_sha256=SHA_B,
            request_sha256=SHA_B,
        )
        await operations.store_policy_decision(
            PolicyDecision(
                policy_decision_id="policy-prepare",
                operation_id=prepare_operation.operation_id,
                policy_id="privileged-policy",
                policy_version="policy-v1",
                decision=PolicyDecisionValue.ALLOW,
                reason_codes=(),
                input_facts_sha256=SHA_A,
                runtime_policy_sha256=SHA_D,
                decided_at=NOW,
            )
        )
        authorised_prepare = await operations.transition(
            prepare_operation.operation_id,
            _transition_to_authorised(prepare_operation),
        )
        running_prepare = await operations.transition(
            prepare_operation.operation_id,
            _transition_to_running(authorised_prepare),
        )
        await operations.transition(
            prepare_operation.operation_id,
            _transition_to_succeeded(running_prepare),
        )
        preparation = _preparation(prepare_operation_id=prepare_operation.operation_id)
        repository = SqlitePrivilegedApplicationRepository(runtime)
        await repository.store_restart_preparation(preparation)
        operation = await _received_operation(
            operations,
            key="3",
            contract="binnacle_restart",
            target_sha256=SHA_B,
        )
        ticket = _ticket(operation, preparation)
        decision = _decision(operation.operation_id)

        authorised, fence, retained = await repository.authorise_restart(
            RestartAuthorisationRequest(
                operation=operation,
                preparation=preparation,
                decision=decision,
                ticket=ticket,
                expected_fence_version=1,
                required_scope_digest=None,
                authorised_at=ticket.issued_at,
            )
        )

        assert authorised.state is OperationState.AUTHORISED
        assert fence.active_operation_id == operation.operation_id
        assert fence.active_contract == "binnacle_restart"
        assert retained.ticket_sha256 == ticket.ticket_sha256
        assert retained.state is PrivilegedOperationState.PREPARED
        assert retained.reservation_state is PrivilegedReservationState.HELD
        assert await repository.get_restart(operation.operation_id) == retained
        assert await repository.restart_recovery_pending()
        await SqliteWorkspaceRepository(runtime).verify_integrity()
        async with runtime.engine.connect() as connection:
            assert (
                await connection.execute(
                    text(
                        "SELECT state,consumed_by_operation_id FROM privileged_preparations "
                        "WHERE prepare_operation_id=:operation_id"
                    ),
                    {"operation_id": prepare_operation.operation_id},
                )
            ).one() == ("consumed", operation.operation_id)

        accepted = _broker_snapshot(ticket)
        with pytest.raises(
            PrivilegedApplicationStoreError,
            match="before the durable dispatch marker",
        ):
            await repository.record_broker_snapshot(
                accepted,
                reconciled_at=ticket.issued_at + timedelta(seconds=1),
            )

        dispatched = await repository.mark_restart_dispatched(
            operation.operation_id,
            dispatched_at=ticket.issued_at + timedelta(seconds=1),
        )
        assert dispatched.state is PrivilegedOperationState.DISPATCHED
        reconciled = await repository.record_broker_snapshot(
            accepted,
            reconciled_at=ticket.issued_at + timedelta(seconds=2),
        )
        assert reconciled.state is PrivilegedOperationState.RECONCILING
        assert reconciled.broker_acceptance_state is BrokerAcceptanceState.ACCEPTED

        uncertain = _broker_snapshot(
            ticket,
            execution_state=BrokerExecutionState.UNCERTAIN,
            effect_knowledge=PrivilegedEffectKnowledge.UNCERTAIN,
            result_evidence_sha256=_digest("uncertain-broker-result"),
        )
        retained_uncertain = await repository.record_broker_snapshot(
            uncertain,
            reconciled_at=ticket.issued_at + timedelta(seconds=3),
        )
        assert retained_uncertain.state is PrivilegedOperationState.UNCERTAIN
        assert retained_uncertain.reservation_state is PrivilegedReservationState.UNCERTAIN
        phase4_uncertain = await operations.get_operation(operation.operation_id)
        assert phase4_uncertain is not None
        assert phase4_uncertain.state is OperationState.UNCERTAIN
        assert phase4_uncertain.effect_knowledge is EffectKnowledge.UNCERTAIN
        await SqliteWorkspaceRepository(runtime).verify_integrity()


@pytest.mark.anyio
async def test_restart_admission_rolls_back_all_writes_when_reservation_is_busy(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        await _active_session(runtime, operations)
        first_prepare = await _qualifying_prepare_operation(
            operations,
            key="4",
        )
        first_preparation = _preparation(prepare_operation_id=first_prepare.operation_id)
        repository = SqlitePrivilegedApplicationRepository(runtime)
        await repository.store_restart_preparation(first_preparation)
        first_operation = await _received_operation(
            operations,
            key="5",
            contract="binnacle_restart",
            target_sha256=SHA_B,
        )
        first_ticket = _ticket(first_operation, first_preparation)
        await repository.authorise_restart(
            RestartAuthorisationRequest(
                operation=first_operation,
                preparation=first_preparation,
                decision=_decision(first_operation.operation_id),
                ticket=first_ticket,
                expected_fence_version=1,
                required_scope_digest=None,
                authorised_at=first_ticket.issued_at,
            )
        )

        second_prepare = await _qualifying_prepare_operation(
            operations,
            key="6",
        )
        second_preparation = _preparation(
            prepare_operation_id=second_prepare.operation_id,
            nonce="2" * 64,
            suffix="second",
        )
        await repository.store_restart_preparation(second_preparation)
        second_operation = await _received_operation(
            operations,
            key="7",
            contract="binnacle_restart",
            target_sha256=SHA_B,
        )
        second_ticket = _ticket(
            second_operation,
            second_preparation,
            nonce="2" * 64,
            ticket_id="ticket-second",
        )
        with pytest.raises(PrivilegedApplicationStoreError, match="fence is busy"):
            await repository.authorise_restart(
                RestartAuthorisationRequest(
                    operation=second_operation,
                    preparation=second_preparation,
                    decision=_decision(second_operation.operation_id),
                    ticket=second_ticket,
                    expected_fence_version=2,
                    required_scope_digest=None,
                    authorised_at=second_ticket.issued_at,
                )
            )

        second_retained = await operations.get_operation(second_operation.operation_id)
        assert second_retained is not None
        assert second_retained.state is OperationState.RECEIVED
        assert await repository.get_restart(second_operation.operation_id) is None
        async with runtime.engine.connect() as connection:
            preparation_row = (
                await connection.execute(
                    text(
                        "SELECT state,consumed_by_operation_id FROM privileged_preparations "
                        "WHERE prepare_operation_id=:operation_id"
                    ),
                    {"operation_id": second_prepare.operation_id},
                )
            ).one()
            policy_count = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM policy_decisions WHERE operation_id=:operation_id"),
                    {"operation_id": second_operation.operation_id},
                )
            ).scalar_one()
        assert preparation_row == ("available", None)
        assert policy_count == 0


def _transition_to_authorised(operation: OperationSnapshot) -> TransitionRequest:
    return TransitionRequest(
        expected_state_version=operation.state_version,
        to_state=OperationState.AUTHORISED,
        effect_knowledge=EffectKnowledge.NONE,
        reason_code="policy_allowed",
    )


def _transition_to_running(operation: OperationSnapshot) -> TransitionRequest:
    return TransitionRequest(
        expected_state_version=operation.state_version,
        to_state=OperationState.RUNNING,
        effect_knowledge=EffectKnowledge.NONE,
        reason_code="operation_started",
        occurred_at=NOW,
    )


def _transition_to_succeeded(operation: OperationSnapshot) -> TransitionRequest:
    return TransitionRequest(
        expected_state_version=operation.state_version,
        to_state=OperationState.SUCCEEDED,
        effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
        reason_code="prepare_complete",
        occurred_at=NOW,
    )


async def _qualifying_prepare_operation(
    operations: SqliteOperationStore,
    *,
    key: str,
) -> OperationSnapshot:
    operation = await _received_operation(
        operations,
        key=key,
        contract="privileged_prepare",
        target_sha256=SHA_B,
        request_sha256=SHA_B,
    )
    await operations.store_policy_decision(
        PolicyDecision(
            policy_decision_id=f"policy-{operation.operation_id}",
            operation_id=operation.operation_id,
            policy_id="privileged-policy",
            policy_version="policy-v1",
            decision=PolicyDecisionValue.ALLOW,
            reason_codes=(),
            input_facts_sha256=SHA_A,
            runtime_policy_sha256=SHA_D,
            decided_at=NOW,
        )
    )
    authorised = await operations.transition(
        operation.operation_id,
        _transition_to_authorised(operation),
    )
    running = await operations.transition(
        operation.operation_id,
        _transition_to_running(authorised),
    )
    return await operations.transition(
        operation.operation_id,
        _transition_to_succeeded(running),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

"""Durable lifecycle, idempotency, prepared nonce, and tombstone tests."""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from tests.phase4_support import NOW, intent, operation_runtime, owner

from binnacle.adapters.sqlite.models import (
    IdempotencyBindingModel,
    OperationTransitionModel,
    PolicyDecisionModel,
)
from binnacle.adapters.sqlite.operation_store import OperationStoreError
from binnacle.application.boundary import DispatchHandoffGate
from binnacle.application.operations import OperationService
from binnacle.application.trusted_time import TrustedTimeGuard
from binnacle.domain.idempotency import (
    BindingRecordKind,
    IdempotencyKey,
    IdempotencyKeyMode,
    IdempotencyOutcome,
    validate_and_digest_key,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationOwner,
    OperationState,
    OperationTransitionError,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.domain.trusted_time import DeadlineStatus, TrustedTimeSnapshot
from binnacle.ports.operation_store import (
    CreateOrFindRequest,
    PreparedNonceRegistration,
)


def _key(mode: IdempotencyKeyMode = IdempotencyKeyMode.CALLER_KEY) -> IdempotencyKey:
    return validate_and_digest_key(secrets.token_hex(32), mode)


def _request(
    key: IdempotencyKey,
    *,
    controller: OperationOwner | None = None,
    fingerprint: str = "a" * 64,
    **kwargs: Any,
) -> CreateOrFindRequest:
    controller = controller or owner()
    return CreateOrFindRequest(
        key=key,
        owner=controller,
        intent=intent(fingerprint=fingerprint),
        tool_name="internal.synthetic",
        contract_version="1.0.0",
        **kwargs,
    )


def _decision(
    operation_id: str, value: PolicyDecisionValue = PolicyDecisionValue.ALLOW
) -> PolicyDecision:
    return PolicyDecision(
        policy_decision_id=f"policy_{secrets.token_hex(16)}",
        operation_id=operation_id,
        policy_id="test-policy",
        policy_version="1.0.0",
        decision=value,
        reason_codes=("test",),
        input_facts_sha256="f" * 64,
        runtime_policy_sha256="e" * 64,
        decided_at=NOW,
    )


@pytest.mark.anyio
async def test_create_find_conflict_and_owner_mismatch_are_global(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        key = _key()
        created = await store.create_or_find(_request(key))
        retained = await store.create_or_find(_request(key))
        conflict = await store.create_or_find(_request(key, fingerprint="9" * 64))
        mismatch = await store.create_or_find(
            _request(key, controller=owner("replacement-controller"))
        )
        assert created.outcome is IdempotencyOutcome.CREATED
        assert retained.outcome is IdempotencyOutcome.RETAINED_OPERATION
        assert created.operation is not None
        assert retained.operation is not None
        assert retained.operation.operation_id == created.operation.operation_id
        assert conflict == type(conflict)(IdempotencyOutcome.CONFLICT, None)
        assert mismatch == type(mismatch)(IdempotencyOutcome.OWNER_MISMATCH, None)


@pytest.mark.anyio
async def test_existing_kernel_rejects_foreign_audit_identity(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        with pytest.raises(OperationStoreError, match="audit identity"):
            await store.initialize_kernel(
                device_id="device-fixture", audit_stream_id="foreign-stream"
            )
        with pytest.raises(OperationStoreError, match="audit identity"):
            await store.initialize_kernel(
                device_id="device-fixture",
                audit_stream_id="stream-fixture",
                audit_epoch="foreign-epoch",
            )


@pytest.mark.anyio
async def test_durable_admission_cannot_open_across_an_audit_failure(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        assert not await store.consequential_admission_enabled()
        await store.set_consequential_admission_enabled(True)
        assert await store.consequential_admission_enabled()
        await store.latch_audit_failure("test_failure")
        assert not await store.consequential_admission_enabled()
        with pytest.raises(OperationStoreError, match="forbids consequential"):
            await store.set_consequential_admission_enabled(True)


@pytest.mark.anyio
async def test_policy_is_required_and_state_versions_are_optimistic(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, store):
        created = await store.create_or_find(_request(_key()))
        assert created.operation is not None
        operation = created.operation
        with pytest.raises(OperationStoreError, match="without policy"):
            await store.transition(
                operation.operation_id,
                TransitionRequest(
                    1, OperationState.AUTHORISED, EffectKnowledge.NONE, "not_allowed"
                ),
            )
        decision = _decision(operation.operation_id)
        await store.store_policy_decision(decision)
        authorised = await store.transition(
            operation.operation_id,
            TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
        )
        assert authorised.state_version == 2
        assert await store.get_policy_decision(operation.operation_id) == decision
        with pytest.raises(OperationTransitionError, match="version conflict"):
            await store.transition(
                operation.operation_id,
                TransitionRequest(1, OperationState.RUNNING, EffectKnowledge.NONE, "stale"),
            )
        async with runtime.session_factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(OperationTransitionModel)
                    .where(OperationTransitionModel.operation_id == operation.operation_id)
                )
            ).scalar_one()
        assert count == 2


@pytest.mark.anyio
async def test_second_or_orphan_policy_decision_is_database_rejected(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, store):
        created = await store.create_or_find(_request(_key()))
        assert created.operation is not None
        await store.store_policy_decision(_decision(created.operation.operation_id))
        with pytest.raises(IntegrityError):
            await store.store_policy_decision(_decision(created.operation.operation_id))
        async with runtime.session_factory() as session, session.begin():
            session.add(
                PolicyDecisionModel(
                    policy_decision_id="orphan",
                    operation_id="op_missing",
                    policy_id="test",
                    policy_version="1",
                    decision="deny",
                    controller_id="controller",
                    controller_epoch=1,
                    operation_contract="synthetic",
                    operation_contract_version="1",
                    required_scope_digest=None,
                    normalized_target_digest=None,
                    input_facts_sha256="a" * 64,
                    reason_codes_json="[]",
                    decided_at=NOW,
                    runtime_policy_sha256="b" * 64,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()


@pytest.mark.anyio
async def test_received_restart_rejection_atomically_creates_one_decision(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, store):
        created = await store.create_or_find(_request(_key()))
        assert created.operation is not None
        rejected = await store.reject_received_on_restart(
            created.operation.operation_id,
            _decision(created.operation.operation_id, PolicyDecisionValue.DENY),
        )
        assert rejected.state is OperationState.REJECTED
        again = await store.reject_received_on_restart(
            rejected.operation_id, _decision(rejected.operation_id, PolicyDecisionValue.DENY)
        )
        assert again == rejected
        async with runtime.session_factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(PolicyDecisionModel)
                    .where(PolicyDecisionModel.operation_id == rejected.operation_id)
                )
            ).scalar_one()
        assert count == 1


@pytest.mark.anyio
async def test_prepared_nonce_expiry_is_durable_and_compacts_exactly(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, store):
        key = _key(IdempotencyKeyMode.PREPARED_EXECUTION_NONCE)
        registration = PreparedNonceRegistration(
            key=key,
            owner=owner(),
            device_id="device-fixture",
            device_epoch=1,
            tool_name="internal.synthetic",
            contract_version="1.0.0",
            request_fingerprint_sha256="a" * 64,
            prepared_operation_id="prepared-fixture",
            prepared_input_sha256="1" * 64,
            prepared_expires_at=NOW + timedelta(minutes=5),
            prepared_state_binding_sha256="2" * 64,
            registered_boot_id_digest="3" * 64,
            monotonic_deadline_ns=100,
        )
        await store.register_prepared_execution_nonce(registration)
        expired_request = _request(
            key,
            fingerprint="9" * 64,
            prepared_operation_id="prepared-fixture",
            prepared_input_sha256="9" * 64,
            prepared_state_binding_sha256="2" * 64,
            prepared_deadline_status=DeadlineStatus.EXPIRED,
        )
        assert (
            await store.create_or_find(expired_request)
        ).outcome is IdempotencyOutcome.PREPARED_EXPIRED
        await store.compact_idempotency_binding(
            device_id="device-fixture",
            device_epoch=1,
            tool_name="internal.synthetic",
            contract_version="1.0.0",
            key_digest_sha256=key.digest_sha256,
            retired_at=NOW + timedelta(days=30),
        )
        assert (
            await store.create_or_find(expired_request)
        ).outcome is IdempotencyOutcome.KEY_RETIRED
        cross_controller = _request(
            key,
            controller=owner("replacement"),
            prepared_operation_id="prepared-fixture",
            prepared_input_sha256="1" * 64,
            prepared_state_binding_sha256="2" * 64,
            prepared_deadline_status=DeadlineStatus.EXPIRED,
        )
        assert (
            await store.create_or_find(cross_controller)
        ).outcome is IdempotencyOutcome.OWNER_MISMATCH
        async with runtime.session_factory() as session:
            row = (await session.execute(select(IdempotencyBindingModel))).scalar_one()
            assert row.record_kind == BindingRecordKind.TOMBSTONE.value
            assert row.operation_id is None
            assert row.owner_controller_id is None
            assert row.prepared_operation_id is None
            assert row.prepared_input_sha256 is None
            assert row.prepared_expires_at is None
            assert row.prepared_state_binding_sha256 is None
            assert row.prepared_registered_boot_id_digest is None
            assert row.prepared_monotonic_deadline_ns is None
            assert row.target_identity_sha256 is None
            assert row.maximum_effect_sha256 is None


@pytest.mark.anyio
async def test_unavailable_trusted_time_is_distinct_and_creates_no_operation(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        key = _key(IdempotencyKeyMode.PREPARED_EXECUTION_NONCE)
        await store.register_prepared_execution_nonce(
            PreparedNonceRegistration(
                key,
                owner(),
                "device-fixture",
                1,
                "internal.synthetic",
                "1.0.0",
                "a" * 64,
                "prepared-fixture",
                "1" * 64,
                NOW + timedelta(minutes=5),
                "2" * 64,
                "3" * 64,
                100,
            )
        )
        result = await store.create_or_find(
            _request(
                key,
                prepared_operation_id="prepared-fixture",
                prepared_input_sha256="1" * 64,
                prepared_state_binding_sha256="2" * 64,
                prepared_deadline_status=DeadlineStatus.UNAVAILABLE,
            )
        )
        assert result.outcome is IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE
        assert result.operation is None


@pytest.mark.anyio
async def test_database_rejects_ownerless_full_idempotency_binding(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, store):
        await store.create_or_find(_request(_key()))
        async with runtime.session_factory() as session, session.begin():
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(IdempotencyBindingModel).values(
                        owner_controller_id=None, owner_controller_epoch=None
                    )
                )


@pytest.mark.anyio
async def test_internal_operation_service_enforces_owner_and_cancellation_states(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        service = OperationService(store, DispatchHandoffGate())
        created = await store.create_or_find(_request(_key()))
        assert created.operation is not None
        operation = created.operation
        assert await service.get_operation(operation.operation_id, owner()) == operation
        with pytest.raises(RuntimeError, match="owner_mismatch"):
            await service.get_operation(operation.operation_id, owner("different"))
        with pytest.raises(RuntimeError, match="not_found"):
            await service.get_operation("op_missing", owner())

        await store.store_policy_decision(_decision(operation.operation_id))
        authorised = await store.transition(
            operation.operation_id,
            TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
        )
        cancelled = await service.request_cancel(authorised.operation_id, owner())
        assert cancelled.state is OperationState.CANCELLED
        with pytest.raises(RuntimeError, match="not_supported"):
            await service.request_cancel(cancelled.operation_id, owner())

        second = await store.create_or_find(_request(_key()))
        assert second.operation is not None
        await store.store_policy_decision(_decision(second.operation.operation_id))
        second_authorised = await store.transition(
            second.operation.operation_id,
            TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
        )
        running = await store.transition(
            second_authorised.operation_id,
            TransitionRequest(2, OperationState.RUNNING, EffectKnowledge.NONE, "dispatch"),
        )
        cancelling = await service.request_cancel(running.operation_id, owner())
        assert cancelling.state is OperationState.CANCELLING


@pytest.mark.anyio
async def test_trusted_time_guard_persists_accepted_high_watermark(
    tmp_path: Path, repo_root: Path
) -> None:
    class Source:
        async def snapshot(self) -> TrustedTimeSnapshot:
            return TrustedTimeSnapshot(NOW, 50, "a" * 64, True)

    async with operation_runtime(tmp_path, repo_root) as (_, store):
        guard = TrustedTimeGuard(source=Source(), store=store)
        result = await guard.evaluate(
            expires_at=NOW + timedelta(minutes=5),
            registered_boot_id_digest="a" * 64,
            monotonic_deadline_ns=100,
        )
        assert result.status is DeadlineStatus.VALID
        assert result.accepted_evidence is not None
        assert await store.get_trusted_time_evidence() == result.accepted_evidence


@pytest.mark.anyio
async def test_valid_prepared_nonce_attaches_once_and_later_expiry_returns_retained(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        key = _key(IdempotencyKeyMode.PREPARED_EXECUTION_NONCE)
        await store.register_prepared_execution_nonce(
            PreparedNonceRegistration(
                key,
                owner(),
                "device-fixture",
                1,
                "internal.synthetic",
                "1.0.0",
                "a" * 64,
                "prepared-fixture",
                "1" * 64,
                NOW + timedelta(minutes=5),
                "2" * 64,
                "3" * 64,
                100,
            )
        )
        request = _request(
            key,
            prepared_operation_id="prepared-fixture",
            prepared_input_sha256="1" * 64,
            prepared_state_binding_sha256="2" * 64,
            prepared_deadline_status=DeadlineStatus.VALID,
        )
        first = await store.create_or_find(request)
        assert first.outcome is IdempotencyOutcome.CREATED
        later = await store.create_or_find(
            _request(
                key,
                prepared_operation_id="prepared-fixture",
                prepared_input_sha256="1" * 64,
                prepared_state_binding_sha256="2" * 64,
                prepared_deadline_status=DeadlineStatus.EXPIRED,
            )
        )
        assert later.outcome is IdempotencyOutcome.RETAINED_OPERATION
        assert later.operation is not None
        assert first.operation is not None
        assert later.operation.operation_id == first.operation.operation_id

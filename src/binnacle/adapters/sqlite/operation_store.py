"""SQLAlchemy/SQLite durable operation and idempotency repository."""

from __future__ import annotations

import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import (
    ControllerOwnerModel,
    IdempotencyBindingModel,
    KernelMetaModel,
    OperationModel,
    OperationTransitionModel,
    PolicyDecisionModel,
)
from binnacle.domain.audit import AuditTail
from binnacle.domain.idempotency import (
    BindingRecordKind,
    IdempotencyKeyMode,
    IdempotencyOutcome,
    owner_digest,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationIntent,
    OperationOwner,
    OperationSnapshot,
    OperationState,
    OperationTransitionError,
    Terminality,
    TransitionRequest,
    new_received_operation,
    transition,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.domain.trusted_time import DeadlineStatus, TrustedTimeEvidence
from binnacle.ports.operation_store import (
    CreateOrFindRequest,
    CreateOrFindResult,
    PreparedExecutionAdmission,
    PreparedExecutionRecord,
    PreparedNonceRegistration,
    ReconciliationCursor,
)


class OperationStoreError(RuntimeError):
    pass


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqliteOperationStore:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime

    async def initialize_kernel(
        self,
        *,
        device_id: str,
        audit_stream_id: str,
        audit_epoch: str = "epoch-1",
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        async with self._runtime.session_factory() as session, session.begin():
            existing = await session.get(KernelMetaModel, 1)
            if existing is None:
                session.add(
                    KernelMetaModel(
                        id=1,
                        schema_generation=2,
                        device_id=device_id,
                        device_epoch=1,
                        created_at=timestamp,
                        updated_at=timestamp,
                        audit_stream_id=audit_stream_id,
                        audit_epoch=audit_epoch,
                        audit_epoch_generation=1,
                        audit_last_sequence=0,
                        audit_last_hash=None,
                        audit_failure_generation=0,
                        audit_failure_latched=False,
                        audit_failure_reason_code=None,
                        audit_failure_detected_at=None,
                        audit_recovered_generation=0,
                        audit_recovery_evidence_sha256=None,
                        trusted_wall_time_high_watermark=None,
                        trusted_time_boot_id_digest=None,
                        trusted_time_monotonic_ns=None,
                        trusted_time_generation=1,
                        consequential_admission_enabled=False,
                    )
                )
            elif (
                existing.schema_generation != 2
                or existing.device_id != device_id
                or existing.audit_stream_id != audit_stream_id
                or existing.audit_epoch != audit_epoch
            ):
                raise OperationStoreError("durable device or audit identity does not match runtime")

    async def _ensure_owner(
        self, session: AsyncSession, owner: OperationOwner, now: datetime
    ) -> None:
        current = await session.get(
            ControllerOwnerModel, (owner.controller_id, owner.controller_epoch)
        )
        if current is None:
            session.add(
                ControllerOwnerModel(
                    controller_id=owner.controller_id,
                    controller_epoch=owner.controller_epoch,
                    controller_profile_id=owner.controller_profile_id,
                    controller_profile_version=owner.controller_profile_version,
                    first_seen_at=now,
                    last_seen_at=now,
                    active=True,
                )
            )
        else:
            if (
                current.controller_profile_id != owner.controller_profile_id
                or current.controller_profile_version != owner.controller_profile_version
            ):
                raise OperationStoreError("controller ownership profile changed incompatibly")
            current.last_seen_at = now

    @staticmethod
    def _scope_filter(request: CreateOrFindRequest) -> tuple[ColumnElement[bool], ...]:
        return (
            IdempotencyBindingModel.device_id == request.intent.device_id,
            IdempotencyBindingModel.device_epoch == request.intent.device_epoch,
            IdempotencyBindingModel.tool_name == request.tool_name,
            IdempotencyBindingModel.contract_version == request.contract_version,
            IdempotencyBindingModel.key_digest_sha256 == request.key.digest_sha256,
        )

    async def find_existing(self, request: CreateOrFindRequest) -> CreateOrFindResult | None:
        """Classify an existing binding without creating a new operation."""

        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                binding = (
                    await session.execute(
                        select(IdempotencyBindingModel).where(*self._scope_filter(request))
                    )
                ).scalar_one_or_none()
                if binding is None:
                    await session.commit()
                    return None
                result = await self._classify_existing(session, binding, request, now)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def create_or_find(self, request: CreateOrFindRequest) -> CreateOrFindResult:
        if request.key.mode is IdempotencyKeyMode.DERIVED_MEMBER_KEY:
            raise OperationStoreError("idempotency_invalid")
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                binding = (
                    await session.execute(
                        select(IdempotencyBindingModel).where(*self._scope_filter(request))
                    )
                ).scalar_one_or_none()
                if binding is not None:
                    result = await self._classify_existing(session, binding, request, now)
                    await session.commit()
                    return result
                if request.key.mode is IdempotencyKeyMode.PREPARED_EXECUTION_NONCE:
                    await session.rollback()
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)
                await self._ensure_owner(session, request.owner, now)
                await session.flush()
                operation = new_received_operation(
                    owner=request.owner, intent=request.intent, now=now
                )
                session.add(self._operation_model(operation))
                await session.flush()
                session.add(self._initial_transition_model(operation))
                session.add(
                    IdempotencyBindingModel(
                        binding_id=f"binding_{secrets.token_hex(16)}",
                        device_id=request.intent.device_id,
                        device_epoch=request.intent.device_epoch,
                        key_mode=request.key.mode.value,
                        key_digest_sha256=request.key.digest_sha256,
                        tool_name=request.tool_name,
                        contract_version=request.contract_version,
                        owner_controller_id=request.owner.controller_id,
                        owner_controller_epoch=request.owner.controller_epoch,
                        owner_controller_digest=owner_digest(request.owner),
                        request_fingerprint_sha256=request.intent.request_fingerprint_sha256,
                        prepared_operation_id=None,
                        prepared_input_sha256=None,
                        prepared_expires_at=None,
                        prepared_state_binding_sha256=None,
                        prepared_registered_boot_id_digest=None,
                        prepared_monotonic_deadline_ns=None,
                        target_identity_sha256=request.intent.target_identity_sha256,
                        maximum_effect_sha256=request.intent.maximum_effect_sha256,
                        operation_id=operation.operation_id,
                        terminal_class=None,
                        created_at=now,
                        last_access_at=now,
                        terminal_at=None,
                        retired_at=None,
                        record_kind=BindingRecordKind.FULL.value,
                        duplicate_count=0,
                        conflict_count=0,
                    )
                )
                await session.commit()
                return CreateOrFindResult(IdempotencyOutcome.CREATED, operation)
            except Exception:
                await session.rollback()
                raise

    async def create_or_find_prepared(
        self, request: PreparedExecutionAdmission
    ) -> CreateOrFindResult:
        """Atomically bind one caller key to one unconsumed prepared nonce.

        The caller binding is always checked first, including on the retry race after
        mutable preparation revalidation.  A retained caller therefore remains
        retrievable after its preparation expires or its external state changes.
        """

        caller = request.caller
        if caller.key.mode is not IdempotencyKeyMode.CALLER_KEY:
            raise OperationStoreError("prepared execution requires caller-key mode")
        if request.prepared_key.mode is not IdempotencyKeyMode.PREPARED_EXECUTION_NONCE:
            raise OperationStoreError("prepared execution requires prepared-nonce mode")
        prepared_request = replace(caller, key=request.prepared_key)
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                caller_binding = (
                    await session.execute(
                        select(IdempotencyBindingModel).where(*self._scope_filter(caller))
                    )
                ).scalar_one_or_none()
                if caller_binding is not None:
                    result = await self._classify_existing(session, caller_binding, caller, now)
                    await session.commit()
                    return result

                prepared = (
                    await session.execute(
                        select(IdempotencyBindingModel).where(*self._scope_filter(prepared_request))
                    )
                ).scalar_one_or_none()
                if prepared is None:
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)
                prepared.last_access_at = now
                if prepared.owner_controller_digest != owner_digest(caller.owner):
                    prepared.conflict_count += 1
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.OWNER_MISMATCH, None)
                if prepared.record_kind == BindingRecordKind.TOMBSTONE.value:
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.KEY_RETIRED, None)
                if prepared.key_mode != IdempotencyKeyMode.PREPARED_EXECUTION_NONCE.value:
                    raise OperationStoreError("prepared binding has an invalid key mode")
                if prepared.operation_id is not None:
                    prepared.conflict_count += 1
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.CONFLICT, None)
                if (
                    prepared.terminal_class == IdempotencyOutcome.PREPARED_EXPIRED.value
                    or caller.prepared_deadline_status is DeadlineStatus.EXPIRED
                ):
                    prepared.terminal_class = IdempotencyOutcome.PREPARED_EXPIRED.value
                    prepared.terminal_at = prepared.terminal_at or now
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_EXPIRED, None)
                if caller.prepared_deadline_status is DeadlineStatus.UNAVAILABLE:
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE, None)
                if prepared.request_fingerprint_sha256 != caller.intent.request_fingerprint_sha256:
                    prepared.conflict_count += 1
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.CONFLICT, None)
                mismatch = (
                    caller.prepared_operation_id != prepared.prepared_operation_id
                    or caller.prepared_input_sha256 != prepared.prepared_input_sha256
                    or caller.prepared_state_binding_sha256
                    != prepared.prepared_state_binding_sha256
                    or caller.intent.target_identity_sha256 != prepared.target_identity_sha256
                    or caller.intent.maximum_effect_sha256 != prepared.maximum_effect_sha256
                )
                if mismatch:
                    prepared.conflict_count += 1
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)
                if caller.prepared_deadline_status is not DeadlineStatus.VALID:
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE, None)
                if (
                    caller.verified_prepared_state_binding_sha256
                    != prepared.prepared_state_binding_sha256
                ):
                    prepared.conflict_count += 1
                    await session.commit()
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)

                await self._ensure_owner(session, caller.owner, now)
                await session.flush()
                operation = new_received_operation(
                    owner=caller.owner,
                    intent=caller.intent,
                    now=now,
                )
                session.add(self._operation_model(operation))
                await session.flush()
                session.add(self._initial_transition_model(operation))
                prepared.operation_id = operation.operation_id
                prepared.duplicate_count += 1
                session.add(
                    IdempotencyBindingModel(
                        binding_id=f"binding_{secrets.token_hex(16)}",
                        device_id=caller.intent.device_id,
                        device_epoch=caller.intent.device_epoch,
                        key_mode=caller.key.mode.value,
                        key_digest_sha256=caller.key.digest_sha256,
                        tool_name=caller.tool_name,
                        contract_version=caller.contract_version,
                        owner_controller_id=caller.owner.controller_id,
                        owner_controller_epoch=caller.owner.controller_epoch,
                        owner_controller_digest=owner_digest(caller.owner),
                        request_fingerprint_sha256=caller.intent.request_fingerprint_sha256,
                        prepared_operation_id=None,
                        prepared_input_sha256=None,
                        prepared_expires_at=None,
                        prepared_state_binding_sha256=None,
                        prepared_registered_boot_id_digest=None,
                        prepared_monotonic_deadline_ns=None,
                        target_identity_sha256=caller.intent.target_identity_sha256,
                        maximum_effect_sha256=caller.intent.maximum_effect_sha256,
                        operation_id=operation.operation_id,
                        terminal_class=None,
                        created_at=now,
                        last_access_at=now,
                        terminal_at=None,
                        retired_at=None,
                        record_kind=BindingRecordKind.FULL.value,
                        duplicate_count=0,
                        conflict_count=0,
                    )
                )
                await session.commit()
                return CreateOrFindResult(IdempotencyOutcome.CREATED, operation)
            except Exception:
                await session.rollback()
                raise

    async def _classify_existing(
        self,
        session: AsyncSession,
        binding: IdempotencyBindingModel,
        request: CreateOrFindRequest,
        now: datetime,
    ) -> CreateOrFindResult:
        current_owner_digest = owner_digest(request.owner)
        binding.last_access_at = now
        if binding.owner_controller_digest != current_owner_digest:
            binding.conflict_count += 1
            return CreateOrFindResult(IdempotencyOutcome.OWNER_MISMATCH, None)
        if binding.record_kind == BindingRecordKind.TOMBSTONE.value:
            return CreateOrFindResult(IdempotencyOutcome.KEY_RETIRED, None)
        if binding.key_mode == IdempotencyKeyMode.PREPARED_EXECUTION_NONCE.value:
            if binding.operation_id is None:
                if (
                    binding.terminal_class == IdempotencyOutcome.PREPARED_EXPIRED.value
                    or request.prepared_deadline_status is DeadlineStatus.EXPIRED
                ):
                    binding.terminal_class = IdempotencyOutcome.PREPARED_EXPIRED.value
                    binding.terminal_at = binding.terminal_at or now
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_EXPIRED, None)
                if request.prepared_deadline_status is DeadlineStatus.UNAVAILABLE:
                    return CreateOrFindResult(IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE, None)
            if binding.request_fingerprint_sha256 != request.intent.request_fingerprint_sha256:
                binding.conflict_count += 1
                return CreateOrFindResult(IdempotencyOutcome.CONFLICT, None)
            mismatch = (
                request.prepared_operation_id != binding.prepared_operation_id
                or request.prepared_input_sha256 != binding.prepared_input_sha256
                or request.prepared_state_binding_sha256 != binding.prepared_state_binding_sha256
            )
            if mismatch:
                binding.conflict_count += 1
                return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)
            if binding.operation_id is None:
                if request.prepared_deadline_status is not DeadlineStatus.VALID:
                    return CreateOrFindResult(IdempotencyOutcome.TRUSTED_TIME_UNAVAILABLE, None)
                if (
                    request.verified_prepared_state_binding_sha256
                    != binding.prepared_state_binding_sha256
                ):
                    binding.conflict_count += 1
                    return CreateOrFindResult(IdempotencyOutcome.PREPARED_MISMATCH, None)
                await self._ensure_owner(session, request.owner, now)
                await session.flush()
                operation = new_received_operation(
                    owner=request.owner, intent=request.intent, now=now
                )
                session.add(self._operation_model(operation))
                await session.flush()
                session.add(self._initial_transition_model(operation))
                binding.operation_id = operation.operation_id
                binding.duplicate_count += 1
                return CreateOrFindResult(IdempotencyOutcome.CREATED, operation)
        elif binding.request_fingerprint_sha256 != request.intent.request_fingerprint_sha256:
            binding.conflict_count += 1
            return CreateOrFindResult(IdempotencyOutcome.CONFLICT, None)
        binding.duplicate_count += 1
        if binding.operation_id is None:
            raise OperationStoreError("full idempotency binding has no operation")
        operation_model = await session.get(OperationModel, binding.operation_id)
        if operation_model is None:
            raise OperationStoreError("idempotency binding references a missing operation")
        return CreateOrFindResult(
            IdempotencyOutcome.RETAINED_OPERATION,
            await self._snapshot(session, operation_model),
        )

    async def register_prepared_execution_nonce(
        self, registration: PreparedNonceRegistration
    ) -> None:
        if registration.key.mode is not IdempotencyKeyMode.PREPARED_EXECUTION_NONCE:
            raise OperationStoreError("prepared registration requires prepared nonce mode")
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                await self._ensure_owner(session, registration.owner, now)
                await session.flush()
                session.add(
                    IdempotencyBindingModel(
                        binding_id=f"binding_{secrets.token_hex(16)}",
                        device_id=registration.device_id,
                        device_epoch=registration.device_epoch,
                        key_mode=registration.key.mode.value,
                        key_digest_sha256=registration.key.digest_sha256,
                        tool_name=registration.tool_name,
                        contract_version=registration.contract_version,
                        owner_controller_id=registration.owner.controller_id,
                        owner_controller_epoch=registration.owner.controller_epoch,
                        owner_controller_digest=owner_digest(registration.owner),
                        request_fingerprint_sha256=registration.request_fingerprint_sha256,
                        prepared_operation_id=registration.prepared_operation_id,
                        prepared_input_sha256=registration.prepared_input_sha256,
                        prepared_expires_at=registration.prepared_expires_at,
                        prepared_state_binding_sha256=registration.prepared_state_binding_sha256,
                        prepared_registered_boot_id_digest=registration.registered_boot_id_digest,
                        prepared_monotonic_deadline_ns=registration.monotonic_deadline_ns,
                        target_identity_sha256=registration.target_identity_sha256,
                        maximum_effect_sha256=registration.maximum_effect_sha256,
                        operation_id=None,
                        terminal_class=None,
                        created_at=now,
                        last_access_at=now,
                        terminal_at=None,
                        retired_at=None,
                        record_kind=BindingRecordKind.FULL.value,
                        duplicate_count=0,
                        conflict_count=0,
                    )
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise OperationStoreError("prepared nonce is already registered") from exc
            except Exception:
                await session.rollback()
                raise

    async def get_prepared_execution(
        self, request: CreateOrFindRequest
    ) -> PreparedExecutionRecord | None:
        """Read exact retained preparation facts without authorising first use."""

        if request.key.mode is not IdempotencyKeyMode.PREPARED_EXECUTION_NONCE:
            return None
        async with self._runtime.session_factory() as session:
            binding = (
                await session.execute(
                    select(IdempotencyBindingModel).where(*self._scope_filter(request))
                )
            ).scalar_one_or_none()
            if (
                binding is None
                or binding.record_kind != BindingRecordKind.FULL.value
                or binding.owner_controller_digest != owner_digest(request.owner)
                or binding.prepared_operation_id is None
                or binding.prepared_expires_at is None
                or binding.prepared_state_binding_sha256 is None
                or binding.prepared_registered_boot_id_digest is None
                or binding.prepared_monotonic_deadline_ns is None
            ):
                return None
            prepared_expires_at = _utc(binding.prepared_expires_at)
            assert prepared_expires_at is not None
            return PreparedExecutionRecord(
                prepared_operation_id=binding.prepared_operation_id,
                prepared_expires_at=prepared_expires_at,
                prepared_state_binding_sha256=binding.prepared_state_binding_sha256,
                registered_boot_id_digest=binding.prepared_registered_boot_id_digest,
                monotonic_deadline_ns=binding.prepared_monotonic_deadline_ns,
            )

    async def get_idempotency_conflict_operation(
        self, request: CreateOrFindRequest
    ) -> OperationSnapshot | None:
        """Return truthful same-owner retained state solely for conflict auditing."""

        async with self._runtime.session_factory() as session:
            binding = (
                await session.execute(
                    select(IdempotencyBindingModel).where(*self._scope_filter(request))
                )
            ).scalar_one_or_none()
            if (
                binding is None
                or binding.record_kind != BindingRecordKind.FULL.value
                or binding.owner_controller_digest != owner_digest(request.owner)
                or binding.operation_id is None
            ):
                return None
            operation = await session.get(OperationModel, binding.operation_id)
            if operation is None:
                raise OperationStoreError("idempotency binding references a missing operation")
            return await self._snapshot(session, operation)

    async def compact_idempotency_binding(
        self,
        *,
        device_id: str,
        device_epoch: int,
        tool_name: str,
        contract_version: str,
        key_digest_sha256: str,
        retired_at: datetime,
    ) -> None:
        """Explicitly compact a terminal full record to the contract tombstone."""

        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                binding = (
                    await session.execute(
                        select(IdempotencyBindingModel).where(
                            IdempotencyBindingModel.device_id == device_id,
                            IdempotencyBindingModel.device_epoch == device_epoch,
                            IdempotencyBindingModel.tool_name == tool_name,
                            IdempotencyBindingModel.contract_version == contract_version,
                            IdempotencyBindingModel.key_digest_sha256 == key_digest_sha256,
                        )
                    )
                ).scalar_one_or_none()
                if binding is None or binding.record_kind != BindingRecordKind.FULL.value:
                    raise OperationStoreError("full idempotency binding was not found")
                terminal_class = binding.terminal_class
                terminal_at = binding.terminal_at
                if binding.operation_id is not None:
                    operation = await session.get(OperationModel, binding.operation_id)
                    if operation is None or operation.terminality != Terminality.TERMINAL.value:
                        raise OperationStoreError("only a terminal operation can be compacted")
                    terminal_class = operation.state
                    terminal_at = operation.terminal_at or operation.updated_at
                elif terminal_class != IdempotencyOutcome.PREPARED_EXPIRED.value:
                    raise OperationStoreError("unconsumed prepared nonce is not proven expired")
                binding.record_kind = BindingRecordKind.TOMBSTONE.value
                binding.operation_id = None
                binding.owner_controller_id = None
                binding.owner_controller_epoch = None
                binding.terminal_class = terminal_class
                binding.terminal_at = terminal_at
                binding.retired_at = retired_at
                binding.prepared_operation_id = None
                binding.prepared_input_sha256 = None
                binding.prepared_expires_at = None
                binding.prepared_state_binding_sha256 = None
                binding.prepared_registered_boot_id_digest = None
                binding.prepared_monotonic_deadline_ns = None
                binding.target_identity_sha256 = None
                binding.maximum_effect_sha256 = None
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def get_operation(self, operation_id: str) -> OperationSnapshot | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(OperationModel, operation_id)
            return None if model is None else await self._snapshot(session, model)

    async def transition(self, operation_id: str, request: TransitionRequest) -> OperationSnapshot:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await session.get(OperationModel, operation_id)
                if model is None:
                    raise OperationStoreError("operation_not_found")
                current = await self._snapshot(session, model)
                updated = transition(current, request)
                if current.state is OperationState.RECEIVED:
                    decision = (
                        await session.execute(
                            select(PolicyDecisionModel.policy_decision_id).where(
                                PolicyDecisionModel.operation_id == operation_id
                            )
                        )
                    ).scalar_one_or_none()
                    if decision is None:
                        raise OperationStoreError("operation cannot leave received without policy")
                result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == operation_id,
                        OperationModel.state_version == request.expected_state_version,
                    )
                    .values(**self._operation_update_values(updated))
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise OperationTransitionError("operation state version conflict")
                session.add(
                    OperationTransitionModel(
                        operation_id=operation_id,
                        state_version=updated.state_version,
                        from_state=current.state.value,
                        to_state=updated.state.value,
                        effect_knowledge=updated.effect_knowledge.value,
                        terminality=updated.terminality.value,
                        reason_code=request.reason_code,
                        error_code=None if updated.error is None else updated.error.code,
                        recorded_at=updated.updated_at,
                        runtime_build_sha256=updated.intent.runtime_build_sha256,
                    )
                )
                await session.commit()
                return updated
            except Exception:
                await session.rollback()
                raise

    async def record_effect_start(
        self,
        operation_id: str,
        *,
        expected_state_version: int,
        effect_knowledge: EffectKnowledge,
        effect_reference: str | None,
        effect_reference_digest: str | None,
    ) -> OperationSnapshot:
        if effect_knowledge not in {
            EffectKnowledge.NONE,
            EffectKnowledge.KNOWN_NO_EFFECT,
            EffectKnowledge.KNOWN_EFFECT,
            EffectKnowledge.PARTIAL,
        }:
            raise OperationStoreError("nonterminal effect knowledge is invalid")
        if effect_reference is not None and (
            not effect_reference_digest or len(effect_reference_digest) != 64
        ):
            raise OperationStoreError("effect reference digest is invalid")
        timestamp = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await session.get(OperationModel, operation_id)
                if model is None:
                    raise OperationStoreError("operation_not_found")
                if (
                    model.state != OperationState.RUNNING.value
                    or model.state_version != expected_state_version
                ):
                    raise OperationTransitionError("operation state version conflict")
                values: dict[str, object] = {
                    "effect_knowledge": effect_knowledge.value,
                    "updated_at": timestamp,
                }
                if effect_reference is not None:
                    values["effect_reference"] = effect_reference
                    values["effect_reference_digest"] = effect_reference_digest
                if (
                    effect_knowledge
                    in {
                        EffectKnowledge.KNOWN_EFFECT,
                        EffectKnowledge.PARTIAL,
                    }
                    and model.effect_boundary_crossed_at is None
                ):
                    values["effect_boundary_crossed_at"] = timestamp
                result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == operation_id,
                        OperationModel.state_version == expected_state_version,
                        OperationModel.state == OperationState.RUNNING.value,
                    )
                    .values(**values)
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise OperationTransitionError("operation state version conflict")
                await session.commit()
                refreshed = await session.get(OperationModel, operation_id)
                if refreshed is None:
                    raise OperationStoreError("operation disappeared after effect start")
                return await self._snapshot(session, refreshed)
            except Exception:
                await session.rollback()
                raise

    async def store_policy_decision(self, decision: PolicyDecision) -> None:
        async with self._runtime.session_factory() as session, session.begin():
            operation = await session.get(OperationModel, decision.operation_id)
            if operation is None:
                raise OperationStoreError("policy decision references missing operation")
            session.add(
                PolicyDecisionModel(
                    policy_decision_id=decision.policy_decision_id,
                    operation_id=decision.operation_id,
                    policy_id=decision.policy_id,
                    policy_version=decision.policy_version,
                    decision=decision.decision.value,
                    controller_id=operation.controller_id,
                    controller_epoch=operation.controller_epoch,
                    operation_contract=operation.operation_contract,
                    operation_contract_version=operation.operation_contract_version,
                    required_scope_digest=None,
                    normalized_target_digest=operation.request_fingerprint_sha256,
                    input_facts_sha256=decision.input_facts_sha256,
                    reason_codes_json=json.dumps(
                        decision.reason_codes, separators=(",", ":"), sort_keys=True
                    ),
                    decided_at=decision.decided_at,
                    runtime_policy_sha256=decision.runtime_policy_sha256,
                )
            )

    async def get_policy_decision(self, operation_id: str) -> PolicyDecision | None:
        async with self._runtime.session_factory() as session:
            model = (
                await session.execute(
                    select(PolicyDecisionModel).where(
                        PolicyDecisionModel.operation_id == operation_id
                    )
                )
            ).scalar_one_or_none()
            if model is None:
                return None
            return PolicyDecision(
                policy_decision_id=model.policy_decision_id,
                operation_id=model.operation_id,
                policy_id=model.policy_id,
                policy_version=model.policy_version,
                decision=PolicyDecisionValue(model.decision),
                reason_codes=tuple(json.loads(model.reason_codes_json)),
                input_facts_sha256=model.input_facts_sha256,
                runtime_policy_sha256=model.runtime_policy_sha256,
                decided_at=_utc(model.decided_at) or model.decided_at,
            )

    async def list_reconcilable(
        self,
        *,
        limit: int = 100,
        after: ReconciliationCursor | None = None,
    ) -> tuple[OperationSnapshot, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("reconciliation page limit is out of range")
        states = (
            OperationState.RECEIVED.value,
            OperationState.AUTHORISED.value,
            OperationState.RUNNING.value,
            OperationState.PAUSED.value,
            OperationState.CANCELLING.value,
            OperationState.UNCERTAIN.value,
        )
        async with self._runtime.session_factory() as session:
            statement = select(OperationModel).where(OperationModel.state.in_(states))
            if after is not None:
                statement = statement.where(
                    or_(
                        OperationModel.created_at > after.created_at,
                        and_(
                            OperationModel.created_at == after.created_at,
                            OperationModel.operation_id > after.operation_id,
                        ),
                    )
                )
            rows = (
                await session.execute(
                    statement.order_by(
                        OperationModel.created_at, OperationModel.operation_id
                    ).limit(limit)
                )
            ).scalars()
            return tuple([await self._snapshot(session, row) for row in rows])

    async def reject_received_on_restart(
        self, operation_id: str, decision: PolicyDecision
    ) -> OperationSnapshot:
        """Atomically ensure one admission decision and reject interrupted received work."""

        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await session.get(OperationModel, operation_id)
                if model is None:
                    raise OperationStoreError("operation_not_found")
                current = await self._snapshot(session, model)
                if current.state is not OperationState.RECEIVED:
                    await session.rollback()
                    return current
                existing = (
                    await session.execute(
                        select(PolicyDecisionModel).where(
                            PolicyDecisionModel.operation_id == operation_id
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        PolicyDecisionModel(
                            policy_decision_id=decision.policy_decision_id,
                            operation_id=operation_id,
                            policy_id=decision.policy_id,
                            policy_version=decision.policy_version,
                            decision=PolicyDecisionValue.DENY.value,
                            controller_id=model.controller_id,
                            controller_epoch=model.controller_epoch,
                            operation_contract=model.operation_contract,
                            operation_contract_version=model.operation_contract_version,
                            required_scope_digest=None,
                            normalized_target_digest=model.request_fingerprint_sha256,
                            input_facts_sha256=decision.input_facts_sha256,
                            reason_codes_json=json.dumps(
                                ("restart_before_admission",), separators=(",", ":")
                            ),
                            decided_at=decision.decided_at,
                            runtime_policy_sha256=decision.runtime_policy_sha256,
                        )
                    )
                request = TransitionRequest(
                    expected_state_version=current.state_version,
                    to_state=OperationState.REJECTED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code="restart_before_admission",
                    error=OperationError(
                        "policy_rejected",
                        "Interrupted admission was rejected during restart reconciliation.",
                    ),
                    occurred_at=datetime.now(UTC),
                )
                updated = transition(current, request)
                result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == operation_id,
                        OperationModel.state_version == current.state_version,
                        OperationModel.state == OperationState.RECEIVED.value,
                    )
                    .values(**self._operation_update_values(updated))
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise OperationTransitionError("operation state version conflict")
                session.add(
                    OperationTransitionModel(
                        operation_id=operation_id,
                        state_version=updated.state_version,
                        from_state=current.state.value,
                        to_state=updated.state.value,
                        effect_knowledge=updated.effect_knowledge.value,
                        terminality=updated.terminality.value,
                        reason_code=request.reason_code,
                        error_code=updated.error.code if updated.error else None,
                        recorded_at=updated.updated_at,
                        runtime_build_sha256=updated.intent.runtime_build_sha256,
                    )
                )
                await session.commit()
                return updated
            except Exception:
                await session.rollback()
                raise

    async def get_trusted_time_evidence(self) -> TrustedTimeEvidence:
        async with self._runtime.session_factory() as session:
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            return TrustedTimeEvidence(
                high_watermark=_utc(model.trusted_wall_time_high_watermark),
                boot_id_digest=model.trusted_time_boot_id_digest,
                monotonic_ns=model.trusted_time_monotonic_ns,
                generation=model.trusted_time_generation,
            )

    async def store_trusted_time_evidence(self, evidence: TrustedTimeEvidence) -> None:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            old_high = _utc(model.trusted_wall_time_high_watermark)
            if old_high is not None and (
                evidence.high_watermark is None or evidence.high_watermark < old_high
            ):
                raise OperationStoreError("trusted time high-water mark cannot move backward")
            if evidence.generation < model.trusted_time_generation:
                raise OperationStoreError("trusted time generation cannot move backward")
            model.trusted_wall_time_high_watermark = evidence.high_watermark
            model.trusted_time_boot_id_digest = evidence.boot_id_digest
            model.trusted_time_monotonic_ns = evidence.monotonic_ns
            model.trusted_time_generation = evidence.generation
            model.updated_at = datetime.now(UTC)

    async def audit_tail_cache(self) -> AuditTail:
        async with self._runtime.session_factory() as session:
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            return AuditTail(model.audit_last_sequence, model.audit_last_hash)

    async def update_audit_tail_cache(self, tail: AuditTail) -> None:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            if tail.sequence < model.audit_last_sequence:
                raise OperationStoreError("audit cache cannot move backward")
            if tail.sequence == model.audit_last_sequence and (
                model.audit_last_hash is not None and tail.event_hash != model.audit_last_hash
            ):
                raise OperationStoreError("audit cache hash diverges")
            model.audit_last_sequence = tail.sequence
            model.audit_last_hash = tail.event_hash
            model.updated_at = datetime.now(UTC)

    async def latch_audit_failure(self, reason_code: str) -> int:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            if not model.audit_failure_latched:
                model.audit_failure_generation += 1
            model.audit_failure_latched = True
            model.audit_failure_reason_code = reason_code
            model.audit_failure_detected_at = datetime.now(UTC)
            model.consequential_admission_enabled = False
            model.updated_at = datetime.now(UTC)
            return model.audit_failure_generation

    async def clear_audit_failure(self, generation: int, evidence_sha256: str) -> None:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(KernelMetaModel, 1)
            if model is None or not model.audit_failure_latched:
                raise OperationStoreError("no active audit failure")
            if generation != model.audit_failure_generation:
                raise OperationStoreError("audit recovery generation mismatch")
            model.audit_failure_latched = False
            model.audit_failure_reason_code = None
            model.audit_failure_detected_at = None
            model.audit_recovered_generation = generation
            model.audit_recovery_evidence_sha256 = evidence_sha256
            model.consequential_admission_enabled = False
            model.updated_at = datetime.now(UTC)

    async def audit_failure_state(self) -> tuple[bool, int, int]:
        async with self._runtime.session_factory() as session:
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            return (
                model.audit_failure_latched,
                model.audit_failure_generation,
                model.audit_recovered_generation,
            )

    async def set_consequential_admission_enabled(self, enabled: bool) -> None:
        """Persist the last verified process-wide admission state."""

        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            if enabled and (
                model.audit_failure_latched
                or model.audit_failure_generation != model.audit_recovered_generation
            ):
                raise OperationStoreError("audit recovery state forbids consequential admission")
            model.consequential_admission_enabled = enabled
            model.updated_at = datetime.now(UTC)

    async def consequential_admission_enabled(self) -> bool:
        async with self._runtime.session_factory() as session:
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            return bool(model.consequential_admission_enabled)

    async def audit_recovery_evidence_sha256(self) -> str | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(KernelMetaModel, 1)
            if model is None:
                raise OperationStoreError("kernel metadata is not initialized")
            return model.audit_recovery_evidence_sha256

    @staticmethod
    def _operation_model(snapshot: OperationSnapshot) -> OperationModel:
        error = snapshot.error
        return OperationModel(
            operation_id=snapshot.operation_id,
            controller_id=snapshot.owner.controller_id,
            controller_epoch=snapshot.owner.controller_epoch,
            device_id=snapshot.intent.device_id,
            device_epoch=snapshot.intent.device_epoch,
            operation_contract=snapshot.intent.operation_contract,
            operation_contract_version=snapshot.intent.operation_contract_version,
            tool_name=snapshot.intent.tool_name,
            tool_contract_version=snapshot.intent.tool_contract_version,
            request_fingerprint_sha256=snapshot.intent.request_fingerprint_sha256,
            state=snapshot.state.value,
            state_version=snapshot.state_version,
            effect_knowledge=snapshot.effect_knowledge.value,
            terminality=snapshot.terminality.value,
            automatic_retry_allowed=False,
            effect_boundary_crossed_at=snapshot.effect_boundary_crossed_at,
            effect_reference=snapshot.effect_reference,
            effect_reference_digest=snapshot.effect_reference_digest,
            error_code=None if error is None else error.code,
            error_summary=None if error is None else error.summary,
            retry_action=None if error is None else error.retry_action,
            runtime_build_sha256=snapshot.intent.runtime_build_sha256,
            runtime_config_sha256=snapshot.intent.runtime_config_sha256,
            controller_profile_version_snapshot=snapshot.owner.controller_profile_version,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            authorised_at=snapshot.authorised_at,
            started_at=snapshot.started_at,
            terminal_at=snapshot.terminal_at,
            last_reconciled_at=snapshot.last_reconciled_at,
        )

    @staticmethod
    def _initial_transition_model(snapshot: OperationSnapshot) -> OperationTransitionModel:
        return OperationTransitionModel(
            operation_id=snapshot.operation_id,
            state_version=1,
            from_state=None,
            to_state=OperationState.RECEIVED.value,
            effect_knowledge=EffectKnowledge.NONE.value,
            terminality=Terminality.NON_TERMINAL.value,
            reason_code="operation_received",
            error_code=None,
            recorded_at=snapshot.created_at,
            runtime_build_sha256=snapshot.intent.runtime_build_sha256,
        )

    @staticmethod
    def _operation_update_values(snapshot: OperationSnapshot) -> dict[str, object]:
        error = snapshot.error
        return {
            "state": snapshot.state.value,
            "state_version": snapshot.state_version,
            "effect_knowledge": snapshot.effect_knowledge.value,
            "terminality": snapshot.terminality.value,
            "updated_at": snapshot.updated_at,
            "authorised_at": snapshot.authorised_at,
            "started_at": snapshot.started_at,
            "terminal_at": snapshot.terminal_at,
            "last_reconciled_at": snapshot.last_reconciled_at,
            "effect_boundary_crossed_at": snapshot.effect_boundary_crossed_at,
            "effect_reference": snapshot.effect_reference,
            "effect_reference_digest": snapshot.effect_reference_digest,
            "error_code": None if error is None else error.code,
            "error_summary": None if error is None else error.summary,
            "retry_action": None if error is None else error.retry_action,
        }

    @staticmethod
    def _assign_operation_model(model: OperationModel, snapshot: OperationSnapshot) -> None:
        for name, value in SqliteOperationStore._operation_update_values(snapshot).items():
            setattr(model, name, value)

    async def _snapshot(self, session: AsyncSession, model: OperationModel) -> OperationSnapshot:
        owner = await session.get(
            ControllerOwnerModel, (model.controller_id, model.controller_epoch)
        )
        if owner is None:
            raise OperationStoreError("operation references a missing controller owner")
        binding = (
            await session.execute(
                select(
                    IdempotencyBindingModel.target_identity_sha256,
                    IdempotencyBindingModel.maximum_effect_sha256,
                )
                .where(IdempotencyBindingModel.operation_id == model.operation_id)
                .order_by(IdempotencyBindingModel.binding_id)
                .limit(1)
            )
        ).one_or_none()
        if binding is None:
            raise OperationStoreError("operation has no durable idempotency binding")
        error = (
            None
            if model.error_code is None
            else OperationError(
                code=model.error_code,
                summary=model.error_summary or model.error_code,
                retry_action=model.retry_action or "none",
            )
        )
        return OperationSnapshot(
            operation_id=model.operation_id,
            owner=OperationOwner(
                controller_id=model.controller_id,
                controller_epoch=model.controller_epoch,
                controller_profile_id=owner.controller_profile_id,
                controller_profile_version=model.controller_profile_version_snapshot,
            ),
            intent=OperationIntent(
                operation_contract=model.operation_contract,
                operation_contract_version=model.operation_contract_version,
                request_fingerprint_sha256=model.request_fingerprint_sha256,
                device_id=model.device_id,
                device_epoch=model.device_epoch,
                runtime_build_sha256=model.runtime_build_sha256,
                runtime_config_sha256=model.runtime_config_sha256,
                tool_name=model.tool_name,
                tool_contract_version=model.tool_contract_version,
                target_identity_sha256=binding[0],
                maximum_effect_sha256=binding[1],
            ),
            state=OperationState(model.state),
            state_version=model.state_version,
            effect_knowledge=EffectKnowledge(model.effect_knowledge),
            terminality=Terminality(model.terminality),
            automatic_retry_allowed=False,
            created_at=_utc(model.created_at) or model.created_at,
            updated_at=_utc(model.updated_at) or model.updated_at,
            authorised_at=_utc(model.authorised_at),
            started_at=_utc(model.started_at),
            terminal_at=_utc(model.terminal_at),
            last_reconciled_at=_utc(model.last_reconciled_at),
            effect_boundary_crossed_at=_utc(model.effect_boundary_crossed_at),
            effect_reference=model.effect_reference,
            effect_reference_digest=model.effect_reference_digest,
            error=error,
        )

"""SQLite persistence for the independently anchored Phase 5 probe ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import (
    IdempotencyBindingModel,
    OperationModel,
    OperationTransitionModel,
    PolicyDecisionModel,
    ProbeArtifactModel,
    ProbeOperationModel,
    ProbePathLedgerModel,
)
from binnacle.adapters.sqlite.operation_store import (
    OperationStoreError,
    SqliteOperationStore,
    _utc,
)
from binnacle.domain.idempotency import BindingRecordKind, IdempotencyKeyMode, owner_digest
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    transition,
)
from binnacle.domain.probe_workspace import (
    EMPTY_TERMINAL_HISTORY_SHA256,
    ProbeArtifact,
    ProbeArtifactState,
    ProbeFileObservation,
    ProbeOperationKind,
    ProbeOperationRecord,
    ProbePathLedger,
    ProbePathSnapshot,
    ProbeTargetState,
    ProbeWorkspaceError,
    operation_fingerprint_sha256,
    prepared_input_sha256,
    prepared_state_sha256,
    terminal_history_sha256,
    validate_path_snapshot,
    validate_sha256,
)
from binnacle.ports.probe_workspace import (
    ProbeAuthorisationRequest,
    ProbeBoundarySnapshot,
    ProbeWorkspaceFilesystem,
)


class ProbeWorkspaceStoreError(ProbeWorkspaceError):
    """Probe state is missing, stale, or structurally inconsistent."""


class SqliteProbeWorkspaceRepository:
    def __init__(
        self,
        runtime: DatabaseRuntime,
        operation_store: SqliteOperationStore,
        filesystem: ProbeWorkspaceFilesystem | None = None,
    ) -> None:
        self._runtime = runtime
        self._operations = operation_store
        self._filesystem = filesystem

    async def ensure_path_anchor(self, relative_path: str) -> ProbePathSnapshot:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                ledger = await session.get(ProbePathLedgerModel, relative_path)
                if ledger is None:
                    artifact_count = int(
                        (
                            await session.execute(
                                select(func.count())
                                .select_from(ProbeArtifactModel)
                                .where(ProbeArtifactModel.relative_path == relative_path)
                            )
                        ).scalar_one()
                    )
                    operation_count = int(
                        (
                            await session.execute(
                                select(func.count())
                                .select_from(ProbeOperationModel)
                                .where(ProbeOperationModel.relative_path == relative_path)
                            )
                        ).scalar_one()
                    )
                    if artifact_count or operation_count:
                        raise ProbeWorkspaceStoreError(
                            "seen probe path is missing its independent ledger"
                        )
                    ledger = ProbePathLedgerModel(
                        relative_path=relative_path,
                        generation_high_water=0,
                        terminal_history_count=0,
                        terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
                        active_artifact_id=None,
                        active_generation=None,
                        active_create_operation_id=None,
                        ledger_version=1,
                        updated_at=now,
                    )
                    session.add(ledger)
                    await session.flush()
                snapshot = await self._path_snapshot(session, ledger)
                validate_path_snapshot(snapshot)
                await session.commit()
                return snapshot
            except Exception:
                await session.rollback()
                raise

    async def get_path_snapshot(self, relative_path: str) -> ProbePathSnapshot:
        async with self._runtime.session_factory() as session:
            ledger = await session.get(ProbePathLedgerModel, relative_path)
            if ledger is None:
                raise ProbeWorkspaceStoreError("probe path ledger is missing")
            snapshot = await self._path_snapshot(session, ledger)
            validate_path_snapshot(snapshot)
            return snapshot

    async def get_probe_operation(self, operation_id: str) -> ProbeOperationRecord | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(ProbeOperationModel, operation_id)
            return None if model is None else self._probe_operation(model)

    async def get_prepared_state_binding_sha256(self, prepared_operation_id: str) -> str | None:
        async with self._runtime.session_factory() as session:
            values = (
                (
                    await session.execute(
                        select(IdempotencyBindingModel.prepared_state_binding_sha256).where(
                            IdempotencyBindingModel.prepared_operation_id == prepared_operation_id,
                            IdempotencyBindingModel.key_mode
                            == IdempotencyKeyMode.PREPARED_EXECUTION_NONCE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not values:
                return None
            if len(values) != 1 or values[0] is None:
                raise ProbeWorkspaceStoreError("prepared operation identity is not unique")
            return values[0]

    async def get_boundary_snapshot(
        self,
        *,
        operation_id: str,
        prepared_operation_id: str,
        relative_path: str,
    ) -> ProbeBoundarySnapshot:
        """Return one transactionally coherent, fully validated dispatch snapshot."""

        async with self._runtime.session_factory() as session:
            probe = await self._require_probe_operation(session, operation_id)
            operation, _artifact = await self._validate_probe_provenance(session, probe)
            prepared = await session.get(IdempotencyBindingModel, probe.prepared_binding_id)
            if (
                operation.state is not OperationState.RUNNING
                or probe.relative_path != relative_path
                or prepared is None
                or prepared.prepared_operation_id != prepared_operation_id
                or prepared.prepared_state_binding_sha256 is None
                or prepared.prepared_state_binding_sha256 != probe.prepared_state_binding_sha256
            ):
                raise ProbeWorkspaceStoreError("probe boundary provenance is inconsistent")
            ledger = await session.get(ProbePathLedgerModel, relative_path)
            if ledger is None:
                raise ProbeWorkspaceStoreError("probe path ledger is missing")
            path = await self._path_snapshot(session, ledger)
            validate_path_snapshot(path)
            return ProbeBoundarySnapshot(
                probe_operation=self._probe_operation(probe),
                path=path,
                prepared_state_binding_sha256=prepared.prepared_state_binding_sha256,
            )

    async def authorise(self, request: ProbeAuthorisationRequest) -> OperationSnapshot:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation_model = await session.get(OperationModel, request.operation.operation_id)
                if operation_model is None:
                    raise ProbeWorkspaceStoreError("probe operation disappeared")
                current = await self._operations._snapshot(session, operation_model)
                if (
                    current.state is not OperationState.RECEIVED
                    or current.state_version != request.operation.state_version
                ):
                    raise ProbeWorkspaceStoreError("probe operation admission is stale")
                if await session.get(ProbeOperationModel, current.operation_id) is not None:
                    raise ProbeWorkspaceStoreError("probe operation was already admitted")
                bindings = (
                    (
                        await session.execute(
                            select(IdempotencyBindingModel).where(
                                IdempotencyBindingModel.operation_id == current.operation_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                caller = [
                    item
                    for item in bindings
                    if item.key_mode == IdempotencyKeyMode.CALLER_KEY.value
                ]
                prepared = [
                    item
                    for item in bindings
                    if item.key_mode == IdempotencyKeyMode.PREPARED_EXECUTION_NONCE.value
                ]
                if len(caller) != 1 or len(prepared) != 1:
                    raise ProbeWorkspaceStoreError(
                        "probe operation does not own one caller and prepared binding"
                    )
                if (
                    prepared[0].prepared_state_binding_sha256
                    != request.prepared_state_binding_sha256
                    or prepared[0].request_fingerprint_sha256
                    != current.intent.request_fingerprint_sha256
                    or caller[0].request_fingerprint_sha256
                    != current.intent.request_fingerprint_sha256
                ):
                    raise ProbeWorkspaceStoreError("probe binding facts changed before admission")
                if (
                    await session.execute(
                        select(PolicyDecisionModel.policy_decision_id).where(
                            PolicyDecisionModel.operation_id == current.operation_id
                        )
                    )
                ).scalar_one_or_none() is not None:
                    raise ProbeWorkspaceStoreError("probe policy decision already exists")

                ledger = await session.get(ProbePathLedgerModel, request.relative_path)
                if ledger is None:
                    raise ProbeWorkspaceStoreError("probe ledger is missing at admission")
                snapshot = await self._path_snapshot(session, ledger)
                validate_path_snapshot(snapshot)
                self._validate_prepared_admission(request, current, snapshot)
                if self._filesystem is None:
                    raise ProbeWorkspaceStoreError(
                        "probe filesystem is unavailable during authorisation"
                    )
                observation = await self._filesystem.observe(request.relative_path)
                self._validate_filesystem_admission(request, observation)
                artifact_id: str
                if request.probe_operation is ProbeOperationKind.WRITE:
                    if request.artifact_id is not None or request.expected_byte_count is None:
                        raise ProbeWorkspaceStoreError("write admission facts are invalid")
                    if snapshot.active_artifact is not None:
                        raise ProbeWorkspaceStoreError("probe path already has an active artifact")
                    artifact_id = (
                        "artifact_"
                        + hashlib.sha256(
                            b"binnacle.probe-artifact.v1\0" + current.operation_id.encode()
                        ).hexdigest()[:32]
                    )
                    generation = ledger.generation_high_water + 1
                    artifact = ProbeArtifactModel(
                        artifact_id=artifact_id,
                        relative_path=request.relative_path,
                        path_generation=generation,
                        owner_controller_id=current.owner.controller_id,
                        owner_controller_epoch=current.owner.controller_epoch,
                        content_sha256=request.expected_content_sha256,
                        byte_count=request.expected_byte_count,
                        state=ProbeArtifactState.RESERVED.value,
                        create_operation_id=current.operation_id,
                        active_cleanup_operation_id=None,
                        removed_by_cleanup_operation_id=None,
                        created_at=now,
                        updated_at=now,
                        removed_at=None,
                        file_identity_digest=None,
                    )
                    session.add(artifact)
                    ledger.generation_high_water = generation
                    ledger.active_artifact_id = artifact_id
                    ledger.active_generation = generation
                    ledger.active_create_operation_id = current.operation_id
                    ledger.ledger_version += 1
                    ledger.updated_at = now
                else:
                    if request.artifact_id is None or request.expected_byte_count is not None:
                        raise ProbeWorkspaceStoreError("cleanup admission facts are invalid")
                    active = snapshot.active_artifact
                    if (
                        active is None
                        or active.artifact_id != request.artifact_id
                        or active.state is not ProbeArtifactState.CREATED
                        or active.active_cleanup_operation_id is not None
                        or active.content_sha256 != request.expected_content_sha256
                        or active.owner_controller_id != current.owner.controller_id
                        or active.owner_controller_epoch != current.owner.controller_epoch
                    ):
                        raise ProbeWorkspaceStoreError("cleanup target is not exact and live")
                    artifact_id = active.artifact_id
                    artifact_model = await session.get(ProbeArtifactModel, artifact_id)
                    if artifact_model is None:
                        raise ProbeWorkspaceStoreError("cleanup artifact disappeared")
                    artifact_model.active_cleanup_operation_id = current.operation_id
                    artifact_model.updated_at = now

                session.add(
                    ProbeOperationModel(
                        operation_id=current.operation_id,
                        probe_operation=request.probe_operation.value,
                        prepared_binding_id=prepared[0].binding_id,
                        caller_binding_id=caller[0].binding_id,
                        artifact_id=artifact_id,
                        relative_path=request.relative_path,
                        expected_content_sha256=request.expected_content_sha256,
                        expected_byte_count=request.expected_byte_count,
                        prepared_state_binding_sha256=request.prepared_state_binding_sha256,
                        created_at=now,
                    )
                )
                session.add(self._policy_model(operation_model, request.decision))
                authorised = transition(
                    current,
                    TransitionRequest(
                        expected_state_version=current.state_version,
                        to_state=OperationState.AUTHORISED,
                        effect_knowledge=EffectKnowledge.NONE,
                        reason_code="policy_allowed",
                        occurred_at=now,
                    ),
                )
                result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == current.operation_id,
                        OperationModel.state_version == current.state_version,
                        OperationModel.state == OperationState.RECEIVED.value,
                    )
                    .values(**SqliteOperationStore._operation_update_values(authorised))
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise ProbeWorkspaceStoreError("probe authorisation CAS failed")
                session.add(
                    self._transition_model(
                        current,
                        authorised,
                        reason_code="policy_allowed",
                    )
                )
                await session.commit()
                return authorised
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    def _validate_prepared_admission(
        request: ProbeAuthorisationRequest,
        operation: OperationSnapshot,
        snapshot: ProbePathSnapshot,
    ) -> None:
        """Re-prove the exact prepared DB projection inside the admission transaction."""

        state = request.prepared_state
        ledger = snapshot.ledger
        if (
            prepared_state_sha256(state) != request.prepared_state_binding_sha256
            or state.operation is not request.probe_operation
            or state.relative_path != request.relative_path
            or state.content_sha256 != request.expected_content_sha256
            or state.byte_count != request.expected_byte_count
            or state.artifact_id != request.artifact_id
            or state.owner_controller_id != operation.owner.controller_id
            or state.owner_controller_epoch != operation.owner.controller_epoch
            or state.ledger_version != ledger.ledger_version
            or state.generation_high_water != ledger.generation_high_water
            or state.terminal_history_count != ledger.terminal_history_count
            or state.terminal_history_sha256 != ledger.terminal_history_sha256
            or state.active_artifact_id != ledger.active_artifact_id
            or state.active_generation != ledger.active_generation
            or state.active_create_operation_id != ledger.active_create_operation_id
        ):
            raise ProbeWorkspaceStoreError("prepared probe state changed before admission")
        validate_sha256(state.root_identity_sha256, name="root_identity_sha256")

        active = snapshot.active_artifact
        if request.probe_operation is ProbeOperationKind.WRITE:
            if (
                active is not None
                or state.write_reservation_transition
                != "absent_generation_N_then_exact_self_reserved_generation_N_plus_1"
                or state.cleanup_target_transition is not None
                or state.cleanup_claim_transition is not None
                or state.expected_file_identity_digest is not None
            ):
                raise ProbeWorkspaceStoreError("prepared write projection is not exact")
            return

        if (
            active is None
            or state.write_reservation_transition is not None
            or state.cleanup_target_transition
            not in {
                "exact_prepared_identity_or_absent_no_start",
                "created_target_observed_absent",
            }
            or state.cleanup_claim_transition != "unclaimed_then_exact_self"
            or state.expected_file_identity_digest != active.file_identity_digest
            or state.artifact_id != active.artifact_id
            or active.active_cleanup_operation_id is not None
        ):
            raise ProbeWorkspaceStoreError("prepared cleanup projection is not exact")

    @staticmethod
    def _validate_filesystem_admission(
        request: ProbeAuthorisationRequest,
        observation: ProbeFileObservation,
    ) -> None:
        """Re-observe the target inside the short post-policy admission transaction."""

        state = request.prepared_state
        if request.probe_operation is ProbeOperationKind.WRITE:
            if observation.state is not ProbeTargetState.ABSENT:
                raise ProbeWorkspaceStoreError("prepared write target changed before admission")
            return
        if state.cleanup_target_transition == "created_target_observed_absent":
            if observation.state is not ProbeTargetState.ABSENT:
                raise ProbeWorkspaceStoreError("prepared cleanup absence changed before admission")
            return
        if (
            observation.state is not ProbeTargetState.EXACT
            or observation.content_sha256 != request.expected_content_sha256
            or observation.file_identity_digest != state.expected_file_identity_digest
        ):
            raise ProbeWorkspaceStoreError("prepared cleanup target changed before admission")

    async def mark_write_uncertain(self, operation_id: str) -> None:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                probe = await self._require_probe_operation(session, operation_id)
                if probe.probe_operation != ProbeOperationKind.WRITE.value:
                    raise ProbeWorkspaceStoreError("only a write reservation may be uncertain")
                await self._validate_probe_provenance(session, probe)
                artifact = await self._require_artifact(session, probe.artifact_id)
                if artifact.state not in {
                    ProbeArtifactState.RESERVED.value,
                    ProbeArtifactState.UNCERTAIN.value,
                }:
                    raise ProbeWorkspaceStoreError("write artifact is not conservative-active")
                artifact.state = ProbeArtifactState.UNCERTAIN.value
                artifact.updated_at = now
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close_write_created(
        self,
        operation_id: str,
        *,
        file_identity_digest: str,
    ) -> OperationSnapshot:
        validate_sha256(file_identity_digest, name="file_identity_digest")
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                probe = await self._require_probe_operation(session, operation_id)
                if probe.probe_operation != ProbeOperationKind.WRITE.value:
                    raise ProbeWorkspaceStoreError("operation is not a probe write")
                operation_model = await self._require_operation(session, operation_id)
                current = await self._operations._snapshot(session, operation_model)
                if (
                    current.state is not OperationState.RUNNING
                    or current.effect_knowledge is not EffectKnowledge.KNOWN_EFFECT
                    or current.effect_reference is None
                ):
                    raise ProbeWorkspaceStoreError("write effect truth is not durably classified")
                ledger = await self._require_ledger(session, probe.relative_path)
                snapshot = await self._path_snapshot(session, ledger)
                validate_path_snapshot(snapshot)
                artifact = await self._require_artifact(session, probe.artifact_id)
                await self._validate_probe_provenance(session, probe)
                if (
                    snapshot.active_artifact is None
                    or snapshot.active_artifact.artifact_id != artifact.artifact_id
                    or artifact.create_operation_id != operation_id
                    or artifact.state
                    not in {
                        ProbeArtifactState.RESERVED.value,
                        ProbeArtifactState.UNCERTAIN.value,
                    }
                ):
                    raise ProbeWorkspaceStoreError("write created closure ownership mismatch")
                expected_reference = (
                    f"probe-write:v1:{artifact.artifact_id}:"
                    f"{artifact.path_generation}:{file_identity_digest}"
                )
                if (
                    current.effect_reference != expected_reference
                    or current.effect_reference_digest
                    != self._effect_reference_digest(expected_reference)
                ):
                    raise ProbeWorkspaceStoreError("write effect reference is not exact")
                artifact.state = ProbeArtifactState.CREATED.value
                artifact.file_identity_digest = file_identity_digest
                artifact.updated_at = now
                ledger.ledger_version += 1
                ledger.updated_at = now
                succeeded = transition(
                    current,
                    TransitionRequest(
                        expected_state_version=current.state_version,
                        to_state=OperationState.SUCCEEDED,
                        effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
                        reason_code="probe_write_created",
                        occurred_at=now,
                    ),
                )
                self._apply_operation_transition(
                    session, operation_model, current, succeeded, "probe_write_created"
                )
                await session.commit()
                return succeeded
            except Exception:
                await session.rollback()
                raise

    async def close_write_abandoned(self, operation_id: str) -> None:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                probe = await self._require_probe_operation(session, operation_id)
                operation = await self._operations._snapshot(
                    session, await self._require_operation(session, operation_id)
                )
                await self._validate_probe_provenance(session, probe)
                if (
                    probe.probe_operation != ProbeOperationKind.WRITE.value
                    or operation.state is not OperationState.FAILED
                    or operation.effect_knowledge is not EffectKnowledge.KNOWN_NO_EFFECT
                ):
                    raise ProbeWorkspaceStoreError("write cannot be abandoned without no-effect")
                await self._terminalize(
                    session,
                    probe,
                    terminal_state=ProbeArtifactState.ABANDONED,
                    removed_by_operation=False,
                    now=now,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close_cleanup_removed(
        self,
        operation_id: str,
        *,
        removed_by_operation: bool,
    ) -> OperationSnapshot | None:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                probe = await self._require_probe_operation(session, operation_id)
                if probe.probe_operation != ProbeOperationKind.CLEANUP.value:
                    raise ProbeWorkspaceStoreError("operation is not probe cleanup")
                operation_model = await self._require_operation(session, operation_id)
                current = await self._operations._snapshot(session, operation_model)
                _validated_operation, artifact = await self._validate_probe_provenance(
                    session, probe
                )
                if removed_by_operation:
                    if (
                        current.state is not OperationState.RUNNING
                        or current.effect_knowledge is not EffectKnowledge.KNOWN_EFFECT
                        or current.effect_reference is None
                    ):
                        raise ProbeWorkspaceStoreError(
                            "cleanup removal lacks durable known-effect truth"
                        )
                    if artifact.file_identity_digest is None:
                        raise ProbeWorkspaceStoreError("cleanup artifact identity is unavailable")
                    expected_reference = (
                        f"probe-cleanup:v1:{artifact.artifact_id}:"
                        f"{artifact.path_generation}:{artifact.file_identity_digest}"
                    )
                    if (
                        current.effect_reference != expected_reference
                        or current.effect_reference_digest
                        != self._effect_reference_digest(expected_reference)
                    ):
                        raise ProbeWorkspaceStoreError("cleanup effect reference is not exact")
                elif (
                    current.state is not OperationState.FAILED
                    or current.effect_knowledge is not EffectKnowledge.KNOWN_NO_EFFECT
                ):
                    raise ProbeWorkspaceStoreError("cleanup absence lacks durable no-effect truth")
                await self._terminalize(
                    session,
                    probe,
                    terminal_state=ProbeArtifactState.REMOVED,
                    removed_by_operation=removed_by_operation,
                    now=now,
                )
                if not removed_by_operation:
                    await session.commit()
                    return None
                succeeded = transition(
                    current,
                    TransitionRequest(
                        expected_state_version=current.state_version,
                        to_state=OperationState.SUCCEEDED,
                        effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
                        reason_code="probe_cleanup_removed",
                        occurred_at=now,
                    ),
                )
                self._apply_operation_transition(
                    session, operation_model, current, succeeded, "probe_cleanup_removed"
                )
                await session.commit()
                return succeeded
            except Exception:
                await session.rollback()
                raise

    async def clear_cleanup_claim(self, operation_id: str) -> None:
        now = datetime.now(UTC)
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                probe = await self._require_probe_operation(session, operation_id)
                operation = await self._operations._snapshot(
                    session, await self._require_operation(session, operation_id)
                )
                await self._validate_probe_provenance(session, probe)
                artifact = await self._require_artifact(session, probe.artifact_id)
                if (
                    probe.probe_operation != ProbeOperationKind.CLEANUP.value
                    or operation.state is not OperationState.FAILED
                    or operation.effect_knowledge is not EffectKnowledge.KNOWN_NO_EFFECT
                    or artifact.state != ProbeArtifactState.CREATED.value
                    or artifact.active_cleanup_operation_id != operation_id
                ):
                    raise ProbeWorkspaceStoreError("cleanup claim cannot be released")
                artifact.active_cleanup_operation_id = None
                artifact.updated_at = now
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def list_probe_operations(self) -> tuple[ProbeOperationRecord, ...]:
        async with self._runtime.session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ProbeOperationModel).order_by(ProbeOperationModel.created_at)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(self._probe_operation(model) for model in models)

    async def list_probe_operations_for_closure(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[ProbeOperationRecord, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("probe closure page limit is out of range")
        if (after_created_at is None) != (after_operation_id is None):
            raise ValueError("probe closure cursor is incomplete")
        async with self._runtime.session_factory() as session:
            statement = select(ProbeOperationModel)
            if after_created_at is not None and after_operation_id is not None:
                statement = statement.where(
                    or_(
                        ProbeOperationModel.created_at > after_created_at,
                        and_(
                            ProbeOperationModel.created_at == after_created_at,
                            ProbeOperationModel.operation_id > after_operation_id,
                        ),
                    )
                )
            models = (
                (
                    await session.execute(
                        statement.order_by(
                            ProbeOperationModel.created_at,
                            ProbeOperationModel.operation_id,
                        ).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(self._probe_operation(model) for model in models)

    async def verify_integrity(self) -> None:
        async with self._runtime.session_factory() as session:
            orphan_artifact = (
                await session.execute(
                    select(ProbeArtifactModel.artifact_id)
                    .outerjoin(
                        ProbePathLedgerModel,
                        ProbePathLedgerModel.relative_path == ProbeArtifactModel.relative_path,
                    )
                    .where(ProbePathLedgerModel.relative_path.is_(None))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if orphan_artifact is not None:
                raise ProbeWorkspaceStoreError("probe artifact is missing its path ledger")
            ledgers = (
                (
                    await session.execute(
                        select(ProbePathLedgerModel).order_by(ProbePathLedgerModel.relative_path)
                    )
                )
                .scalars()
                .all()
            )
            for ledger in ledgers:
                validate_path_snapshot(await self._path_snapshot(session, ledger))
            probes = (await session.execute(select(ProbeOperationModel))).scalars().all()
            for probe in probes:
                await self._validate_probe_provenance(session, probe)

    async def _validate_probe_provenance(
        self,
        session: AsyncSession,
        probe: ProbeOperationModel,
    ) -> tuple[OperationSnapshot, ProbeArtifact]:
        """Validate the complete operation/binding/artifact identity graph."""

        operation_model = await session.get(OperationModel, probe.operation_id)
        artifact_model = await session.get(ProbeArtifactModel, probe.artifact_id)
        prepared = await session.get(IdempotencyBindingModel, probe.prepared_binding_id)
        caller = await session.get(IdempotencyBindingModel, probe.caller_binding_id)
        if operation_model is None or artifact_model is None or prepared is None or caller is None:
            raise ProbeWorkspaceStoreError("probe operation provenance is incomplete")
        operation = await self._operations._snapshot(session, operation_model)
        artifact = self._artifact(artifact_model)
        kind = ProbeOperationKind(probe.probe_operation)
        tool_name = f"probe_workspace_{kind.value}"
        prepared_artifact_id = None if kind is ProbeOperationKind.WRITE else probe.artifact_id
        input_digest = prepared_input_sha256(
            operation=kind,
            relative_path=probe.relative_path,
            expected_content_sha256=probe.expected_content_sha256,
            byte_count=probe.expected_byte_count,
            artifact_id=prepared_artifact_id,
        )
        if (
            prepared.prepared_operation_id is None
            or prepared.target_identity_sha256 is None
            or prepared.maximum_effect_sha256 is None
        ):
            raise ProbeWorkspaceStoreError("probe prepared provenance is incomplete")
        fingerprint = operation_fingerprint_sha256(
            operation=kind,
            prepared_operation_id=prepared.prepared_operation_id,
            prepared_input_sha256=input_digest,
            relative_path=probe.relative_path,
            expected_content_sha256=probe.expected_content_sha256,
            byte_count=probe.expected_byte_count,
            artifact_id=prepared_artifact_id,
            target_identity_digest=prepared.target_identity_sha256,
            maximum_effect_digest=prepared.maximum_effect_sha256,
        )
        expected_owner_digest = owner_digest(operation.owner)
        if (
            probe.prepared_binding_id == probe.caller_binding_id
            or prepared.operation_id != probe.operation_id
            or caller.operation_id != probe.operation_id
            or prepared.key_mode != IdempotencyKeyMode.PREPARED_EXECUTION_NONCE.value
            or caller.key_mode != IdempotencyKeyMode.CALLER_KEY.value
            or prepared.record_kind != BindingRecordKind.FULL.value
            or caller.record_kind != BindingRecordKind.FULL.value
            or prepared.owner_controller_id != operation.owner.controller_id
            or prepared.owner_controller_epoch != operation.owner.controller_epoch
            or caller.owner_controller_id != operation.owner.controller_id
            or caller.owner_controller_epoch != operation.owner.controller_epoch
            or prepared.owner_controller_digest != expected_owner_digest
            or caller.owner_controller_digest != expected_owner_digest
            or prepared.device_id != operation.intent.device_id
            or prepared.device_epoch != operation.intent.device_epoch
            or caller.device_id != operation.intent.device_id
            or caller.device_epoch != operation.intent.device_epoch
            or prepared.tool_name != tool_name
            or caller.tool_name != tool_name
            or prepared.contract_version != "1.1"
            or caller.contract_version != "1.1"
            or operation.intent.operation_contract != tool_name
            or operation.intent.operation_contract_version != "1.1"
            or operation.intent.tool_name != tool_name
            or operation.intent.tool_contract_version != "1.1"
            or prepared.request_fingerprint_sha256 != fingerprint
            or caller.request_fingerprint_sha256 != fingerprint
            or operation.intent.request_fingerprint_sha256 != fingerprint
            or prepared.prepared_input_sha256 != input_digest
            or prepared.prepared_state_binding_sha256 != probe.prepared_state_binding_sha256
            or caller.target_identity_sha256 != prepared.target_identity_sha256
            or caller.maximum_effect_sha256 != prepared.maximum_effect_sha256
            or operation.intent.target_identity_sha256 != prepared.target_identity_sha256
            or operation.intent.maximum_effect_sha256 != prepared.maximum_effect_sha256
            or probe.relative_path != artifact.relative_path
            or probe.expected_content_sha256 != artifact.content_sha256
            or artifact.owner_controller_id != operation.owner.controller_id
            or artifact.owner_controller_epoch != operation.owner.controller_epoch
        ):
            raise ProbeWorkspaceStoreError("probe operation provenance is inconsistent")

        create_probe = await session.get(ProbeOperationModel, artifact.create_operation_id)
        if (
            create_probe is None
            or create_probe.probe_operation != ProbeOperationKind.WRITE.value
            or create_probe.artifact_id != artifact.artifact_id
            or create_probe.relative_path != artifact.relative_path
            or create_probe.expected_content_sha256 != artifact.content_sha256
            or create_probe.expected_byte_count != artifact.byte_count
        ):
            raise ProbeWorkspaceStoreError("probe artifact creation provenance is inconsistent")
        if create_probe.operation_id != probe.operation_id:
            await self._validate_probe_provenance(session, create_probe)
        if kind is ProbeOperationKind.WRITE:
            expected_artifact_id = (
                "artifact_"
                + hashlib.sha256(
                    b"binnacle.probe-artifact.v1\0" + probe.operation_id.encode()
                ).hexdigest()[:32]
            )
            if (
                probe.expected_byte_count != artifact.byte_count
                or probe.artifact_id != expected_artifact_id
                or artifact.create_operation_id != probe.operation_id
            ):
                raise ProbeWorkspaceStoreError("probe write provenance is inconsistent")
        elif probe.expected_byte_count is not None:
            raise ProbeWorkspaceStoreError("probe cleanup provenance is inconsistent")

        for cleanup_operation_id in (
            artifact.active_cleanup_operation_id,
            artifact.removed_by_cleanup_operation_id,
        ):
            if cleanup_operation_id is None:
                continue
            cleanup_probe = await session.get(ProbeOperationModel, cleanup_operation_id)
            if (
                cleanup_probe is None
                or cleanup_probe.probe_operation != ProbeOperationKind.CLEANUP.value
                or cleanup_probe.artifact_id != artifact.artifact_id
                or cleanup_probe.relative_path != artifact.relative_path
                or cleanup_probe.expected_content_sha256 != artifact.content_sha256
            ):
                raise ProbeWorkspaceStoreError("probe cleanup provenance is inconsistent")
        return operation, artifact

    async def _path_snapshot(
        self, session: AsyncSession, ledger: ProbePathLedgerModel
    ) -> ProbePathSnapshot:
        artifacts = (
            (
                await session.execute(
                    select(ProbeArtifactModel)
                    .where(ProbeArtifactModel.relative_path == ledger.relative_path)
                    .order_by(ProbeArtifactModel.path_generation)
                )
            )
            .scalars()
            .all()
        )
        active_model = None
        terminal: list[ProbeArtifact] = []
        for model in artifacts:
            if model.artifact_id == ledger.active_artifact_id:
                if active_model is not None:
                    raise ProbeWorkspaceStoreError("probe ledger identifies duplicate active rows")
                active_model = model
            elif model.state in {
                ProbeArtifactState.REMOVED.value,
                ProbeArtifactState.ABANDONED.value,
            }:
                terminal.append(self._artifact(model))
            else:
                raise ProbeWorkspaceStoreError(
                    "nonterminal probe artifact is not independently ledger-active"
                )
        return ProbePathSnapshot(
            ledger=ProbePathLedger(
                relative_path=ledger.relative_path,
                generation_high_water=ledger.generation_high_water,
                terminal_history_count=ledger.terminal_history_count,
                terminal_history_sha256=ledger.terminal_history_sha256,
                active_artifact_id=ledger.active_artifact_id,
                active_generation=ledger.active_generation,
                active_create_operation_id=ledger.active_create_operation_id,
                ledger_version=ledger.ledger_version,
                updated_at=_utc(ledger.updated_at) or ledger.updated_at,
            ),
            terminal_artifacts=tuple(terminal),
            active_artifact=None if active_model is None else self._artifact(active_model),
        )

    async def _terminalize(
        self,
        session: AsyncSession,
        probe: ProbeOperationModel,
        *,
        terminal_state: ProbeArtifactState,
        removed_by_operation: bool,
        now: datetime,
    ) -> None:
        ledger = await self._require_ledger(session, probe.relative_path)
        snapshot = await self._path_snapshot(session, ledger)
        validate_path_snapshot(snapshot)
        artifact = await self._require_artifact(session, probe.artifact_id)
        if (
            snapshot.active_artifact is None
            or snapshot.active_artifact.artifact_id != artifact.artifact_id
            or ledger.active_artifact_id != artifact.artifact_id
        ):
            raise ProbeWorkspaceStoreError("terminal probe ownership is not exact")
        if terminal_state is ProbeArtifactState.ABANDONED:
            if artifact.state not in {
                ProbeArtifactState.RESERVED.value,
                ProbeArtifactState.UNCERTAIN.value,
            }:
                raise ProbeWorkspaceStoreError("only conservative write state can be abandoned")
        elif (
            artifact.state != ProbeArtifactState.CREATED.value
            or artifact.active_cleanup_operation_id != probe.operation_id
        ):
            raise ProbeWorkspaceStoreError("cleanup terminalization claim is not exact")
        terminal_artifact = replace(
            self._artifact(artifact),
            state=terminal_state,
            active_cleanup_operation_id=None,
            removed_by_cleanup_operation_id=(probe.operation_id if removed_by_operation else None),
            updated_at=now,
            removed_at=now,
        )
        history = (*snapshot.terminal_artifacts, terminal_artifact)
        artifact.state = terminal_state.value
        artifact.active_cleanup_operation_id = None
        artifact.removed_by_cleanup_operation_id = (
            probe.operation_id if removed_by_operation else None
        )
        artifact.updated_at = now
        artifact.removed_at = now
        ledger.terminal_history_count += 1
        ledger.terminal_history_sha256 = terminal_history_sha256(history)
        ledger.active_artifact_id = None
        ledger.active_generation = None
        ledger.active_create_operation_id = None
        ledger.ledger_version += 1
        ledger.updated_at = now

    def _apply_operation_transition(
        self,
        session: AsyncSession,
        model: OperationModel,
        current: OperationSnapshot,
        updated: OperationSnapshot,
        reason_code: str,
    ) -> None:
        SqliteOperationStore._assign_operation_model(model, updated)
        session.add(self._transition_model(current, updated, reason_code=reason_code))

    @staticmethod
    def _effect_reference_digest(reference: str) -> str:
        return hashlib.sha256(b"binnacle.effect-reference.v1\0" + reference.encode()).hexdigest()

    @staticmethod
    def _transition_model(
        current: OperationSnapshot,
        updated: OperationSnapshot,
        *,
        reason_code: str,
    ) -> OperationTransitionModel:
        return OperationTransitionModel(
            operation_id=updated.operation_id,
            state_version=updated.state_version,
            from_state=current.state.value,
            to_state=updated.state.value,
            effect_knowledge=updated.effect_knowledge.value,
            terminality=updated.terminality.value,
            reason_code=reason_code,
            error_code=None if updated.error is None else updated.error.code,
            recorded_at=updated.updated_at,
            runtime_build_sha256=updated.intent.runtime_build_sha256,
        )

    @staticmethod
    def _policy_model(operation: OperationModel, decision: object) -> PolicyDecisionModel:
        from binnacle.domain.policy import PolicyDecision

        if not isinstance(decision, PolicyDecision):
            raise TypeError("probe authorisation requires a policy decision")
        return PolicyDecisionModel(
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

    @staticmethod
    def _artifact(model: ProbeArtifactModel) -> ProbeArtifact:
        return ProbeArtifact(
            artifact_id=model.artifact_id,
            relative_path=model.relative_path,
            path_generation=model.path_generation,
            owner_controller_id=model.owner_controller_id,
            owner_controller_epoch=model.owner_controller_epoch,
            content_sha256=model.content_sha256,
            byte_count=model.byte_count,
            state=ProbeArtifactState(model.state),
            create_operation_id=model.create_operation_id,
            active_cleanup_operation_id=model.active_cleanup_operation_id,
            removed_by_cleanup_operation_id=model.removed_by_cleanup_operation_id,
            created_at=_utc(model.created_at) or model.created_at,
            updated_at=_utc(model.updated_at) or model.updated_at,
            removed_at=_utc(model.removed_at),
            file_identity_digest=model.file_identity_digest,
        )

    @staticmethod
    def _probe_operation(model: ProbeOperationModel) -> ProbeOperationRecord:
        return ProbeOperationRecord(
            operation_id=model.operation_id,
            probe_operation=ProbeOperationKind(model.probe_operation),
            prepared_binding_id=model.prepared_binding_id,
            caller_binding_id=model.caller_binding_id,
            artifact_id=model.artifact_id,
            relative_path=model.relative_path,
            expected_content_sha256=model.expected_content_sha256,
            expected_byte_count=model.expected_byte_count,
            prepared_state_binding_sha256=model.prepared_state_binding_sha256,
            created_at=_utc(model.created_at) or model.created_at,
        )

    @staticmethod
    async def _require_probe_operation(
        session: AsyncSession, operation_id: str
    ) -> ProbeOperationModel:
        value = await session.get(ProbeOperationModel, operation_id)
        if value is None:
            raise ProbeWorkspaceStoreError("probe operation is missing")
        return value

    @staticmethod
    async def _require_operation(session: AsyncSession, operation_id: str) -> OperationModel:
        value = await session.get(OperationModel, operation_id)
        if value is None:
            raise OperationStoreError("operation_not_found")
        return value

    @staticmethod
    async def _require_artifact(session: AsyncSession, artifact_id: str) -> ProbeArtifactModel:
        value = await session.get(ProbeArtifactModel, artifact_id)
        if value is None:
            raise ProbeWorkspaceStoreError("probe artifact is missing")
        return value

    @staticmethod
    async def _require_ledger(session: AsyncSession, relative_path: str) -> ProbePathLedgerModel:
        value = await session.get(ProbePathLedgerModel, relative_path)
        if value is None:
            raise ProbeWorkspaceStoreError("probe ledger is missing")
        return value


__all__ = ["ProbeWorkspaceStoreError", "SqliteProbeWorkspaceRepository"]

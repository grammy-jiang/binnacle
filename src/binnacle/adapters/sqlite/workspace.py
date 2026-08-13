"""SQLite repository for registered workspaces, operation facts, and mutation fences."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import (
    DevelopmentSessionModel,
    OperationModel,
    OperationTransitionModel,
    PolicyDecisionModel,
    RegisteredWorkspaceModel,
    WorkspaceMutationFenceModel,
    WorkspaceOperationModel,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore, _utc
from binnacle.domain.development_session import ActivationClosure, DevelopmentSessionState
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    transition,
)
from binnacle.domain.workspace import (
    WorkspaceFence,
    WorkspaceMutationKind,
    WorkspaceObjectKind,
    validate_sha256,
)
from binnacle.ports.workspace import (
    RegisteredWorkspaceSnapshot,
    WorkspaceAuthorisationRequest,
    WorkspaceOperationRecord,
)


class WorkspaceStoreError(RuntimeError):
    """Registered workspace persistence is missing, stale, or inconsistent."""


class SqliteWorkspaceRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime
        self._operations = SqliteOperationStore(runtime)

    async def register_workspace(
        self,
        registration: RegisteredWorkspaceSnapshot,
    ) -> RegisteredWorkspaceSnapshot:
        """Insert one immutable stopped-service registration and its free fence."""

        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                existing = await session.get(RegisteredWorkspaceModel, registration.workspace_id)
                if existing is not None:
                    retained = self._registration(existing)
                    fence = await session.get(
                        WorkspaceMutationFenceModel, registration.workspace_id
                    )
                    if retained != registration or fence is None:
                        raise WorkspaceStoreError(
                            "workspace registration conflicts with retained identity"
                        )
                    await session.commit()
                    return retained
                session.add(self._registration_model(registration))
                session.add(
                    WorkspaceMutationFenceModel(
                        workspace_id=registration.workspace_id,
                        fence_version=1,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=registration.registered_at,
                    )
                )
                await session.flush()
                await session.commit()
                return registration
            except IntegrityError as exc:
                await session.rollback()
                raise WorkspaceStoreError(
                    "workspace registration could not be inserted exactly once"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def get_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(RegisteredWorkspaceModel, workspace_id)
            return None if model is None else self._registration(model)

    async def require_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot:
        registration = await self.get_registration(workspace_id)
        if registration is None:
            raise WorkspaceStoreError("registered workspace is missing")
        return registration

    async def get_fence(self, workspace_id: str) -> WorkspaceFence:
        async with self._runtime.session_factory() as session:
            model = await session.get(WorkspaceMutationFenceModel, workspace_id)
            if model is None:
                raise WorkspaceStoreError("workspace mutation fence is missing")
            return self._fence(model)

    async def acquire_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        contract: str,
        acquired_at: datetime,
    ) -> WorkspaceFence:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == workspace_id,
                        WorkspaceMutationFenceModel.fence_version == expected_version,
                        WorkspaceMutationFenceModel.active_operation_id.is_(None),
                        WorkspaceMutationFenceModel.active_contract.is_(None),
                        WorkspaceMutationFenceModel.acquired_at.is_(None),
                    )
                    .values(
                        fence_version=expected_version + 1,
                        active_operation_id=operation_id,
                        active_contract=contract,
                        acquired_at=acquired_at,
                        updated_at=acquired_at,
                    )
                )
                self._require_one_row(result, "workspace mutation fence is busy or stale")
                await session.commit()
                return WorkspaceFence(
                    workspace_id=workspace_id,
                    fence_version=expected_version + 1,
                    active_operation_id=operation_id,
                    active_contract=contract,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise WorkspaceStoreError("workspace mutation fence owner is invalid") from exc
            except Exception:
                await session.rollback()
                raise

    async def release_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        released_at: datetime,
    ) -> WorkspaceFence:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == workspace_id,
                        WorkspaceMutationFenceModel.fence_version == expected_version,
                        WorkspaceMutationFenceModel.active_operation_id == operation_id,
                        WorkspaceMutationFenceModel.active_contract.is_not(None),
                        WorkspaceMutationFenceModel.acquired_at.is_not(None),
                    )
                    .values(
                        fence_version=expected_version + 1,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=released_at,
                    )
                )
                self._require_one_row(result, "workspace mutation fence owner/version changed")
                await session.commit()
                return WorkspaceFence(
                    workspace_id=workspace_id,
                    fence_version=expected_version + 1,
                    active_operation_id=None,
                    active_contract=None,
                )
            except Exception:
                await session.rollback()
                raise

    async def authorise_mutation(
        self,
        request: WorkspaceAuthorisationRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence]:
        """Commit the allow decision, binding, fence, and lifecycle edge atomically."""

        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation_model = await session.get(OperationModel, request.operation.operation_id)
                if operation_model is None:
                    raise WorkspaceStoreError("workspace operation disappeared")
                current = await self._operations._snapshot(session, operation_model)
                if (
                    current != request.operation
                    or current.state is not OperationState.RECEIVED
                    or current.state_version != request.operation.state_version
                ):
                    raise WorkspaceStoreError("workspace mutation admission is stale")

                session_model = await session.get(
                    DevelopmentSessionModel, request.record.session_id
                )
                registration = await session.get(
                    RegisteredWorkspaceModel, request.record.workspace_id
                )
                fence = await session.get(WorkspaceMutationFenceModel, request.record.workspace_id)
                self._validate_authorisation(
                    request,
                    current=current,
                    session=session_model,
                    registration=registration,
                    fence=fence,
                )
                if await session.get(WorkspaceOperationModel, current.operation_id) is not None:
                    raise WorkspaceStoreError("workspace mutation was already admitted")
                if (
                    await session.execute(
                        select(PolicyDecisionModel.policy_decision_id).where(
                            PolicyDecisionModel.operation_id == current.operation_id
                        )
                    )
                ).scalar_one_or_none() is not None:
                    raise WorkspaceStoreError("workspace policy decision already exists")

                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == request.record.workspace_id,
                        WorkspaceMutationFenceModel.fence_version == request.expected_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id.is_(None),
                        WorkspaceMutationFenceModel.active_contract.is_(None),
                        WorkspaceMutationFenceModel.acquired_at.is_(None),
                    )
                    .values(
                        fence_version=request.expected_fence_version + 1,
                        active_operation_id=current.operation_id,
                        active_contract=current.intent.operation_contract,
                        acquired_at=request.authorised_at,
                        updated_at=request.authorised_at,
                    )
                )
                self._require_one_row(fence_result, "workspace mutation fence is busy or stale")
                session.add(self._operation_model(request.record))
                session.add(self._policy_model(operation_model, request))
                authorised = transition(
                    current,
                    TransitionRequest(
                        expected_state_version=current.state_version,
                        to_state=OperationState.AUTHORISED,
                        effect_knowledge=EffectKnowledge.NONE,
                        reason_code="policy_allowed",
                        occurred_at=request.authorised_at,
                    ),
                )
                operation_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == current.operation_id,
                        OperationModel.state == OperationState.RECEIVED.value,
                        OperationModel.state_version == current.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(authorised))
                )
                self._require_one_row(
                    operation_result, "workspace operation authorisation CAS failed"
                )
                session.add(
                    OperationTransitionModel(
                        operation_id=current.operation_id,
                        state_version=authorised.state_version,
                        from_state=current.state.value,
                        to_state=authorised.state.value,
                        effect_knowledge=authorised.effect_knowledge.value,
                        terminality=authorised.terminality.value,
                        reason_code="policy_allowed",
                        error_code=None,
                        recorded_at=authorised.updated_at,
                        runtime_build_sha256=authorised.intent.runtime_build_sha256,
                    )
                )
                await session.commit()
                return authorised, WorkspaceFence(
                    workspace_id=request.record.workspace_id,
                    fence_version=request.expected_fence_version + 1,
                    active_operation_id=current.operation_id,
                    active_contract=current.intent.operation_contract,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise WorkspaceStoreError(
                    "workspace mutation authority facts violated durable constraints"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def get_operation(self, operation_id: str) -> WorkspaceOperationRecord | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(WorkspaceOperationModel, operation_id)
            return None if model is None else self._operation(model)

    async def list_operations(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[WorkspaceOperationRecord, ...]:
        if limit < 1:
            raise WorkspaceStoreError("workspace operation page limit must be positive")
        if (after_created_at is None) != (after_operation_id is None):
            raise WorkspaceStoreError("workspace operation cursor must contain both fields")
        statement = select(WorkspaceOperationModel)
        if after_created_at is not None and after_operation_id is not None:
            statement = statement.where(
                or_(
                    WorkspaceOperationModel.created_at > after_created_at,
                    and_(
                        WorkspaceOperationModel.created_at == after_created_at,
                        WorkspaceOperationModel.operation_id > after_operation_id,
                    ),
                )
            )
        statement = statement.order_by(
            WorkspaceOperationModel.created_at, WorkspaceOperationModel.operation_id
        ).limit(limit)
        async with self._runtime.session_factory() as session:
            models = (await session.execute(statement)).scalars().all()
            return tuple(self._operation(model) for model in models)

    async def list_operations_for_closure(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[WorkspaceOperationRecord, ...]:
        if not 1 <= limit <= 1_000:
            raise WorkspaceStoreError("workspace closure page limit is invalid")
        if (after_created_at is None) != (after_operation_id is None):
            raise WorkspaceStoreError("workspace closure cursor must contain both fields")
        statement = (
            select(WorkspaceOperationModel)
            .join(
                WorkspaceMutationFenceModel,
                WorkspaceMutationFenceModel.workspace_id == WorkspaceOperationModel.workspace_id,
            )
            .where(
                WorkspaceMutationFenceModel.active_operation_id
                == WorkspaceOperationModel.operation_id
            )
        )
        if after_created_at is not None and after_operation_id is not None:
            statement = statement.where(
                or_(
                    WorkspaceOperationModel.created_at > after_created_at,
                    and_(
                        WorkspaceOperationModel.created_at == after_created_at,
                        WorkspaceOperationModel.operation_id > after_operation_id,
                    ),
                )
            )
        statement = statement.order_by(
            WorkspaceOperationModel.created_at, WorkspaceOperationModel.operation_id
        ).limit(limit)
        async with self._runtime.session_factory() as session:
            models = (await session.execute(statement)).scalars().all()
            return tuple(self._operation(model) for model in models)

    async def verify_integrity(self) -> None:
        async with self._runtime.session_factory() as session:
            missing_fences = (
                await session.execute(
                    select(func.count())
                    .select_from(RegisteredWorkspaceModel)
                    .outerjoin(
                        WorkspaceMutationFenceModel,
                        WorkspaceMutationFenceModel.workspace_id
                        == RegisteredWorkspaceModel.workspace_id,
                    )
                    .where(WorkspaceMutationFenceModel.workspace_id.is_(None))
                )
            ).scalar_one()
            mismatched_operations = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM workspace_operations wo
                        LEFT JOIN development_sessions s ON s.session_id=wo.session_id
                        LEFT JOIN operations o ON o.operation_id=wo.operation_id
                        LEFT JOIN policy_decisions p ON p.operation_id=wo.operation_id
                        LEFT JOIN workspace_mutation_fences f ON f.workspace_id=wo.workspace_id
                        WHERE s.session_id IS NULL OR o.operation_id IS NULL
                           OR p.operation_id IS NULL OR f.workspace_id IS NULL
                           OR wo.workspace_id!=s.workspace_id
                           OR wo.expected_mount_identity_sha256!=s.workspace_mount_identity_sha256
                           OR o.controller_id!=s.controller_id
                           OR o.controller_epoch!=s.controller_epoch
                           OR o.device_id!=s.device_id OR o.device_epoch!=s.device_epoch
                           OR p.decision!='allow' OR p.policy_version!=s.policy_version
                           OR p.controller_id!=o.controller_id
                           OR p.controller_epoch!=o.controller_epoch
                           OR p.operation_contract!=o.operation_contract
                           OR p.operation_contract_version!=o.operation_contract_version
                           OR NOT EXISTS (
                               SELECT 1 FROM idempotency_bindings b
                               WHERE b.operation_id=o.operation_id
                           )
                           OR EXISTS (
                               SELECT 1 FROM idempotency_bindings b
                               WHERE b.operation_id=o.operation_id
                                 AND b.target_identity_sha256 IS NOT p.normalized_target_digest
                           )
                           OR o.operation_contract!=('workspace_' || wo.mutation_kind)
                           OR o.tool_name!=o.operation_contract
                           OR o.state IN ('received','rejected')
                           OR (o.state IN ('authorised','running','paused','cancelling','uncertain')
                               AND f.active_operation_id!=o.operation_id)
                        """
                    )
                )
            ).scalar_one()
            mismatched_fences = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM workspace_mutation_fences f
                        LEFT JOIN workspace_operations wo
                          ON wo.operation_id=f.active_operation_id
                        LEFT JOIN command_operations co
                          ON co.operation_id=f.active_operation_id
                        LEFT JOIN git_operations go
                          ON go.operation_id=f.active_operation_id
                        LEFT JOIN privileged_operations po
                          ON po.operation_id=f.active_operation_id
                        LEFT JOIN operations o ON o.operation_id=f.active_operation_id
                        WHERE f.active_operation_id IS NOT NULL
                          AND (o.operation_id IS NULL
                               OR ((wo.operation_id IS NOT NULL) +
                                   (co.operation_id IS NOT NULL) +
                                   (go.operation_id IS NOT NULL) +
                                   (po.operation_id IS NOT NULL)) != 1
                               OR (wo.operation_id IS NOT NULL AND
                                   (wo.workspace_id!=f.workspace_id OR
                                    f.active_contract!=('workspace_' || wo.mutation_kind)))
                               OR (co.operation_id IS NOT NULL AND
                                   (co.workspace_id!=f.workspace_id OR
                                    co.closure_state!='pending'))
                               OR (go.operation_id IS NOT NULL AND
                                   (go.workspace_id!=f.workspace_id OR
                                    go.state='terminal'))
                               OR (po.operation_id IS NOT NULL AND
                                   (po.workspace_id!=f.workspace_id OR
                                    po.workspace_fence_version!=f.fence_version OR
                                    po.action='package_install' OR po.state='terminal'))
                               OR o.operation_contract!=f.active_contract
                               OR o.state IN ('received','rejected'))
                        """
                    )
                )
            ).scalar_one()
            if int(missing_fences) or int(mismatched_operations) or int(mismatched_fences):
                raise WorkspaceStoreError(
                    "workspace registration or mutation state failed exact integrity checks"
                )

    @staticmethod
    def _require_one_row(result: object, message: str) -> None:
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise WorkspaceStoreError(message)

    @staticmethod
    def _validate_authorisation(
        request: WorkspaceAuthorisationRequest,
        *,
        current: OperationSnapshot,
        session: DevelopmentSessionModel | None,
        registration: RegisteredWorkspaceModel | None,
        fence: WorkspaceMutationFenceModel | None,
    ) -> None:
        record = request.record
        decision = request.decision
        expected_contract = f"workspace_{record.mutation_kind.value}"
        try:
            validate_sha256(request.normalized_target_digest, name="normalized_target_digest")
            if request.required_scope_digest is not None:
                validate_sha256(request.required_scope_digest, name="required_scope_digest")
        except ValueError as exc:
            raise WorkspaceStoreError("workspace policy digests are invalid") from exc
        if (
            not decision.allowed
            or decision.operation_id != current.operation_id
            or decision.decided_at > request.authorised_at
            or record.operation_id != current.operation_id
            or record.created_at != request.authorised_at
            or record.updated_at != request.authorised_at
            or current.intent.operation_contract != expected_contract
            or current.intent.tool_name != expected_contract
            or current.intent.operation_contract_version != current.intent.tool_contract_version
            or current.intent.target_identity_sha256 != request.normalized_target_digest
        ):
            raise WorkspaceStoreError("workspace policy or operation facts are not exact")
        if session is None or registration is None or fence is None:
            raise WorkspaceStoreError("workspace authority state is incomplete")
        if (
            session.state != DevelopmentSessionState.ACTIVE.value
            or session.activation_closure != ActivationClosure.COMPLETE.value
            or session.controller_id != current.owner.controller_id
            or session.controller_epoch != current.owner.controller_epoch
            or session.device_id != current.intent.device_id
            or session.device_epoch != current.intent.device_epoch
            or session.workspace_id != record.workspace_id
            or session.policy_version != decision.policy_version
            or session.workspace_profile_sha256 != registration.profile_sha256
            or session.workspace_root_identity_sha256 != registration.root_identity_sha256
            or session.workspace_mount_identity_sha256 != registration.mount_identity_sha256
            or record.expected_mount_identity_sha256 != registration.mount_identity_sha256
            or record.primitive_profile_version != registration.primitive_profile_version
            or fence.fence_version != request.expected_fence_version
            or fence.active_operation_id is not None
            or fence.active_contract is not None
            or fence.acquired_at is not None
        ):
            raise WorkspaceStoreError("workspace session, registration, or fence is not exact")

    @staticmethod
    def _operation_model(record: WorkspaceOperationRecord) -> WorkspaceOperationModel:
        return WorkspaceOperationModel(
            operation_id=record.operation_id,
            session_id=record.session_id,
            workspace_id=record.workspace_id,
            mutation_kind=record.mutation_kind.value,
            object_kind=record.object_kind.value,
            source_path_sha256=record.source_path_sha256,
            target_path_sha256=record.target_path_sha256,
            expected_object_sha256=record.expected_object_sha256,
            expected_content_sha256=record.expected_content_sha256,
            expected_link_count=record.expected_link_count,
            expected_mount_identity_sha256=record.expected_mount_identity_sha256,
            proposed_content_sha256=record.proposed_content_sha256,
            proposed_byte_count=record.proposed_byte_count,
            state_binding_sha256=record.state_binding_sha256,
            staging_reference=record.staging_reference,
            staging_reference_sha256=record.staging_reference_sha256,
            primitive_profile_version=record.primitive_profile_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _policy_model(
        operation: OperationModel,
        request: WorkspaceAuthorisationRequest,
    ) -> PolicyDecisionModel:
        decision = request.decision
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
            required_scope_digest=request.required_scope_digest,
            normalized_target_digest=request.normalized_target_digest,
            input_facts_sha256=decision.input_facts_sha256,
            reason_codes_json=json.dumps(
                decision.reason_codes, separators=(",", ":"), sort_keys=True
            ),
            decided_at=decision.decided_at,
            runtime_policy_sha256=decision.runtime_policy_sha256,
        )

    @staticmethod
    def _registration_model(
        registration: RegisteredWorkspaceSnapshot,
    ) -> RegisteredWorkspaceModel:
        return RegisteredWorkspaceModel(
            workspace_id=registration.workspace_id,
            profile_sha256=registration.profile_sha256,
            root_identity_sha256=registration.root_identity_sha256,
            mount_identity_sha256=registration.mount_identity_sha256,
            root_device=registration.root_device,
            root_inode=registration.root_inode,
            mount_id=registration.mount_id,
            mount_device=registration.mount_device,
            filesystem_type=registration.filesystem_type,
            owner_uid=registration.owner_uid,
            owner_gid=registration.owner_gid,
            mode=registration.mode,
            primitive_profile_version=registration.primitive_profile_version,
            registration_version=registration.registration_version,
            registered_at=registration.registered_at,
            updated_at=registration.updated_at,
        )

    @staticmethod
    def _registration(model: RegisteredWorkspaceModel) -> RegisteredWorkspaceSnapshot:
        registered_at = _utc(model.registered_at)
        updated_at = _utc(model.updated_at)
        if registered_at is None or updated_at is None:
            raise WorkspaceStoreError("registered workspace timestamps are absent")
        return RegisteredWorkspaceSnapshot(
            workspace_id=model.workspace_id,
            profile_sha256=model.profile_sha256,
            root_identity_sha256=model.root_identity_sha256,
            mount_identity_sha256=model.mount_identity_sha256,
            root_device=model.root_device,
            root_inode=model.root_inode,
            mount_id=model.mount_id,
            mount_device=model.mount_device,
            filesystem_type=model.filesystem_type,
            owner_uid=model.owner_uid,
            owner_gid=model.owner_gid,
            mode=model.mode,
            primitive_profile_version=model.primitive_profile_version,
            registration_version=model.registration_version,
            registered_at=registered_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _fence(model: WorkspaceMutationFenceModel) -> WorkspaceFence:
        return WorkspaceFence(
            workspace_id=model.workspace_id,
            fence_version=model.fence_version,
            active_operation_id=model.active_operation_id,
            active_contract=model.active_contract,
        )

    @staticmethod
    def _operation(model: WorkspaceOperationModel) -> WorkspaceOperationRecord:
        created_at = _utc(model.created_at)
        updated_at = _utc(model.updated_at)
        if created_at is None or updated_at is None:
            raise WorkspaceStoreError("workspace operation timestamps are absent")
        return WorkspaceOperationRecord(
            operation_id=model.operation_id,
            session_id=model.session_id,
            workspace_id=model.workspace_id,
            mutation_kind=WorkspaceMutationKind(model.mutation_kind),
            object_kind=WorkspaceObjectKind(model.object_kind),
            source_path_sha256=model.source_path_sha256,
            target_path_sha256=model.target_path_sha256,
            expected_object_sha256=model.expected_object_sha256,
            expected_content_sha256=model.expected_content_sha256,
            expected_link_count=model.expected_link_count,
            expected_mount_identity_sha256=model.expected_mount_identity_sha256,
            proposed_content_sha256=model.proposed_content_sha256,
            proposed_byte_count=model.proposed_byte_count,
            state_binding_sha256=model.state_binding_sha256,
            staging_reference=model.staging_reference,
            staging_reference_sha256=model.staging_reference_sha256,
            primitive_profile_version=model.primitive_profile_version,
            created_at=created_at,
            updated_at=updated_at,
        )


__all__ = ["SqliteWorkspaceRepository", "WorkspaceStoreError"]

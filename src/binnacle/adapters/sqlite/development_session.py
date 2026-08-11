"""SQLite repository for durable Phase 6 development-session authority state."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import (
    DevelopmentSessionModel,
    OperationModel,
    OperationTransitionModel,
    PolicyDecisionModel,
    RegisteredWorkspaceModel,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore, _utc
from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    activate_session,
    complete_activation,
    reduce_session,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    transition,
)
from binnacle.domain.workspace import validate_sha256
from binnacle.ports.development_session import SessionAuthorisationRequest


class DevelopmentSessionStoreError(RuntimeError):
    """Durable session state is missing, conflicting, or structurally inconsistent."""


class DevelopmentSessionSlotBusy(DevelopmentSessionStoreError):
    """The exact device-epoch/workspace live slot is already retained."""


class SqliteDevelopmentSessionRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime
        self._operations = SqliteOperationStore(runtime)

    async def authorise_begin(
        self, request: SessionAuthorisationRequest
    ) -> tuple[OperationSnapshot, DevelopmentSessionSnapshot]:
        """Commit one allow decision, PENDING slot, and lifecycle edge atomically."""

        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation_model = await session.get(OperationModel, request.operation.operation_id)
                if operation_model is None:
                    raise DevelopmentSessionStoreError("session begin operation disappeared")
                current = await self._operations._snapshot(session, operation_model)
                registration = await session.get(
                    RegisteredWorkspaceModel, request.snapshot.workspace_id
                )
                self._validate_authorisation(
                    request,
                    current=current,
                    registration=registration,
                )
                if await session.get(DevelopmentSessionModel, request.snapshot.session_id):
                    raise DevelopmentSessionStoreError("development session already exists")
                if (
                    await session.execute(
                        select(PolicyDecisionModel.policy_decision_id).where(
                            PolicyDecisionModel.operation_id == current.operation_id
                        )
                    )
                ).scalar_one_or_none() is not None:
                    raise DevelopmentSessionStoreError("session policy decision already exists")

                session.add(self._model(request.snapshot, updated_at=request.snapshot.created_at))
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
                result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == current.operation_id,
                        OperationModel.state == OperationState.RECEIVED.value,
                        OperationModel.state_version == current.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(authorised))
                )
                self._require_one_row(result, "session begin authorisation CAS failed")
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
                return authorised, request.snapshot
            except IntegrityError as exc:
                await session.rollback()
                if "development_sessions.device_id" in str(exc.orig):
                    raise DevelopmentSessionSlotBusy(
                        "development session live slot is already retained"
                    ) from exc
                raise DevelopmentSessionStoreError(
                    "session begin authority facts violated durable constraints"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def get_session(self, session_id: str) -> DevelopmentSessionSnapshot | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(DevelopmentSessionModel, session_id)
            return None if model is None else self._snapshot(model)

    async def require_session(self, session_id: str) -> DevelopmentSessionSnapshot:
        snapshot = await self.get_session(session_id)
        if snapshot is None:
            raise DevelopmentSessionStoreError("development session is missing")
        return snapshot

    async def get_by_begin_operation(
        self, begin_operation_id: str
    ) -> DevelopmentSessionSnapshot | None:
        async with self._runtime.session_factory() as session:
            model = (
                await session.execute(
                    select(DevelopmentSessionModel).where(
                        DevelopmentSessionModel.begin_operation_id == begin_operation_id
                    )
                )
            ).scalar_one_or_none()
            return None if model is None else self._snapshot(model)

    async def activate(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        effect_reference: str,
        effect_reference_sha256: str,
        started_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await self._require_model(session, session_id)
                current = self._snapshot(model)
                desired = activate_session(
                    current,
                    expected_state_version=expected_state_version,
                    effect_reference=effect_reference,
                    effect_reference_sha256=effect_reference_sha256,
                    now=started_at,
                )
                result = await session.execute(
                    update(DevelopmentSessionModel)
                    .where(
                        DevelopmentSessionModel.session_id == session_id,
                        DevelopmentSessionModel.state == DevelopmentSessionState.PENDING.value,
                        DevelopmentSessionModel.state_version == expected_state_version,
                    )
                    .values(
                        state=desired.state.value,
                        state_version=desired.state_version,
                        started_at=desired.started_at,
                        activation_effect_reference=desired.activation_effect_reference,
                        activation_effect_reference_sha256=(
                            desired.activation_effect_reference_sha256
                        ),
                        updated_at=started_at,
                    )
                )
                self._require_one_row(result, "session activation lost its exact version")
                await session.commit()
                return desired
            except Exception:
                await session.rollback()
                raise

    async def complete_activation(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        closed_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await self._require_model(session, session_id)
                current = self._snapshot(model)
                desired = complete_activation(
                    current, expected_state_version=expected_state_version
                )
                result = await session.execute(
                    update(DevelopmentSessionModel)
                    .where(
                        DevelopmentSessionModel.session_id == session_id,
                        DevelopmentSessionModel.state.in_(
                            (
                                DevelopmentSessionState.ACTIVE.value,
                                DevelopmentSessionState.ENDED.value,
                                DevelopmentSessionState.EXPIRED.value,
                                DevelopmentSessionState.REVOKED.value,
                            )
                        ),
                        DevelopmentSessionModel.state_version == expected_state_version,
                        DevelopmentSessionModel.activation_closure
                        == ActivationClosure.PENDING.value,
                        DevelopmentSessionModel.activation_closure_version
                        == current.activation_closure_version,
                    )
                    .values(
                        state_version=desired.state_version,
                        activation_closure=desired.activation_closure.value,
                        activation_closure_version=desired.activation_closure_version,
                        updated_at=closed_at,
                    )
                )
                self._require_one_row(result, "activation closure lost its exact version")
                await session.commit()
                return desired
            except Exception:
                await session.rollback()
                raise

    async def reduce(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        target: DevelopmentSessionState,
        reason: str,
        terminal_at: datetime,
    ) -> DevelopmentSessionSnapshot:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                model = await self._require_model(session, session_id)
                current = self._snapshot(model)
                desired = reduce_session(
                    current,
                    expected_state_version=expected_state_version,
                    target=target,
                    reason=reason,
                    now=terminal_at,
                )
                result = await session.execute(
                    update(DevelopmentSessionModel)
                    .where(
                        DevelopmentSessionModel.session_id == session_id,
                        DevelopmentSessionModel.state.in_(
                            (
                                DevelopmentSessionState.PENDING.value,
                                DevelopmentSessionState.ACTIVE.value,
                            )
                        ),
                        DevelopmentSessionModel.state_version == expected_state_version,
                    )
                    .values(
                        state=desired.state.value,
                        state_version=desired.state_version,
                        terminal_at=desired.terminal_at,
                        terminal_reason=desired.terminal_reason,
                        updated_at=terminal_at,
                    )
                )
                self._require_one_row(result, "session reduction lost its exact version")
                await session.commit()
                return desired
            except Exception:
                await session.rollback()
                raise

    async def list_live(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]:
        if limit < 1:
            raise DevelopmentSessionStoreError("session page limit must be positive")
        if (after_created_at is None) != (after_session_id is None):
            raise DevelopmentSessionStoreError("session cursor must contain both fields")
        statement = select(DevelopmentSessionModel).where(
            DevelopmentSessionModel.state.in_(
                (DevelopmentSessionState.PENDING.value, DevelopmentSessionState.ACTIVE.value)
            )
        )
        if after_created_at is not None and after_session_id is not None:
            statement = statement.where(
                or_(
                    DevelopmentSessionModel.created_at > after_created_at,
                    and_(
                        DevelopmentSessionModel.created_at == after_created_at,
                        DevelopmentSessionModel.session_id > after_session_id,
                    ),
                )
            )
        statement = statement.order_by(
            DevelopmentSessionModel.created_at, DevelopmentSessionModel.session_id
        ).limit(limit)
        async with self._runtime.session_factory() as session:
            models = (await session.execute(statement)).scalars().all()
            return tuple(self._snapshot(model) for model in models)

    async def list_activation_closures(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]:
        if not 1 <= limit <= 1_000:
            raise DevelopmentSessionStoreError("session closure page limit is invalid")
        if (after_created_at is None) != (after_session_id is None):
            raise DevelopmentSessionStoreError("session closure cursor must contain both fields")
        statement = select(DevelopmentSessionModel).where(
            DevelopmentSessionModel.activation_closure == ActivationClosure.PENDING.value
        )
        if after_created_at is not None and after_session_id is not None:
            statement = statement.where(
                or_(
                    DevelopmentSessionModel.created_at > after_created_at,
                    and_(
                        DevelopmentSessionModel.created_at == after_created_at,
                        DevelopmentSessionModel.session_id > after_session_id,
                    ),
                )
            )
        statement = statement.order_by(
            DevelopmentSessionModel.created_at, DevelopmentSessionModel.session_id
        ).limit(limit)
        async with self._runtime.session_factory() as session:
            models = (await session.execute(statement)).scalars().all()
            return tuple(self._snapshot(model) for model in models)

    async def verify_integrity(self) -> None:
        async with self._runtime.session_factory() as session:
            duplicate_slot = (
                await session.execute(
                    select(func.count()).select_from(
                        select(
                            DevelopmentSessionModel.device_id,
                            DevelopmentSessionModel.device_epoch,
                            DevelopmentSessionModel.workspace_id,
                        )
                        .where(
                            DevelopmentSessionModel.state.in_(
                                (
                                    DevelopmentSessionState.PENDING.value,
                                    DevelopmentSessionState.ACTIVE.value,
                                )
                            )
                        )
                        .group_by(
                            DevelopmentSessionModel.device_id,
                            DevelopmentSessionModel.device_epoch,
                            DevelopmentSessionModel.workspace_id,
                        )
                        .having(func.count() > 1)
                        .subquery()
                    )
                )
            ).scalar_one()
            mismatched = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM development_sessions s
                        LEFT JOIN registered_workspaces w ON w.workspace_id=s.workspace_id
                        LEFT JOIN operations o ON o.operation_id=s.begin_operation_id
                        LEFT JOIN policy_decisions p ON p.operation_id=s.begin_operation_id
                        WHERE w.workspace_id IS NULL OR o.operation_id IS NULL
                           OR p.operation_id IS NULL
                           OR s.workspace_profile_sha256!=w.profile_sha256
                           OR s.workspace_root_identity_sha256!=w.root_identity_sha256
                           OR s.workspace_mount_identity_sha256!=w.mount_identity_sha256
                           OR s.controller_id!=o.controller_id
                           OR s.controller_epoch!=o.controller_epoch
                           OR s.device_id!=o.device_id OR s.device_epoch!=o.device_epoch
                           OR p.decision!='allow' OR p.policy_version!=s.policy_version
                           OR p.controller_id!=o.controller_id
                           OR p.controller_epoch!=o.controller_epoch
                           OR p.operation_contract!=o.operation_contract
                           OR p.operation_contract_version!=o.operation_contract_version
                           OR p.decided_at>s.created_at
                           OR o.operation_contract!='development_session_begin'
                           OR o.tool_name!='development_session_begin'
                           OR o.tool_contract_version!=o.operation_contract_version
                           OR o.state IN ('received','rejected')
                           OR NOT EXISTS (
                               SELECT 1 FROM idempotency_bindings b
                               WHERE b.operation_id=o.operation_id
                           )
                           OR EXISTS (
                               SELECT 1 FROM idempotency_bindings b
                               WHERE b.operation_id=o.operation_id
                                 AND b.target_identity_sha256 IS NOT p.normalized_target_digest
                           )
                           OR NOT EXISTS (
                               SELECT 1 FROM operation_transitions t
                               WHERE t.operation_id=o.operation_id
                                 AND t.state_version=2
                                 AND t.from_state='received'
                                 AND t.to_state='authorised'
                                 AND t.effect_knowledge='none'
                                 AND t.reason_code='policy_allowed'
                           )
                           OR (s.activation_effect_reference IS NOT NULL
                               AND o.state NOT IN ('running','uncertain','succeeded'))
                           OR (s.state='active'
                               AND o.state NOT IN ('running','uncertain','succeeded'))
                           OR (o.effect_reference IS NOT NULL
                               AND o.effect_reference IS NOT s.activation_effect_reference)
                           OR (o.effect_reference_digest IS NOT NULL
                               AND o.effect_reference_digest
                                   IS NOT s.activation_effect_reference_sha256)
                           OR (o.state='succeeded'
                               AND (o.effect_knowledge!='known_effect'
                                    OR o.effect_reference
                                       IS NOT s.activation_effect_reference
                                    OR o.effect_reference_digest
                                       IS NOT s.activation_effect_reference_sha256))
                           OR (s.activation_closure='complete'
                               AND (o.state!='succeeded'
                                    OR o.effect_knowledge!='known_effect'
                                    OR o.effect_reference
                                       IS NOT s.activation_effect_reference
                                    OR o.effect_reference_digest
                                       IS NOT s.activation_effect_reference_sha256))
                        """
                    )
                )
            ).scalar_one()
            if int(duplicate_slot) or int(mismatched):
                raise DevelopmentSessionStoreError(
                    "development session authority state failed exact integrity checks"
                )

    @staticmethod
    async def _require_model(session: AsyncSession, session_id: str) -> DevelopmentSessionModel:
        model = await session.get(DevelopmentSessionModel, session_id)
        if model is None:
            raise DevelopmentSessionStoreError("development session is missing")
        return model

    @staticmethod
    def _require_one_row(result: object, message: str) -> None:
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise DevelopmentSessionStoreError(message)

    @staticmethod
    def _validate_authorisation(
        request: SessionAuthorisationRequest,
        *,
        current: OperationSnapshot,
        registration: RegisteredWorkspaceModel | None,
    ) -> None:
        snapshot = request.snapshot
        decision = request.decision
        try:
            validate_sha256(request.normalized_target_digest, name="normalized_target_digest")
            if request.required_scope_digest is not None:
                validate_sha256(request.required_scope_digest, name="required_scope_digest")
        except ValueError as exc:
            raise DevelopmentSessionStoreError("session policy digests are invalid") from exc
        if (
            current != request.operation
            or current.state is not OperationState.RECEIVED
            or current.state_version != request.operation.state_version
            or not decision.allowed
            or decision.operation_id != current.operation_id
            or decision.decided_at > request.authorised_at
            or snapshot.begin_operation_id != current.operation_id
            or snapshot.created_at != request.authorised_at
            or snapshot.state is not DevelopmentSessionState.PENDING
            or snapshot.state_version != 1
            or snapshot.activation_closure is not ActivationClosure.PENDING
            or snapshot.activation_closure_version != 1
            or current.intent.operation_contract != "development_session_begin"
            or current.intent.tool_name != "development_session_begin"
            or current.intent.operation_contract_version != current.intent.tool_contract_version
            or current.intent.target_identity_sha256 != request.normalized_target_digest
        ):
            raise DevelopmentSessionStoreError(
                "session policy, operation, or initial pending facts are not exact"
            )
        if registration is None:
            raise DevelopmentSessionStoreError("registered workspace is missing")
        if (
            snapshot.controller_id != current.owner.controller_id
            or snapshot.controller_epoch != current.owner.controller_epoch
            or snapshot.device_id != current.intent.device_id
            or snapshot.device_epoch != current.intent.device_epoch
            or snapshot.policy_version != decision.policy_version
            or snapshot.workspace_profile_sha256 != registration.profile_sha256
            or snapshot.workspace_root_identity_sha256 != registration.root_identity_sha256
            or snapshot.workspace_mount_identity_sha256 != registration.mount_identity_sha256
        ):
            raise DevelopmentSessionStoreError(
                "session owner, workspace, or policy provenance is not exact"
            )

    @staticmethod
    def _policy_model(
        operation: OperationModel,
        request: SessionAuthorisationRequest,
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
    def _model(
        snapshot: DevelopmentSessionSnapshot, *, updated_at: datetime
    ) -> DevelopmentSessionModel:
        return DevelopmentSessionModel(
            session_id=snapshot.session_id,
            begin_operation_id=snapshot.begin_operation_id,
            state=snapshot.state.value,
            state_version=snapshot.state_version,
            activation_closure=snapshot.activation_closure.value,
            activation_closure_version=snapshot.activation_closure_version,
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
            objective_sha256=snapshot.objective_sha256,
            created_at=snapshot.created_at,
            updated_at=updated_at,
            expires_at=snapshot.expires_at,
            trusted_time_generation=snapshot.trusted_time_generation,
            activation_boot_id_digest=snapshot.activation_boot_id_digest,
            monotonic_deadline_ns=snapshot.monotonic_deadline_ns,
            started_at=snapshot.started_at,
            terminal_at=snapshot.terminal_at,
            terminal_reason=snapshot.terminal_reason,
            activation_effect_reference=snapshot.activation_effect_reference,
            activation_effect_reference_sha256=snapshot.activation_effect_reference_sha256,
        )

    @staticmethod
    def _snapshot(model: DevelopmentSessionModel) -> DevelopmentSessionSnapshot:
        created_at = _utc(model.created_at)
        expires_at = _utc(model.expires_at)
        if created_at is None or expires_at is None:
            raise DevelopmentSessionStoreError("development session time fields are absent")
        return DevelopmentSessionSnapshot(
            session_id=model.session_id,
            begin_operation_id=model.begin_operation_id,
            state=DevelopmentSessionState(model.state),
            state_version=model.state_version,
            activation_closure=ActivationClosure(model.activation_closure),
            activation_closure_version=model.activation_closure_version,
            controller_id=model.controller_id,
            controller_epoch=model.controller_epoch,
            device_id=model.device_id,
            device_epoch=model.device_epoch,
            workspace_id=model.workspace_id,
            workspace_profile_sha256=model.workspace_profile_sha256,
            workspace_root_identity_sha256=model.workspace_root_identity_sha256,
            workspace_mount_identity_sha256=model.workspace_mount_identity_sha256,
            policy_version=model.policy_version,
            contract_profile_sha256=model.contract_profile_sha256,
            objective_sha256=model.objective_sha256,
            created_at=created_at,
            expires_at=expires_at,
            trusted_time_generation=model.trusted_time_generation,
            activation_boot_id_digest=model.activation_boot_id_digest,
            monotonic_deadline_ns=model.monotonic_deadline_ns,
            started_at=_utc(model.started_at),
            terminal_at=_utc(model.terminal_at),
            terminal_reason=model.terminal_reason,
            activation_effect_reference=model.activation_effect_reference,
            activation_effect_reference_sha256=model.activation_effect_reference_sha256,
        )


__all__ = [
    "DevelopmentSessionSlotBusy",
    "DevelopmentSessionStoreError",
    "SqliteDevelopmentSessionRepository",
]

"""Atomic application-side Phase 9 restart admission persistence."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import (
    DevelopmentSessionModel,
    OperationModel,
    OperationTransitionModel,
    PolicyDecisionModel,
    PrivilegedEffectReservationModel,
    PrivilegedOperationModel,
    PrivilegedPreparationModel,
    RegisteredWorkspaceModel,
    WorkspaceMutationFenceModel,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore, _utc
from binnacle.domain.development_session import ActivationClosure, DevelopmentSessionState
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    transition,
)
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedMaximumEffect,
    canonical_sha256,
    canonical_timestamp,
)
from binnacle.domain.privileged_restart import (
    PrivilegedOperationState,
    PrivilegedPreparationState,
    PrivilegedReservationState,
    PrivilegedRestartPreparation,
    PrivilegedRestartRecord,
    RestartAcceptedClosureRequest,
    RestartAuthorisationRequest,
    RestartNoAcceptClosureRequest,
    ServiceRestartAcceptedClosureRequest,
)
from binnacle.domain.workspace import WorkspaceFence


class PrivilegedApplicationStoreError(RuntimeError):
    """Application-side privileged evidence is missing, stale, or contradictory."""


class SqlitePrivilegedApplicationRepository:
    """Persist exact restart preparation and atomic post-policy admission."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime
        self._operations = SqliteOperationStore(runtime)

    async def store_restart_preparation(
        self,
        preparation: PrivilegedRestartPreparation,
    ) -> PrivilegedRestartPreparation:
        if preparation.state is not PrivilegedPreparationState.AVAILABLE:
            raise PrivilegedApplicationStoreError("restart preparation must begin available")
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                existing = await session.get(
                    PrivilegedPreparationModel,
                    preparation.prepare_operation_id,
                )
                if existing is not None:
                    retained = self._preparation(existing)
                    if retained != preparation:
                        raise PrivilegedApplicationStoreError(
                            "restart preparation conflicts with retained evidence"
                        )
                    await session.commit()
                    return retained
                session.add(self._preparation_model(preparation))
                await session.flush()
                await session.commit()
                return preparation
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "restart preparation violates durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def authorise_restart(
        self,
        request: RestartAuthorisationRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]:
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation_model = await session.get(OperationModel, request.operation.operation_id)
                preparation_model = await session.get(
                    PrivilegedPreparationModel,
                    request.preparation.prepare_operation_id,
                )
                session_model = await session.get(
                    DevelopmentSessionModel,
                    request.preparation.session_id,
                )
                registration = await session.get(
                    RegisteredWorkspaceModel,
                    request.preparation.workspace_id,
                )
                fence = await session.get(
                    WorkspaceMutationFenceModel,
                    request.preparation.workspace_id,
                )
                if operation_model is None or preparation_model is None:
                    raise PrivilegedApplicationStoreError(
                        "restart operation or preparation disappeared"
                    )
                current = await self._operations._snapshot(session, operation_model)
                retained_preparation = self._preparation(preparation_model)
                self._validate_admission(
                    request,
                    current=current,
                    preparation=retained_preparation,
                    development_session=session_model,
                    registration=registration,
                    fence=fence,
                )
                if await session.get(PrivilegedOperationModel, current.operation_id) is not None:
                    raise PrivilegedApplicationStoreError("restart operation was already admitted")
                if (
                    await session.execute(
                        select(PolicyDecisionModel.policy_decision_id).where(
                            PolicyDecisionModel.operation_id == current.operation_id
                        )
                    )
                ).scalar_one_or_none() is not None:
                    raise PrivilegedApplicationStoreError("restart policy decision already exists")

                fence_version = request.expected_fence_version + 1
                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id
                        == request.preparation.workspace_id,
                        WorkspaceMutationFenceModel.fence_version == request.expected_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id.is_(None),
                        WorkspaceMutationFenceModel.active_contract.is_(None),
                        WorkspaceMutationFenceModel.acquired_at.is_(None),
                    )
                    .values(
                        fence_version=fence_version,
                        active_operation_id=current.operation_id,
                        active_contract=current.intent.operation_contract,
                        acquired_at=request.authorised_at,
                        updated_at=request.authorised_at,
                    )
                )
                self._require_one_row(fence_result, "restart workspace fence is busy or stale")
                reservation_generation = (
                    int(
                        (
                            await session.execute(
                                select(
                                    func.coalesce(
                                        func.max(
                                            PrivilegedEffectReservationModel.reservation_generation
                                        ),
                                        0,
                                    )
                                )
                            )
                        ).scalar_one()
                    )
                    + 1
                )
                session.add(self._policy_model(operation_model, request))
                await session.flush()
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
                self._require_one_row(operation_result, "restart authorisation CAS failed")
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
                await session.flush()
                privileged = self._operation_model(
                    request,
                    fence_version=fence_version,
                    reservation_generation=reservation_generation,
                )
                session.add(privileged)
                await session.flush()
                session.add(
                    PrivilegedEffectReservationModel(
                        operation_id=current.operation_id,
                        workspace_id=request.preparation.workspace_id,
                        workspace_fence_version=fence_version,
                        reservation_generation=reservation_generation,
                        active_slot=1,
                        state=PrivilegedReservationState.HELD.value,
                        closure_evidence_sha256=None,
                        acquired_at=request.authorised_at,
                        released_at=None,
                        updated_at=request.authorised_at,
                    )
                )
                preparation_model.state = PrivilegedPreparationState.CONSUMED.value
                preparation_model.consumed_by_operation_id = current.operation_id
                preparation_model.consumed_at = request.authorised_at
                preparation_model.updated_at = request.authorised_at
                await session.flush()
                await session.commit()
                return (
                    authorised,
                    WorkspaceFence(
                        workspace_id=request.preparation.workspace_id,
                        fence_version=fence_version,
                        active_operation_id=current.operation_id,
                        active_contract=current.intent.operation_contract,
                    ),
                    self._record(privileged, PrivilegedReservationState.HELD),
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "restart admission violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def get_restart(self, operation_id: str) -> PrivilegedRestartRecord | None:
        async with self._runtime.session_factory() as session:
            operation = await session.get(PrivilegedOperationModel, operation_id)
            if operation is None or operation.action == PrivilegedAction.PACKAGE_INSTALL.value:
                return None
            reservation = await session.get(PrivilegedEffectReservationModel, operation_id)
            if reservation is None:
                raise PrivilegedApplicationStoreError("restart reservation is missing")
            try:
                state = PrivilegedReservationState(reservation.state)
            except ValueError as exc:
                raise PrivilegedApplicationStoreError(
                    "restart reservation state is invalid"
                ) from exc
            return self._record(operation, state)

    async def mark_restart_dispatched(
        self,
        operation_id: str,
        *,
        dispatched_at: datetime,
    ) -> PrivilegedRestartRecord:
        if dispatched_at.tzinfo is None or dispatched_at.utcoffset() is None:
            raise PrivilegedApplicationStoreError("restart dispatch time is naive")
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(PrivilegedOperationModel, operation_id)
                phase4 = await session.get(OperationModel, operation_id)
                reservation = await session.get(PrivilegedEffectReservationModel, operation_id)
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError("restart dispatch evidence is incomplete")
                updated_at = _utc(operation.updated_at)
                if updated_at is None or dispatched_at < updated_at:
                    raise PrivilegedApplicationStoreError("restart dispatch time regressed")
                if (
                    operation.state != PrivilegedOperationState.PREPARED.value
                    or operation.broker_acceptance_state != BrokerAcceptanceState.UNRESOLVED.value
                    or reservation.state != PrivilegedReservationState.HELD.value
                ):
                    raise PrivilegedApplicationStoreError(
                        "restart dispatch marker conflicts with retained state"
                    )
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                running = transition(
                    phase4_snapshot,
                    TransitionRequest(
                        expected_state_version=phase4_snapshot.state_version,
                        to_state=OperationState.RUNNING,
                        effect_knowledge=EffectKnowledge.NONE,
                        reason_code="privileged_dispatch_committed",
                        occurred_at=dispatched_at,
                    ),
                )
                phase4_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == phase4_snapshot.operation_id,
                        OperationModel.state == OperationState.AUTHORISED.value,
                        OperationModel.state_version == phase4_snapshot.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(running))
                )
                self._require_one_row(
                    phase4_result,
                    "privileged dispatch Phase 4 CAS failed",
                )
                session.add(
                    OperationTransitionModel(
                        operation_id=phase4_snapshot.operation_id,
                        state_version=running.state_version,
                        from_state=phase4_snapshot.state.value,
                        to_state=running.state.value,
                        effect_knowledge=running.effect_knowledge.value,
                        terminality=running.terminality.value,
                        reason_code="privileged_dispatch_committed",
                        error_code=None,
                        recorded_at=running.updated_at,
                        runtime_build_sha256=running.intent.runtime_build_sha256,
                    )
                )
                await session.flush()
                operation.state = PrivilegedOperationState.DISPATCHED.value
                operation.updated_at = dispatched_at
                await session.flush()
                await session.commit()
                return self._record(operation, PrivilegedReservationState.HELD)
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "restart dispatch marker violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def record_broker_snapshot(
        self,
        snapshot: BrokerBindingSnapshot,
        *,
        reconciled_at: datetime,
    ) -> PrivilegedRestartRecord:
        if reconciled_at.tzinfo is None or reconciled_at.utcoffset() is None:
            raise PrivilegedApplicationStoreError("restart reconciliation time is naive")
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(
                    PrivilegedOperationModel,
                    snapshot.identity.operation_id,
                )
                phase4 = await session.get(OperationModel, snapshot.identity.operation_id)
                reservation = await session.get(
                    PrivilegedEffectReservationModel,
                    snapshot.identity.operation_id,
                )
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError(
                        "restart reconciliation evidence is incomplete"
                    )
                self._require_broker_identity(operation, phase4, snapshot)
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                updated_at = _utc(operation.updated_at)
                if updated_at is None or reconciled_at < updated_at:
                    raise PrivilegedApplicationStoreError("restart reconciliation time regressed")
                current_state = PrivilegedOperationState(operation.state)
                current_acceptance = BrokerAcceptanceState(operation.broker_acceptance_state)
                if snapshot.evidence_generation < operation.broker_evidence_generation:
                    raise PrivilegedApplicationStoreError("broker evidence generation regressed")
                if (
                    current_acceptance is not BrokerAcceptanceState.UNRESOLVED
                    and snapshot.acceptance_state is not current_acceptance
                ):
                    raise PrivilegedApplicationStoreError("broker acceptance decision changed")
                if (
                    operation.broker_acceptance_evidence_sha256 is not None
                    and snapshot.acceptance_evidence_sha256
                    != operation.broker_acceptance_evidence_sha256
                ):
                    raise PrivilegedApplicationStoreError("broker acceptance evidence changed")
                if (
                    snapshot.acceptance_state is not BrokerAcceptanceState.UNRESOLVED
                    and current_state is PrivilegedOperationState.PREPARED
                ):
                    raise PrivilegedApplicationStoreError(
                        "broker accepted before the durable dispatch marker"
                    )
                if snapshot.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                    raise PrivilegedApplicationStoreError(
                        "broker no-accept requires atomic terminal closure"
                    )

                next_state, next_reservation = self._reconciled_states(
                    current_state,
                    snapshot,
                )
                if next_reservation is not PrivilegedReservationState(reservation.state):
                    reservation.state = next_reservation.value
                    reservation.updated_at = reconciled_at
                    await session.flush()

                if (
                    next_state
                    in {
                        PrivilegedOperationState.UNCERTAIN,
                        PrivilegedOperationState.RESTRICTED_RECOVERY,
                    }
                    and phase4_snapshot.state is not OperationState.UNCERTAIN
                ):
                    uncertain = transition(
                        phase4_snapshot,
                        TransitionRequest(
                            expected_state_version=phase4_snapshot.state_version,
                            to_state=OperationState.UNCERTAIN,
                            effect_knowledge=EffectKnowledge.UNCERTAIN,
                            reason_code="privileged_broker_uncertain",
                            error=OperationError(
                                "operation_uncertain",
                                "Privileged broker effect requires retained reconciliation.",
                                "reconcile",
                            ),
                            occurred_at=reconciled_at,
                        ),
                    )
                    phase4_result = await session.execute(
                        update(OperationModel)
                        .where(
                            OperationModel.operation_id == phase4_snapshot.operation_id,
                            OperationModel.state == phase4_snapshot.state.value,
                            OperationModel.state_version == phase4_snapshot.state_version,
                        )
                        .values(**SqliteOperationStore._operation_update_values(uncertain))
                    )
                    self._require_one_row(
                        phase4_result,
                        "privileged Phase 4 uncertainty CAS failed",
                    )
                    session.add(
                        OperationTransitionModel(
                            operation_id=phase4_snapshot.operation_id,
                            state_version=uncertain.state_version,
                            from_state=phase4_snapshot.state.value,
                            to_state=uncertain.state.value,
                            effect_knowledge=uncertain.effect_knowledge.value,
                            terminality=uncertain.terminality.value,
                            reason_code="privileged_broker_uncertain",
                            error_code="operation_uncertain",
                            recorded_at=uncertain.updated_at,
                            runtime_build_sha256=(uncertain.intent.runtime_build_sha256),
                        )
                    )
                    await session.flush()

                closure_state, closure_evidence = self._broker_closure(
                    next_state,
                    snapshot,
                )
                operation.broker_acceptance_state = snapshot.acceptance_state.value
                operation.broker_evidence_generation = snapshot.evidence_generation
                operation.broker_acceptance_evidence_sha256 = snapshot.acceptance_evidence_sha256
                operation.broker_decided_at = snapshot.accepted_at or snapshot.sealed_at
                operation.broker_closure_state = closure_state
                operation.broker_closure_evidence_sha256 = closure_evidence
                operation.state = next_state.value
                operation.updated_at = reconciled_at
                operation.last_reconciled_at = reconciled_at
                await session.flush()
                await session.commit()
                return self._record(operation, next_reservation)
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "broker evidence violated restart authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def restart_recovery_pending(self) -> bool:
        async with self._runtime.session_factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(PrivilegedOperationModel)
                    .where(
                        PrivilegedOperationModel.action.in_(
                            (
                                PrivilegedAction.SERVICE_RESTART.value,
                                PrivilegedAction.CONTROLLED_RESTART.value,
                            )
                        ),
                        PrivilegedOperationModel.state != PrivilegedOperationState.TERMINAL.value,
                    )
                )
            ).scalar_one()
            return int(count) > 0

    async def close_restart_before_dispatch(
        self,
        operation_id: str,
        *,
        closed_at: datetime,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]:
        """Atomically unwind authority that never crossed the dispatch marker."""

        if closed_at.tzinfo is None or closed_at.utcoffset() is None:
            raise PrivilegedApplicationStoreError("restart pre-dispatch closure time is naive")
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(PrivilegedOperationModel, operation_id)
                phase4 = await session.get(OperationModel, operation_id)
                reservation = await session.get(
                    PrivilegedEffectReservationModel,
                    operation_id,
                )
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError(
                        "restart pre-dispatch evidence is incomplete"
                    )
                if (
                    operation.action
                    not in {
                        PrivilegedAction.SERVICE_RESTART.value,
                        PrivilegedAction.CONTROLLED_RESTART.value,
                    }
                    or operation.workspace_id is None
                    or operation.workspace_fence_version is None
                ):
                    raise PrivilegedApplicationStoreError(
                        "restart pre-dispatch workspace authority is absent"
                    )
                operation_updated_at = _utc(operation.updated_at)
                if operation_updated_at is None or closed_at < operation_updated_at:
                    raise PrivilegedApplicationStoreError(
                        "restart pre-dispatch closure time regressed"
                    )
                fence = await session.get(
                    WorkspaceMutationFenceModel,
                    operation.workspace_id,
                )
                if fence is None:
                    raise PrivilegedApplicationStoreError(
                        "restart pre-dispatch workspace fence is absent"
                    )
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                closure_evidence = canonical_sha256(
                    {
                        "closed_at": canonical_timestamp(closed_at),
                        "closure_kind": "restart_before_dispatch",
                        "operation_id": operation_id,
                        "ticket_sha256": operation.ticket_sha256,
                        "workspace_fence_version": operation.workspace_fence_version,
                        "workspace_id": operation.workspace_id,
                    }
                )
                if operation.state == PrivilegedOperationState.TERMINAL.value:
                    operation_closed_at = _utc(operation.closed_at)
                    reservation_released_at = _utc(reservation.released_at)
                    if (
                        operation.broker_acceptance_state != BrokerAcceptanceState.UNRESOLVED.value
                        or operation.broker_evidence_generation != 0
                        or operation.broker_acceptance_evidence_sha256 is not None
                        or operation.broker_decided_at is not None
                        or operation.restart_checkpoint_sha256 is not None
                        or operation.broker_closure_state != "not_required"
                        or operation.broker_closure_evidence_sha256 is not None
                        or operation.audit_closure_state != "not_required"
                        or operation.audit_closure_evidence_sha256 is not None
                        or operation.fence_closure_state != "released"
                        or operation.fence_release_evidence_sha256 != closure_evidence
                        or (
                            operation.action == PrivilegedAction.SERVICE_RESTART.value
                            and (
                                operation.candidate_outcome != "not_applicable"
                                or operation.rollback_outcome != "not_applicable"
                            )
                        )
                        or (
                            operation.action == PrivilegedAction.CONTROLLED_RESTART.value
                            and (
                                operation.candidate_outcome != "failed"
                                or operation.rollback_outcome != "not_started"
                            )
                        )
                        or operation_closed_at != closed_at
                        or phase4_snapshot.state is not OperationState.FAILED
                        or phase4_snapshot.effect_knowledge is not EffectKnowledge.KNOWN_NO_EFFECT
                        or phase4_snapshot.error is None
                        or phase4_snapshot.error.code != "reconciliation_unavailable"
                        or reservation.state != PrivilegedReservationState.RELEASED.value
                        or reservation.closure_evidence_sha256 != closure_evidence
                        or reservation_released_at != closed_at
                        or fence.fence_version != operation.workspace_fence_version + 1
                        or fence.active_operation_id is not None
                        or fence.active_contract is not None
                        or fence.acquired_at is not None
                    ):
                        raise PrivilegedApplicationStoreError(
                            "restart pre-dispatch closure conflicts with retained evidence"
                        )
                    await session.commit()
                    return (
                        phase4_snapshot,
                        WorkspaceFence(
                            workspace_id=fence.workspace_id,
                            fence_version=fence.fence_version,
                            active_operation_id=None,
                            active_contract=None,
                        ),
                        self._record(operation, PrivilegedReservationState.RELEASED),
                    )
                if (
                    operation.state != PrivilegedOperationState.PREPARED.value
                    or operation.broker_acceptance_state != BrokerAcceptanceState.UNRESOLVED.value
                    or operation.broker_evidence_generation != 0
                    or operation.broker_acceptance_evidence_sha256 is not None
                    or operation.broker_decided_at is not None
                    or operation.restart_checkpoint_sha256 is not None
                    or operation.broker_closure_state != "pending"
                    or operation.broker_closure_evidence_sha256 is not None
                    or operation.audit_closure_state != "pending"
                    or operation.audit_closure_evidence_sha256 is not None
                    or operation.fence_closure_state != "held"
                    or operation.fence_release_evidence_sha256 is not None
                    or phase4_snapshot.state is not OperationState.AUTHORISED
                    or phase4_snapshot.effect_knowledge is not EffectKnowledge.NONE
                    or reservation.state != PrivilegedReservationState.HELD.value
                    or fence.fence_version != operation.workspace_fence_version
                    or fence.active_operation_id != operation_id
                    or fence.active_contract != phase4_snapshot.intent.operation_contract
                    or fence.acquired_at is None
                ):
                    raise PrivilegedApplicationStoreError(
                        "restart pre-dispatch closure lacks exact retained authority"
                    )

                reservation.state = PrivilegedReservationState.RELEASED.value
                reservation.active_slot = None
                reservation.closure_evidence_sha256 = closure_evidence
                reservation.released_at = closed_at
                reservation.updated_at = closed_at
                await session.flush()

                failed = transition(
                    phase4_snapshot,
                    TransitionRequest(
                        expected_state_version=phase4_snapshot.state_version,
                        to_state=OperationState.FAILED,
                        effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                        reason_code="restart_before_dispatch",
                        error=OperationError(
                            "reconciliation_unavailable",
                            "Authorised operation did not reach the durable dispatch marker.",
                        ),
                        occurred_at=closed_at,
                    ),
                )
                phase4_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == phase4_snapshot.operation_id,
                        OperationModel.state == OperationState.AUTHORISED.value,
                        OperationModel.state_version == phase4_snapshot.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(failed))
                )
                self._require_one_row(
                    phase4_result,
                    "restart pre-dispatch Phase 4 CAS failed",
                )
                session.add(
                    OperationTransitionModel(
                        operation_id=phase4_snapshot.operation_id,
                        state_version=failed.state_version,
                        from_state=phase4_snapshot.state.value,
                        to_state=failed.state.value,
                        effect_knowledge=failed.effect_knowledge.value,
                        terminality=failed.terminality.value,
                        reason_code="restart_before_dispatch",
                        error_code="reconciliation_unavailable",
                        recorded_at=failed.updated_at,
                        runtime_build_sha256=failed.intent.runtime_build_sha256,
                    )
                )
                await session.flush()

                released_fence_version = operation.workspace_fence_version + 1
                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == operation.workspace_id,
                        WorkspaceMutationFenceModel.fence_version
                        == operation.workspace_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id == operation_id,
                        WorkspaceMutationFenceModel.active_contract
                        == phase4_snapshot.intent.operation_contract,
                        WorkspaceMutationFenceModel.acquired_at.is_not(None),
                    )
                    .values(
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=closed_at,
                    )
                )
                self._require_one_row(
                    fence_result,
                    "restart pre-dispatch fence release CAS failed",
                )

                if operation.action == PrivilegedAction.CONTROLLED_RESTART.value:
                    operation.candidate_outcome = "failed"
                operation.broker_closure_state = "not_required"
                operation.audit_closure_state = "not_required"
                operation.fence_closure_state = "released"
                operation.fence_release_evidence_sha256 = closure_evidence
                operation.state = PrivilegedOperationState.TERMINAL.value
                operation.closed_at = closed_at
                operation.updated_at = closed_at
                operation.last_reconciled_at = closed_at
                await session.flush()
                await session.commit()
                return (
                    failed,
                    WorkspaceFence(
                        workspace_id=operation.workspace_id,
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                    ),
                    self._record(operation, PrivilegedReservationState.RELEASED),
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "restart pre-dispatch closure violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def close_restart_no_accept(
        self,
        request: RestartNoAcceptClosureRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]:
        snapshot = request.snapshot
        operation_id = snapshot.identity.operation_id
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(PrivilegedOperationModel, operation_id)
                phase4 = await session.get(OperationModel, operation_id)
                reservation = await session.get(
                    PrivilegedEffectReservationModel,
                    operation_id,
                )
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept evidence is incomplete"
                    )
                if operation.workspace_id is None or operation.workspace_fence_version is None:
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept workspace authority is absent"
                    )
                operation_updated_at = _utc(operation.updated_at)
                if operation_updated_at is None or request.closed_at < operation_updated_at:
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept closure time regressed"
                    )
                fence = await session.get(
                    WorkspaceMutationFenceModel,
                    operation.workspace_id,
                )
                if fence is None:
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept workspace fence is absent"
                    )
                self._require_broker_identity(operation, phase4, snapshot)
                if snapshot.evidence_generation < operation.broker_evidence_generation:
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept evidence generation regressed"
                    )
                current_acceptance = BrokerAcceptanceState(operation.broker_acceptance_state)
                if current_acceptance is BrokerAcceptanceState.ACCEPTED:
                    raise PrivilegedApplicationStoreError(
                        "accepted privileged work cannot close as no-accept"
                    )
                fence_evidence = canonical_sha256(
                    {
                        "audit_closure_evidence_sha256": (request.audit_closure_evidence_sha256),
                        "broker_acceptance_evidence_sha256": (snapshot.acceptance_evidence_sha256),
                        "broker_result_evidence_sha256": snapshot.result_evidence_sha256,
                        "closed_at": canonical_timestamp(request.closed_at),
                        "operation_id": operation_id,
                        "ticket_sha256": operation.ticket_sha256,
                        "workspace_fence_version": operation.workspace_fence_version,
                        "workspace_id": operation.workspace_id,
                    }
                )
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                if operation.state == PrivilegedOperationState.TERMINAL.value:
                    if (
                        current_acceptance is not BrokerAcceptanceState.SEALED_NO_ACCEPT
                        or operation.broker_acceptance_evidence_sha256
                        != snapshot.acceptance_evidence_sha256
                        or operation.broker_closure_evidence_sha256
                        != snapshot.result_evidence_sha256
                        or operation.audit_closure_evidence_sha256
                        != request.audit_closure_evidence_sha256
                        or operation.fence_release_evidence_sha256 != fence_evidence
                        or reservation.state != PrivilegedReservationState.RELEASED.value
                    ):
                        raise PrivilegedApplicationStoreError(
                            "restart no-accept closure conflicts with retained evidence"
                        )
                    await session.commit()
                    return (
                        phase4_snapshot,
                        WorkspaceFence(
                            workspace_id=fence.workspace_id,
                            fence_version=fence.fence_version,
                            active_operation_id=fence.active_operation_id,
                            active_contract=fence.active_contract,
                        ),
                        self._record(operation, PrivilegedReservationState.RELEASED),
                    )
                if (
                    current_acceptance is not BrokerAcceptanceState.UNRESOLVED
                    or operation.state
                    not in {
                        PrivilegedOperationState.DISPATCHED.value,
                        PrivilegedOperationState.RECONCILING.value,
                        PrivilegedOperationState.UNCERTAIN.value,
                        PrivilegedOperationState.RESTRICTED_RECOVERY.value,
                    }
                    or reservation.state
                    not in {
                        PrivilegedReservationState.HELD.value,
                        PrivilegedReservationState.UNCERTAIN.value,
                        PrivilegedReservationState.RESTRICTED_RECOVERY.value,
                    }
                    or fence.fence_version != operation.workspace_fence_version
                    or fence.active_operation_id != operation_id
                    or fence.active_contract != phase4_snapshot.intent.operation_contract
                    or fence.acquired_at is None
                ):
                    raise PrivilegedApplicationStoreError(
                        "restart no-accept closure lacks exact retained authority"
                    )

                reservation.state = PrivilegedReservationState.RELEASED.value
                reservation.active_slot = None
                reservation.closure_evidence_sha256 = fence_evidence
                reservation.released_at = request.closed_at
                reservation.updated_at = request.closed_at
                await session.flush()

                failed = transition(
                    phase4_snapshot,
                    TransitionRequest(
                        expected_state_version=phase4_snapshot.state_version,
                        to_state=OperationState.FAILED,
                        effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                        reason_code="privileged_no_accept_proven",
                        error=OperationError(
                            "effect_not_started",
                            "The privileged broker proved that no root subeffect was accepted.",
                        ),
                        occurred_at=request.closed_at,
                    ),
                )
                phase4_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == phase4_snapshot.operation_id,
                        OperationModel.state == phase4_snapshot.state.value,
                        OperationModel.state_version == phase4_snapshot.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(failed))
                )
                self._require_one_row(phase4_result, "restart no-accept Phase 4 CAS failed")
                session.add(
                    OperationTransitionModel(
                        operation_id=phase4_snapshot.operation_id,
                        state_version=failed.state_version,
                        from_state=phase4_snapshot.state.value,
                        to_state=failed.state.value,
                        effect_knowledge=failed.effect_knowledge.value,
                        terminality=failed.terminality.value,
                        reason_code="privileged_no_accept_proven",
                        error_code="effect_not_started",
                        recorded_at=failed.updated_at,
                        runtime_build_sha256=failed.intent.runtime_build_sha256,
                    )
                )
                await session.flush()

                released_fence_version = operation.workspace_fence_version + 1
                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == operation.workspace_id,
                        WorkspaceMutationFenceModel.fence_version
                        == operation.workspace_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id == operation_id,
                        WorkspaceMutationFenceModel.active_contract
                        == phase4_snapshot.intent.operation_contract,
                        WorkspaceMutationFenceModel.acquired_at.is_not(None),
                    )
                    .values(
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=request.closed_at,
                    )
                )
                self._require_one_row(fence_result, "restart no-accept fence release CAS failed")

                operation.broker_acceptance_state = BrokerAcceptanceState.SEALED_NO_ACCEPT.value
                operation.broker_evidence_generation = snapshot.evidence_generation
                operation.broker_acceptance_evidence_sha256 = snapshot.acceptance_evidence_sha256
                operation.broker_decided_at = snapshot.sealed_at
                operation.broker_closure_state = "complete"
                operation.broker_closure_evidence_sha256 = snapshot.result_evidence_sha256
                operation.audit_closure_state = "complete"
                operation.audit_closure_evidence_sha256 = request.audit_closure_evidence_sha256
                operation.fence_closure_state = "released"
                operation.fence_release_evidence_sha256 = fence_evidence
                if operation.action == PrivilegedAction.CONTROLLED_RESTART.value:
                    operation.candidate_outcome = "failed"
                operation.state = PrivilegedOperationState.TERMINAL.value
                operation.closed_at = request.closed_at
                operation.updated_at = request.closed_at
                operation.last_reconciled_at = request.closed_at
                await session.flush()
                await session.commit()
                return (
                    failed,
                    WorkspaceFence(
                        workspace_id=operation.workspace_id,
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                    ),
                    self._record(operation, PrivilegedReservationState.RELEASED),
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "restart no-accept closure violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def close_service_restart_accepted(
        self,
        request: ServiceRestartAcceptedClosureRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]:
        """Atomically close accepted fixed-service, audit, reservation, and fence truth."""

        snapshot = request.snapshot
        operation_id = snapshot.identity.operation_id
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(PrivilegedOperationModel, operation_id)
                phase4 = await session.get(OperationModel, operation_id)
                reservation = await session.get(
                    PrivilegedEffectReservationModel,
                    operation_id,
                )
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart closure evidence is incomplete"
                    )
                if (
                    operation.workspace_id is None
                    or operation.workspace_fence_version is None
                    or operation.action != PrivilegedAction.SERVICE_RESTART.value
                    or operation.candidate_slot_id is not None
                    or operation.restart_checkpoint_sha256 is not None
                ):
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart closure authority is absent"
                    )
                operation_updated_at = _utc(operation.updated_at)
                if operation_updated_at is None or request.closed_at < operation_updated_at:
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart closure time regressed"
                    )
                fence = await session.get(
                    WorkspaceMutationFenceModel,
                    operation.workspace_id,
                )
                if fence is None:
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart workspace fence is absent"
                    )
                self._require_broker_identity(operation, phase4, snapshot)
                if snapshot.evidence_generation < operation.broker_evidence_generation:
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart evidence generation regressed"
                    )
                current_acceptance = BrokerAcceptanceState(operation.broker_acceptance_state)
                if current_acceptance is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                    raise PrivilegedApplicationStoreError(
                        "sealed privileged work cannot close as accepted"
                    )
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                final_state, effect_knowledge, reason_code, error = (
                    self._accepted_service_phase4_outcome(snapshot.effect_knowledge)
                )
                fence_evidence = canonical_sha256(
                    {
                        "audit_closure_evidence_sha256": (request.audit_closure_evidence_sha256),
                        "broker_acceptance_evidence_sha256": (snapshot.acceptance_evidence_sha256),
                        "broker_result_evidence_sha256": snapshot.result_evidence_sha256,
                        "closed_at": canonical_timestamp(request.closed_at),
                        "effect_knowledge": snapshot.effect_knowledge,
                        "operation_id": operation_id,
                        "service_profile_sha256": operation.service_profile_sha256,
                        "ticket_sha256": operation.ticket_sha256,
                        "workspace_fence_version": operation.workspace_fence_version,
                        "workspace_id": operation.workspace_id,
                    }
                )
                if operation.state == PrivilegedOperationState.TERMINAL.value:
                    operation_closed_at = _utc(operation.closed_at)
                    broker_decided_at = _utc(operation.broker_decided_at)
                    reservation_released_at = _utc(reservation.released_at)
                    if (
                        current_acceptance is not BrokerAcceptanceState.ACCEPTED
                        or operation.broker_evidence_generation != snapshot.evidence_generation
                        or operation.broker_acceptance_evidence_sha256
                        != snapshot.acceptance_evidence_sha256
                        or broker_decided_at != snapshot.accepted_at
                        or operation.restart_checkpoint_sha256 is not None
                        or operation.candidate_outcome != "not_applicable"
                        or operation.rollback_outcome != "not_applicable"
                        or operation.broker_closure_state != "complete"
                        or operation.broker_closure_evidence_sha256
                        != snapshot.result_evidence_sha256
                        or operation.audit_closure_state != "complete"
                        or operation.audit_closure_evidence_sha256
                        != request.audit_closure_evidence_sha256
                        or operation.fence_closure_state != "released"
                        or operation.fence_release_evidence_sha256 != fence_evidence
                        or operation_closed_at != request.closed_at
                        or phase4_snapshot.state is not final_state
                        or phase4_snapshot.effect_knowledge is not effect_knowledge
                        or reservation.state != PrivilegedReservationState.RELEASED.value
                        or reservation.closure_evidence_sha256 != fence_evidence
                        or reservation_released_at != request.closed_at
                        or fence.fence_version != operation.workspace_fence_version + 1
                        or fence.active_operation_id is not None
                        or fence.active_contract is not None
                        or fence.acquired_at is not None
                    ):
                        raise PrivilegedApplicationStoreError(
                            "accepted service restart closure conflicts with retained evidence"
                        )
                    await session.commit()
                    return (
                        phase4_snapshot,
                        WorkspaceFence(
                            workspace_id=fence.workspace_id,
                            fence_version=fence.fence_version,
                            active_operation_id=None,
                            active_contract=None,
                        ),
                        self._record(operation, PrivilegedReservationState.RELEASED),
                    )
                if (
                    current_acceptance
                    not in {
                        BrokerAcceptanceState.UNRESOLVED,
                        BrokerAcceptanceState.ACCEPTED,
                    }
                    or operation.state
                    not in {
                        PrivilegedOperationState.DISPATCHED.value,
                        PrivilegedOperationState.RECONCILING.value,
                        PrivilegedOperationState.UNCERTAIN.value,
                        PrivilegedOperationState.RESTRICTED_RECOVERY.value,
                    }
                    or reservation.state
                    not in {
                        PrivilegedReservationState.HELD.value,
                        PrivilegedReservationState.UNCERTAIN.value,
                        PrivilegedReservationState.RESTRICTED_RECOVERY.value,
                    }
                    or fence.fence_version != operation.workspace_fence_version
                    or fence.active_operation_id != operation_id
                    or fence.active_contract != phase4_snapshot.intent.operation_contract
                    or fence.acquired_at is None
                ):
                    raise PrivilegedApplicationStoreError(
                        "accepted service restart closure lacks exact retained authority"
                    )

                reservation.state = PrivilegedReservationState.RELEASED.value
                reservation.active_slot = None
                reservation.closure_evidence_sha256 = fence_evidence
                reservation.released_at = request.closed_at
                reservation.updated_at = request.closed_at
                await session.flush()

                closed = transition(
                    phase4_snapshot,
                    TransitionRequest(
                        expected_state_version=phase4_snapshot.state_version,
                        to_state=final_state,
                        effect_knowledge=effect_knowledge,
                        reason_code=reason_code,
                        error=error,
                        occurred_at=request.closed_at,
                    ),
                )
                phase4_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == phase4_snapshot.operation_id,
                        OperationModel.state == phase4_snapshot.state.value,
                        OperationModel.state_version == phase4_snapshot.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(closed))
                )
                self._require_one_row(
                    phase4_result,
                    "accepted service restart Phase 4 closure CAS failed",
                )
                session.add(
                    OperationTransitionModel(
                        operation_id=phase4_snapshot.operation_id,
                        state_version=closed.state_version,
                        from_state=phase4_snapshot.state.value,
                        to_state=closed.state.value,
                        effect_knowledge=closed.effect_knowledge.value,
                        terminality=closed.terminality.value,
                        reason_code=reason_code,
                        error_code=None if error is None else error.code,
                        recorded_at=closed.updated_at,
                        runtime_build_sha256=closed.intent.runtime_build_sha256,
                    )
                )
                await session.flush()

                released_fence_version = operation.workspace_fence_version + 1
                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == operation.workspace_id,
                        WorkspaceMutationFenceModel.fence_version
                        == operation.workspace_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id == operation_id,
                        WorkspaceMutationFenceModel.active_contract
                        == phase4_snapshot.intent.operation_contract,
                        WorkspaceMutationFenceModel.acquired_at.is_not(None),
                    )
                    .values(
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=request.closed_at,
                    )
                )
                self._require_one_row(
                    fence_result,
                    "accepted service restart fence release CAS failed",
                )

                operation.broker_acceptance_state = BrokerAcceptanceState.ACCEPTED.value
                operation.broker_evidence_generation = snapshot.evidence_generation
                operation.broker_acceptance_evidence_sha256 = snapshot.acceptance_evidence_sha256
                operation.broker_decided_at = snapshot.accepted_at
                operation.broker_closure_state = "complete"
                operation.broker_closure_evidence_sha256 = snapshot.result_evidence_sha256
                operation.audit_closure_state = "complete"
                operation.audit_closure_evidence_sha256 = request.audit_closure_evidence_sha256
                operation.fence_closure_state = "released"
                operation.fence_release_evidence_sha256 = fence_evidence
                operation.state = PrivilegedOperationState.TERMINAL.value
                operation.closed_at = request.closed_at
                operation.updated_at = request.closed_at
                operation.last_reconciled_at = request.closed_at
                await session.flush()
                await session.commit()
                return (
                    closed,
                    WorkspaceFence(
                        workspace_id=operation.workspace_id,
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                    ),
                    self._record(operation, PrivilegedReservationState.RELEASED),
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "accepted service restart closure violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    async def close_restart_accepted(
        self,
        request: RestartAcceptedClosureRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]:
        """Atomically close accepted broker, Phase 4, reservation, and fence truth."""

        snapshot = request.snapshot
        operation_id = snapshot.identity.operation_id
        outcome = snapshot.restart_outcome
        if outcome is None or snapshot.restart_checkpoint_sha256 is None:
            raise PrivilegedApplicationStoreError("accepted restart checkpoint is absent")
        async with self._runtime.session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                operation = await session.get(PrivilegedOperationModel, operation_id)
                phase4 = await session.get(OperationModel, operation_id)
                reservation = await session.get(
                    PrivilegedEffectReservationModel,
                    operation_id,
                )
                if operation is None or phase4 is None or reservation is None:
                    raise PrivilegedApplicationStoreError(
                        "accepted restart closure evidence is incomplete"
                    )
                if (
                    operation.workspace_id is None
                    or operation.workspace_fence_version is None
                    or operation.action != PrivilegedAction.CONTROLLED_RESTART.value
                    or operation.lkg_slot_id is None
                    or operation.candidate_slot_id != snapshot.candidate_slot_id
                    or operation.lkg_slot_id != snapshot.lkg_slot_id
                ):
                    raise PrivilegedApplicationStoreError(
                        "accepted restart closure authority is absent"
                    )
                operation_updated_at = _utc(operation.updated_at)
                if operation_updated_at is None or request.closed_at < operation_updated_at:
                    raise PrivilegedApplicationStoreError("accepted restart closure time regressed")
                fence = await session.get(
                    WorkspaceMutationFenceModel,
                    operation.workspace_id,
                )
                if fence is None:
                    raise PrivilegedApplicationStoreError(
                        "accepted restart workspace fence is absent"
                    )
                self._require_broker_identity(operation, phase4, snapshot)
                if snapshot.evidence_generation < operation.broker_evidence_generation:
                    raise PrivilegedApplicationStoreError(
                        "accepted restart evidence generation regressed"
                    )
                current_acceptance = BrokerAcceptanceState(operation.broker_acceptance_state)
                if current_acceptance is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                    raise PrivilegedApplicationStoreError(
                        "sealed privileged work cannot close as accepted"
                    )
                phase4_snapshot = await self._operations._snapshot(session, phase4)
                final_state, effect_knowledge, reason_code, error = self._accepted_phase4_outcome(
                    outcome
                )
                fence_evidence = canonical_sha256(
                    {
                        "audit_closure_evidence_sha256": (request.audit_closure_evidence_sha256),
                        "broker_acceptance_evidence_sha256": (snapshot.acceptance_evidence_sha256),
                        "broker_result_evidence_sha256": snapshot.result_evidence_sha256,
                        "closed_at": canonical_timestamp(request.closed_at),
                        "lkg_promotion_evidence_sha256": (snapshot.lkg_promotion_evidence_sha256),
                        "operation_id": operation_id,
                        "restart_checkpoint_sha256": snapshot.restart_checkpoint_sha256,
                        "restart_outcome": outcome,
                        "ticket_sha256": operation.ticket_sha256,
                        "workspace_fence_version": operation.workspace_fence_version,
                        "workspace_id": operation.workspace_id,
                    }
                )
                if operation.state == PrivilegedOperationState.TERMINAL.value:
                    if (
                        current_acceptance is not BrokerAcceptanceState.ACCEPTED
                        or operation.broker_acceptance_evidence_sha256
                        != snapshot.acceptance_evidence_sha256
                        or operation.restart_checkpoint_sha256 != snapshot.restart_checkpoint_sha256
                        or operation.broker_closure_evidence_sha256
                        != snapshot.result_evidence_sha256
                        or operation.audit_closure_evidence_sha256
                        != request.audit_closure_evidence_sha256
                        or operation.fence_release_evidence_sha256 != fence_evidence
                        or phase4_snapshot.state is not final_state
                        or phase4_snapshot.effect_knowledge is not effect_knowledge
                        or reservation.state != PrivilegedReservationState.RELEASED.value
                    ):
                        raise PrivilegedApplicationStoreError(
                            "accepted restart closure conflicts with retained evidence"
                        )
                    await session.commit()
                    return (
                        phase4_snapshot,
                        WorkspaceFence(
                            workspace_id=fence.workspace_id,
                            fence_version=fence.fence_version,
                            active_operation_id=fence.active_operation_id,
                            active_contract=fence.active_contract,
                        ),
                        self._record(operation, PrivilegedReservationState.RELEASED),
                    )
                if (
                    current_acceptance
                    not in {
                        BrokerAcceptanceState.UNRESOLVED,
                        BrokerAcceptanceState.ACCEPTED,
                    }
                    or operation.state
                    not in {
                        PrivilegedOperationState.DISPATCHED.value,
                        PrivilegedOperationState.RECONCILING.value,
                        PrivilegedOperationState.UNCERTAIN.value,
                        PrivilegedOperationState.RESTRICTED_RECOVERY.value,
                    }
                    or reservation.state
                    not in {
                        PrivilegedReservationState.HELD.value,
                        PrivilegedReservationState.UNCERTAIN.value,
                        PrivilegedReservationState.RESTRICTED_RECOVERY.value,
                    }
                    or fence.fence_version != operation.workspace_fence_version
                    or fence.active_operation_id != operation_id
                    or fence.active_contract != phase4_snapshot.intent.operation_contract
                    or fence.acquired_at is None
                ):
                    raise PrivilegedApplicationStoreError(
                        "accepted restart closure lacks exact retained authority"
                    )

                reservation.state = PrivilegedReservationState.RELEASED.value
                reservation.active_slot = None
                reservation.closure_evidence_sha256 = fence_evidence
                reservation.released_at = request.closed_at
                reservation.updated_at = request.closed_at
                await session.flush()

                closed = transition(
                    phase4_snapshot,
                    TransitionRequest(
                        expected_state_version=phase4_snapshot.state_version,
                        to_state=final_state,
                        effect_knowledge=effect_knowledge,
                        reason_code=reason_code,
                        error=error,
                        occurred_at=request.closed_at,
                    ),
                )
                phase4_result = await session.execute(
                    update(OperationModel)
                    .where(
                        OperationModel.operation_id == phase4_snapshot.operation_id,
                        OperationModel.state == phase4_snapshot.state.value,
                        OperationModel.state_version == phase4_snapshot.state_version,
                    )
                    .values(**SqliteOperationStore._operation_update_values(closed))
                )
                self._require_one_row(
                    phase4_result,
                    "accepted restart Phase 4 closure CAS failed",
                )
                session.add(
                    OperationTransitionModel(
                        operation_id=phase4_snapshot.operation_id,
                        state_version=closed.state_version,
                        from_state=phase4_snapshot.state.value,
                        to_state=closed.state.value,
                        effect_knowledge=closed.effect_knowledge.value,
                        terminality=closed.terminality.value,
                        reason_code=reason_code,
                        error_code=None if error is None else error.code,
                        recorded_at=closed.updated_at,
                        runtime_build_sha256=closed.intent.runtime_build_sha256,
                    )
                )
                await session.flush()

                released_fence_version = operation.workspace_fence_version + 1
                fence_result = await session.execute(
                    update(WorkspaceMutationFenceModel)
                    .where(
                        WorkspaceMutationFenceModel.workspace_id == operation.workspace_id,
                        WorkspaceMutationFenceModel.fence_version
                        == operation.workspace_fence_version,
                        WorkspaceMutationFenceModel.active_operation_id == operation_id,
                        WorkspaceMutationFenceModel.active_contract
                        == phase4_snapshot.intent.operation_contract,
                        WorkspaceMutationFenceModel.acquired_at.is_not(None),
                    )
                    .values(
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                        acquired_at=None,
                        updated_at=request.closed_at,
                    )
                )
                self._require_one_row(
                    fence_result,
                    "accepted restart fence release CAS failed",
                )

                candidate_outcome, rollback_outcome = self._application_restart_outcomes(
                    outcome,
                    selected_slot_id=snapshot.selected_runtime_slot_id,
                    lkg_slot_id=operation.lkg_slot_id,
                )
                operation.broker_acceptance_state = BrokerAcceptanceState.ACCEPTED.value
                operation.broker_evidence_generation = snapshot.evidence_generation
                operation.broker_acceptance_evidence_sha256 = snapshot.acceptance_evidence_sha256
                operation.broker_decided_at = snapshot.accepted_at
                operation.restart_checkpoint_sha256 = snapshot.restart_checkpoint_sha256
                operation.candidate_outcome = candidate_outcome
                operation.rollback_outcome = rollback_outcome
                operation.broker_closure_state = "complete"
                operation.broker_closure_evidence_sha256 = snapshot.result_evidence_sha256
                operation.audit_closure_state = "complete"
                operation.audit_closure_evidence_sha256 = request.audit_closure_evidence_sha256
                operation.fence_closure_state = "released"
                operation.fence_release_evidence_sha256 = fence_evidence
                operation.state = PrivilegedOperationState.TERMINAL.value
                operation.closed_at = request.closed_at
                operation.updated_at = request.closed_at
                operation.last_reconciled_at = request.closed_at
                await session.flush()
                await session.commit()
                return (
                    closed,
                    WorkspaceFence(
                        workspace_id=operation.workspace_id,
                        fence_version=released_fence_version,
                        active_operation_id=None,
                        active_contract=None,
                    ),
                    self._record(operation, PrivilegedReservationState.RELEASED),
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PrivilegedApplicationStoreError(
                    "accepted restart closure violated durable authority"
                ) from exc
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    def _validate_admission(
        request: RestartAuthorisationRequest,
        *,
        current: OperationSnapshot,
        preparation: PrivilegedRestartPreparation,
        development_session: DevelopmentSessionModel | None,
        registration: RegisteredWorkspaceModel | None,
        fence: WorkspaceMutationFenceModel | None,
    ) -> None:
        if current != request.operation or preparation != request.preparation:
            raise PrivilegedApplicationStoreError("restart admission uses stale evidence")
        if development_session is None or registration is None or fence is None:
            raise PrivilegedApplicationStoreError("restart workspace authority is incomplete")
        if (
            development_session.state != DevelopmentSessionState.ACTIVE.value
            or development_session.activation_closure != ActivationClosure.COMPLETE.value
            or development_session.workspace_id != preparation.workspace_id
            or development_session.controller_id != current.owner.controller_id
            or development_session.controller_epoch != current.owner.controller_epoch
            or development_session.device_id != current.intent.device_id
            or development_session.device_epoch != current.intent.device_epoch
            or development_session.workspace_profile_sha256 != registration.profile_sha256
            or development_session.workspace_root_identity_sha256
            != registration.root_identity_sha256
            or development_session.workspace_mount_identity_sha256
            != registration.mount_identity_sha256
            or development_session.policy_version != request.decision.policy_version
            or fence.fence_version != request.expected_fence_version
        ):
            raise PrivilegedApplicationStoreError(
                "restart session, registration, or fence is not exact"
            )
        if (
            fence.active_operation_id is not None
            or fence.active_contract is not None
            or fence.acquired_at is not None
        ):
            raise PrivilegedApplicationStoreError("restart workspace fence is busy")

    @staticmethod
    def _require_broker_identity(
        operation: PrivilegedOperationModel,
        phase4: OperationModel,
        snapshot: BrokerBindingSnapshot,
    ) -> None:
        identity = snapshot.identity
        issued_at = _utc(operation.ticket_issued_at)
        expires_at = _utc(operation.ticket_expires_at)
        if (
            identity.operation_id != operation.operation_id
            or identity.ticket_id != operation.ticket_id
            or identity.ticket_sha256 != operation.ticket_sha256
            or identity.ticket_nonce_sha256 != operation.ticket_nonce_sha256
            or identity.action.value != operation.action
            or identity.target_profile_id != operation.target_profile_id
            or identity.target_profile_sha256 != operation.target_profile_sha256
            or identity.broker_profile_sha256 != operation.broker_profile_sha256
            or identity.request_fingerprint_sha256 != phase4.request_fingerprint_sha256
            or identity.current_state_binding_sha256 != operation.current_state_binding_sha256
            or identity.policy_evidence_sha256 != operation.policy_evidence_sha256
            or identity.issued_at != issued_at
            or identity.expires_at != expires_at
        ):
            raise PrivilegedApplicationStoreError(
                "broker snapshot differs from the retained ticket"
            )

    @staticmethod
    def _reconciled_states(
        current: PrivilegedOperationState,
        snapshot: BrokerBindingSnapshot,
    ) -> tuple[PrivilegedOperationState, PrivilegedReservationState]:
        if current is PrivilegedOperationState.TERMINAL:
            return current, PrivilegedReservationState.RELEASED
        if current is PrivilegedOperationState.RESTRICTED_RECOVERY:
            return current, PrivilegedReservationState.RESTRICTED_RECOVERY
        if current is PrivilegedOperationState.UNCERTAIN:
            if snapshot.execution_state is BrokerExecutionState.RESTRICTED_RECOVERY:
                return (
                    PrivilegedOperationState.RESTRICTED_RECOVERY,
                    PrivilegedReservationState.RESTRICTED_RECOVERY,
                )
            return current, PrivilegedReservationState.UNCERTAIN
        if snapshot.execution_state is BrokerExecutionState.UNCERTAIN:
            return PrivilegedOperationState.UNCERTAIN, PrivilegedReservationState.UNCERTAIN
        if snapshot.execution_state is BrokerExecutionState.RESTRICTED_RECOVERY:
            return (
                PrivilegedOperationState.RESTRICTED_RECOVERY,
                PrivilegedReservationState.RESTRICTED_RECOVERY,
            )
        if snapshot.acceptance_state is BrokerAcceptanceState.UNRESOLVED:
            return current, PrivilegedReservationState.HELD
        if current is PrivilegedOperationState.DISPATCHED:
            return PrivilegedOperationState.RECONCILING, PrivilegedReservationState.HELD
        return current, PrivilegedReservationState.HELD

    @staticmethod
    def _broker_closure(
        state: PrivilegedOperationState,
        snapshot: BrokerBindingSnapshot,
    ) -> tuple[str, str | None]:
        if state is PrivilegedOperationState.UNCERTAIN:
            return "uncertain", snapshot.result_evidence_sha256
        if state is PrivilegedOperationState.RESTRICTED_RECOVERY:
            return "restricted_recovery", snapshot.result_evidence_sha256
        if snapshot.execution_state is BrokerExecutionState.TERMINAL:
            return "complete", snapshot.result_evidence_sha256
        if snapshot.effect_knowledge is PrivilegedEffectKnowledge.UNCERTAIN:
            raise PrivilegedApplicationStoreError(
                "open broker execution reports contradictory uncertainty"
            )
        return "pending", None

    @staticmethod
    def _accepted_service_phase4_outcome(
        effect_knowledge: PrivilegedEffectKnowledge,
    ) -> tuple[OperationState, EffectKnowledge, str, OperationError | None]:
        if effect_knowledge is PrivilegedEffectKnowledge.KNOWN_EFFECT:
            return (
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_service_ready",
                None,
            )
        if effect_knowledge is PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT:
            return (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_NO_EFFECT,
                "privileged_effect_not_started",
                OperationError(
                    "effect_not_started",
                    "The broker accepted the service restart but proved no root subeffect started.",
                ),
            )
        raise PrivilegedApplicationStoreError(
            "accepted service restart lacks terminal effect truth"
        )

    @staticmethod
    def _accepted_phase4_outcome(
        outcome: BrokerRestartOutcome,
    ) -> tuple[OperationState, EffectKnowledge, str, OperationError | None]:
        if outcome is BrokerRestartOutcome.CANDIDATE_READY:
            return (
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_candidate_ready",
                None,
            )
        if outcome is BrokerRestartOutcome.ROLLBACK_READY:
            return (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_restart_rolled_back",
                OperationError(
                    "restart_rolled_back",
                    "The candidate failed verification and the exact LKG runtime was restored.",
                ),
            )
        if outcome is BrokerRestartOutcome.NO_SUBEFFECT:
            return (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_NO_EFFECT,
                "privileged_effect_not_started",
                OperationError(
                    "effect_not_started",
                    "The broker accepted the request but proved no root subeffect started.",
                ),
            )
        if outcome is BrokerRestartOutcome.FAILED:
            return (
                OperationState.FAILED,
                EffectKnowledge.KNOWN_EFFECT,
                "privileged_restart_failed",
                OperationError(
                    "restart_failed",
                    "The controlled restart reached a known terminal failure.",
                    "inspect",
                ),
            )
        raise PrivilegedApplicationStoreError("accepted restart outcome is not terminally closable")

    @staticmethod
    def _application_restart_outcomes(
        outcome: BrokerRestartOutcome,
        *,
        selected_slot_id: str | None,
        lkg_slot_id: str,
    ) -> tuple[str, str]:
        if outcome is BrokerRestartOutcome.CANDIDATE_READY:
            return "ready", "not_started"
        if outcome is BrokerRestartOutcome.ROLLBACK_READY:
            return "failed", "ready"
        if outcome is BrokerRestartOutcome.NO_SUBEFFECT:
            return "failed", "not_started"
        if outcome is BrokerRestartOutcome.FAILED:
            return (
                "failed",
                "failed" if selected_slot_id == lkg_slot_id else "not_started",
            )
        raise PrivilegedApplicationStoreError("accepted restart outcome is not terminally closable")

    @staticmethod
    def _policy_model(
        operation: OperationModel,
        request: RestartAuthorisationRequest,
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
            normalized_target_digest=request.preparation.target_profile_sha256,
            input_facts_sha256=decision.input_facts_sha256,
            reason_codes_json=json.dumps(
                decision.reason_codes,
                separators=(",", ":"),
                sort_keys=True,
            ),
            decided_at=decision.decided_at,
            runtime_policy_sha256=decision.runtime_policy_sha256,
        )

    @staticmethod
    def _operation_model(
        request: RestartAuthorisationRequest,
        *,
        fence_version: int,
        reservation_generation: int,
    ) -> PrivilegedOperationModel:
        preparation = request.preparation
        ticket = request.ticket
        return PrivilegedOperationModel(
            operation_id=request.operation.operation_id,
            prepare_operation_id=preparation.prepare_operation_id,
            session_id=preparation.session_id,
            workspace_id=preparation.workspace_id,
            workspace_fence_version=fence_version,
            reservation_generation=reservation_generation,
            action=preparation.action.value,
            maximum_effect=preparation.maximum_effect.value,
            target_profile_id=preparation.target_profile_id,
            target_profile_sha256=preparation.target_profile_sha256,
            broker_profile_id=ticket.broker_profile_id,
            broker_profile_sha256=ticket.broker_profile_sha256,
            prepared_evidence_sha256=preparation.prepared_evidence_sha256,
            current_state_binding_sha256=preparation.current_state_binding_sha256,
            policy_decision_id=request.decision.policy_decision_id,
            policy_evidence_sha256=request.decision.runtime_policy_sha256,
            ticket_id=ticket.ticket_id,
            ticket_sha256=ticket.ticket_sha256,
            ticket_nonce_sha256=preparation.execution_nonce_sha256,
            ticket_issued_at=ticket.issued_at,
            ticket_expires_at=ticket.expires_at,
            broker_acceptance_state=BrokerAcceptanceState.UNRESOLVED.value,
            broker_evidence_generation=0,
            broker_acceptance_evidence_sha256=None,
            package_transaction_plan_sha256=None,
            service_profile_sha256=preparation.service_profile_sha256,
            candidate_verification_reference=preparation.candidate_verification_reference,
            candidate_verification_sha256=preparation.candidate_verification_sha256,
            candidate_slot_id=preparation.candidate_slot_id,
            lkg_slot_id=preparation.lkg_slot_id,
            restart_checkpoint_sha256=None,
            schema_heads_sha256=preparation.schema_heads_sha256,
            runtime_layout_sha256=preparation.runtime_layout_sha256,
            deployed_peer_set_sha256=preparation.deployed_peer_set_sha256,
            candidate_outcome=(
                "pending"
                if preparation.action is PrivilegedAction.CONTROLLED_RESTART
                else "not_applicable"
            ),
            rollback_outcome=(
                "not_started"
                if preparation.action is PrivilegedAction.CONTROLLED_RESTART
                else "not_applicable"
            ),
            broker_closure_state="pending",
            broker_closure_evidence_sha256=None,
            audit_closure_state="pending",
            audit_closure_evidence_sha256=None,
            fence_closure_state="held",
            fence_release_evidence_sha256=None,
            state=PrivilegedOperationState.PREPARED.value,
            created_at=request.authorised_at,
            broker_decided_at=None,
            closed_at=None,
            updated_at=request.authorised_at,
            last_reconciled_at=None,
        )

    @staticmethod
    def _preparation_model(
        value: PrivilegedRestartPreparation,
    ) -> PrivilegedPreparationModel:
        return PrivilegedPreparationModel(
            prepare_operation_id=value.prepare_operation_id,
            session_id=value.session_id,
            workspace_id=value.workspace_id,
            action=value.action.value,
            target_profile_id=value.target_profile_id,
            target_profile_sha256=value.target_profile_sha256,
            maximum_effect=value.maximum_effect.value,
            normalized_request_sha256=value.normalized_request_sha256,
            current_state_binding_sha256=value.current_state_binding_sha256,
            prepared_evidence_sha256=value.prepared_evidence_sha256,
            execution_nonce_sha256=value.execution_nonce_sha256,
            package_transaction_plan_sha256=None,
            service_profile_sha256=value.service_profile_sha256,
            candidate_verification_reference=value.candidate_verification_reference,
            candidate_verification_sha256=value.candidate_verification_sha256,
            candidate_slot_id=value.candidate_slot_id,
            lkg_slot_id=value.lkg_slot_id,
            schema_heads_sha256=value.schema_heads_sha256,
            runtime_layout_sha256=value.runtime_layout_sha256,
            deployed_peer_set_sha256=value.deployed_peer_set_sha256,
            state=value.state.value,
            consumed_by_operation_id=value.consumed_by_operation_id,
            created_at=value.created_at,
            expires_at=value.expires_at,
            consumed_at=value.consumed_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _preparation(model: PrivilegedPreparationModel) -> PrivilegedRestartPreparation:
        timestamps = (
            _utc(model.created_at),
            _utc(model.expires_at),
            _utc(model.consumed_at),
            _utc(model.updated_at),
        )
        if timestamps[0] is None or timestamps[1] is None or timestamps[3] is None:
            raise PrivilegedApplicationStoreError("restart preparation timestamps are absent")
        return PrivilegedRestartPreparation(
            prepare_operation_id=model.prepare_operation_id,
            session_id=model.session_id or "",
            workspace_id=model.workspace_id or "",
            action=PrivilegedAction(model.action),
            target_profile_id=model.target_profile_id,
            target_profile_sha256=model.target_profile_sha256,
            maximum_effect=PrivilegedMaximumEffect(model.maximum_effect),
            normalized_request_sha256=model.normalized_request_sha256,
            current_state_binding_sha256=model.current_state_binding_sha256,
            prepared_evidence_sha256=model.prepared_evidence_sha256,
            execution_nonce_sha256=model.execution_nonce_sha256,
            service_profile_sha256=model.service_profile_sha256 or "",
            candidate_verification_reference=model.candidate_verification_reference or "",
            candidate_verification_sha256=model.candidate_verification_sha256 or "",
            candidate_slot_id=model.candidate_slot_id,
            lkg_slot_id=model.lkg_slot_id or "",
            schema_heads_sha256=model.schema_heads_sha256 or "",
            runtime_layout_sha256=model.runtime_layout_sha256 or "",
            deployed_peer_set_sha256=model.deployed_peer_set_sha256 or "",
            state=PrivilegedPreparationState(model.state),
            consumed_by_operation_id=model.consumed_by_operation_id,
            created_at=timestamps[0],
            expires_at=timestamps[1],
            consumed_at=timestamps[2],
            updated_at=timestamps[3],
        )

    @staticmethod
    def _record(
        model: PrivilegedOperationModel,
        reservation_state: PrivilegedReservationState,
    ) -> PrivilegedRestartRecord:
        issued_at = _utc(model.ticket_issued_at)
        expires_at = _utc(model.ticket_expires_at)
        created_at = _utc(model.created_at)
        updated_at = _utc(model.updated_at)
        if None in {issued_at, expires_at, created_at, updated_at}:
            raise PrivilegedApplicationStoreError("restart operation timestamps are absent")
        assert issued_at is not None
        assert expires_at is not None
        assert created_at is not None
        assert updated_at is not None
        return PrivilegedRestartRecord(
            operation_id=model.operation_id,
            prepare_operation_id=model.prepare_operation_id,
            session_id=model.session_id or "",
            workspace_id=model.workspace_id or "",
            workspace_fence_version=model.workspace_fence_version or 0,
            reservation_generation=model.reservation_generation,
            action=PrivilegedAction(model.action),
            maximum_effect=PrivilegedMaximumEffect(model.maximum_effect),
            target_profile_id=model.target_profile_id,
            target_profile_sha256=model.target_profile_sha256,
            broker_profile_id=model.broker_profile_id,
            broker_profile_sha256=model.broker_profile_sha256,
            prepared_evidence_sha256=model.prepared_evidence_sha256,
            current_state_binding_sha256=model.current_state_binding_sha256,
            policy_decision_id=model.policy_decision_id,
            policy_evidence_sha256=model.policy_evidence_sha256,
            ticket_id=model.ticket_id,
            ticket_sha256=model.ticket_sha256,
            ticket_nonce_sha256=model.ticket_nonce_sha256,
            ticket_issued_at=issued_at,
            ticket_expires_at=expires_at,
            broker_acceptance_state=BrokerAcceptanceState(model.broker_acceptance_state),
            broker_evidence_generation=model.broker_evidence_generation,
            broker_acceptance_evidence_sha256=model.broker_acceptance_evidence_sha256,
            service_profile_sha256=model.service_profile_sha256 or "",
            candidate_verification_reference=model.candidate_verification_reference or "",
            candidate_verification_sha256=model.candidate_verification_sha256 or "",
            candidate_slot_id=model.candidate_slot_id,
            lkg_slot_id=model.lkg_slot_id or "",
            schema_heads_sha256=model.schema_heads_sha256 or "",
            runtime_layout_sha256=model.runtime_layout_sha256 or "",
            deployed_peer_set_sha256=model.deployed_peer_set_sha256 or "",
            state=PrivilegedOperationState(model.state),
            reservation_state=reservation_state,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _require_one_row(result: object, message: str) -> None:
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise PrivilegedApplicationStoreError(message)


__all__ = [
    "PrivilegedApplicationStoreError",
    "SqlitePrivilegedApplicationRepository",
]

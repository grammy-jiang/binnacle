"""Atomic application-side Phase 9 restart admission persistence."""

from __future__ import annotations

import json

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
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    transition,
)
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    PrivilegedAction,
    PrivilegedMaximumEffect,
)
from binnacle.domain.privileged_restart import (
    PrivilegedOperationState,
    PrivilegedPreparationState,
    PrivilegedReservationState,
    PrivilegedRestartPreparation,
    PrivilegedRestartRecord,
    RestartAuthorisationRequest,
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

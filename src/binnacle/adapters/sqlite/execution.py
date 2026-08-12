"""Application-owned Phase 7 command correlation and cancel-delivery repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import CommandCancelRequestModel, CommandOperationModel
from binnacle.adapters.sqlite.operation_store import _utc
from binnacle.domain.execution import (
    CancelDisposition,
    CommandAcceptanceState,
    CommandClosureState,
    CommandExecutionSnapshot,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorEvidenceState,
    ExecutorSnapshot,
    TicketRoutingIdentity,
    require_executor_transition,
    ticket_correlation_sha256,
)


class CommandExecutionStoreError(RuntimeError):
    """Authoritative command correlation is missing, stale, or contradictory."""


class SqliteCommandExecutionRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime

    async def create(
        self,
        ticket: ExecutionTicket,
        *,
        created_at: datetime,
    ) -> CommandExecutionSnapshot:
        async with self._runtime.session_factory() as session:
            existing = await session.get(CommandOperationModel, ticket.operation_id)
            if existing is not None:
                retained = self._snapshot(existing)
                self._require_ticket(retained, ticket)
                return retained
            model = CommandOperationModel(
                operation_id=ticket.operation_id,
                session_id=ticket.development_session_id,
                workspace_id=ticket.workspace_id,
                controller_epoch=ticket.controller_epoch,
                device_epoch=ticket.device_epoch,
                development_session_state_version=ticket.development_session_state_version,
                development_session_closure_sha256=(ticket.development_session_closure_sha256),
                ticket_id=ticket.ticket_id,
                ticket_sha256=ticket.ticket_sha256,
                single_use_nonce_sha256=ticket.routing_identity.nonce_sha256,
                ticket_issued_at=ticket.issued_at,
                ticket_expires_at=ticket.expires_at,
                ticket_boot_id_digest=ticket.boot_id_digest,
                ticket_monotonic_deadline_ns=ticket.monotonic_deadline_ns,
                admission_record_id=ticket.admission_record_id,
                command_profile_id=ticket.command_profile_id,
                workspace_profile_sha256=ticket.workspace_profile_sha256,
                workspace_root_identity_sha256=ticket.workspace_root_identity_sha256,
                workspace_mount_identity_sha256=ticket.workspace_mount_identity_sha256,
                workspace_fence_version=ticket.workspace_fence_version,
                executable_identity_sha256=ticket.executable_identity_sha256,
                argv_sha256=ticket.argv_sha256,
                cwd_sha256=ticket.cwd_sha256,
                environment_sha256=ticket.environment_sha256,
                stdin_sha256=ticket.stdin_sha256,
                stdin_reference_sha256=ticket.stdin_reference_sha256,
                workspace_script_sha256=ticket.workspace_script_sha256,
                mount_plan_sha256=ticket.mount_plan_sha256,
                policy_sha256=ticket.policy_sha256,
                resource_plan_sha256=ticket.resource_plan_sha256,
                sandbox_plan_sha256=ticket.sandbox_plan_sha256,
                process_isolation_plan_sha256=ticket.process_isolation_plan_sha256,
                network_plan_sha256=ticket.network_plan_sha256,
                record_version=1,
                acceptance_state=CommandAcceptanceState.UNRESOLVED.value,
                execution_id=None,
                executor_reference=None,
                accepted_receipt_sha256=None,
                no_accept_reference=None,
                no_accept_receipt_sha256=None,
                phase7_cancel_generation=0,
                supervisor_ack_cancel_generation=0,
                supervisor_cancel_disposition=None,
                supervisor_evidence_generation=0,
                supervisor_cancel_evidence_sha256=None,
                last_executor_state=None,
                terminal_evidence_sha256=None,
                descendants_stopped=False,
                output_finalized=False,
                private_resources_cleaned=False,
                cleanup_evidence_sha256=None,
                closure_state=CommandClosureState.PENDING.value,
                created_at=created_at,
                updated_at=created_at,
                last_reconciled_at=None,
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise CommandExecutionStoreError(
                    "command ticket conflicts with retained authority"
                ) from exc
            return self._snapshot(model)

    async def get(self, operation_id: str) -> CommandExecutionSnapshot | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(CommandOperationModel, operation_id)
            return None if model is None else self._snapshot(model)

    async def record_start_receipt(
        self,
        operation_id: str,
        *,
        receipt: ExecutionStartReceipt,
        recorded_at: datetime,
    ) -> CommandExecutionSnapshot:
        current = await self._required(operation_id)
        if current.acceptance_state is not CommandAcceptanceState.UNRESOLVED:
            _require_start_receipt_matches(current, receipt)
            return current
        accepted = receipt.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
        values: dict[str, object] = {
            "record_version": CommandOperationModel.record_version + 1,
            "acceptance_state": receipt.disposition.value,
            "execution_id": receipt.execution_id,
            "executor_reference": receipt.executor_reference,
            "accepted_receipt_sha256": receipt.receipt_sha256 if accepted else None,
            "no_accept_reference": receipt.no_accept_reference,
            "no_accept_receipt_sha256": None if accepted else receipt.receipt_sha256,
            "supervisor_evidence_generation": case(
                (
                    CommandOperationModel.supervisor_evidence_generation
                    < receipt.evidence_generation,
                    receipt.evidence_generation,
                ),
                else_=CommandOperationModel.supervisor_evidence_generation,
            ),
            "updated_at": recorded_at,
            "last_reconciled_at": recorded_at,
        }
        if not accepted:
            values.update(
                terminal_evidence_sha256=receipt.receipt_sha256,
                descendants_stopped=True,
                output_finalized=True,
                private_resources_cleaned=True,
                cleanup_evidence_sha256=receipt.receipt_sha256,
                closure_state=case(
                    (
                        CommandOperationModel.phase7_cancel_generation
                        == CommandOperationModel.supervisor_ack_cancel_generation,
                        CommandClosureState.COMPLETE.value,
                    ),
                    else_=CommandClosureState.PENDING.value,
                ),
            )
        async with self._runtime.session_factory() as session:
            try:
                result = await session.execute(
                    update(CommandOperationModel)
                    .where(
                        CommandOperationModel.operation_id == operation_id,
                        CommandOperationModel.acceptance_state
                        == CommandAcceptanceState.UNRESOLVED.value,
                    )
                    .values(**values)
                )
                if not isinstance(result, CursorResult) or result.rowcount not in {0, 1}:
                    raise CommandExecutionStoreError("command start receipt merge failed")
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise CommandExecutionStoreError("command start receipt merge failed") from exc
        merged = await self._required(operation_id)
        _require_start_receipt_matches(merged, receipt)
        return merged

    async def request_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        cancel_operation_id: str,
        request_fingerprint_sha256: str,
        requested_at: datetime,
    ) -> CommandExecutionSnapshot:
        async with self._runtime.session_factory() as session:
            existing = await session.get(CommandCancelRequestModel, cancel_operation_id)
            if existing is not None:
                if (
                    existing.command_operation_id != operation_id
                    or existing.request_fingerprint_sha256 != request_fingerprint_sha256
                ):
                    raise ExecutionConflictError("cancel idempotency identity conflicts")
                model = await session.get(CommandOperationModel, operation_id)
                if model is None:
                    raise CommandExecutionStoreError("command operation is missing")
                return self._snapshot(model)
            model = await session.get(CommandOperationModel, operation_id)
            if model is None or model.record_version != expected_record_version:
                raise CommandExecutionStoreError("command cancel request is stale")
            generation = model.phase7_cancel_generation + 1
            result = await session.execute(
                update(CommandOperationModel)
                .where(
                    CommandOperationModel.operation_id == operation_id,
                    CommandOperationModel.record_version == expected_record_version,
                )
                .values(
                    record_version=expected_record_version + 1,
                    phase7_cancel_generation=generation,
                    updated_at=requested_at,
                )
            )
            self._require_one(result, "command cancel request CAS failed")
            session.add(
                CommandCancelRequestModel(
                    cancel_operation_id=cancel_operation_id,
                    command_operation_id=operation_id,
                    cancel_generation=generation,
                    request_fingerprint_sha256=request_fingerprint_sha256,
                    created_at=requested_at,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise CommandExecutionStoreError("command cancel generation conflicts") from exc
        return await self._required(operation_id)

    async def acknowledge_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        receipt: ExecutorCancelReceipt,
        snapshot: ExecutorSnapshot | None,
        reconciled_at: datetime,
    ) -> CommandExecutionSnapshot:
        current = await self._required(operation_id)
        if current.record_version != expected_record_version:
            raise CommandExecutionStoreError("command cancel acknowledgement is stale")
        if not current.acknowledged_cancel_generation <= receipt.acknowledged_cancel_generation:
            raise CommandExecutionStoreError("supervisor cancel acknowledgement regressed")
        if receipt.acknowledged_cancel_generation > current.cancel_generation:
            raise CommandExecutionStoreError("supervisor acknowledged an unrequested generation")
        if receipt.evidence_generation < current.supervisor_evidence_generation:
            raise CommandExecutionStoreError("supervisor evidence generation regressed")
        if current.execution_id is not None and receipt.execution_id != current.execution_id:
            raise CommandExecutionStoreError("supervisor cancel execution identity conflicts")
        if snapshot is not None:
            _require_executor_snapshot(
                current,
                snapshot,
                minimum_evidence_generation=receipt.evidence_generation,
                allow_unresolved=True,
            )
            if snapshot.execution_id != receipt.execution_id:
                raise CommandExecutionStoreError("supervisor snapshot correlation conflicts")
        digest = receipt.receipt_sha256
        values: dict[str, object] = {
            "record_version": expected_record_version + 1,
            "supervisor_ack_cancel_generation": receipt.acknowledged_cancel_generation,
            "supervisor_cancel_disposition": receipt.disposition.value,
            "supervisor_evidence_generation": max(
                receipt.evidence_generation,
                0 if snapshot is None else snapshot.evidence_generation,
            ),
            "supervisor_cancel_evidence_sha256": digest,
            "updated_at": reconciled_at,
            "last_reconciled_at": reconciled_at,
        }
        if snapshot is not None:
            values["last_executor_state"] = snapshot.state.value
        if snapshot is not None and snapshot.state is ExecutorEvidenceState.CLOSED:
            values.update(
                terminal_evidence_sha256=snapshot.terminal_evidence_sha256,
                descendants_stopped=snapshot.descendants_stopped,
                output_finalized=snapshot.output_finalized,
                private_resources_cleaned=snapshot.cleanup_complete,
                cleanup_evidence_sha256=snapshot.cleanup_evidence_sha256,
                closure_state=(
                    CommandClosureState.COMPLETE.value
                    if current.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
                    and receipt.acknowledged_cancel_generation == current.cancel_generation
                    else CommandClosureState.PENDING.value
                ),
            )
        elif (
            current.acceptance_state is CommandAcceptanceState.NO_ACCEPT_PROVEN
            and receipt.disposition is CancelDisposition.NO_ACCEPT_PROVEN
            and receipt.acknowledged_cancel_generation == current.cancel_generation
        ):
            values["closure_state"] = CommandClosureState.COMPLETE.value
        await self._update_one(
            operation_id,
            expected_record_version=expected_record_version,
            extra_predicates=(),
            values=values,
            stale="command cancel acknowledgement CAS failed",
        )
        return await self._required(operation_id)

    async def record_executor_snapshot(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        snapshot: ExecutorSnapshot,
        reconciled_at: datetime,
    ) -> CommandExecutionSnapshot:
        current = await self._required(operation_id)
        if current.record_version != expected_record_version:
            raise CommandExecutionStoreError("command executor snapshot is stale")
        _require_executor_snapshot(current, snapshot)
        values: dict[str, object] = {
            "record_version": expected_record_version + 1,
            "supervisor_evidence_generation": snapshot.evidence_generation,
            "last_executor_state": snapshot.state.value,
            "updated_at": reconciled_at,
            "last_reconciled_at": reconciled_at,
        }
        if snapshot.state is ExecutorEvidenceState.CLOSED:
            values.update(
                terminal_evidence_sha256=snapshot.terminal_evidence_sha256,
                descendants_stopped=snapshot.descendants_stopped,
                output_finalized=snapshot.output_finalized,
                private_resources_cleaned=snapshot.cleanup_complete,
                cleanup_evidence_sha256=snapshot.cleanup_evidence_sha256,
                closure_state=(
                    CommandClosureState.COMPLETE.value
                    if current.cancel_generation == current.acknowledged_cancel_generation
                    else CommandClosureState.PENDING.value
                ),
            )
        await self._update_one(
            operation_id,
            expected_record_version=expected_record_version,
            extra_predicates=(
                CommandOperationModel.acceptance_state
                == CommandAcceptanceState.ACCEPTED_EXECUTION.value,
            ),
            values=values,
            stale="command executor snapshot CAS failed",
        )
        return await self._required(operation_id)

    async def list_unclosed(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int,
    ) -> tuple[CommandExecutionSnapshot, ...]:
        if not 1 <= limit <= 256:
            raise CommandExecutionStoreError("command reconciliation page limit is invalid")
        async with self._runtime.session_factory() as session:
            rows = (
                await session.execute(
                    select(CommandOperationModel)
                    .where(
                        CommandOperationModel.closure_state == CommandClosureState.PENDING.value,
                        CommandOperationModel.operation_id
                        > ("" if after_operation_id is None else after_operation_id),
                    )
                    .order_by(CommandOperationModel.operation_id)
                    .limit(limit)
                )
            ).scalars()
            return tuple(self._snapshot(row) for row in rows)

    async def _update_one(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        extra_predicates: tuple[ColumnElement[bool], ...],
        values: dict[str, object],
        stale: str,
    ) -> None:
        async with self._runtime.session_factory() as session:
            statement = update(CommandOperationModel).where(
                CommandOperationModel.operation_id == operation_id,
                CommandOperationModel.record_version == expected_record_version,
                *extra_predicates,
            )
            try:
                result = await session.execute(statement.values(**values))
                self._require_one(result, stale)
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise CommandExecutionStoreError(stale) from exc

    async def _required(self, operation_id: str) -> CommandExecutionSnapshot:
        result = await self.get(operation_id)
        if result is None:
            raise CommandExecutionStoreError("command operation is missing")
        return result

    @staticmethod
    def _snapshot(model: CommandOperationModel) -> CommandExecutionSnapshot:
        return CommandExecutionSnapshot(
            operation_id=model.operation_id,
            session_id=model.session_id,
            workspace_id=model.workspace_id,
            ticket_identity=TicketRoutingIdentity(
                operation_id=model.operation_id,
                ticket_id=model.ticket_id,
                ticket_sha256=model.ticket_sha256,
                nonce_sha256=model.single_use_nonce_sha256,
                boot_id_digest=model.ticket_boot_id_digest,
                expires_at=_required_utc(model.ticket_expires_at),
                monotonic_deadline_ns=model.ticket_monotonic_deadline_ns,
            ),
            ticket_correlation_sha256=_model_correlation_sha256(model),
            record_version=model.record_version,
            acceptance_state=CommandAcceptanceState(model.acceptance_state),
            execution_id=model.execution_id,
            executor_reference=model.executor_reference,
            accepted_receipt_sha256=model.accepted_receipt_sha256,
            no_accept_reference=model.no_accept_reference,
            no_accept_receipt_sha256=model.no_accept_receipt_sha256,
            cancel_generation=model.phase7_cancel_generation,
            acknowledged_cancel_generation=model.supervisor_ack_cancel_generation,
            cancel_disposition=(
                None
                if model.supervisor_cancel_disposition is None
                else CancelDisposition(model.supervisor_cancel_disposition)
            ),
            supervisor_evidence_generation=model.supervisor_evidence_generation,
            supervisor_cancel_evidence_sha256=model.supervisor_cancel_evidence_sha256,
            last_executor_state=(
                None
                if model.last_executor_state is None
                else ExecutorEvidenceState(model.last_executor_state)
            ),
            terminal_evidence_sha256=model.terminal_evidence_sha256,
            descendants_stopped=model.descendants_stopped,
            output_finalized=model.output_finalized,
            private_resources_cleaned=model.private_resources_cleaned,
            cleanup_evidence_sha256=model.cleanup_evidence_sha256,
            closure_state=CommandClosureState(model.closure_state),
            created_at=_required_utc(model.created_at),
            updated_at=_required_utc(model.updated_at),
            last_reconciled_at=_utc(model.last_reconciled_at),
        )

    @staticmethod
    def _require_ticket(retained: CommandExecutionSnapshot, ticket: ExecutionTicket) -> None:
        if (
            retained.ticket_identity != ticket.routing_identity
            or retained.ticket_correlation_sha256 != ticket_correlation_sha256(ticket)
            or retained.session_id != ticket.development_session_id
            or retained.workspace_id != ticket.workspace_id
        ):
            raise ExecutionConflictError("command operation ticket identity conflicts")

    @staticmethod
    def _require_one(result: object, message: str) -> None:
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise CommandExecutionStoreError(message)


def _required_utc(value: datetime) -> datetime:
    result = _utc(value)
    if result is None:
        raise CommandExecutionStoreError("command timestamp is absent")
    return result


def _model_correlation_sha256(model: CommandOperationModel) -> str:
    from binnacle.domain.execution import canonical_sha256

    return canonical_sha256(
        {
            "admission_record_id": model.admission_record_id,
            "argv_sha256": model.argv_sha256,
            "command_profile_id": model.command_profile_id,
            "controller_epoch": model.controller_epoch,
            "cwd_sha256": model.cwd_sha256,
            "development_session_closure_sha256": (model.development_session_closure_sha256),
            "development_session_id": model.session_id,
            "development_session_state_version": model.development_session_state_version,
            "device_epoch": model.device_epoch,
            "environment_sha256": model.environment_sha256,
            "executable_identity_sha256": model.executable_identity_sha256,
            "mount_plan_sha256": model.mount_plan_sha256,
            "network_plan_sha256": model.network_plan_sha256,
            "policy_sha256": model.policy_sha256,
            "process_isolation_plan_sha256": model.process_isolation_plan_sha256,
            "resource_plan_sha256": model.resource_plan_sha256,
            "sandbox_plan_sha256": model.sandbox_plan_sha256,
            "stdin_reference_sha256": model.stdin_reference_sha256,
            "stdin_sha256": model.stdin_sha256,
            "workspace_fence_version": model.workspace_fence_version,
            "workspace_id": model.workspace_id,
            "workspace_mount_identity_sha256": model.workspace_mount_identity_sha256,
            "workspace_profile_sha256": model.workspace_profile_sha256,
            "workspace_root_identity_sha256": model.workspace_root_identity_sha256,
            "workspace_script_sha256": model.workspace_script_sha256,
        }
    )


def _require_start_receipt_matches(
    current: CommandExecutionSnapshot,
    receipt: ExecutionStartReceipt,
) -> None:
    if (
        current.acceptance_state.value != receipt.disposition.value
        or current.execution_id != receipt.execution_id
        or current.executor_reference != receipt.executor_reference
        or current.no_accept_reference != receipt.no_accept_reference
        or (current.accepted_receipt_sha256 or current.no_accept_receipt_sha256)
        != receipt.receipt_sha256
    ):
        raise ExecutionConflictError("executor start receipt conflicts with application truth")


def _require_executor_snapshot(
    current: CommandExecutionSnapshot,
    snapshot: ExecutorSnapshot,
    *,
    minimum_evidence_generation: int = 0,
    allow_unresolved: bool = False,
) -> None:
    if current.acceptance_state is not CommandAcceptanceState.ACCEPTED_EXECUTION and not (
        allow_unresolved and current.acceptance_state is CommandAcceptanceState.UNRESOLVED
    ):
        raise CommandExecutionStoreError("executor snapshot requires accepted execution truth")
    if (
        snapshot.operation_id != current.operation_id
        or snapshot.ticket_id != current.ticket_identity.ticket_id
        or snapshot.ticket_sha256 != current.ticket_identity.ticket_sha256
        or (current.execution_id is not None and snapshot.execution_id != current.execution_id)
    ):
        raise CommandExecutionStoreError("supervisor snapshot correlation conflicts")
    if snapshot.evidence_generation < max(
        current.supervisor_evidence_generation,
        minimum_evidence_generation,
    ):
        raise CommandExecutionStoreError("supervisor snapshot evidence generation regressed")
    if (
        snapshot.acknowledged_cancel_generation < current.acknowledged_cancel_generation
        or snapshot.effective_cancel_generation > current.cancel_generation
        or snapshot.acknowledged_cancel_generation > current.cancel_generation
    ):
        raise CommandExecutionStoreError("supervisor snapshot cancellation truth conflicts")
    if current.last_executor_state is not None and not _executor_state_reachable(
        current.last_executor_state,
        snapshot.state,
    ):
        raise CommandExecutionStoreError("supervisor snapshot state regressed")


def _executor_state_reachable(
    current: ExecutorEvidenceState,
    target: ExecutorEvidenceState,
) -> bool:
    if current is target:
        return True
    visited = {current}
    pending = [current]
    while pending:
        state = pending.pop()
        for candidate in ExecutorEvidenceState:
            if candidate in visited:
                continue
            try:
                require_executor_transition(state, candidate)
            except ValueError:
                continue
            if candidate is target:
                return True
            visited.add(candidate)
            pending.append(candidate)
    return False


__all__ = [
    "CommandExecutionStoreError",
    "SqliteCommandExecutionRepository",
]

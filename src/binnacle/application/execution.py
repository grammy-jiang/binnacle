"""Application-side Phase 7 dispatch knowledge, cancellation, and reconciliation."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime

from binnacle.domain.execution import (
    CancelDisposition,
    CommandAcceptanceState,
    CommandExecutionSnapshot,
    DispatchCommitKnowledge,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    NoAcceptSealResult,
    validate_sha256,
)
from binnacle.ports.execution import (
    CommandExecutionRepository,
    CommandRecoveryVerifier,
    ExecutionSupervisorPort,
)


class ExecutionCoordinationError(RuntimeError):
    """Execution dispatch/cancellation evidence is stale or contradictory."""


@dataclass(frozen=True, slots=True)
class DispatchCommitHandle:
    operation_id: str
    ticket_sha256: str
    token: str


@dataclass(frozen=True, slots=True)
class PreparedExecutionDispatch:
    ticket: ExecutionTicket
    record: CommandExecutionSnapshot
    handle: DispatchCommitHandle


@dataclass(slots=True)
class _LatchEntry:
    ticket_sha256: str
    token: str
    knowledge: DispatchCommitKnowledge


class DispatchCommitLatch:
    """Process-local knowledge only; a replacement instance starts UNKNOWN."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._entries: dict[str, _LatchEntry] = {}

    async def prepare(self, operation_id: str, ticket_sha256: str) -> DispatchCommitHandle:
        async with self._lock:
            retained = self._entries.get(operation_id)
            if retained is not None:
                if retained.ticket_sha256 != ticket_sha256:
                    raise ExecutionConflictError("dispatch latch ticket identity conflicts")
                return DispatchCommitHandle(operation_id, ticket_sha256, retained.token)
            token = secrets.token_hex(16)
            self._entries[operation_id] = _LatchEntry(
                ticket_sha256=ticket_sha256,
                token=token,
                knowledge=DispatchCommitKnowledge.PRE_COMMIT_CURRENT_RUNTIME,
            )
            return DispatchCommitHandle(operation_id, ticket_sha256, token)

    async def mark_committed(self, handle: DispatchCommitHandle) -> None:
        async with self._lock:
            entry = self._require(handle)
            entry.knowledge = DispatchCommitKnowledge.COMMITTED_CURRENT_RUNTIME

    async def knowledge(
        self,
        operation_id: str,
        ticket_sha256: str,
    ) -> DispatchCommitKnowledge:
        async with self._lock:
            entry = self._entries.get(operation_id)
            if entry is None:
                return DispatchCommitKnowledge.UNKNOWN_AFTER_RUNTIME_LOSS
            if entry.ticket_sha256 != ticket_sha256:
                raise ExecutionConflictError("dispatch latch ticket identity conflicts")
            return entry.knowledge

    async def require_committed(self, handle: DispatchCommitHandle) -> None:
        async with self._lock:
            if (
                self._require(handle).knowledge
                is not DispatchCommitKnowledge.COMMITTED_CURRENT_RUNTIME
            ):
                raise ExecutionCoordinationError("call_start dispatch is not committed")

    async def forget(self, handle: DispatchCommitHandle) -> None:
        async with self._lock:
            self._require(handle)
            del self._entries[handle.operation_id]

    def _require(self, handle: DispatchCommitHandle) -> _LatchEntry:
        entry = self._entries.get(handle.operation_id)
        if (
            entry is None
            or entry.ticket_sha256 != handle.ticket_sha256
            or entry.token != handle.token
        ):
            raise ExecutionCoordinationError("dispatch latch handle is stale")
        return entry


class ApplicationExecutionCoordinator:
    """Keep application truth durable while the independent executor owns acceptance."""

    def __init__(
        self,
        *,
        repository: CommandExecutionRepository,
        supervisor: ExecutionSupervisorPort,
        dispatch_latch: DispatchCommitLatch,
        recovery_verifier: CommandRecoveryVerifier,
    ) -> None:
        self._repository = repository
        self._supervisor = supervisor
        self._dispatch_latch = dispatch_latch
        self._recovery_verifier = recovery_verifier

    async def prepare(
        self,
        ticket: ExecutionTicket,
        *,
        created_at: datetime,
    ) -> PreparedExecutionDispatch:
        record = await self._repository.create(ticket, created_at=created_at)
        handle = await self._dispatch_latch.prepare(ticket.operation_id, ticket.ticket_sha256)
        return PreparedExecutionDispatch(ticket=ticket, record=record, handle=handle)

    async def mark_call_start_committed(self, prepared: PreparedExecutionDispatch) -> None:
        await self._dispatch_latch.mark_committed(prepared.handle)

    async def dispatch_start(
        self,
        prepared: PreparedExecutionDispatch,
        *,
        recorded_at: datetime,
    ) -> CommandExecutionSnapshot:
        await self._dispatch_latch.require_committed(prepared.handle)
        receipt = await self._supervisor.start(prepared.ticket)
        current = await self._required(prepared.ticket.operation_id)
        if current.acceptance_state is CommandAcceptanceState.UNRESOLVED:
            current = await self._repository.record_start_receipt(
                current.operation_id,
                receipt=receipt,
                recorded_at=recorded_at,
            )
        else:
            self._require_receipt_matches(current, receipt)
        await self._dispatch_latch.forget(prepared.handle)
        return current

    async def cancel(
        self,
        operation_id: str,
        *,
        cancel_operation_id: str,
        request_fingerprint_sha256: str,
        requested_at: datetime,
        retain_until: datetime,
    ) -> CommandExecutionSnapshot:
        current = await self._required(operation_id)
        current = await self._repository.request_cancel(
            operation_id,
            expected_record_version=current.record_version,
            cancel_operation_id=cancel_operation_id,
            request_fingerprint_sha256=request_fingerprint_sha256,
            requested_at=requested_at,
        )
        knowledge = await self._dispatch_latch.knowledge(
            operation_id,
            current.ticket_identity.ticket_sha256,
        )
        if (
            knowledge is DispatchCommitKnowledge.PRE_COMMIT_CURRENT_RUNTIME
            and current.acceptance_state is CommandAcceptanceState.UNRESOLVED
        ):
            sealed = await self._supervisor.seal_no_accept(
                current.ticket_identity,
                "cancelled_before_call_start_commit",
                current.cancel_generation,
                retain_until,
            )
            current = await self._record_seal_result(current, sealed, requested_at)
            if sealed.disposition is ExecutionStartDisposition.NO_ACCEPT_PROVEN:
                cancel_receipt = ExecutorCancelReceipt(
                    acknowledged_cancel_generation=sealed.acknowledged_cancel_generation,
                    disposition=CancelDisposition.NO_ACCEPT_PROVEN,
                    evidence_generation=sealed.evidence_generation,
                    execution_id=None,
                    receipt_sha256=sealed.receipt_sha256,
                )
                return await self._repository.acknowledge_cancel(
                    operation_id,
                    expected_record_version=current.record_version,
                    receipt=cancel_receipt,
                    snapshot=None,
                    reconciled_at=requested_at,
                )
        receipt = await self._supervisor.cancel(
            current.ticket_identity,
            current.cancel_generation,
            current.execution_id,
        )
        snapshot = await self._supervisor.get(operation_id)
        current = await self._required(operation_id)
        return await self._repository.acknowledge_cancel(
            operation_id,
            expected_record_version=current.record_version,
            receipt=receipt,
            snapshot=snapshot,
            reconciled_at=requested_at,
        )

    async def reconcile_startup(
        self,
        *,
        reconciled_at: datetime,
        retain_until: datetime,
        limit: int = 256,
    ) -> tuple[CommandExecutionSnapshot, ...]:
        results: list[CommandExecutionSnapshot] = []
        after: str | None = None
        while True:
            records = await self._repository.list_unclosed(
                after_operation_id=after,
                limit=limit,
            )
            if not records:
                break
            for retained in records:
                current = retained
                if current.acceptance_state is CommandAcceptanceState.UNRESOLVED:
                    proof_sha256 = await self._recovery_verifier.prove_no_future_dispatch(current)
                    validate_sha256(proof_sha256, name="no_future_dispatch_evidence_sha256")
                    sealed = await self._supervisor.seal_no_accept(
                        current.ticket_identity,
                        f"replacement_runtime_{proof_sha256}",
                        current.cancel_generation,
                        retain_until,
                    )
                    current = await self._record_seal_result(current, sealed, reconciled_at)
                if current.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION:
                    snapshot = await self._supervisor.get(current.operation_id)
                    if snapshot is None:
                        raise ExecutionCoordinationError(
                            "accepted execution is missing supervisor evidence"
                        )
                    current = await self._required(current.operation_id)
                    current = await self._repository.record_executor_snapshot(
                        current.operation_id,
                        expected_record_version=current.record_version,
                        snapshot=snapshot,
                        reconciled_at=reconciled_at,
                    )
                if current.cancel_generation > current.acknowledged_cancel_generation:
                    receipt = await self._supervisor.cancel(
                        current.ticket_identity,
                        current.cancel_generation,
                        current.execution_id,
                    )
                    snapshot = await self._supervisor.get(current.operation_id)
                    current = await self._required(current.operation_id)
                    current = await self._repository.acknowledge_cancel(
                        current.operation_id,
                        expected_record_version=current.record_version,
                        receipt=receipt,
                        snapshot=snapshot,
                        reconciled_at=reconciled_at,
                    )
                results.append(current)
                after = retained.operation_id
            if len(records) < limit:
                break
        return tuple(results)

    async def _record_seal_result(
        self,
        current: CommandExecutionSnapshot,
        result: NoAcceptSealResult,
        recorded_at: datetime,
    ) -> CommandExecutionSnapshot:
        if result.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION:
            if result.snapshot is None or result.executor_reference is None:
                raise ExecutionCoordinationError("accepted reconciliation lacks exact evidence")
            receipt = ExecutionStartReceipt(
                disposition=result.disposition,
                execution_id=result.snapshot.execution_id,
                evidence_generation=result.evidence_generation,
                accepted_at=result.snapshot.accepted_at,
                executor_reference=result.executor_reference,
                no_accept_reference=None,
                receipt_sha256=result.receipt_sha256,
            )
        else:
            receipt = ExecutionStartReceipt(
                disposition=result.disposition,
                execution_id=None,
                evidence_generation=result.evidence_generation,
                accepted_at=None,
                executor_reference=None,
                no_accept_reference=result.seal_reference,
                receipt_sha256=result.receipt_sha256,
            )
        return await self._repository.record_start_receipt(
            current.operation_id,
            receipt=receipt,
            recorded_at=recorded_at,
        )

    async def _required(self, operation_id: str) -> CommandExecutionSnapshot:
        current = await self._repository.get(operation_id)
        if current is None:
            raise ExecutionCoordinationError("command execution record is missing")
        return current

    @staticmethod
    def _require_receipt_matches(
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


__all__ = [
    "ApplicationExecutionCoordinator",
    "DispatchCommitHandle",
    "DispatchCommitLatch",
    "ExecutionCoordinationError",
    "PreparedExecutionDispatch",
]

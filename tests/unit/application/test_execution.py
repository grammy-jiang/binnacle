from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.phase7_support import NOW, SHA_A, SHA_B, execution_ticket

from binnacle.application.execution import (
    ApplicationExecutionCoordinator,
    DispatchCommitLatch,
    ExecutionCoordinationError,
)
from binnacle.domain.execution import (
    CancelDisposition,
    CommandAcceptanceState,
    CommandClosureState,
    CommandExecutionSnapshot,
    CreateReceiptDisposition,
    DispatchCommitKnowledge,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorEvidenceState,
    ExecutorHello,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputStream,
    TicketRoutingIdentity,
    ticket_correlation_sha256,
)


def _accepted_start_receipt(*, receipt_sha256: str = SHA_A) -> ExecutionStartReceipt:
    return ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
        execution_id="exec-fixture",
        evidence_generation=1,
        accepted_at=NOW,
        executor_reference="accept-fixture",
        no_accept_reference=None,
        receipt_sha256=receipt_sha256,
    )


def _accepted_snapshot(
    *,
    state: ExecutorEvidenceState = ExecutorEvidenceState.RUNNING,
    evidence_generation: int = 2,
    cancel_generation: int = 1,
) -> ExecutorSnapshot:
    closed = state is ExecutorEvidenceState.CLOSED
    return ExecutorSnapshot(
        operation_id="op-fixture",
        ticket_id="ticket-fixture",
        ticket_sha256=execution_ticket().ticket_sha256,
        execution_id="exec-fixture",
        state=state,
        state_version=8 if closed else 2,
        evidence_generation=evidence_generation,
        effective_cancel_generation=cancel_generation,
        acknowledged_cancel_generation=cancel_generation,
        cancel_disposition=(None if cancel_generation == 0 else CancelDisposition.SIGNAL_PENDING),
        launch_generation=1,
        launch_committed_at=NOW,
        create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
        backend_reference="backend-fixture",
        backend_domain_identity_sha256=SHA_A,
        accepted_at=NOW,
        exit_code=0 if closed else None,
        descendants_stopped=closed,
        output_finalized=closed,
        cleanup_complete=closed,
        terminal_evidence_sha256=SHA_A if closed else None,
        cleanup_evidence_sha256=SHA_B if closed else None,
    )


class MemoryRepository:
    def __init__(self) -> None:
        self.record: CommandExecutionSnapshot | None = None

    async def create(
        self, ticket: ExecutionTicket, *, created_at: object
    ) -> CommandExecutionSnapshot:
        assert isinstance(created_at, type(NOW))
        self.record = CommandExecutionSnapshot(
            operation_id=ticket.operation_id,
            session_id=ticket.development_session_id,
            workspace_id=ticket.workspace_id,
            ticket_identity=ticket.routing_identity,
            ticket_correlation_sha256=ticket_correlation_sha256(ticket),
            record_version=1,
            acceptance_state=CommandAcceptanceState.UNRESOLVED,
            execution_id=None,
            executor_reference=None,
            accepted_receipt_sha256=None,
            no_accept_reference=None,
            no_accept_receipt_sha256=None,
            cancel_generation=0,
            acknowledged_cancel_generation=0,
            cancel_disposition=None,
            supervisor_evidence_generation=0,
            supervisor_cancel_evidence_sha256=None,
            last_executor_state=None,
            terminal_evidence_sha256=None,
            descendants_stopped=False,
            output_finalized=False,
            private_resources_cleaned=False,
            cleanup_evidence_sha256=None,
            closure_state=CommandClosureState.PENDING,
            created_at=NOW,
            updated_at=NOW,
            last_reconciled_at=None,
        )
        return self.record

    async def get(self, operation_id: str) -> CommandExecutionSnapshot | None:
        assert self.record is None or self.record.operation_id == operation_id
        return self.record

    async def record_start_receipt(
        self,
        operation_id: str,
        *,
        receipt: ExecutionStartReceipt,
        recorded_at: object,
    ) -> CommandExecutionSnapshot:
        assert self.record is not None
        assert self.record.operation_id == operation_id
        expected_record_version = self.record.record_version
        accepted = receipt.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
        self.record = replace(
            self.record,
            record_version=expected_record_version + 1,
            acceptance_state=CommandAcceptanceState(receipt.disposition.value),
            execution_id=receipt.execution_id,
            executor_reference=receipt.executor_reference,
            accepted_receipt_sha256=receipt.receipt_sha256 if accepted else None,
            no_accept_reference=receipt.no_accept_reference,
            no_accept_receipt_sha256=None if accepted else receipt.receipt_sha256,
            supervisor_evidence_generation=receipt.evidence_generation,
            terminal_evidence_sha256=None if accepted else receipt.receipt_sha256,
            descendants_stopped=not accepted,
            output_finalized=not accepted,
            private_resources_cleaned=not accepted,
            cleanup_evidence_sha256=None if accepted else receipt.receipt_sha256,
            closure_state=(
                CommandClosureState.PENDING
                if accepted or self.record.cancel_generation > 0
                else CommandClosureState.COMPLETE
            ),
            updated_at=NOW,
        )
        return self.record

    async def request_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        cancel_operation_id: str,
        request_fingerprint_sha256: str,
        requested_at: object,
    ) -> CommandExecutionSnapshot:
        del cancel_operation_id, request_fingerprint_sha256, requested_at
        assert self.record is not None and self.record.operation_id == operation_id
        assert self.record.record_version == expected_record_version
        self.record = replace(
            self.record,
            record_version=expected_record_version + 1,
            cancel_generation=self.record.cancel_generation + 1,
        )
        return self.record

    async def acknowledge_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        receipt: ExecutorCancelReceipt,
        snapshot: ExecutorSnapshot | None,
        reconciled_at: object,
    ) -> CommandExecutionSnapshot:
        del reconciled_at
        assert self.record is not None and self.record.operation_id == operation_id
        assert self.record.record_version == expected_record_version
        closed_snapshot = (
            snapshot
            if snapshot is not None and snapshot.state is ExecutorEvidenceState.CLOSED
            else None
        )
        self.record = replace(
            self.record,
            record_version=expected_record_version + 1,
            acknowledged_cancel_generation=receipt.acknowledged_cancel_generation,
            cancel_disposition=receipt.disposition,
            supervisor_evidence_generation=max(
                receipt.evidence_generation,
                0 if snapshot is None else snapshot.evidence_generation,
            ),
            supervisor_cancel_evidence_sha256=receipt.receipt_sha256,
            last_executor_state=(
                self.record.last_executor_state if snapshot is None else snapshot.state
            ),
            terminal_evidence_sha256=(
                self.record.terminal_evidence_sha256
                if closed_snapshot is None
                else closed_snapshot.terminal_evidence_sha256
            ),
            descendants_stopped=(
                self.record.descendants_stopped
                if closed_snapshot is None
                else closed_snapshot.descendants_stopped
            ),
            output_finalized=(
                self.record.output_finalized
                if closed_snapshot is None
                else closed_snapshot.output_finalized
            ),
            private_resources_cleaned=(
                self.record.private_resources_cleaned
                if closed_snapshot is None
                else closed_snapshot.cleanup_complete
            ),
            cleanup_evidence_sha256=(
                self.record.cleanup_evidence_sha256
                if closed_snapshot is None
                else closed_snapshot.cleanup_evidence_sha256
            ),
            closure_state=(
                CommandClosureState.COMPLETE
                if receipt.disposition is CancelDisposition.NO_ACCEPT_PROVEN
                or (
                    closed_snapshot is not None
                    and receipt.acknowledged_cancel_generation == self.record.cancel_generation
                )
                else CommandClosureState.PENDING
            ),
        )
        return self.record

    async def record_executor_snapshot(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        snapshot: ExecutorSnapshot,
        reconciled_at: object,
    ) -> CommandExecutionSnapshot:
        del reconciled_at
        assert self.record is not None and self.record.operation_id == operation_id
        assert self.record.record_version == expected_record_version
        assert self.record.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        closed = snapshot.state is ExecutorEvidenceState.CLOSED
        self.record = replace(
            self.record,
            record_version=expected_record_version + 1,
            supervisor_evidence_generation=snapshot.evidence_generation,
            last_executor_state=snapshot.state,
            terminal_evidence_sha256=(
                self.record.terminal_evidence_sha256
                if not closed
                else snapshot.terminal_evidence_sha256
            ),
            descendants_stopped=(
                self.record.descendants_stopped if not closed else snapshot.descendants_stopped
            ),
            output_finalized=(
                self.record.output_finalized if not closed else snapshot.output_finalized
            ),
            private_resources_cleaned=(
                self.record.private_resources_cleaned if not closed else snapshot.cleanup_complete
            ),
            cleanup_evidence_sha256=(
                self.record.cleanup_evidence_sha256
                if not closed
                else snapshot.cleanup_evidence_sha256
            ),
            closure_state=(
                CommandClosureState.COMPLETE
                if closed
                and self.record.cancel_generation == self.record.acknowledged_cancel_generation
                else CommandClosureState.PENDING
            ),
        )
        return self.record

    async def list_unclosed(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int,
    ) -> tuple[CommandExecutionSnapshot, ...]:
        assert limit > 0
        assert after_operation_id is None or isinstance(after_operation_id, str)
        return () if self.record is None else (self.record,)


class FakeRecoveryVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def prove_no_future_dispatch(self, record: CommandExecutionSnapshot) -> str:
        assert record.acceptance_state is CommandAcceptanceState.UNRESOLVED
        self.calls += 1
        return SHA_A


class RejectingRecoveryVerifier:
    async def prove_no_future_dispatch(self, record: CommandExecutionSnapshot) -> str:
        del record
        raise ExecutionCoordinationError("Phase 4 dispatch remains possible")


class FakeSupervisor:
    def __init__(self) -> None:
        self.start_calls = 0
        self.cancel_calls = 0
        self.seal_calls = 0

    async def hello(self) -> ExecutorHello:
        raise AssertionError

    async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
        self.start_calls += 1
        assert ticket.operation_id == "op-fixture"
        return ExecutionStartReceipt(
            disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
            execution_id="exec-fixture",
            evidence_generation=1,
            accepted_at=NOW,
            executor_reference="accept-fixture",
            no_accept_reference=None,
            receipt_sha256=SHA_A,
        )

    async def get(self, operation_id: str) -> ExecutorSnapshot | None:
        assert operation_id == "op-fixture"
        return None

    async def read_output(
        self, operation_id: str, stream: OutputStream, offset: int, max_bytes: int
    ) -> ExecutorOutputChunk:
        del operation_id, stream, offset, max_bytes
        raise AssertionError

    async def cancel(
        self,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
        execution_id: str | None = None,
    ) -> ExecutorCancelReceipt:
        self.cancel_calls += 1
        return ExecutorCancelReceipt(
            acknowledged_cancel_generation=cancel_generation,
            disposition=(
                CancelDisposition.PENDING_PREACCEPT
                if execution_id is None
                else CancelDisposition.SIGNAL_PENDING
            ),
            evidence_generation=3,
            execution_id=execution_id,
            receipt_sha256=SHA_A,
        )

    async def seal_no_accept(
        self,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: object,
    ) -> NoAcceptSealResult:
        del identity, reason, retain_until
        self.seal_calls += 1
        return NoAcceptSealResult(
            disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
            acknowledged_cancel_generation=close_generation,
            evidence_generation=2,
            snapshot=None,
            seal_reference="seal-fixture",
            executor_reference=None,
            receipt_sha256=SHA_A,
        )

    async def list(self, operation_ids: tuple[str, ...]) -> tuple[ExecutorSnapshot, ...]:
        del operation_ids
        return ()


class SnapshotSupervisor(FakeSupervisor):
    def __init__(
        self,
        snapshot: ExecutorSnapshot,
        *,
        cancelled_snapshot: ExecutorSnapshot | None = None,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._cancelled_snapshot = cancelled_snapshot or snapshot

    async def get(self, operation_id: str) -> ExecutorSnapshot | None:
        assert operation_id == "op-fixture"
        return self._cancelled_snapshot if self.cancel_calls else self._snapshot


def test_dispatch_latch_is_process_local_and_requires_commit() -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        latch = DispatchCommitLatch()
        handle = await latch.prepare(ticket.operation_id, ticket.ticket_sha256)
        assert (
            await latch.knowledge(ticket.operation_id, ticket.ticket_sha256)
            is DispatchCommitKnowledge.PRE_COMMIT_CURRENT_RUNTIME
        )
        with pytest.raises(ExecutionCoordinationError, match="not committed"):
            await latch.require_committed(handle)
        await latch.mark_committed(handle)
        await latch.require_committed(handle)
        replacement = DispatchCommitLatch()
        assert (
            await replacement.knowledge(ticket.operation_id, ticket.ticket_sha256)
            is DispatchCommitKnowledge.UNKNOWN_AFTER_RUNTIME_LOSS
        )

    asyncio.run(exercise())


def test_precommit_cancel_seals_without_forwarding_start() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(cancel_generation=0),
            cancelled_snapshot=_accepted_snapshot(
                evidence_generation=3,
                cancel_generation=1,
            ),
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        await coordinator.prepare(execution_ticket(), created_at=NOW)
        result = await coordinator.cancel(
            "op-fixture",
            cancel_operation_id="cancel-fixture",
            request_fingerprint_sha256=SHA_A,
            requested_at=NOW,
            retain_until=NOW + timedelta(hours=1),
        )
        assert supervisor.seal_calls == 1
        assert supervisor.cancel_calls == 0
        assert result.acceptance_state is CommandAcceptanceState.NO_ACCEPT_PROVEN
        assert result.closure_state is CommandClosureState.COMPLETE

    asyncio.run(exercise())


def test_committed_dispatch_starts_once_and_cancel_is_forwarded() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(cancel_generation=0),
            cancelled_snapshot=_accepted_snapshot(
                evidence_generation=3,
                cancel_generation=1,
            ),
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        prepared = await coordinator.prepare(execution_ticket(), created_at=NOW)
        await coordinator.mark_call_start_committed(prepared)
        started = await coordinator.dispatch_start(prepared, recorded_at=NOW)
        assert started.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        cancelled = await coordinator.cancel(
            "op-fixture",
            cancel_operation_id="cancel-fixture",
            request_fingerprint_sha256=SHA_A,
            requested_at=NOW,
            retain_until=NOW + timedelta(hours=1),
        )
        assert supervisor.start_calls == 1
        assert supervisor.seal_calls == 0
        assert supervisor.cancel_calls == 1
        assert cancelled.cancel_disposition is CancelDisposition.SIGNAL_PENDING

    asyncio.run(exercise())


def test_replacement_runtime_seals_unresolved_before_opening() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(cancel_generation=0),
            cancelled_snapshot=_accepted_snapshot(
                evidence_generation=3,
                cancel_generation=1,
            ),
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        await repository.create(execution_ticket(), created_at=NOW)
        (result,) = await coordinator.reconcile_startup(
            reconciled_at=NOW,
            retain_until=NOW + timedelta(hours=1),
        )
        assert supervisor.seal_calls == 1
        assert result.acceptance_state is CommandAcceptanceState.NO_ACCEPT_PROVEN

    asyncio.run(exercise())


def test_replacement_runtime_cannot_seal_without_phase4_proof() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        supervisor = FakeSupervisor()
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=RejectingRecoveryVerifier(),
        )
        await repository.create(execution_ticket(), created_at=NOW)

        with pytest.raises(ExecutionCoordinationError, match="dispatch remains possible"):
            await coordinator.reconcile_startup(
                reconciled_at=NOW,
                retain_until=NOW + timedelta(hours=1),
            )
        assert supervisor.seal_calls == 0

    asyncio.run(exercise())


def test_start_receipt_merge_preserves_a_concurrent_cancel_generation() -> None:
    class RacingSupervisor(FakeSupervisor):
        def __init__(self, repository: MemoryRepository) -> None:
            super().__init__()
            self._repository = repository

        async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
            current = await self._repository.get(ticket.operation_id)
            assert current is not None
            await self._repository.request_cancel(
                ticket.operation_id,
                expected_record_version=current.record_version,
                cancel_operation_id="cancel-race",
                request_fingerprint_sha256=SHA_A,
                requested_at=NOW,
            )
            return await super().start(ticket)

    async def exercise() -> None:
        repository = MemoryRepository()
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=RacingSupervisor(repository),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        prepared = await coordinator.prepare(execution_ticket(), created_at=NOW)
        await coordinator.mark_call_start_committed(prepared)

        classified = await coordinator.dispatch_start(prepared, recorded_at=NOW)

        assert classified.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        assert classified.cancel_generation == 1

    asyncio.run(exercise())


def test_dispatch_latch_replays_identity_and_rejects_conflicts_or_stale_handles() -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        latch = DispatchCommitLatch()
        handle = await latch.prepare(ticket.operation_id, ticket.ticket_sha256)

        replay = await latch.prepare(ticket.operation_id, ticket.ticket_sha256)
        assert replay == handle
        with pytest.raises(ExecutionConflictError, match="ticket identity conflicts"):
            await latch.prepare(ticket.operation_id, SHA_B)
        with pytest.raises(ExecutionConflictError, match="ticket identity conflicts"):
            await latch.knowledge(ticket.operation_id, SHA_B)
        with pytest.raises(ExecutionCoordinationError, match="handle is stale"):
            await latch.mark_committed(replace(handle, token="stale-token"))

        await latch.forget(handle)
        with pytest.raises(ExecutionCoordinationError, match="handle is stale"):
            await latch.require_committed(handle)

    asyncio.run(exercise())


def test_dispatch_reconciles_an_already_classified_receipt_and_rejects_conflict() -> None:
    class ConflictingSupervisor(FakeSupervisor):
        async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
            del ticket
            self.start_calls += 1
            return _accepted_start_receipt(receipt_sha256=SHA_B)

    async def exercise() -> None:
        repository = MemoryRepository()
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=SnapshotSupervisor(_accepted_snapshot(cancel_generation=0)),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        prepared = await coordinator.prepare(execution_ticket(), created_at=NOW)
        await coordinator.mark_call_start_committed(prepared)
        retained = await repository.record_start_receipt(
            prepared.ticket.operation_id,
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )

        assert await coordinator.dispatch_start(prepared, recorded_at=NOW) == retained

        conflict_repository = MemoryRepository()
        conflict_coordinator = ApplicationExecutionCoordinator(
            repository=conflict_repository,
            supervisor=ConflictingSupervisor(),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        conflict = await conflict_coordinator.prepare(execution_ticket(), created_at=NOW)
        await conflict_coordinator.mark_call_start_committed(conflict)
        await conflict_repository.record_start_receipt(
            conflict.ticket.operation_id,
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )

        with pytest.raises(ExecutionConflictError, match="receipt conflicts"):
            await conflict_coordinator.dispatch_start(conflict, recorded_at=NOW)

    asyncio.run(exercise())


def test_precommit_cancel_follows_acceptance_that_wins_the_seal_race() -> None:
    class AcceptanceWinningSupervisor(FakeSupervisor):
        async def seal_no_accept(
            self,
            identity: TicketRoutingIdentity,
            reason: str,
            close_generation: int,
            retain_until: object,
        ) -> NoAcceptSealResult:
            del identity, reason, retain_until
            self.seal_calls += 1
            return NoAcceptSealResult(
                disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
                acknowledged_cancel_generation=close_generation,
                evidence_generation=2,
                snapshot=_accepted_snapshot(),
                seal_reference=None,
                executor_reference="accept-fixture",
                receipt_sha256=SHA_A,
            )

        async def get(self, operation_id: str) -> ExecutorSnapshot | None:
            assert operation_id == "op-fixture"
            return _accepted_snapshot()

    async def exercise() -> None:
        repository = MemoryRepository()
        supervisor = AcceptanceWinningSupervisor()
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        await coordinator.prepare(execution_ticket(), created_at=NOW)

        result = await coordinator.cancel(
            "op-fixture",
            cancel_operation_id="cancel-fixture",
            request_fingerprint_sha256=SHA_A,
            requested_at=NOW,
            retain_until=NOW + timedelta(hours=1),
        )

        assert supervisor.seal_calls == 1
        assert supervisor.cancel_calls == 1
        assert result.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        assert result.acknowledged_cancel_generation == 1

    asyncio.run(exercise())


def test_startup_replays_outstanding_cancel_and_handles_an_empty_store() -> None:
    async def exercise() -> None:
        empty_repository = MemoryRepository()
        empty = ApplicationExecutionCoordinator(
            repository=empty_repository,
            supervisor=FakeSupervisor(),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        assert (
            await empty.reconcile_startup(
                reconciled_at=NOW,
                retain_until=NOW + timedelta(hours=1),
            )
            == ()
        )

        repository = MemoryRepository()
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(cancel_generation=0),
            cancelled_snapshot=_accepted_snapshot(
                evidence_generation=3,
                cancel_generation=1,
            ),
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        await repository.create(execution_ticket(), created_at=NOW)
        accepted = await repository.record_start_receipt(
            "op-fixture",
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )
        await repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id="cancel-fixture",
            request_fingerprint_sha256=SHA_A,
            requested_at=NOW,
        )

        (reconciled,) = await coordinator.reconcile_startup(
            reconciled_at=NOW,
            retain_until=NOW + timedelta(hours=1),
        )

        assert supervisor.seal_calls == 0
        assert supervisor.cancel_calls == 1
        assert reconciled.acknowledged_cancel_generation == 1

    asyncio.run(exercise())


def test_startup_projects_natural_closed_execution_without_a_cancel() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        await repository.create(execution_ticket(), created_at=NOW)
        await repository.record_start_receipt(
            "op-fixture",
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(
                state=ExecutorEvidenceState.CLOSED,
                evidence_generation=4,
                cancel_generation=0,
            )
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )

        (closed,) = await coordinator.reconcile_startup(
            reconciled_at=NOW + timedelta(seconds=1),
            retain_until=NOW + timedelta(hours=1),
        )

        assert closed.closure_state is CommandClosureState.COMPLETE
        assert closed.last_executor_state is ExecutorEvidenceState.CLOSED
        assert closed.terminal_evidence_sha256 == SHA_A
        assert closed.cleanup_evidence_sha256 == SHA_B
        assert supervisor.cancel_calls == 0

    asyncio.run(exercise())


def test_startup_projects_cleanup_after_cancel_delivery_was_already_acknowledged() -> None:
    async def exercise() -> None:
        repository = MemoryRepository()
        created = await repository.create(execution_ticket(), created_at=NOW)
        accepted = await repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )
        requested = await repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id="cancel-fixture",
            request_fingerprint_sha256=SHA_A,
            requested_at=NOW,
        )
        acknowledged = await repository.acknowledge_cancel(
            requested.operation_id,
            expected_record_version=requested.record_version,
            receipt=ExecutorCancelReceipt(
                acknowledged_cancel_generation=1,
                disposition=CancelDisposition.SIGNAL_PENDING,
                evidence_generation=2,
                execution_id="exec-fixture",
                receipt_sha256=SHA_A,
            ),
            snapshot=_accepted_snapshot(evidence_generation=2),
            reconciled_at=NOW,
        )
        assert acknowledged.cancel_generation == acknowledged.acknowledged_cancel_generation
        supervisor = SnapshotSupervisor(
            _accepted_snapshot(
                state=ExecutorEvidenceState.CLOSED,
                evidence_generation=4,
            )
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=supervisor,
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )

        (closed,) = await coordinator.reconcile_startup(
            reconciled_at=NOW + timedelta(seconds=1),
            retain_until=NOW + timedelta(hours=1),
        )

        assert closed.closure_state is CommandClosureState.COMPLETE
        assert closed.last_executor_state is ExecutorEvidenceState.CLOSED
        assert closed.acknowledged_cancel_generation == 1
        assert supervisor.cancel_calls == 0

    asyncio.run(exercise())


def test_startup_reconciliation_paginates_until_the_store_is_empty() -> None:
    class PagedMemoryRepository(MemoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.list_calls: list[str | None] = []

        async def list_unclosed(
            self,
            *,
            after_operation_id: str | None = None,
            limit: int,
        ) -> tuple[CommandExecutionSnapshot, ...]:
            assert limit == 1
            self.list_calls.append(after_operation_id)
            if len(self.list_calls) > 1:
                return ()
            assert self.record is not None
            return (self.record,)

    async def exercise() -> None:
        repository = PagedMemoryRepository()
        await repository.create(execution_ticket(), created_at=NOW)
        await repository.record_start_receipt(
            "op-fixture",
            receipt=_accepted_start_receipt(),
            recorded_at=NOW,
        )
        coordinator = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=SnapshotSupervisor(_accepted_snapshot(cancel_generation=0)),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )

        (reconciled,) = await coordinator.reconcile_startup(
            reconciled_at=NOW,
            retain_until=NOW + timedelta(hours=1),
            limit=1,
        )

        assert reconciled.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        assert repository.list_calls == [None, "op-fixture"]

    asyncio.run(exercise())


def test_coordinator_fails_closed_for_missing_records_and_malformed_seal_evidence() -> None:
    class MalformedAcceptanceSealSupervisor(FakeSupervisor):
        async def seal_no_accept(
            self,
            identity: TicketRoutingIdentity,
            reason: str,
            close_generation: int,
            retain_until: object,
        ) -> NoAcceptSealResult:
            del identity, reason, retain_until
            self.seal_calls += 1
            valid = NoAcceptSealResult(
                disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
                acknowledged_cancel_generation=close_generation,
                evidence_generation=2,
                snapshot=_accepted_snapshot(),
                seal_reference=None,
                executor_reference="accept-fixture",
                receipt_sha256=SHA_A,
            )
            object.__setattr__(valid, "snapshot", None)
            return valid

    async def exercise() -> None:
        missing = ApplicationExecutionCoordinator(
            repository=MemoryRepository(),
            supervisor=FakeSupervisor(),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        with pytest.raises(ExecutionCoordinationError, match="record is missing"):
            await missing.cancel(
                "op-fixture",
                cancel_operation_id="cancel-fixture",
                request_fingerprint_sha256=SHA_A,
                requested_at=NOW,
                retain_until=NOW + timedelta(hours=1),
            )

        repository = MemoryRepository()
        malformed = ApplicationExecutionCoordinator(
            repository=repository,
            supervisor=MalformedAcceptanceSealSupervisor(),
            dispatch_latch=DispatchCommitLatch(),
            recovery_verifier=FakeRecoveryVerifier(),
        )
        await malformed.prepare(execution_ticket(), created_at=NOW)
        with pytest.raises(ExecutionCoordinationError, match="lacks exact evidence"):
            await malformed.cancel(
                "op-fixture",
                cancel_operation_id="cancel-fixture",
                request_fingerprint_sha256=SHA_A,
                requested_at=NOW,
                retain_until=NOW + timedelta(hours=1),
            )

    asyncio.run(exercise())

"""Application-owned Phase 7 command correlation and cancellation persistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from tests.integration.test_development_workspace_persistence import (
    _active_session,
    _operation_snapshot,
    _registration,
)
from tests.phase4_support import NOW, operation_runtime
from tests.phase7_support import resource_plan

from binnacle.adapters.sqlite import execution as execution_adapter
from binnacle.adapters.sqlite.development_session import SqliteDevelopmentSessionRepository
from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.execution import (
    CommandExecutionStoreError,
    SqliteCommandExecutionRepository,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.adapters.sqlite.workspace import SqliteWorkspaceRepository
from binnacle.domain.execution import (
    CancelDisposition,
    CommandAcceptanceState,
    CommandClosureState,
    CommandExecutionSnapshot,
    CreateReceiptDisposition,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorEvidenceState,
    ExecutorSnapshot,
    build_execution_ticket,
    canonical_sha256,
)
from binnacle.domain.operation import EffectKnowledge, OperationState, TransitionRequest
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue

_POLICY_SHA256 = "b" * 64
_START_RECEIPT_SHA256 = "c" * 64
_CANCEL_RECEIPT_SHA256 = "d" * 64


@dataclass(frozen=True, slots=True)
class _RepositoryFixture:
    repository: SqliteCommandExecutionRepository
    operations: SqliteOperationStore
    ticket: ExecutionTicket


class _PausedStartReceiptRepository(SqliteCommandExecutionRepository):
    """Pause after the merge's first read so a cancellation can win the interleaving."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        super().__init__(runtime)
        self.first_read = asyncio.Event()
        self.resume = asyncio.Event()
        self._required_calls = 0

    async def _required(self, operation_id: str) -> CommandExecutionSnapshot:
        snapshot = await super()._required(operation_id)
        self._required_calls += 1
        if self._required_calls == 1:
            self.first_read.set()
            await self.resume.wait()
        return snapshot


async def _repository_fixture(
    runtime: DatabaseRuntime,
    operations: SqliteOperationStore,
    *,
    paused: bool = False,
) -> _RepositoryFixture:
    workspaces = SqliteWorkspaceRepository(runtime)
    sessions = SqliteDevelopmentSessionRepository(runtime)
    await workspaces.register_workspace(_registration())
    active_session = await _active_session(
        sessions,
        operations,
        key_byte="s",
        session_id="session-command",
    )
    operation = await _operation_snapshot(
        operations,
        key_byte="r",
        fingerprint="r",
        contract="command_run",
    )
    decision = PolicyDecision(
        policy_decision_id="decision-command",
        operation_id=operation.operation_id,
        policy_id="command-policy",
        policy_version="policy-v1",
        decision=PolicyDecisionValue.ALLOW,
        reason_codes=("command_allowed",),
        input_facts_sha256="a" * 64,
        runtime_policy_sha256=_POLICY_SHA256,
        decided_at=NOW + timedelta(seconds=3),
    )
    await operations.store_policy_decision(decision)
    authorised = await operations.transition(
        operation.operation_id,
        TransitionRequest(
            operation.state_version,
            OperationState.AUTHORISED,
            EffectKnowledge.NONE,
            "policy_allowed",
            occurred_at=decision.decided_at,
        ),
    )
    await operations.transition(
        operation.operation_id,
        TransitionRequest(
            authorised.state_version,
            OperationState.RUNNING,
            EffectKnowledge.NONE,
            "dispatch_attempt_recorded",
            occurred_at=NOW + timedelta(seconds=4),
        ),
    )
    fence = await workspaces.acquire_fence(
        workspace_id=active_session.workspace_id,
        expected_version=1,
        operation_id=operation.operation_id,
        contract="command_run",
        acquired_at=NOW + timedelta(seconds=4),
    )
    ticket = _ticket(
        operation_id=operation.operation_id,
        admission_record_id=decision.policy_decision_id,
        session_id=active_session.session_id,
        session_state_version=active_session.state_version,
        session_closure_sha256=canonical_sha256(
            {
                "activation_closure": active_session.activation_closure.value,
                "activation_closure_version": active_session.activation_closure_version,
                "session_id": active_session.session_id,
            }
        ),
        workspace_fence_version=fence.fence_version,
    )
    repository = (
        _PausedStartReceiptRepository(runtime)
        if paused
        else SqliteCommandExecutionRepository(runtime)
    )
    return _RepositoryFixture(repository, operations, ticket)


def _ticket(
    *,
    operation_id: str,
    admission_record_id: str,
    session_id: str,
    session_state_version: int,
    session_closure_sha256: str,
    workspace_fence_version: int,
    ticket_id: str = "ticket-command",
    nonce: str = "nonce-command",
) -> ExecutionTicket:
    issued_at = NOW + timedelta(seconds=5)
    return build_execution_ticket(
        ticket_id=ticket_id,
        operation_id=operation_id,
        controller_identity_sha256="a" * 64,
        controller_epoch=1,
        device_id="device-fixture",
        device_epoch=1,
        development_session_id=session_id,
        development_session_state_version=session_state_version,
        development_session_closure_sha256=session_closure_sha256,
        command_profile_id="command-profile-v1",
        workspace_id="workspace-fixture",
        workspace_profile_sha256="1" * 64,
        workspace_root_identity_sha256="2" * 64,
        workspace_mount_identity_sha256="3" * 64,
        workspace_fence_version=workspace_fence_version,
        executable_path="/usr/bin/python3",
        executable_identity_sha256="4" * 64,
        argv=("python3", "-c", "print('fixture')"),
        cwd_relative=".",
        environment={"LANG": "C.UTF-8"},
        inline_stdin=b"fixture-input",
        stdin_reference_sha256=None,
        workspace_script_sha256=None,
        policy_sha256=_POLICY_SHA256,
        resource_plan=resource_plan(),
        mount_plan_id="mount-plan-v1",
        mount_plan_sha256="5" * 64,
        sandbox_profile_id="sandbox-profile-v1",
        sandbox_plan_sha256="6" * 64,
        process_isolation_profile_id="process-profile-v1",
        process_isolation_plan_sha256="7" * 64,
        network_profile_id="network-denied-v1",
        network_plan_sha256="8" * 64,
        listener_exposure="denied",
        admission_record_id=admission_record_id,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=10),
        boot_id_digest="9" * 64,
        monotonic_deadline_ns=3_600_000_000_000,
        single_use_nonce=nonce,
    )


async def _cancel_operation(operations: SqliteOperationStore, key_byte: str) -> str:
    operation = await _operation_snapshot(
        operations,
        key_byte=key_byte,
        fingerprint=key_byte,
        contract="operation_cancel",
    )
    return operation.operation_id


def _accepted_receipt(*, evidence_generation: int = 1) -> ExecutionStartReceipt:
    return ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
        execution_id="execution-command",
        evidence_generation=evidence_generation,
        accepted_at=NOW + timedelta(seconds=6),
        executor_reference="accept-command",
        no_accept_reference=None,
        receipt_sha256=_START_RECEIPT_SHA256,
    )


def _no_accept_receipt(*, evidence_generation: int = 1) -> ExecutionStartReceipt:
    return ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
        execution_id=None,
        evidence_generation=evidence_generation,
        accepted_at=None,
        executor_reference=None,
        no_accept_reference="seal-command",
        receipt_sha256=_START_RECEIPT_SHA256,
    )


def _pending_cancel_receipt(*, evidence_generation: int = 2) -> ExecutorCancelReceipt:
    return ExecutorCancelReceipt(
        acknowledged_cancel_generation=1,
        disposition=CancelDisposition.PENDING_PREACCEPT,
        evidence_generation=evidence_generation,
        execution_id=None,
        receipt_sha256=_CANCEL_RECEIPT_SHA256,
    )


def _cancel_receipt(
    *,
    acknowledged_generation: int,
    evidence_generation: int,
    execution_id: str | None,
    receipt_sha256: str = _CANCEL_RECEIPT_SHA256,
    disposition: CancelDisposition = CancelDisposition.SIGNAL_PENDING,
) -> ExecutorCancelReceipt:
    return ExecutorCancelReceipt(
        acknowledged_cancel_generation=acknowledged_generation,
        disposition=disposition,
        evidence_generation=evidence_generation,
        execution_id=execution_id,
        receipt_sha256=receipt_sha256,
    )


def _executor_snapshot(
    ticket: ExecutionTicket,
    *,
    operation_id: str | None = None,
    ticket_sha256: str | None = None,
    state: ExecutorEvidenceState = ExecutorEvidenceState.RUNNING,
    evidence_generation: int = 4,
    cancel_generation: int = 1,
) -> ExecutorSnapshot:
    terminal = state is ExecutorEvidenceState.CLOSED
    return ExecutorSnapshot(
        operation_id=operation_id or ticket.operation_id,
        ticket_id=ticket.ticket_id,
        ticket_sha256=ticket_sha256 or ticket.ticket_sha256,
        execution_id="execution-command",
        state=state,
        state_version=8 if terminal else 4,
        evidence_generation=evidence_generation,
        effective_cancel_generation=cancel_generation,
        acknowledged_cancel_generation=cancel_generation,
        cancel_disposition=(None if cancel_generation == 0 else CancelDisposition.SIGNAL_APPLIED),
        launch_generation=1,
        launch_committed_at=NOW + timedelta(seconds=6),
        create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
        backend_reference="backend-command",
        backend_domain_identity_sha256="f" * 64,
        accepted_at=NOW + timedelta(seconds=6),
        exit_code=0 if terminal else None,
        descendants_stopped=terminal,
        output_finalized=terminal,
        cleanup_complete=terminal,
        terminal_evidence_sha256="6" * 64 if terminal else None,
        cleanup_evidence_sha256="7" * 64 if terminal else None,
    )


@pytest.mark.anyio
async def test_create_replays_exact_ticket_and_rejects_conflicting_identity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        replay = await fixture.repository.create(fixture.ticket, created_at=NOW)

        assert replay == created
        assert created.record_version == 1
        assert created.acceptance_state is CommandAcceptanceState.UNRESOLVED
        assert await fixture.repository.get(created.operation_id) == created
        assert await fixture.repository.get("operation-missing") is None

        conflict = _ticket(
            operation_id=fixture.ticket.operation_id,
            admission_record_id=fixture.ticket.admission_record_id,
            session_id=fixture.ticket.development_session_id,
            session_state_version=fixture.ticket.development_session_state_version,
            session_closure_sha256=fixture.ticket.development_session_closure_sha256,
            workspace_fence_version=fixture.ticket.workspace_fence_version,
            ticket_id="ticket-conflict",
            nonce="nonce-conflict",
        )
        with pytest.raises(ExecutionConflictError, match="ticket identity conflicts"):
            await fixture.repository.create(conflict, created_at=NOW)


@pytest.mark.anyio
async def test_cancel_request_is_idempotent_and_generation_cas_is_strict(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        first_cancel_id = await _cancel_operation(operations, "c")
        first = await fixture.repository.request_cancel(
            created.operation_id,
            expected_record_version=created.record_version,
            cancel_operation_id=first_cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        replay = await fixture.repository.request_cancel(
            created.operation_id,
            expected_record_version=created.record_version,
            cancel_operation_id=first_cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=8),
        )

        assert replay == first
        assert first.cancel_generation == 1
        assert first.record_version == 2
        with pytest.raises(ExecutionConflictError, match="idempotency identity conflicts"):
            await fixture.repository.request_cancel(
                created.operation_id,
                expected_record_version=first.record_version,
                cancel_operation_id=first_cancel_id,
                request_fingerprint_sha256="2" * 64,
                requested_at=NOW + timedelta(seconds=8),
            )

        second_cancel_id = await _cancel_operation(operations, "d")
        second = await fixture.repository.request_cancel(
            created.operation_id,
            expected_record_version=first.record_version,
            cancel_operation_id=second_cancel_id,
            request_fingerprint_sha256="3" * 64,
            requested_at=NOW + timedelta(seconds=9),
        )
        assert second.cancel_generation == 2
        assert second.record_version == 3

        stale_cancel_id = await _cancel_operation(operations, "e")
        with pytest.raises(CommandExecutionStoreError, match="cancel request is stale"):
            await fixture.repository.request_cancel(
                created.operation_id,
                expected_record_version=first.record_version,
                cancel_operation_id=stale_cancel_id,
                request_fingerprint_sha256="4" * 64,
                requested_at=NOW + timedelta(seconds=10),
            )


@pytest.mark.anyio
async def test_accepted_start_receipt_merges_over_concurrent_cancel_without_losing_it(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations, paused=True)
        repository = fixture.repository
        assert isinstance(repository, _PausedStartReceiptRepository)
        created = await repository.create(fixture.ticket, created_at=NOW)
        start_task = asyncio.create_task(
            repository.record_start_receipt(
                created.operation_id,
                receipt=_accepted_receipt(),
                recorded_at=NOW + timedelta(seconds=8),
            )
        )
        await repository.first_read.wait()
        cancel_id = await _cancel_operation(operations, "c")
        cancelled = await repository.request_cancel(
            created.operation_id,
            expected_record_version=created.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        repository.resume.set()
        merged = await start_task

        assert cancelled.cancel_generation == 1
        assert merged.record_version == 3
        assert merged.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        assert merged.accepted_receipt_sha256 == _START_RECEIPT_SHA256
        assert merged.cancel_generation == 1
        assert merged.acknowledged_cancel_generation == 0

        replay = await repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=9),
        )
        assert replay == merged
        with pytest.raises(ExecutionConflictError, match="receipt conflicts"):
            await repository.record_start_receipt(
                created.operation_id,
                receipt=ExecutionStartReceipt(
                    disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
                    execution_id="execution-conflict",
                    evidence_generation=1,
                    accepted_at=NOW + timedelta(seconds=6),
                    executor_reference="accept-command",
                    no_accept_reference=None,
                    receipt_sha256="e" * 64,
                ),
                recorded_at=NOW + timedelta(seconds=9),
            )


@pytest.mark.anyio
async def test_no_accept_merge_keeps_concurrent_cancel_open_until_acknowledged(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations, paused=True)
        repository = fixture.repository
        assert isinstance(repository, _PausedStartReceiptRepository)
        created = await repository.create(fixture.ticket, created_at=NOW)
        start_task = asyncio.create_task(
            repository.record_start_receipt(
                created.operation_id,
                receipt=_no_accept_receipt(),
                recorded_at=NOW + timedelta(seconds=8),
            )
        )
        await repository.first_read.wait()
        cancel_id = await _cancel_operation(operations, "c")
        await repository.request_cancel(
            created.operation_id,
            expected_record_version=created.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        repository.resume.set()
        merged = await start_task

        assert merged.acceptance_state is CommandAcceptanceState.NO_ACCEPT_PROVEN
        assert merged.cancel_generation == 1
        assert merged.acknowledged_cancel_generation == 0
        assert merged.closure_state is CommandClosureState.PENDING
        assert await repository.list_unclosed(limit=1) == (merged,)

        closed = await repository.acknowledge_cancel(
            created.operation_id,
            expected_record_version=merged.record_version,
            receipt=ExecutorCancelReceipt(
                acknowledged_cancel_generation=1,
                disposition=CancelDisposition.NO_ACCEPT_PROVEN,
                evidence_generation=2,
                execution_id=None,
                receipt_sha256=_START_RECEIPT_SHA256,
            ),
            snapshot=None,
            reconciled_at=NOW + timedelta(seconds=9),
        )
        assert closed.closure_state is CommandClosureState.COMPLETE
        assert await repository.list_unclosed(limit=1) == ()


@pytest.mark.anyio
async def test_start_merge_preserves_a_newer_preaccept_cancel_acknowledgement(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        cancel_id = await _cancel_operation(operations, "c")
        requested = await fixture.repository.request_cancel(
            created.operation_id,
            expected_record_version=created.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        acknowledged = await fixture.repository.acknowledge_cancel(
            created.operation_id,
            expected_record_version=requested.record_version,
            receipt=_pending_cancel_receipt(),
            snapshot=None,
            reconciled_at=NOW + timedelta(seconds=8),
        )

        merged = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(evidence_generation=1),
            recorded_at=NOW + timedelta(seconds=9),
        )

        assert merged.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        assert merged.cancel_generation == acknowledged.cancel_generation == 1
        assert merged.acknowledged_cancel_generation == 1
        assert merged.cancel_disposition is CancelDisposition.PENDING_PREACCEPT
        assert merged.supervisor_evidence_generation == 2
        assert merged.supervisor_cancel_evidence_sha256 == _CANCEL_RECEIPT_SHA256


@pytest.mark.anyio
async def test_foreign_key_and_start_merge_integrity_failures_are_store_errors(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        missing_operation_ticket = _ticket(
            operation_id="operation-missing",
            admission_record_id=fixture.ticket.admission_record_id,
            session_id=fixture.ticket.development_session_id,
            session_state_version=fixture.ticket.development_session_state_version,
            session_closure_sha256=fixture.ticket.development_session_closure_sha256,
            workspace_fence_version=fixture.ticket.workspace_fence_version,
            ticket_id="ticket-missing-operation",
            nonce="nonce-missing-operation",
        )
        with pytest.raises(CommandExecutionStoreError, match="retained authority"):
            await fixture.repository.create(missing_operation_ticket, created_at=NOW)

        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        with pytest.raises(CommandExecutionStoreError, match="start receipt merge failed"):
            await fixture.repository.record_start_receipt(
                created.operation_id,
                receipt=_accepted_receipt(),
                recorded_at=NOW - timedelta(seconds=1),
            )
        retained = await fixture.repository.get(created.operation_id)
        assert retained == created


@pytest.mark.anyio
async def test_cancel_insert_foreign_key_failure_rolls_back_generation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)

        with pytest.raises(CommandExecutionStoreError, match="cancel generation conflicts"):
            await fixture.repository.request_cancel(
                created.operation_id,
                expected_record_version=created.record_version,
                cancel_operation_id="cancel-operation-missing",
                request_fingerprint_sha256="1" * 64,
                requested_at=NOW + timedelta(seconds=7),
            )

        retained = await fixture.repository.get(created.operation_id)
        assert retained == created


@pytest.mark.anyio
async def test_cancel_acknowledgement_rejects_stale_and_uncorrelated_evidence(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(evidence_generation=3),
            recorded_at=NOW + timedelta(seconds=6),
        )
        cancel_id = await _cancel_operation(operations, "c")
        requested = await fixture.repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )

        cases = (
            (
                created.record_version,
                _cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=3,
                    execution_id="execution-command",
                ),
                None,
                "acknowledgement is stale",
            ),
            (
                requested.record_version,
                _cancel_receipt(
                    acknowledged_generation=2,
                    evidence_generation=3,
                    execution_id="execution-command",
                ),
                None,
                "unrequested generation",
            ),
            (
                requested.record_version,
                _cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=2,
                    execution_id="execution-command",
                ),
                None,
                "evidence generation regressed",
            ),
            (
                requested.record_version,
                _cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=3,
                    execution_id="execution-other",
                ),
                None,
                "execution identity conflicts",
            ),
            (
                requested.record_version,
                _cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=3,
                    execution_id="execution-command",
                ),
                _executor_snapshot(fixture.ticket, operation_id="operation-other"),
                "snapshot correlation conflicts",
            ),
            (
                requested.record_version,
                _cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=3,
                    execution_id="execution-command",
                ),
                _executor_snapshot(fixture.ticket, ticket_sha256="0" * 64),
                "snapshot correlation conflicts",
            ),
        )
        for expected_version, receipt, snapshot, message in cases:
            with pytest.raises(CommandExecutionStoreError, match=message):
                await fixture.repository.acknowledge_cancel(
                    requested.operation_id,
                    expected_record_version=expected_version,
                    receipt=receipt,
                    snapshot=snapshot,
                    reconciled_at=NOW + timedelta(seconds=8),
                )


@pytest.mark.anyio
async def test_closed_executor_snapshot_completes_application_closure(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=6),
        )
        cancel_id = await _cancel_operation(operations, "c")
        requested = await fixture.repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        snapshot = _executor_snapshot(
            fixture.ticket,
            state=ExecutorEvidenceState.CLOSED,
            evidence_generation=4,
        )
        closed = await fixture.repository.acknowledge_cancel(
            requested.operation_id,
            expected_record_version=requested.record_version,
            receipt=_cancel_receipt(
                acknowledged_generation=1,
                evidence_generation=4,
                execution_id="execution-command",
                disposition=CancelDisposition.SIGNAL_APPLIED,
            ),
            snapshot=snapshot,
            reconciled_at=NOW + timedelta(seconds=8),
        )

        assert closed.closure_state is CommandClosureState.COMPLETE
        assert closed.last_executor_state is ExecutorEvidenceState.CLOSED
        assert closed.terminal_evidence_sha256 == snapshot.terminal_evidence_sha256
        assert closed.cleanup_evidence_sha256 == snapshot.cleanup_evidence_sha256
        assert closed.descendants_stopped
        assert closed.output_finalized
        assert closed.private_resources_cleaned


@pytest.mark.anyio
async def test_natural_closed_snapshot_projects_without_cancel_acknowledgement(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        natural_close = _executor_snapshot(
            fixture.ticket,
            state=ExecutorEvidenceState.CLOSED,
            evidence_generation=4,
            cancel_generation=0,
        )
        with pytest.raises(CommandExecutionStoreError, match="requires accepted execution"):
            await fixture.repository.record_executor_snapshot(
                created.operation_id,
                expected_record_version=created.record_version,
                snapshot=natural_close,
                reconciled_at=NOW + timedelta(seconds=6),
            )
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=6),
        )

        closed = await fixture.repository.record_executor_snapshot(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            snapshot=natural_close,
            reconciled_at=NOW + timedelta(seconds=8),
        )

        assert closed.cancel_generation == closed.acknowledged_cancel_generation == 0
        assert closed.last_executor_state is ExecutorEvidenceState.CLOSED
        assert closed.supervisor_evidence_generation == 4
        assert closed.closure_state is CommandClosureState.COMPLETE
        assert closed.terminal_evidence_sha256 == natural_close.terminal_evidence_sha256
        assert closed.cleanup_evidence_sha256 == natural_close.cleanup_evidence_sha256
        assert await fixture.repository.list_unclosed(limit=1) == ()

        with pytest.raises(CommandExecutionStoreError, match="snapshot state regressed"):
            await fixture.repository.record_executor_snapshot(
                closed.operation_id,
                expected_record_version=closed.record_version,
                snapshot=_executor_snapshot(
                    fixture.ticket,
                    state=ExecutorEvidenceState.RUNNING,
                    evidence_generation=5,
                    cancel_generation=0,
                ),
                reconciled_at=NOW + timedelta(seconds=9),
            )


@pytest.mark.anyio
async def test_acknowledged_cancel_projects_later_cleanup_without_new_receipt(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=6),
        )
        cancel_id = await _cancel_operation(operations, "c")
        requested = await fixture.repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id=cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        acknowledged = await fixture.repository.acknowledge_cancel(
            requested.operation_id,
            expected_record_version=requested.record_version,
            receipt=_cancel_receipt(
                acknowledged_generation=1,
                evidence_generation=2,
                execution_id="execution-command",
            ),
            snapshot=_executor_snapshot(
                fixture.ticket,
                evidence_generation=2,
                cancel_generation=1,
            ),
            reconciled_at=NOW + timedelta(seconds=8),
        )
        assert acknowledged.closure_state is CommandClosureState.PENDING
        assert acknowledged.cancel_generation == acknowledged.acknowledged_cancel_generation == 1

        closed_snapshot = _executor_snapshot(
            fixture.ticket,
            state=ExecutorEvidenceState.CLOSED,
            evidence_generation=4,
            cancel_generation=1,
        )
        closed = await fixture.repository.record_executor_snapshot(
            acknowledged.operation_id,
            expected_record_version=acknowledged.record_version,
            snapshot=closed_snapshot,
            reconciled_at=NOW + timedelta(seconds=10),
        )

        assert closed.closure_state is CommandClosureState.COMPLETE
        assert closed.last_executor_state is ExecutorEvidenceState.CLOSED
        assert closed.supervisor_cancel_evidence_sha256 == _CANCEL_RECEIPT_SHA256
        assert closed.supervisor_evidence_generation == 4


@pytest.mark.anyio
async def test_higher_cancel_generation_accepts_its_distinct_receipt_evidence(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=6),
        )
        first_cancel_id = await _cancel_operation(operations, "c")
        first = await fixture.repository.request_cancel(
            accepted.operation_id,
            expected_record_version=accepted.record_version,
            cancel_operation_id=first_cancel_id,
            request_fingerprint_sha256="1" * 64,
            requested_at=NOW + timedelta(seconds=7),
        )
        first_ack = await fixture.repository.acknowledge_cancel(
            first.operation_id,
            expected_record_version=first.record_version,
            receipt=_cancel_receipt(
                acknowledged_generation=1,
                evidence_generation=2,
                execution_id="execution-command",
                receipt_sha256="1" * 64,
            ),
            snapshot=None,
            reconciled_at=NOW + timedelta(seconds=8),
        )
        second_cancel_id = await _cancel_operation(operations, "d")
        second = await fixture.repository.request_cancel(
            first_ack.operation_id,
            expected_record_version=first_ack.record_version,
            cancel_operation_id=second_cancel_id,
            request_fingerprint_sha256="2" * 64,
            requested_at=NOW + timedelta(seconds=9),
        )

        second_ack = await fixture.repository.acknowledge_cancel(
            second.operation_id,
            expected_record_version=second.record_version,
            receipt=_cancel_receipt(
                acknowledged_generation=2,
                evidence_generation=3,
                execution_id="execution-command",
                receipt_sha256="2" * 64,
            ),
            snapshot=None,
            reconciled_at=NOW + timedelta(seconds=10),
        )

        assert second_ack.acknowledged_cancel_generation == 2
        assert second_ack.supervisor_cancel_evidence_sha256 == "2" * 64


@pytest.mark.anyio
async def test_repository_bounds_and_corrupt_value_guards_fail_closed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        for limit in (0, 257):
            with pytest.raises(CommandExecutionStoreError, match="page limit is invalid"):
                await fixture.repository.list_unclosed(limit=limit)
        with pytest.raises(CommandExecutionStoreError, match="command operation is missing"):
            await fixture.repository.record_start_receipt(
                "operation-missing",
                receipt=_accepted_receipt(),
                recorded_at=NOW,
            )
        with pytest.raises(CommandExecutionStoreError, match="synthetic CAS"):
            fixture.repository._require_one(object(), "synthetic CAS")
        with pytest.raises(CommandExecutionStoreError, match="timestamp is absent"):
            execution_adapter._required_utc(cast(datetime, None))


@pytest.mark.anyio
async def test_cancel_acknowledgement_regression_and_same_generation_rewrite_fail_closed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operations):
        fixture = await _repository_fixture(runtime, operations)
        created = await fixture.repository.create(fixture.ticket, created_at=NOW)
        accepted = await fixture.repository.record_start_receipt(
            created.operation_id,
            receipt=_accepted_receipt(),
            recorded_at=NOW + timedelta(seconds=6),
        )
        current = accepted
        for generation, key in ((1, "c"), (2, "d")):
            cancel_id = await _cancel_operation(operations, key)
            requested = await fixture.repository.request_cancel(
                current.operation_id,
                expected_record_version=current.record_version,
                cancel_operation_id=cancel_id,
                request_fingerprint_sha256=key * 64,
                requested_at=NOW + timedelta(seconds=6 + generation * 2),
            )
            current = await fixture.repository.acknowledge_cancel(
                requested.operation_id,
                expected_record_version=requested.record_version,
                receipt=_cancel_receipt(
                    acknowledged_generation=generation,
                    evidence_generation=generation + 1,
                    execution_id="execution-command",
                    receipt_sha256=_CANCEL_RECEIPT_SHA256,
                ),
                snapshot=None,
                reconciled_at=NOW + timedelta(seconds=7 + generation * 2),
            )
        third_cancel_id = await _cancel_operation(operations, "e")
        third = await fixture.repository.request_cancel(
            current.operation_id,
            expected_record_version=current.record_version,
            cancel_operation_id=third_cancel_id,
            request_fingerprint_sha256="e" * 64,
            requested_at=NOW + timedelta(seconds=12),
        )
        with pytest.raises(CommandExecutionStoreError, match="acknowledgement regressed"):
            await fixture.repository.acknowledge_cancel(
                third.operation_id,
                expected_record_version=third.record_version,
                receipt=_cancel_receipt(
                    acknowledged_generation=1,
                    evidence_generation=4,
                    execution_id="execution-command",
                ),
                snapshot=None,
                reconciled_at=NOW + timedelta(seconds=13),
            )
        with pytest.raises(CommandExecutionStoreError, match="acknowledgement CAS failed"):
            await fixture.repository.acknowledge_cancel(
                third.operation_id,
                expected_record_version=third.record_version,
                receipt=_cancel_receipt(
                    acknowledged_generation=2,
                    evidence_generation=4,
                    execution_id="execution-command",
                    receipt_sha256="e" * 64,
                ),
                snapshot=None,
                reconciled_at=NOW + timedelta(seconds=13),
            )

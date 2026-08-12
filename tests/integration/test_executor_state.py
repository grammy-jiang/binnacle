from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.phase7_support import NOW, execution_ticket, executor_store

from binnacle.domain.execution import (
    CancelRoutingDisposition,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
)
from binnacle.executor.reconcile import ExecutorRestartReconciler
from binnacle.executor.state import ExecutorStoreError


def test_accept_once_survives_duplicate_and_restart(tmp_path: Path) -> None:
    async def exercise() -> None:
        repo_root = Path(__file__).parents[2]
        root = tmp_path / "executor"
        ticket = execution_ticket()
        async with executor_store(root, repo_root) as store:
            first = await store.accept_once(ticket)
            second = await store.accept_once(ticket)
            assert first == second
            assert first.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
        async with executor_store(root, repo_root, migrate=False) as reopened:
            replay = await reopened.accept_once(ticket)
            assert replay == first
            assert (await reopened.get(ticket.operation_id)) is not None

    asyncio.run(exercise())


def test_cancel_before_accept_attaches_atomically(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            pending = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=4,
            )
            assert pending.disposition is CancelRoutingDisposition.PENDING_PREACCEPT
            accepted = await store.accept_once(ticket)
            snapshot = await store.get(ticket.operation_id)
            assert accepted.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
            assert snapshot is not None
            assert snapshot.effective_cancel_generation == 4
            assert snapshot.acknowledged_cancel_generation == 4

    asyncio.run(exercise())


def test_no_accept_seal_wins_before_queued_accept(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            sealed = await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="application_runtime_lost",
                close_generation=2,
                retain_until=NOW + timedelta(hours=1),
            )
            replay = await store.accept_once(ticket)
            assert sealed.disposition is ExecutionStartDisposition.NO_ACCEPT_PROVEN
            assert replay.disposition is ExecutionStartDisposition.NO_ACCEPT_PROVEN
            assert replay.no_accept_reference == sealed.seal_reference
            assert await store.get(ticket.operation_id) is None

    asyncio.run(exercise())


def test_accept_and_seal_have_exactly_one_durable_home(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            accepted, sealed = await asyncio.gather(
                store.accept_once(ticket),
                store.seal_no_accept(
                    identity=ticket.routing_identity,
                    reason="runtime_reconciliation",
                    close_generation=0,
                    retain_until=NOW + timedelta(hours=1),
                ),
            )
            assert accepted.disposition is sealed.disposition
            assert accepted.disposition in {
                ExecutionStartDisposition.ACCEPTED_EXECUTION,
                ExecutionStartDisposition.NO_ACCEPT_PROVEN,
            }

    asyncio.run(exercise())


def test_different_valid_ticket_for_same_operation_conflicts(tmp_path: Path) -> None:
    async def exercise() -> None:
        first = execution_ticket()
        second = execution_ticket(ticket_id="ticket-other", nonce="nonce-other")
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            await store.accept_once(first)
            with pytest.raises(ExecutionConflictError, match="conflicts"):
                await store.accept_once(second)

    asyncio.run(exercise())


def test_accepted_receipt_is_stable_after_later_cancel_evidence(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            accepted = await store.accept_once(ticket)
            await store.cancel_or_attach(identity=ticket.routing_identity, cancel_generation=1)
            replay = await store.accept_once(ticket)

            assert replay == accepted

    asyncio.run(exercise())


def test_no_accept_receipt_is_stable_after_later_cancel_evidence(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[2]
        async with executor_store(root, repo_root) as store:
            sealed = await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="runtime_reconciliation",
                close_generation=1,
                retain_until=NOW + timedelta(hours=1),
            )
            await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=2,
            )
            replay = await store.accept_once(ticket)
            assert replay.receipt_sha256 == sealed.receipt_sha256
        async with executor_store(root, repo_root, migrate=False) as reopened:
            replay = await reopened.accept_once(ticket)
            assert replay.receipt_sha256 == sealed.receipt_sha256

    asyncio.run(exercise())


def test_durable_cancel_invalidates_a_stale_launch_worker(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            await store.accept_once(ticket)
            before_cancel = await store.get(ticket.operation_id)
            assert before_cancel is not None
            routed = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=1,
            )
            assert routed.snapshot is not None
            assert routed.snapshot.state is ExecutorEvidenceState.CANCEL_REQUESTED
            with pytest.raises(ExecutionConflictError, match="precondition is stale"):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="stale-launch-worker",
                        operation_id=ticket.operation_id,
                        expected_state=before_cancel.state,
                        expected_state_version=before_cancel.state_version,
                        target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                        reason_code="launch_prepare",
                        recorded_at=datetime.now(UTC),
                    )
                )

    asyncio.run(exercise())


def test_restart_closes_only_proven_prelaunch_and_reports_terminal_cancel(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[2]
        async with executor_store(root, repo_root) as store:
            await store.accept_once(ticket)
        async with executor_store(root, repo_root, migrate=False) as reopened:
            assert reopened.readiness == "recovering"
            report = await ExecutorRestartReconciler(reopened).reconcile()
            closed = await reopened.get(ticket.operation_id)
            assert report.readiness == "ready"
            assert closed is not None and closed.state is ExecutorEvidenceState.CLOSED
            routed = await reopened.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=1,
            )
            assert routed.snapshot is not None
            assert routed.snapshot.cancel_disposition is not None
            assert routed.snapshot.cancel_disposition.value == "terminal_already_won"

    asyncio.run(exercise())


def test_restart_never_respawns_a_launch_committed_execution(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[2]
        async with executor_store(root, repo_root) as store:
            await store.accept_once(ticket)
            snapshot = await store.get(ticket.operation_id)
            assert snapshot is not None
            preparing = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="launch-preparing",
                    operation_id=ticket.operation_id,
                    expected_state=snapshot.state,
                    expected_state_version=snapshot.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                    reason_code="launch_prepare",
                    recorded_at=datetime.now(UTC),
                )
            )
            await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="launch-committed",
                    operation_id=ticket.operation_id,
                    expected_state=preparing.state,
                    expected_state_version=preparing.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_COMMITTED,
                    reason_code="launch_commit",
                    recorded_at=datetime.now(UTC),
                )
            )
        async with executor_store(root, repo_root, migrate=False) as reopened:
            report = await ExecutorRestartReconciler(reopened).reconcile()
            retained = await reopened.get(ticket.operation_id)
            assert report.readiness == "recovering"
            assert retained is not None
            assert retained.state is ExecutorEvidenceState.EXECUTOR_UNCERTAIN
            assert retained.launch_generation == 1

    asyncio.run(exercise())


def test_restart_rejects_cross_table_ticket_identity_collision(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[2]
        async with executor_store(root, repo_root) as store:
            await store.accept_once(ticket)
        database = root / "state/executor-state.sqlite3"
        with sqlite3.connect(database) as connection:
            timestamp = NOW.isoformat(timespec="microseconds")
            connection.execute(
                """
                INSERT INTO pending_cancel_intents (
                    operation_id, ticket_id, ticket_sha256, nonce_sha256, boot_id_digest,
                    ticket_expires_at, monotonic_deadline_ns, cancel_generation,
                    last_evidence_generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 2, ?, ?)
                """,
                (
                    "op-other",
                    ticket.ticket_id,
                    "e" * 64,
                    "f" * 64,
                    ticket.boot_id_digest,
                    ticket.expires_at.isoformat(timespec="microseconds"),
                    ticket.monotonic_deadline_ns,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO executor_evidence_events (
                    evidence_generation, event_id, operation_id, ticket_id, execution_id,
                    event_type, from_state, to_state, reason, event_sha256, recorded_at
                ) VALUES (2, 'tampered-event', 'op-other', ?, NULL,
                          'cancel.pending_preaccept', NULL, NULL,
                          'tampered', ?, ?)
                """,
                (ticket.ticket_id, "d" * 64, timestamp),
            )
            connection.execute(
                "UPDATE executor_meta SET evidence_generation_high_water=2 WHERE id=1"
            )
        with pytest.raises(ExecutorStoreError, match="durable evidence verification"):
            async with executor_store(root, repo_root, migrate=False):
                pass

    asyncio.run(exercise())

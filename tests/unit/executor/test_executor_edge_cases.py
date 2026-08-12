from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from tests.phase7_support import (
    BOOT_SHA,
    SHA_A,
    SHA_B,
    SHA_C,
    SHA_D,
    execution_ticket,
    executor_store,
    migrate_executor_database,
)

from binnacle.domain.execution import (
    CancelDisposition,
    CreateReceiptDisposition,
    ExecutionConflictError,
    ExecutionError,
    ExecutionStartDisposition,
    ExecutionTicket,
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
    canonical_sha256,
    canonical_timestamp,
)
from binnacle.executor import integrity as executor_integrity
from binnacle.executor import state as executor_state
from binnacle.executor.backend import (
    ExecutionBackendUnavailable,
    UnavailableExecutionDomainBackend,
)
from binnacle.executor.config import (
    ExecutorConfigError,
    boot_id_digest,
    load_executor_settings,
)
from binnacle.executor.integrity import (
    ExecutorIntegrityError,
    ExecutorIntegrityReport,
    verify_executor_connection,
)
from binnacle.executor.reconcile import ExecutorRestartReconciler
from binnacle.executor.state import (
    EXECUTOR_REVISION,
    ExecutorStoreError,
    ExecutorStoreIdentity,
    ExecutorStoreSettings,
    open_executor_store,
)
from binnacle.ports.execution import DomainHandle, SignalRequest

_CONFIG = """
[executor]
database_path = "/var/lib/binnacle-executor/state/executor-state.sqlite3"
runtime_directory = "/run/binnacle-executor/private"
output_directory = "/var/lib/binnacle-executor/output"
expected_application_uid = 1200
expected_application_gid = 1200
build_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
profile_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
busy_timeout_ms = 5000
"""


def _write_config(path: Path, content: str = _CONFIG) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o640)


def _identity() -> ExecutorStoreIdentity:
    return ExecutorStoreIdentity(
        supervisor_instance_id="supervisor-edge-case",
        boot_id_digest=BOOT_SHA,
        protocol_version="1.0",
        build_sha256=SHA_B,
        profile_sha256=SHA_C,
    )


def _migrated_database(root: Path) -> Path:
    state = root / "state"
    state.mkdir(parents=True)
    database = state / "executor-state.sqlite3"
    migrate_executor_database(database, Path(__file__).parents[3])
    return database


def _verify_database(
    database: Path,
    *,
    revision: str = EXECUTOR_REVISION,
) -> ExecutorIntegrityReport:
    with closing(sqlite3.connect(database)) as connection, connection:
        return verify_executor_connection(connection, expected_revision=revision)


def _ticket_from_wire(**changes: object) -> ExecutionTicket:
    wire = execution_ticket().to_wire()
    wire.update(changes)
    digest_document = dict(wire)
    digest_document.pop("ticket_sha256")
    wire["ticket_sha256"] = canonical_sha256(digest_document)
    return ExecutionTicket.from_wire(wire)


def _accepted_database(root: Path) -> Path:
    async def prepare() -> None:
        async with executor_store(root, Path(__file__).parents[3]) as store:
            await store.accept_once(execution_ticket())

    asyncio.run(prepare())
    return root / "state/executor-state.sqlite3"


def _pending_database(root: Path) -> Path:
    async def prepare() -> None:
        async with executor_store(root, Path(__file__).parents[3]) as store:
            await store.cancel_or_attach(
                identity=execution_ticket().routing_identity,
                cancel_generation=1,
            )

    asyncio.run(prepare())
    return root / "state/executor-state.sqlite3"


def _tombstone_database(root: Path) -> Path:
    async def prepare() -> None:
        ticket = execution_ticket()
        async with executor_store(root, Path(__file__).parents[3]) as store:
            await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="edge_case_no_accept",
                close_generation=1,
                retain_until=ticket.expires_at + timedelta(hours=1),
            )

    asyncio.run(prepare())
    return root / "state/executor-state.sqlite3"


def test_config_loader_rejects_symlink_invalid_toml_and_oversize(tmp_path: Path) -> None:
    target = tmp_path / "target.toml"
    _write_config(target)
    alias = tmp_path / "executor.toml"
    alias.symlink_to(target)
    with pytest.raises(ExecutorConfigError, match="could not be loaded"):
        load_executor_settings(alias, expected_owner_uid=os.geteuid())

    malformed = tmp_path / "malformed.toml"
    _write_config(malformed, "[executor\n")
    with pytest.raises(ExecutorConfigError, match="could not be loaded"):
        load_executor_settings(malformed, expected_owner_uid=os.geteuid())

    oversized = tmp_path / "oversized.toml"
    _write_config(oversized, "x" * 65_537)
    with pytest.raises(ExecutorConfigError, match="exceeds the reviewed limit"):
        load_executor_settings(oversized, expected_owner_uid=os.geteuid())


@pytest.mark.parametrize(
    ("content", "message"),
    (
        (
            _CONFIG.replace(
                "/var/lib/binnacle-executor/state/executor-state.sqlite3",
                "/tmp/executor-state.sqlite3",
            ),
            "database path is not the protected path",
        ),
        (
            _CONFIG.replace("expected_application_uid = 1200", "expected_application_uid = 0"),
            "peer identity is invalid",
        ),
        (
            _CONFIG.replace("expected_application_uid = 1200", "expected_application_uid = true"),
            "must be an integer",
        ),
        (
            _CONFIG.replace("busy_timeout_ms = 5000", "busy_timeout_ms = 99"),
            "busy timeout is outside the safe range",
        ),
        (
            _CONFIG.replace("a" * 64, "not-a-digest"),
            "runtime digest is invalid",
        ),
    ),
)
def test_config_loader_rejects_unsafe_values(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "executor.toml"
    _write_config(path, content)

    with pytest.raises(ExecutorConfigError, match=message):
        load_executor_settings(path, expected_owner_uid=os.geteuid())


def test_boot_identity_rejects_missing_empty_and_oversize_sources(tmp_path: Path) -> None:
    with pytest.raises(ExecutorConfigError, match="unavailable"):
        boot_id_digest(tmp_path / "missing")

    path = tmp_path / "boot-id"
    path.write_bytes(b"")
    with pytest.raises(ExecutorConfigError, match="invalid"):
        boot_id_digest(path)

    path.write_bytes(b"x" * 129)
    with pytest.raises(ExecutorConfigError, match="invalid"):
        boot_id_digest(path)


def test_unavailable_backend_denies_every_operation() -> None:
    async def exercise() -> None:
        backend = UnavailableExecutionDomainBackend()
        handle = DomainHandle(execution_id="execution-fixture", backend_reference="backend-fixture")
        request = SignalRequest(cancel_generation=1, graceful_timeout_seconds=1.0)

        assert await backend.ready() is False
        with pytest.raises(ExecutionBackendUnavailable, match="not promoted"):
            await backend.create(execution_ticket(), "execution-fixture")
        with pytest.raises(ExecutionBackendUnavailable, match="not promoted"):
            await backend.inspect(handle)
        with pytest.raises(ExecutionBackendUnavailable, match="not promoted"):
            await backend.signal(handle, request)
        with pytest.raises(ExecutionBackendUnavailable, match="not promoted"):
            await backend.terminate_tree(handle)
        with pytest.raises(ExecutionBackendUnavailable, match="not promoted"):
            await backend.cleanup(handle)

    asyncio.run(exercise())


def test_integrity_rejects_revision_and_unexpected_tables(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path / "executor")
    report = _verify_database(database)
    assert report.readiness == "uninitialized"
    assert report.evidence_generation == 0

    with pytest.raises(ExecutorIntegrityError, match="identity is incompatible"):
        _verify_database(database, revision="wrong-revision")

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE unexpected_executor_state (id INTEGER PRIMARY KEY)")
    with pytest.raises(ExecutorIntegrityError, match="table set is incompatible"):
        _verify_database(database)


def test_integrity_rejects_event_gaps_and_illegal_transitions(tmp_path: Path) -> None:
    gap_database = _migrated_database(tmp_path / "gap")
    with closing(sqlite3.connect(gap_database)) as connection, connection:
        connection.execute("UPDATE executor_meta SET evidence_generation_high_water=1 WHERE id=1")
    with pytest.raises(ExecutorIntegrityError, match="generation sequence has a gap"):
        _verify_database(gap_database)

    transition_database = _migrated_database(tmp_path / "transition")
    with closing(sqlite3.connect(transition_database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO executor_evidence_events (
                evidence_generation, event_id, operation_id, ticket_id, execution_id,
                event_type, from_state, to_state, reason, event_sha256, recorded_at
            ) VALUES (1, 'event-illegal', 'operation-orphan', 'ticket-orphan', NULL,
                      'execution.state_changed', 'closed', 'running', 'tampered', ?, ?)
            """,
            (SHA_A, datetime.now(UTC).isoformat(timespec="microseconds")),
        )
        connection.execute("UPDATE executor_meta SET evidence_generation_high_water=1 WHERE id=1")
    with pytest.raises(ExecutorIntegrityError, match="illegal state transition"):
        _verify_database(transition_database)


def test_store_settings_and_identity_fail_before_database_access(tmp_path: Path) -> None:
    with pytest.raises(ExecutorStoreError, match="supervisor instance identity"):
        ExecutorStoreIdentity("", BOOT_SHA, "1.0", SHA_B, SHA_C)
    with pytest.raises(ExecutorStoreError, match="runtime identity digest"):
        ExecutorStoreIdentity("supervisor", "invalid", "1.0", SHA_B, SHA_C)
    with pytest.raises(ExecutorStoreError, match="protocol version"):
        ExecutorStoreIdentity("supervisor", BOOT_SHA, "", SHA_B, SHA_C)

    async def exercise() -> None:
        cases = (
            (
                ExecutorStoreSettings(path=tmp_path / "wrong.sqlite3"),
                "database filename is fixed",
            ),
            (
                ExecutorStoreSettings(
                    path=tmp_path / "executor-state.sqlite3",
                    busy_timeout_ms=99,
                ),
                "busy timeout is outside the safe range",
            ),
            (
                ExecutorStoreSettings(
                    path=tmp_path / "executor-state.sqlite3",
                    maximum_launch_spec_bytes=65_535,
                ),
                "launch-spec limit is outside the safe range",
            ),
        )
        for settings, message in cases:
            with pytest.raises(ExecutorStoreError, match=message):
                await open_executor_store(settings=settings, identity=_identity())

    asyncio.run(exercise())


def test_store_lock_is_exclusive_and_released_on_close(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "executor"
        database = _migrated_database(root)
        runtime = root / "run"
        runtime.mkdir()
        settings = ExecutorStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        )
        first = await open_executor_store(settings=settings, identity=_identity())
        try:
            with pytest.raises(ExecutorStoreError, match="writer or maintenance process is active"):
                await open_executor_store(settings=settings, identity=_identity())
        finally:
            await first.close()

        reopened = await open_executor_store(settings=settings, identity=_identity())
        await reopened.close()

    asyncio.run(exercise())


def test_store_rejects_invalid_queries_readiness_and_event_targets(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            with pytest.raises(ExecutionError, match="cancel generation must be positive"):
                await store.cancel_or_attach(
                    identity=execution_ticket().routing_identity,
                    cancel_generation=0,
                )
            with pytest.raises(ExecutionError, match="list request exceeds"):
                await store.list(tuple(f"operation-{index}" for index in range(257)))
            for limit in (0, 257):
                with pytest.raises(ExecutionError, match="page limit is invalid"):
                    await store.list_outstanding(limit=limit)
            with pytest.raises(ExecutorStoreError, match="readiness value is invalid"):
                await store.set_readiness("unknown")

            await store.accept_once(execution_ticket())
            with pytest.raises(ExecutorStoreError, match="unresolved executions"):
                await store.set_readiness("ready")
            with pytest.raises(ExecutorStoreError, match="event target is unavailable"):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="missing-event-target",
                        operation_id="missing-operation",
                        expected_state=ExecutorEvidenceState.ACCEPTED,
                        expected_state_version=1,
                        target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                        reason_code="missing_target",
                        recorded_at=datetime.now(UTC),
                    )
                )

    asyncio.run(exercise())


def test_event_replay_is_idempotent_but_event_id_reuse_conflicts(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            await store.accept_once(execution_ticket())
            current = await store.get("op-fixture")
            assert current is not None
            event = ExecutorEvidenceEvent(
                event_id="edge-event",
                operation_id=current.operation_id,
                expected_state=current.state,
                expected_state_version=current.state_version,
                target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                reason_code="edge_uncertain",
                recorded_at=datetime.now(UTC),
            )
            applied = await store.apply_event(event)
            assert await store.apply_event(event) == applied

            conflicting = ExecutorEvidenceEvent(
                event_id=event.event_id,
                operation_id=applied.operation_id,
                expected_state=applied.state,
                expected_state_version=applied.state_version,
                target_state=ExecutorEvidenceState.CLOSED,
                reason_code="edge_closed",
                recorded_at=datetime.now(UTC),
                terminal_reason="no_domain_created",
                descendants_stopped=True,
                output_finalized=True,
                cleanup_complete=True,
                terminal_evidence_sha256=SHA_A,
                cleanup_evidence_sha256=SHA_B,
            )
            with pytest.raises(ExecutionConflictError, match="event identity was reused"):
                await store.apply_event(conflicting)

    asyncio.run(exercise())


def test_restart_reconciler_closes_an_already_uncertain_prelaunch_row(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[3]
        async with executor_store(root, repo_root) as store:
            await store.accept_once(execution_ticket())
            current = await store.get("op-fixture")
            assert current is not None
            await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="prelaunch-uncertain",
                    operation_id=current.operation_id,
                    expected_state=current.state,
                    expected_state_version=current.state_version,
                    target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                    reason_code="prelaunch_uncertain",
                    recorded_at=datetime.now(UTC),
                )
            )

        async with executor_store(root, repo_root, migrate=False) as reopened:
            report = await ExecutorRestartReconciler(reopened).reconcile()
            closed = await reopened.get("op-fixture")
            assert report.closed_without_launch == 1
            assert report.readiness == "ready"
            assert closed is not None
            assert closed.state is ExecutorEvidenceState.CLOSED

    asyncio.run(exercise())


def test_restart_reconciler_does_not_rewrite_terminal_committed_evidence(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "executor"
        repo_root = Path(__file__).parents[3]
        async with executor_store(root, repo_root) as store:
            await store.accept_once(execution_ticket())
            accepted = await store.get("op-fixture")
            assert accepted is not None
            preparing = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="edge-launch-preparing",
                    operation_id=accepted.operation_id,
                    expected_state=accepted.state,
                    expected_state_version=accepted.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                    reason_code="launch_prepare",
                    recorded_at=datetime.now(UTC),
                )
            )
            committed = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="edge-launch-committed",
                    operation_id=preparing.operation_id,
                    expected_state=preparing.state,
                    expected_state_version=preparing.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_COMMITTED,
                    reason_code="launch_commit",
                    recorded_at=datetime.now(UTC),
                    create_receipt_disposition=CreateReceiptDisposition.COMMITTED_PENDING,
                )
            )
            exited = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="edge-launch-exited",
                    operation_id=committed.operation_id,
                    expected_state=committed.state,
                    expected_state_version=committed.state_version,
                    target_state=ExecutorEvidenceState.EXITED,
                    reason_code="launch_exit",
                    recorded_at=datetime.now(UTC),
                    exit_code=1,
                    terminal_reason="command_failed",
                    terminal_evidence_sha256=SHA_A,
                )
            )

        async with executor_store(root, repo_root, migrate=False) as reopened:
            report = await ExecutorRestartReconciler(reopened).reconcile()
            retained = await reopened.get("op-fixture")
            assert report.unresolved_after_launch_commit == 1
            assert report.readiness == "recovering"
            assert retained == exited

    asyncio.run(exercise())


def test_store_identity_deadlines_and_launch_spec_limit_fail_closed(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "executor"
        database = _migrated_database(root)
        runtime = root / "run"
        runtime.mkdir()
        settings = ExecutorStoreSettings(
            path=database,
            runtime_directory=runtime,
            maximum_launch_spec_bytes=65_536,
            verify_permissions=False,
        )
        store = await open_executor_store(settings=settings, identity=_identity())
        try:
            assert store.supervisor_generation >= 2
            wrong_boot = _ticket_from_wire(boot_id_digest=SHA_A)
            with pytest.raises(ExecutionConflictError, match="boot identity"):
                await store.accept_once(wrong_boot)

            issued = datetime.now(UTC) - timedelta(minutes=2)
            expired = _ticket_from_wire(
                issued_at=canonical_timestamp(issued),
                expires_at=canonical_timestamp(issued + timedelta(minutes=1)),
            )
            with pytest.raises(ExecutionConflictError, match="deadline elapsed"):
                await store.accept_once(expired)

            stdin = b"x" * 65_536
            oversized = _ticket_from_wire(
                inline_stdin_base64=base64.b64encode(stdin).decode("ascii"),
                stdin_sha256=hashlib.sha256(stdin).hexdigest(),
            )
            with pytest.raises(ExecutorStoreError, match="launch specification exceeds"):
                await store.accept_once(oversized)
        finally:
            await store.close()
            await store.close()

    asyncio.run(exercise())


def test_cancel_replays_pending_updates_and_rolls_back_identity_conflict(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            first = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=1,
            )
            replay = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=1,
            )
            updated = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=3,
            )
            assert replay == first
            assert updated.acknowledged_cancel_generation == 3
            assert updated.evidence_generation > first.evidence_generation

            conflicting = execution_ticket(ticket_id="ticket-conflict", nonce="nonce-conflict")
            with pytest.raises(ExecutionConflictError, match="retained state"):
                await store.cancel_or_attach(
                    identity=conflicting.routing_identity,
                    cancel_generation=4,
                )
            retained = await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=3,
            )
            assert retained == updated

    asyncio.run(exercise())


def test_cancel_routes_uncertain_committed_and_already_requested_states(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            uncertain_ticket = execution_ticket()
            await store.accept_once(uncertain_ticket)
            uncertain = await store.get(uncertain_ticket.operation_id)
            assert uncertain is not None
            uncertain = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="cancel-uncertain-state",
                    operation_id=uncertain.operation_id,
                    expected_state=uncertain.state,
                    expected_state_version=uncertain.state_version,
                    target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                    reason_code="uncertain_before_cancel",
                    recorded_at=datetime.now(UTC),
                )
            )
            routed_uncertain = await store.cancel_or_attach(
                identity=uncertain_ticket.routing_identity,
                cancel_generation=1,
            )
            assert routed_uncertain.snapshot is not None
            assert routed_uncertain.snapshot.state is ExecutorEvidenceState.EXECUTOR_UNCERTAIN
            assert routed_uncertain.snapshot.cancel_disposition is CancelDisposition.UNCERTAIN

            committed_ticket = execution_ticket(
                operation_id="op-committed",
                ticket_id="ticket-committed",
                nonce="nonce-committed",
            )
            await store.accept_once(committed_ticket)
            committed = await store.get(committed_ticket.operation_id)
            assert committed is not None
            preparing = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="cancel-launch-preparing",
                    operation_id=committed.operation_id,
                    expected_state=committed.state,
                    expected_state_version=committed.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                    reason_code="launch_prepare",
                    recorded_at=datetime.now(UTC),
                )
            )
            committed = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="cancel-launch-committed",
                    operation_id=preparing.operation_id,
                    expected_state=preparing.state,
                    expected_state_version=preparing.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_COMMITTED,
                    reason_code="launch_commit",
                    recorded_at=datetime.now(UTC),
                )
            )
            routed_committed = await store.cancel_or_attach(
                identity=committed_ticket.routing_identity,
                cancel_generation=1,
            )
            assert routed_committed.snapshot is not None
            assert routed_committed.snapshot.state is ExecutorEvidenceState.CANCEL_REQUESTED
            assert routed_committed.snapshot.cancel_disposition is CancelDisposition.SIGNAL_PENDING

            routed_again = await store.cancel_or_attach(
                identity=committed_ticket.routing_identity,
                cancel_generation=2,
            )
            assert routed_again.snapshot is not None
            assert routed_again.snapshot.state is ExecutorEvidenceState.CANCEL_REQUESTED
            assert routed_again.snapshot.cancel_disposition is CancelDisposition.SIGNAL_PENDING

    asyncio.run(exercise())


def test_no_accept_validation_pending_consumption_and_tombstone_replay(tmp_path: Path) -> None:
    async def exercise() -> None:
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            with pytest.raises(ExecutionError, match="seal request is invalid"):
                await store.seal_no_accept(
                    identity=ticket.routing_identity,
                    reason="",
                    close_generation=0,
                    retain_until=ticket.expires_at,
                )
            with pytest.raises(ExecutionError, match="retention does not cover"):
                await store.seal_no_accept(
                    identity=ticket.routing_identity,
                    reason="invalid_retention",
                    close_generation=0,
                    retain_until=ticket.expires_at - timedelta(seconds=1),
                )

            await store.cancel_or_attach(
                identity=ticket.routing_identity,
                cancel_generation=2,
            )
            sealed = await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="runtime_lost",
                close_generation=1,
                retain_until=ticket.expires_at + timedelta(hours=1),
            )
            assert sealed.disposition is ExecutionStartDisposition.NO_ACCEPT_PROVEN
            assert sealed.acknowledged_cancel_generation == 2

            replay = await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="runtime_lost",
                close_generation=2,
                retain_until=ticket.expires_at + timedelta(hours=1),
            )
            advanced = await store.seal_no_accept(
                identity=ticket.routing_identity,
                reason="runtime_lost",
                close_generation=4,
                retain_until=ticket.expires_at + timedelta(hours=1),
            )
            assert replay.receipt_sha256 == sealed.receipt_sha256
            assert advanced.receipt_sha256 == sealed.receipt_sha256
            assert advanced.acknowledged_cancel_generation == 4
            assert advanced.evidence_generation > replay.evidence_generation

            conflicting = execution_ticket(ticket_id="ticket-other", nonce="nonce-other")
            with pytest.raises(ExecutionConflictError, match="retained state"):
                await store.seal_no_accept(
                    identity=conflicting.routing_identity,
                    reason="runtime_lost",
                    close_generation=4,
                    retain_until=conflicting.expires_at + timedelta(hours=1),
                )

    asyncio.run(exercise())


def test_lists_are_bounded_ordered_and_empty(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            assert await store.list(()) == ()
            later = execution_ticket(
                operation_id="op-z",
                ticket_id="ticket-z",
                nonce="nonce-z",
            )
            earlier = execution_ticket(
                operation_id="op-a",
                ticket_id="ticket-a",
                nonce="nonce-a",
            )
            await store.accept_once(later)
            await store.accept_once(earlier)
            listed = await store.list((later.operation_id, "missing", earlier.operation_id))
            assert {item.operation_id for item in listed} == {"op-a", "op-z"}
            outstanding = await store.list_outstanding(after_operation_id="op-a", limit=1)
            assert tuple(item.operation_id for item in outstanding) == ("op-z",)

    asyncio.run(exercise())


def test_durable_cancel_suppresses_a_tampered_launch_attempt(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            ticket = execution_ticket()
            await store.accept_once(ticket)
            await store._connection.execute(
                "UPDATE execution_records SET effective_cancel_generation=1, "
                "acknowledged_cancel_generation=1, cancel_disposition='attached_prelaunch' "
                "WHERE operation_id=?",
                (ticket.operation_id,),
            )
            await store._connection.commit()
            current = await store.get(ticket.operation_id)
            assert current is not None
            with pytest.raises(ExecutionConflictError, match="cancellation suppresses"):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="launch-after-durable-cancel",
                        operation_id=current.operation_id,
                        expected_state=current.state,
                        expected_state_version=current.state_version,
                        target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                        reason_code="launch_after_cancel",
                        recorded_at=datetime.now(UTC),
                    )
                )

    asyncio.run(exercise())


def test_create_receipt_and_retained_evidence_cannot_be_replaced(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            await store.accept_once(execution_ticket())
            accepted = await store.get("op-fixture")
            assert accepted is not None
            with pytest.raises(ExecutionConflictError, match="create receipt disposition"):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="invalid-create-disposition",
                        operation_id=accepted.operation_id,
                        expected_state=accepted.state,
                        expected_state_version=accepted.state_version,
                        target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                        reason_code="invalid_create_truth",
                        recorded_at=datetime.now(UTC),
                        create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
                    )
                )

            preparing = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="stable-evidence-prepare",
                    operation_id=accepted.operation_id,
                    expected_state=accepted.state,
                    expected_state_version=accepted.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
                    reason_code="launch_prepare",
                    recorded_at=datetime.now(UTC),
                )
            )
            committed = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="stable-evidence-commit",
                    operation_id=preparing.operation_id,
                    expected_state=preparing.state,
                    expected_state_version=preparing.state_version,
                    target_state=ExecutorEvidenceState.LAUNCH_COMMITTED,
                    reason_code="launch_commit",
                    recorded_at=datetime.now(UTC),
                    backend_reference="backend-stable",
                    backend_domain_identity_sha256=SHA_A,
                )
            )
            with pytest.raises(
                ExecutionConflictError,
                match="backend reference cannot be replaced",
            ):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="replace-stable-evidence",
                        operation_id=committed.operation_id,
                        expected_state=committed.state,
                        expected_state_version=committed.state_version,
                        target_state=ExecutorEvidenceState.RUNNING,
                        reason_code="replace_backend",
                        recorded_at=datetime.now(UTC),
                        backend_reference="backend-other",
                        create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
                    )
                )

            running = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="resolve-create-receipt",
                    operation_id=committed.operation_id,
                    expected_state=committed.state,
                    expected_state_version=committed.state_version,
                    target_state=ExecutorEvidenceState.RUNNING,
                    reason_code="domain_created",
                    recorded_at=datetime.now(UTC),
                    backend_reference="backend-stable",
                    backend_domain_identity_sha256=SHA_A,
                    create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
                )
            )
            assert running.create_receipt_disposition is CreateReceiptDisposition.DOMAIN_CREATED

    asyncio.run(exercise())


def test_no_domain_closure_rejects_nonempty_unfinalized_stream(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            await store.accept_once(execution_ticket())
            accepted = await store.get("op-fixture")
            assert accepted is not None
            uncertain = await store.apply_event(
                ExecutorEvidenceEvent(
                    event_id="contradictory-output-uncertain",
                    operation_id=accepted.operation_id,
                    expected_state=accepted.state,
                    expected_state_version=accepted.state_version,
                    target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                    reason_code="prelaunch_uncertain",
                    recorded_at=datetime.now(UTC),
                )
            )
            await store._connection.execute(
                "UPDATE execution_streams SET observed_bytes=1 WHERE execution_id=? "
                "AND stream='stdout'",
                (uncertain.execution_id,),
            )
            await store._connection.commit()
            with pytest.raises(ExecutorStoreError, match="cannot finalize contradictory output"):
                await store.apply_event(
                    ExecutorEvidenceEvent(
                        event_id="contradictory-output-close",
                        operation_id=uncertain.operation_id,
                        expected_state=uncertain.state,
                        expected_state_version=uncertain.state_version,
                        target_state=ExecutorEvidenceState.CLOSED,
                        reason_code="no_domain_created",
                        recorded_at=datetime.now(UTC),
                        terminal_reason="no_domain_created",
                        descendants_stopped=True,
                        output_finalized=True,
                        cleanup_complete=True,
                        terminal_evidence_sha256=SHA_A,
                        cleanup_evidence_sha256=SHA_B,
                    )
                )

    asyncio.run(exercise())


class _QuickCheckCursor:
    def fetchone(self) -> tuple[str]:
        return ("corrupt",)


class _QuickCheckFailure:
    def execute(self, query: str) -> _QuickCheckCursor:
        assert query == "PRAGMA quick_check"
        return _QuickCheckCursor()


def test_integrity_wraps_invalid_values_and_rejects_failed_quick_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ExecutorIntegrityError, match="SQLite integrity check failed"):
        verify_executor_connection(
            cast(sqlite3.Connection, _QuickCheckFailure()),
            expected_revision=EXECUTOR_REVISION,
        )

    def invalid_value(
        connection: sqlite3.Connection,
        *,
        expected_revision: str,
    ) -> ExecutorIntegrityReport:
        del connection, expected_revision
        raise ValueError("private malformed value")

    monkeypatch.setattr(executor_integrity, "_verify_executor_connection", invalid_value)
    with (
        closing(sqlite3.connect(":memory:")) as connection,
        pytest.raises(ExecutorIntegrityError, match="contains an invalid value"),
    ):
        verify_executor_connection(connection, expected_revision=EXECUTOR_REVISION)


def test_integrity_rejects_contradictory_metadata_and_orphan_events(tmp_path: Path) -> None:
    contradictory = _migrated_database(tmp_path / "contradictory")
    with closing(sqlite3.connect(contradictory)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("DROP TRIGGER executor_meta_guarded_update")
        connection.execute("UPDATE executor_meta SET schema_generation=2 WHERE id=1")
        with pytest.raises(ExecutorIntegrityError, match="metadata is contradictory"):
            verify_executor_connection(connection, expected_revision=EXECUTOR_REVISION)

    orphan = _migrated_database(tmp_path / "orphan")
    with closing(sqlite3.connect(orphan)) as connection, connection:
        connection.execute(
            """
            INSERT INTO executor_evidence_events (
                evidence_generation, event_id, operation_id, ticket_id, execution_id,
                event_type, from_state, to_state, reason, event_sha256, recorded_at
            ) VALUES (1, 'orphan-event', 'orphan-operation', 'orphan-ticket', NULL,
                      'cancel.pending_preaccept', NULL, NULL, 'orphan', ?, ?)
            """,
            (SHA_A, canonical_timestamp(datetime.now(UTC))),
        )
        connection.execute("UPDATE executor_meta SET evidence_generation_high_water=1 WHERE id=1")
    with pytest.raises(ExecutorIntegrityError, match="no exact retained acceptance home"):
        _verify_database(orphan)


def test_integrity_rejects_multiple_acceptance_homes(tmp_path: Path) -> None:
    database = _pending_database(tmp_path / "executor")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO no_accept_tombstones (
                operation_id, ticket_id, ticket_sha256, nonce_sha256, boot_id_digest,
                ticket_expires_at, monotonic_deadline_ns, reason, sealed_cancel_generation,
                closed_cancel_generation, last_evidence_generation, seal_reference,
                receipt_sha256, sealed_at, retain_until
            )
            SELECT operation_id, ticket_id, ticket_sha256, nonce_sha256, boot_id_digest,
                   ticket_expires_at, monotonic_deadline_ns, 'conflicting_home',
                   cancel_generation, cancel_generation, last_evidence_generation,
                   'conflicting-seal', ?, created_at, ticket_expires_at
            FROM pending_cancel_intents
            """,
            (SHA_A,),
        )
    with pytest.raises(ExecutorIntegrityError, match="multiple homes"):
        _verify_database(database)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("launch_json", "launch specification is not JSON"),
        ("launch_digest", "launch specification digest is invalid"),
        ("accepted_receipt", "accepted receipt is not stable"),
        ("accepted_event", "accepted receipt has no exact event"),
        ("missing_stream", "output stream set is incomplete"),
        ("stream_path", "output evidence is contradictory"),
        ("false_finalization", "unfinalized output is final"),
        ("event_head_range", "evidence head is outside"),
        ("event_head_state", "does not match its event history"),
    ),
)
def test_integrity_rejects_tampered_accepted_evidence(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    database = _accepted_database(tmp_path / case)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        if case == "launch_json":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute("UPDATE execution_records SET launch_spec_json='{'")
        elif case == "launch_digest":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute("UPDATE execution_records SET launch_spec_sha256=?", (SHA_D,))
        elif case == "accepted_receipt":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute("UPDATE execution_records SET accepted_receipt_sha256=?", (SHA_D,))
        elif case == "accepted_event":
            connection.execute("DROP TRIGGER executor_evidence_events_no_update")
            connection.execute(
                "UPDATE executor_evidence_events SET event_type='tampered.acceptance'"
            )
        elif case == "missing_stream":
            connection.execute("DROP TRIGGER execution_streams_no_delete")
            connection.execute("DELETE FROM execution_streams WHERE stream='stderr'")
        elif case == "stream_path":
            connection.execute("DROP TRIGGER execution_streams_guarded_update")
            connection.execute(
                "UPDATE execution_streams SET relative_path='wrong/path.bin' WHERE stream='stdout'"
            )
        elif case == "false_finalization":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute("UPDATE execution_records SET output_finalized=1")
        elif case == "event_head_range":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute("UPDATE execution_records SET last_evidence_generation=2")
        elif case == "event_head_state":
            connection.execute("DROP TRIGGER execution_records_guarded_update")
            connection.execute(
                "UPDATE execution_records SET state='executor_uncertain', state_version=2"
            )
        else:  # pragma: no cover - exhaustive parameter table.
            raise AssertionError(case)

    with pytest.raises(ExecutorIntegrityError, match=message):
        _verify_database(database)


def test_integrity_verifies_and_rejects_routing_evidence(tmp_path: Path) -> None:
    pending = _pending_database(tmp_path / "pending-valid")
    pending_report = _verify_database(pending)
    assert pending_report.pending_cancels == 1

    invalid_generation = _pending_database(tmp_path / "pending-generation")
    with closing(sqlite3.connect(invalid_generation)) as connection, connection:
        connection.execute("DROP TRIGGER pending_cancel_intents_guarded_update")
        connection.execute("UPDATE pending_cancel_intents SET last_evidence_generation=2")
    with pytest.raises(ExecutorIntegrityError, match="routing evidence generation is invalid"):
        _verify_database(invalid_generation)

    wrong_event = _pending_database(tmp_path / "pending-event")
    with closing(sqlite3.connect(wrong_event)) as connection, connection:
        connection.execute("DROP TRIGGER executor_evidence_events_no_update")
        connection.execute("UPDATE executor_evidence_events SET operation_id='other-operation'")
    with pytest.raises(ExecutorIntegrityError, match="routing evidence has no exact event"):
        _verify_database(wrong_event)

    tombstone = _tombstone_database(tmp_path / "tombstone-valid")
    tombstone_report = _verify_database(tombstone)
    assert tombstone_report.no_accept_tombstones == 1

    invalid_receipt = _tombstone_database(tmp_path / "tombstone-receipt")
    with closing(sqlite3.connect(invalid_receipt)) as connection, connection:
        connection.execute("DROP TRIGGER no_accept_tombstones_guarded_update")
        connection.execute("UPDATE no_accept_tombstones SET receipt_sha256=?", (SHA_D,))
    with pytest.raises(ExecutorIntegrityError, match="no-accept receipt is invalid"):
        _verify_database(invalid_receipt)


def test_integrity_scalar_guards_reject_unsafe_types_and_normalize_naive_time() -> None:
    with pytest.raises(ExecutorIntegrityError, match="timestamp is invalid"):
        executor_integrity._timestamp(1)
    with pytest.raises(ExecutorIntegrityError, match="integer field is invalid"):
        executor_integrity._integer(True)
    parsed = executor_integrity._timestamp("2026-01-02T03:04:05")
    assert parsed.tzinfo is UTC


def test_store_path_permission_and_type_guards(tmp_path: Path) -> None:
    async def expect(settings: ExecutorStoreSettings, message: str) -> None:
        with pytest.raises(ExecutorStoreError, match=message):
            await open_executor_store(settings=settings, identity=_identity())

    async def exercise() -> None:
        target = tmp_path / "target.sqlite3"
        target.touch()
        symlink = tmp_path / "executor-state.sqlite3"
        symlink.symlink_to(target)
        await expect(ExecutorStoreSettings(path=symlink), "may not be a symlink")

        missing = tmp_path / "missing/state/executor-state.sqlite3"
        await expect(ExecutorStoreSettings(path=missing), "state directory is unavailable")

        unsafe_parent = tmp_path / "unsafe-parent"
        unsafe_parent.write_text("not a directory", encoding="utf-8")
        await expect(
            ExecutorStoreSettings(path=unsafe_parent / "executor-state.sqlite3"),
            "state directory is unsafe",
        )

        broad_root = tmp_path / "broad"
        database = _migrated_database(broad_root)
        database.parent.chmod(0o755)
        await expect(ExecutorStoreSettings(path=database), "ownership/mode is invalid")
        database.parent.chmod(0o700)

        missing_runtime = broad_root / "missing-run"
        await expect(
            ExecutorStoreSettings(path=database, runtime_directory=missing_runtime),
            "runtime directory is unavailable",
        )

        runtime_file = broad_root / "runtime-file"
        runtime_file.write_text("not a directory", encoding="utf-8")
        await expect(
            ExecutorStoreSettings(path=database, runtime_directory=runtime_file),
            "runtime directory is unsafe",
        )

        runtime = broad_root / "runtime"
        runtime.mkdir(mode=0o755)
        await expect(
            ExecutorStoreSettings(path=database, runtime_directory=runtime),
            "runtime directory ownership/mode is invalid",
        )

    asyncio.run(exercise())


def test_store_internal_guards_reject_missing_rows_and_invalid_scalars(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            assert store.readiness == "ready"
            assert await store.list(("missing-operation",)) == ()
            with pytest.raises(AssertionError, match="unreviewed executor identity table"):
                await store._find_identity_row(
                    "unreviewed_table",
                    execution_ticket().routing_identity,
                )
            with pytest.raises(ExecutorStoreError, match="accepted executor record"):
                await store._get_required("missing-operation")
            with pytest.raises(ExecutorStoreError, match="query returned no row"):
                await executor_state._single_value(
                    store._connection,
                    "SELECT id FROM executor_meta WHERE id=999",
                )

        with pytest.raises(ExecutorStoreError, match="timestamp is invalid"):
            executor_state._timestamp(1)
        parsed = executor_state._timestamp("2026-01-02T03:04:05")
        assert parsed.tzinfo is UTC
        with pytest.raises(ExecutorStoreError, match="integer field is invalid"):
            executor_state._as_int(1.5)

    asyncio.run(exercise())


def test_store_missing_metadata_rolls_back_next_generation(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with executor_store(tmp_path / "executor", Path(__file__).parents[3]) as store:
            await store._connection.execute("DROP TRIGGER executor_meta_no_delete")
            await store._connection.execute("DELETE FROM executor_meta")
            await store._connection.commit()
            with pytest.raises(ExecutorStoreError, match="metadata is absent"):
                await store.accept_once(execution_ticket())

    asyncio.run(exercise())


def test_open_rejects_outstanding_identity_change_and_releases_lock(tmp_path: Path) -> None:
    root = tmp_path / "executor"
    database = _accepted_database(root)

    async def exercise() -> None:
        runtime = root / "run"
        settings = ExecutorStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        )
        changed = ExecutorStoreIdentity(
            supervisor_instance_id="supervisor-changed",
            boot_id_digest=BOOT_SHA,
            protocol_version="1.0",
            build_sha256=SHA_D,
            profile_sha256=SHA_C,
        )
        with pytest.raises(ExecutorStoreError, match="requires exact recovery"):
            await open_executor_store(settings=settings, identity=changed)

        reopened = await open_executor_store(settings=settings, identity=_identity())
        await reopened.close()

    asyncio.run(exercise())


def test_open_rechecks_metadata_after_integrity_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        root = tmp_path / "executor"
        database = _migrated_database(root)
        runtime = root / "run"
        runtime.mkdir()
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("DROP TRIGGER executor_meta_no_delete")
            connection.execute("DELETE FROM executor_meta")

        report = ExecutorIntegrityReport(
            revision=EXECUTOR_REVISION,
            readiness="uninitialized",
            schema_generation=1,
            evidence_generation=0,
            accepted_executions=0,
            pending_cancels=0,
            no_accept_tombstones=0,
            outstanding_executions=0,
        )
        monkeypatch.setattr(
            executor_state,
            "verify_executor_connection",
            lambda *args, **kwargs: report,
        )
        with pytest.raises(ExecutorStoreError, match="metadata is absent or incompatible"):
            await open_executor_store(
                settings=ExecutorStoreSettings(
                    path=database,
                    runtime_directory=runtime,
                    verify_permissions=False,
                ),
                identity=_identity(),
            )

    asyncio.run(exercise())

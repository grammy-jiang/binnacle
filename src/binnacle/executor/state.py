"""Executor-owned durable single-use acceptance and lifecycle evidence."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import quote

import aiosqlite

from binnacle.domain.execution import (
    CancelDisposition,
    CancelRoutingDisposition,
    CancelRoutingResult,
    CreateReceiptDisposition,
    ExecutionConflictError,
    ExecutionError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
    ExecutorSnapshot,
    NoAcceptSealResult,
    TicketRoutingIdentity,
    canonical_sha256,
    canonical_timestamp,
    ticket_correlation_sha256,
)
from binnacle.executor.integrity import (
    ExecutorIntegrityError,
    verify_executor_connection,
)

EXECUTOR_REVISION: Final = "0001_executor_evidence"
_ZERO_DIGEST: Final = "0" * 64


class ExecutorStoreError(RuntimeError):
    """Executor evidence storage is unavailable, corrupt, or contradictory."""


@dataclass(frozen=True, slots=True)
class ExecutorStoreSettings:
    path: Path = Path("/var/lib/binnacle-executor/state/executor-state.sqlite3")
    runtime_directory: Path = Path("/run/binnacle-executor/private")
    busy_timeout_ms: int = 5_000
    maximum_launch_spec_bytes: int = 1_048_576
    verify_permissions: bool = True


@dataclass(frozen=True, slots=True)
class ExecutorStoreIdentity:
    supervisor_instance_id: str
    boot_id_digest: str
    protocol_version: str
    build_sha256: str
    profile_sha256: str

    def __post_init__(self) -> None:
        if not self.supervisor_instance_id or len(self.supervisor_instance_id) > 160:
            raise ExecutorStoreError("supervisor instance identity is invalid")
        for value in (self.boot_id_digest, self.build_sha256, self.profile_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ExecutorStoreError("executor runtime identity digest is invalid")
        if not self.protocol_version or len(self.protocol_version) > 32:
            raise ExecutorStoreError("executor protocol version is invalid")


@dataclass(slots=True)
class _StoreLock:
    descriptor: int

    def close(self) -> None:
        if self.descriptor < 0:
            return
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1


class SqliteExecutorEvidenceStore:
    """One short FULL transaction owns every accept/cancel/seal decision."""

    def __init__(
        self,
        *,
        connection: aiosqlite.Connection,
        settings: ExecutorStoreSettings,
        identity: ExecutorStoreIdentity,
        runtime_lock: _StoreLock,
        supervisor_generation: int,
        readiness: str,
    ) -> None:
        self._connection = connection
        self._settings = settings
        self._identity = identity
        self._runtime_lock = runtime_lock
        self._supervisor_generation = supervisor_generation
        self._readiness = readiness
        self._acceptance_gate = asyncio.Lock()
        self._closed = False

    @property
    def supervisor_generation(self) -> int:
        return self._supervisor_generation

    @property
    def readiness(self) -> str:
        return self._readiness

    async def accept_once(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
        if ticket.boot_id_digest != self._identity.boot_id_digest:
            raise ExecutionConflictError("ticket boot identity does not match executor")
        async with self._acceptance_gate:
            await self._begin()
            try:
                tombstone = await self._find_identity_row(
                    "no_accept_tombstones", ticket.routing_identity
                )
                if tombstone is not None:
                    self._require_exact_routing(tombstone, ticket.routing_identity)
                    result = self._no_accept_start_receipt(tombstone)
                    await self._connection.commit()
                    return result
                retained = await self._find_identity_row(
                    "execution_records", ticket.routing_identity
                )
                if retained is not None:
                    self._require_exact_routing(retained, ticket.routing_identity)
                    result = self._accepted_start_receipt(retained)
                    await self._connection.commit()
                    return result
                pending = await self._find_identity_row(
                    "pending_cancel_intents", ticket.routing_identity
                )
                if pending is not None:
                    self._require_exact_routing(pending, ticket.routing_identity)
                now = datetime.now(UTC)
                if now >= ticket.expires_at or time.monotonic_ns() >= ticket.monotonic_deadline_ns:
                    raise ExecutionConflictError("ticket acceptance deadline elapsed")
                await self._require_no_cross_table_conflict(ticket.routing_identity)
                launch_spec = self._launch_spec(ticket)
                launch_bytes = _canonical_bytes(launch_spec)
                if len(launch_bytes) > self._settings.maximum_launch_spec_bytes:
                    raise ExecutorStoreError("executor launch specification exceeds its limit")
                generation = await self._next_evidence_generation()
                execution_id = f"exec_{ticket.ticket_sha256[:24]}"
                accepted_at = datetime.now(UTC)
                executor_reference = f"accept_{ticket.ticket_sha256[:24]}"
                accepted_receipt_sha256 = _accepted_receipt_sha256(
                    operation_id=ticket.operation_id,
                    execution_id=execution_id,
                    evidence_generation=generation,
                    executor_reference=executor_reference,
                )
                cancel_generation = 0 if pending is None else _as_int(pending["cancel_generation"])
                if pending is not None:
                    await self._connection.execute(
                        "DELETE FROM pending_cancel_intents WHERE operation_id = ?",
                        (ticket.operation_id,),
                    )
                cancel_disposition = (
                    None if cancel_generation == 0 else CancelDisposition.ATTACHED_PRELAUNCH.value
                )
                initial_state = (
                    ExecutorEvidenceState.ACCEPTED
                    if cancel_generation == 0
                    else ExecutorEvidenceState.CANCEL_REQUESTED
                )
                await self._connection.execute(
                    """
                    INSERT INTO execution_records (
                        execution_id, operation_id, ticket_id, ticket_sha256, nonce_sha256,
                        boot_id_digest, ticket_expires_at, monotonic_deadline_ns,
                        ticket_correlation_sha256, launch_spec_json, launch_spec_bytes,
                        launch_spec_sha256, state, state_version, last_evidence_generation,
                        accepted_evidence_generation, accepted_executor_reference,
                        accepted_receipt_sha256,
                        effective_cancel_generation, acknowledged_cancel_generation,
                        cancel_disposition, launch_generation, launch_committed_at,
                        backend_reference, backend_domain_identity_sha256,
                        create_receipt_disposition, exit_code, exit_signal, terminal_reason,
                        terminal_evidence_sha256, descendants_stopped, output_finalized,
                        cleanup_complete, cleanup_evidence_sha256, accepted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?,
                              0, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, 0, 0, 0,
                              NULL, ?, ?)
                    """,
                    (
                        execution_id,
                        ticket.operation_id,
                        ticket.ticket_id,
                        ticket.ticket_sha256,
                        ticket.routing_identity.nonce_sha256,
                        ticket.boot_id_digest,
                        canonical_timestamp(ticket.expires_at),
                        ticket.monotonic_deadline_ns,
                        self._ticket_correlation_sha256(ticket),
                        launch_bytes.decode("utf-8"),
                        len(launch_bytes),
                        hashlib.sha256(launch_bytes).hexdigest(),
                        initial_state.value,
                        generation,
                        generation,
                        executor_reference,
                        accepted_receipt_sha256,
                        cancel_generation,
                        cancel_generation,
                        cancel_disposition,
                        CreateReceiptDisposition.NOT_ATTEMPTED.value,
                        canonical_timestamp(accepted_at),
                        canonical_timestamp(accepted_at),
                    ),
                )
                for stream in ("stdout", "stderr"):
                    await self._connection.execute(
                        """
                        INSERT INTO execution_streams (
                            execution_id, stream, relative_path, observed_bytes, retained_bytes,
                            stream_sha256, availability, finalized, last_evidence_generation,
                            updated_at
                        ) VALUES (?, ?, ?, 0, 0, NULL, 'available', 0, ?, ?)
                        """,
                        (
                            execution_id,
                            stream,
                            f"{execution_id}/{stream}.bin",
                            generation,
                            canonical_timestamp(accepted_at),
                        ),
                    )
                await self._append_event(
                    generation=generation,
                    event_id=f"accept_{ticket.ticket_sha256[:24]}",
                    operation_id=ticket.operation_id,
                    ticket_id=ticket.ticket_id,
                    execution_id=execution_id,
                    event_type="ticket.accepted",
                    from_state=None,
                    to_state=initial_state,
                    reason="first_acceptance",
                    event_sha256=canonical_sha256(
                        {
                            "execution_id": execution_id,
                            "ticket_sha256": ticket.ticket_sha256,
                            "cancel_generation": cancel_generation,
                        }
                    ),
                    recorded_at=accepted_at,
                )
                await self._connection.commit()
                row = await self._get_required_row(ticket.operation_id)
                return self._accepted_start_receipt(row)
            except BaseException:
                await self._connection.rollback()
                raise

    async def cancel_or_attach(
        self,
        *,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
    ) -> CancelRoutingResult:
        if cancel_generation < 1:
            raise ExecutionError("cancel generation must be positive")
        async with self._acceptance_gate:
            await self._begin()
            try:
                tombstone = await self._find_identity_row("no_accept_tombstones", identity)
                if tombstone is not None:
                    self._require_exact_routing(tombstone, identity)
                    current = _as_int(tombstone["closed_cancel_generation"])
                    generation = _as_int(tombstone["last_evidence_generation"])
                    if cancel_generation > current:
                        generation = await self._next_evidence_generation()
                        recorded_at = datetime.now(UTC)
                        await self._connection.execute(
                            """
                            UPDATE no_accept_tombstones
                            SET closed_cancel_generation = ?, last_evidence_generation = ?
                            WHERE operation_id = ?
                            """,
                            (cancel_generation, generation, identity.operation_id),
                        )
                        await self._append_event(
                            generation=generation,
                            event_id=(f"cancel_{identity.ticket_sha256[:16]}_{cancel_generation}"),
                            operation_id=identity.operation_id,
                            ticket_id=identity.ticket_id,
                            execution_id=None,
                            event_type="cancel.no_accept_acknowledged",
                            from_state=None,
                            to_state=None,
                            reason="no_accept_retained",
                            event_sha256=canonical_sha256(
                                {
                                    "cancel_generation": cancel_generation,
                                    "operation_id": identity.operation_id,
                                    "seal_reference": str(tombstone["seal_reference"]),
                                }
                            ),
                            recorded_at=recorded_at,
                        )
                    await self._connection.commit()
                    return CancelRoutingResult(
                        disposition=CancelRoutingDisposition.NO_ACCEPT_PROVEN,
                        acknowledged_cancel_generation=max(current, cancel_generation),
                        evidence_generation=generation,
                        snapshot=None,
                        no_accept_reference=str(tombstone["seal_reference"]),
                    )
                retained = await self._find_identity_row("execution_records", identity)
                if retained is not None:
                    self._require_exact_routing(retained, identity)
                    current = _as_int(retained["effective_cancel_generation"])
                    if cancel_generation > current:
                        generation = await self._next_evidence_generation()
                        recorded_at = datetime.now(UTC)
                        state = ExecutorEvidenceState(str(retained["state"]))
                        disposition: CancelDisposition
                        target_state: ExecutorEvidenceState
                        if state is ExecutorEvidenceState.CLOSED:
                            disposition = CancelDisposition.TERMINAL_ALREADY_WON
                            target_state = state
                        elif state in {
                            ExecutorEvidenceState.ACCEPTED,
                            ExecutorEvidenceState.LAUNCH_PREPARING,
                        }:
                            disposition = CancelDisposition.ATTACHED_PRELAUNCH
                            target_state = ExecutorEvidenceState.CANCEL_REQUESTED
                        elif state is ExecutorEvidenceState.EXECUTOR_UNCERTAIN:
                            disposition = CancelDisposition.UNCERTAIN
                            target_state = state
                        elif state in {
                            ExecutorEvidenceState.LAUNCH_COMMITTED,
                            ExecutorEvidenceState.RUNNING,
                        }:
                            disposition = CancelDisposition.SIGNAL_PENDING
                            target_state = ExecutorEvidenceState.CANCEL_REQUESTED
                        else:
                            disposition = CancelDisposition.SIGNAL_PENDING
                            target_state = state
                        state_version = _as_int(retained["state_version"])
                        next_state_version = state_version + int(target_state is not state)
                        await self._connection.execute(
                            """
                            UPDATE execution_records SET
                                state = ?, state_version = ?,
                                effective_cancel_generation = ?,
                                acknowledged_cancel_generation = ?,
                                cancel_disposition = ?,
                                last_evidence_generation = ?,
                                updated_at = ?
                            WHERE operation_id = ? AND state = ? AND state_version = ?
                            """,
                            (
                                target_state.value,
                                next_state_version,
                                cancel_generation,
                                cancel_generation,
                                disposition.value,
                                generation,
                                canonical_timestamp(recorded_at),
                                identity.operation_id,
                                state.value,
                                state_version,
                            ),
                        )
                        await self._append_event(
                            generation=generation,
                            event_id=(f"cancel_{identity.ticket_sha256[:16]}_{cancel_generation}"),
                            operation_id=identity.operation_id,
                            ticket_id=identity.ticket_id,
                            execution_id=str(retained["execution_id"]),
                            event_type="cancel.attached",
                            from_state=state,
                            to_state=target_state,
                            reason=disposition.value,
                            event_sha256=canonical_sha256(
                                {
                                    "cancel_generation": cancel_generation,
                                    "disposition": disposition.value,
                                    "execution_id": str(retained["execution_id"]),
                                }
                            ),
                            recorded_at=recorded_at,
                        )
                    await self._connection.commit()
                    snapshot = await self._get_required(identity.operation_id)
                    return CancelRoutingResult(
                        disposition=CancelRoutingDisposition.ACCEPTED_EXECUTION,
                        acknowledged_cancel_generation=snapshot.acknowledged_cancel_generation,
                        evidence_generation=snapshot.evidence_generation,
                        snapshot=snapshot,
                    )
                pending = await self._find_identity_row("pending_cancel_intents", identity)
                if pending is not None:
                    self._require_exact_routing(pending, identity)
                await self._require_no_cross_table_conflict(identity)
                current = 0 if pending is None else _as_int(pending["cancel_generation"])
                generation = (
                    _as_int(pending["last_evidence_generation"])
                    if pending is not None and cancel_generation <= current
                    else await self._next_evidence_generation()
                )
                now = datetime.now(UTC)
                if pending is None:
                    await self._connection.execute(
                        """
                        INSERT INTO pending_cancel_intents (
                            operation_id, ticket_id, ticket_sha256, nonce_sha256, boot_id_digest,
                            ticket_expires_at, monotonic_deadline_ns, cancel_generation,
                            last_evidence_generation, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identity.operation_id,
                            identity.ticket_id,
                            identity.ticket_sha256,
                            identity.nonce_sha256,
                            identity.boot_id_digest,
                            canonical_timestamp(identity.expires_at),
                            identity.monotonic_deadline_ns,
                            cancel_generation,
                            generation,
                            canonical_timestamp(now),
                            canonical_timestamp(now),
                        ),
                    )
                elif cancel_generation > current:
                    await self._connection.execute(
                        """
                        UPDATE pending_cancel_intents SET cancel_generation = ?,
                            last_evidence_generation = ?, updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (
                            cancel_generation,
                            generation,
                            canonical_timestamp(now),
                            identity.operation_id,
                        ),
                    )
                if pending is None or cancel_generation > current:
                    await self._append_event(
                        generation=generation,
                        event_id=f"pending_{identity.ticket_sha256[:16]}_{cancel_generation}",
                        operation_id=identity.operation_id,
                        ticket_id=identity.ticket_id,
                        execution_id=None,
                        event_type="cancel.pending_preaccept",
                        from_state=None,
                        to_state=None,
                        reason="cancel_before_acceptance",
                        event_sha256=canonical_sha256(
                            {
                                "cancel_generation": cancel_generation,
                                "operation_id": identity.operation_id,
                                "ticket_sha256": identity.ticket_sha256,
                            }
                        ),
                        recorded_at=now,
                    )
                await self._connection.commit()
                return CancelRoutingResult(
                    disposition=CancelRoutingDisposition.PENDING_PREACCEPT,
                    acknowledged_cancel_generation=max(current, cancel_generation),
                    evidence_generation=generation,
                    snapshot=None,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def seal_no_accept(
        self,
        *,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: datetime,
    ) -> NoAcceptSealResult:
        if not reason or len(reason) > 160 or close_generation < 0:
            raise ExecutionError("no-accept seal request is invalid")
        if retain_until.tzinfo is None or retain_until < identity.expires_at:
            raise ExecutionError("no-accept retention does not cover ticket replay")
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._find_identity_row("execution_records", identity)
                if retained is not None:
                    self._require_exact_routing(retained, identity)
                    snapshot = self._snapshot(retained)
                    receipt = self._accepted_start_receipt(retained)
                    await self._connection.commit()
                    return NoAcceptSealResult(
                        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
                        acknowledged_cancel_generation=snapshot.acknowledged_cancel_generation,
                        evidence_generation=snapshot.evidence_generation,
                        snapshot=snapshot,
                        seal_reference=None,
                        executor_reference=receipt.executor_reference,
                        receipt_sha256=receipt.receipt_sha256,
                    )
                tombstone = await self._find_identity_row("no_accept_tombstones", identity)
                if tombstone is not None:
                    self._require_exact_routing(tombstone, identity)
                    current = _as_int(tombstone["closed_cancel_generation"])
                    generation = _as_int(tombstone["last_evidence_generation"])
                    if close_generation > current:
                        generation = await self._next_evidence_generation()
                        recorded_at = datetime.now(UTC)
                        await self._connection.execute(
                            """
                            UPDATE no_accept_tombstones SET closed_cancel_generation = ?,
                                last_evidence_generation = ? WHERE operation_id = ?
                            """,
                            (close_generation, generation, identity.operation_id),
                        )
                        await self._append_event(
                            generation=generation,
                            event_id=(
                                f"seal_close_{identity.ticket_sha256[:16]}_{close_generation}"
                            ),
                            operation_id=identity.operation_id,
                            ticket_id=identity.ticket_id,
                            execution_id=None,
                            event_type="ticket.no_accept_cancel_closed",
                            from_state=None,
                            to_state=None,
                            reason=reason,
                            event_sha256=canonical_sha256(
                                {
                                    "close_generation": close_generation,
                                    "seal_reference": str(tombstone["seal_reference"]),
                                }
                            ),
                            recorded_at=recorded_at,
                        )
                    await self._connection.commit()
                    return NoAcceptSealResult(
                        disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
                        acknowledged_cancel_generation=max(current, close_generation),
                        evidence_generation=generation,
                        snapshot=None,
                        seal_reference=str(tombstone["seal_reference"]),
                        executor_reference=None,
                        receipt_sha256=str(tombstone["receipt_sha256"]),
                    )
                pending = await self._find_identity_row("pending_cancel_intents", identity)
                if pending is not None:
                    self._require_exact_routing(pending, identity)
                await self._require_no_cross_table_conflict(identity)
                closed_generation = max(
                    close_generation,
                    0 if pending is None else _as_int(pending["cancel_generation"]),
                )
                generation = await self._next_evidence_generation()
                if pending is not None:
                    await self._connection.execute(
                        "DELETE FROM pending_cancel_intents WHERE operation_id = ?",
                        (identity.operation_id,),
                    )
                now = datetime.now(UTC)
                seal_reference = f"seal_{identity.ticket_sha256[:24]}"
                receipt_sha256 = canonical_sha256(
                    {
                        "closed_cancel_generation": closed_generation,
                        "operation_id": identity.operation_id,
                        "reason": reason,
                        "seal_reference": seal_reference,
                        "ticket_sha256": identity.ticket_sha256,
                    }
                )
                await self._connection.execute(
                    """
                    INSERT INTO no_accept_tombstones (
                        operation_id, ticket_id, ticket_sha256, nonce_sha256, boot_id_digest,
                        ticket_expires_at, monotonic_deadline_ns, reason,
                        sealed_cancel_generation, closed_cancel_generation,
                        last_evidence_generation, seal_reference,
                        receipt_sha256, sealed_at, retain_until
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity.operation_id,
                        identity.ticket_id,
                        identity.ticket_sha256,
                        identity.nonce_sha256,
                        identity.boot_id_digest,
                        canonical_timestamp(identity.expires_at),
                        identity.monotonic_deadline_ns,
                        reason,
                        closed_generation,
                        closed_generation,
                        generation,
                        seal_reference,
                        receipt_sha256,
                        canonical_timestamp(now),
                        canonical_timestamp(retain_until),
                    ),
                )
                await self._append_event(
                    generation=generation,
                    event_id=f"seal_{identity.ticket_sha256[:24]}",
                    operation_id=identity.operation_id,
                    ticket_id=identity.ticket_id,
                    execution_id=None,
                    event_type="ticket.no_accept_sealed",
                    from_state=None,
                    to_state=None,
                    reason=reason,
                    event_sha256=receipt_sha256,
                    recorded_at=now,
                )
                await self._connection.commit()
                return NoAcceptSealResult(
                    disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
                    acknowledged_cancel_generation=closed_generation,
                    evidence_generation=generation,
                    snapshot=None,
                    seal_reference=seal_reference,
                    executor_reference=None,
                    receipt_sha256=receipt_sha256,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def get(self, operation_id: str) -> ExecutorSnapshot | None:
        async with self._acceptance_gate:
            row = await self._fetchone(
                "SELECT * FROM execution_records WHERE operation_id = ?", (operation_id,)
            )
            return None if row is None else self._snapshot(row)

    async def list(self, operation_ids: tuple[str, ...]) -> tuple[ExecutorSnapshot, ...]:
        if not operation_ids:
            return ()
        if len(operation_ids) > 256:
            raise ExecutionError("executor list request exceeds the reviewed limit")
        async with self._acceptance_gate:
            placeholders = ",".join("?" for _ in operation_ids)
            cursor = await self._connection.execute(
                f"SELECT * FROM execution_records WHERE operation_id IN ({placeholders}) "
                "ORDER BY accepted_at, operation_id",
                operation_ids,
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return tuple(self._snapshot(row) for row in rows)

    async def list_outstanding(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int = 256,
    ) -> tuple[ExecutorSnapshot, ...]:
        if not 1 <= limit <= 256:
            raise ExecutionError("executor reconciliation page limit is invalid")
        async with self._acceptance_gate:
            cursor = await self._connection.execute(
                "SELECT * FROM execution_records WHERE state!='closed' AND operation_id>? "
                "ORDER BY operation_id LIMIT ?",
                ("" if after_operation_id is None else after_operation_id, limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return tuple(self._snapshot(row) for row in rows)

    async def set_readiness(self, readiness: str) -> None:
        if readiness not in {"recovering", "ready", "integrity_failed"}:
            raise ExecutorStoreError("executor readiness value is invalid")
        async with self._acceptance_gate:
            await self._begin()
            try:
                outstanding = _as_int(
                    await _single_value(
                        self._connection,
                        "SELECT COUNT(*) FROM execution_records WHERE state!='closed'",
                    )
                )
                if readiness == "ready" and outstanding:
                    raise ExecutorStoreError(
                        "executor cannot become ready with unresolved executions"
                    )
                if readiness == "ready":
                    await self._connection.execute(
                        "UPDATE executor_meta SET readiness='ready', failure_reason=NULL, "
                        "last_verified_recovery_generation=evidence_generation_high_water, "
                        "updated_at=? WHERE id=1",
                        (canonical_timestamp(datetime.now(UTC)),),
                    )
                else:
                    await self._connection.execute(
                        "UPDATE executor_meta SET readiness=?, updated_at=? WHERE id=1",
                        (readiness, canonical_timestamp(datetime.now(UTC))),
                    )
                await self._connection.commit()
                self._readiness = readiness
            except BaseException:
                await self._connection.rollback()
                raise

    async def apply_event(self, event: ExecutorEvidenceEvent) -> ExecutorSnapshot:
        async with self._acceptance_gate:
            await self._begin()
            try:
                existing_event = await self._fetchone(
                    "SELECT event_sha256 FROM executor_evidence_events WHERE event_id = ?",
                    (event.event_id,),
                )
                if existing_event is not None:
                    if str(existing_event["event_sha256"]) != event.event_sha256:
                        raise ExecutionConflictError("executor event identity was reused")
                    snapshot = await self._get_required(event.operation_id)
                    await self._connection.commit()
                    return snapshot
                row = await self._fetchone(
                    "SELECT * FROM execution_records WHERE operation_id = ?",
                    (event.operation_id,),
                )
                if row is None:
                    raise ExecutorStoreError("executor event target is unavailable")
                current = self._snapshot(row)
                if (
                    current.state is not event.expected_state
                    or current.state_version != event.expected_state_version
                ):
                    raise ExecutionConflictError("executor event precondition is stale")
                if (
                    event.target_state
                    in {
                        ExecutorEvidenceState.LAUNCH_PREPARING,
                        ExecutorEvidenceState.LAUNCH_COMMITTED,
                    }
                    and current.effective_cancel_generation
                ):
                    raise ExecutionConflictError(
                        "durable cancellation suppresses executor launch commit"
                    )
                _require_stable_evidence(
                    current.backend_reference,
                    event.backend_reference,
                    name="backend reference",
                )
                _require_stable_evidence(
                    current.backend_domain_identity_sha256,
                    event.backend_domain_identity_sha256,
                    name="backend domain identity",
                )
                _require_stable_evidence(current.exit_code, event.exit_code, name="exit code")
                _require_stable_evidence(
                    current.exit_signal,
                    event.exit_signal,
                    name="exit signal",
                )
                _require_stable_evidence(
                    current.terminal_reason,
                    event.terminal_reason,
                    name="terminal reason",
                )
                _require_stable_evidence(
                    current.terminal_evidence_sha256,
                    event.terminal_evidence_sha256,
                    name="terminal evidence",
                )
                _require_stable_evidence(
                    current.cleanup_evidence_sha256,
                    event.cleanup_evidence_sha256,
                    name="cleanup evidence",
                )
                generation = await self._next_evidence_generation()
                launch_generation = current.launch_generation
                launch_committed_at = current.launch_committed_at
                create_disposition = current.create_receipt_disposition
                if event.target_state is ExecutorEvidenceState.LAUNCH_COMMITTED:
                    launch_generation += 1
                    launch_committed_at = event.recorded_at
                    create_disposition = (
                        event.create_receipt_disposition
                        or CreateReceiptDisposition.COMMITTED_PENDING
                    )
                elif event.create_receipt_disposition is not None:
                    create_disposition = event.create_receipt_disposition
                _require_create_disposition_transition(
                    current.create_receipt_disposition,
                    create_disposition,
                )
                values = {
                    "backend_reference": (
                        current.backend_reference
                        if event.backend_reference is None
                        else event.backend_reference
                    ),
                    "backend_domain_identity_sha256": (
                        current.backend_domain_identity_sha256
                        if event.backend_domain_identity_sha256 is None
                        else event.backend_domain_identity_sha256
                    ),
                    "cancel_disposition": (
                        current.cancel_disposition
                        if event.cancel_disposition is None
                        else event.cancel_disposition
                    ),
                    "cleanup_complete": (
                        current.cleanup_complete
                        if event.cleanup_complete is None
                        else event.cleanup_complete
                    ),
                    "cleanup_evidence_sha256": (
                        current.cleanup_evidence_sha256
                        if event.cleanup_evidence_sha256 is None
                        else event.cleanup_evidence_sha256
                    ),
                    "descendants_stopped": (
                        current.descendants_stopped
                        if event.descendants_stopped is None
                        else event.descendants_stopped
                    ),
                    "exit_code": current.exit_code if event.exit_code is None else event.exit_code,
                    "exit_signal": (
                        current.exit_signal if event.exit_signal is None else event.exit_signal
                    ),
                    "output_finalized": (
                        current.output_finalized
                        if event.output_finalized is None
                        else event.output_finalized
                    ),
                    "terminal_evidence_sha256": (
                        current.terminal_evidence_sha256
                        if event.terminal_evidence_sha256 is None
                        else event.terminal_evidence_sha256
                    ),
                    "terminal_reason": (
                        current.terminal_reason
                        if event.terminal_reason is None
                        else event.terminal_reason
                    ),
                }
                update_cursor = await self._connection.execute(
                    """
                    UPDATE execution_records SET state = ?, state_version = state_version + 1,
                        last_evidence_generation = ?, cancel_disposition = ?,
                        launch_generation = ?, launch_committed_at = ?, backend_reference = ?,
                        backend_domain_identity_sha256 = ?, create_receipt_disposition = ?,
                        exit_code = ?, exit_signal = ?, terminal_reason = ?,
                        terminal_evidence_sha256 = ?, descendants_stopped = ?,
                        output_finalized = ?, cleanup_complete = ?, cleanup_evidence_sha256 = ?,
                        updated_at = ? WHERE operation_id = ? AND state = ? AND state_version = ?
                        AND (? = 0 OR effective_cancel_generation = 0)
                    """,
                    (
                        event.target_state.value,
                        generation,
                        _enum_value(values["cancel_disposition"]),
                        launch_generation,
                        _optional_timestamp(launch_committed_at),
                        values["backend_reference"],
                        values["backend_domain_identity_sha256"],
                        create_disposition.value,
                        values["exit_code"],
                        values["exit_signal"],
                        values["terminal_reason"],
                        values["terminal_evidence_sha256"],
                        int(bool(values["descendants_stopped"])),
                        int(bool(values["output_finalized"])),
                        int(bool(values["cleanup_complete"])),
                        values["cleanup_evidence_sha256"],
                        canonical_timestamp(event.recorded_at),
                        event.operation_id,
                        event.expected_state.value,
                        event.expected_state_version,
                        int(
                            event.target_state
                            in {
                                ExecutorEvidenceState.LAUNCH_PREPARING,
                                ExecutorEvidenceState.LAUNCH_COMMITTED,
                            }
                        ),
                    ),
                )
                if update_cursor.rowcount != 1:
                    raise ExecutionConflictError("executor event compare-and-swap failed")
                await update_cursor.close()
                if (
                    event.target_state is ExecutorEvidenceState.CLOSED
                    and current.launch_generation == 0
                    and event.output_finalized is True
                ):
                    empty_sha256 = hashlib.sha256(b"").hexdigest()
                    streams_cursor = await self._connection.execute(
                        """
                        UPDATE execution_streams SET stream_sha256=?, finalized=1,
                            last_evidence_generation=?, updated_at=?
                        WHERE execution_id=? AND observed_bytes=0 AND retained_bytes=0
                    """,
                        (
                            empty_sha256,
                            generation,
                            canonical_timestamp(event.recorded_at),
                            current.execution_id,
                        ),
                    )
                    if streams_cursor.rowcount != 2:
                        raise ExecutorStoreError(
                            "no-domain closure cannot finalize contradictory output"
                        )
                    await streams_cursor.close()
                await self._append_event(
                    generation=generation,
                    event_id=event.event_id,
                    operation_id=event.operation_id,
                    ticket_id=current.ticket_id,
                    execution_id=current.execution_id,
                    event_type="execution.state_changed",
                    from_state=event.expected_state,
                    to_state=event.target_state,
                    reason=event.reason_code,
                    event_sha256=event.event_sha256,
                    recorded_at=event.recorded_at,
                )
                updated = await self._get_required(event.operation_id)
                await self._connection.commit()
                return updated
            except BaseException:
                await self._connection.rollback()
                raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._connection.close()
        finally:
            self._runtime_lock.close()

    async def _begin(self) -> None:
        await self._connection.execute("BEGIN IMMEDIATE")

    async def _next_evidence_generation(self) -> int:
        row = await self._fetchone(
            "SELECT evidence_generation_high_water FROM executor_meta WHERE id = 1"
        )
        if row is None:
            raise ExecutorStoreError("executor metadata is absent")
        generation = _as_int(row["evidence_generation_high_water"]) + 1
        await self._connection.execute(
            "UPDATE executor_meta SET evidence_generation_high_water = ?, updated_at = ? "
            "WHERE id = 1",
            (generation, canonical_timestamp(datetime.now(UTC))),
        )
        return generation

    async def _find_identity_row(
        self,
        table: str,
        identity: TicketRoutingIdentity,
    ) -> sqlite3.Row | None:
        if table not in {
            "execution_records",
            "pending_cancel_intents",
            "no_accept_tombstones",
        }:
            raise AssertionError("unreviewed executor identity table")
        return await self._fetchone(
            f"SELECT * FROM {table} WHERE operation_id = ? OR ticket_id = ? "
            "OR ticket_sha256 = ? OR nonce_sha256 = ? LIMIT 1",
            (
                identity.operation_id,
                identity.ticket_id,
                identity.ticket_sha256,
                identity.nonce_sha256,
            ),
        )

    async def _require_no_cross_table_conflict(self, identity: TicketRoutingIdentity) -> None:
        for table in (
            "execution_records",
            "pending_cancel_intents",
            "no_accept_tombstones",
        ):
            row = await self._find_identity_row(table, identity)
            if row is not None:
                self._require_exact_routing(row, identity)

    @staticmethod
    def _require_exact_routing(row: sqlite3.Row, identity: TicketRoutingIdentity) -> None:
        if (
            str(row["operation_id"]) != identity.operation_id
            or str(row["ticket_id"]) != identity.ticket_id
            or str(row["ticket_sha256"]) != identity.ticket_sha256
            or str(row["nonce_sha256"]) != identity.nonce_sha256
            or str(row["boot_id_digest"]) != identity.boot_id_digest
            or _timestamp(row["ticket_expires_at"]) != identity.expires_at
            or _as_int(row["monotonic_deadline_ns"]) != identity.monotonic_deadline_ns
        ):
            raise ExecutionConflictError("executor ticket identity conflicts with retained state")

    async def _append_event(
        self,
        *,
        generation: int,
        event_id: str,
        operation_id: str,
        ticket_id: str,
        execution_id: str | None,
        event_type: str,
        from_state: ExecutorEvidenceState | None,
        to_state: ExecutorEvidenceState | None,
        reason: str,
        event_sha256: str,
        recorded_at: datetime,
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO executor_evidence_events (
                evidence_generation, event_id, operation_id, ticket_id, execution_id,
                event_type, from_state, to_state, reason, event_sha256, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation,
                event_id,
                operation_id,
                ticket_id,
                execution_id,
                event_type,
                None if from_state is None else from_state.value,
                None if to_state is None else to_state.value,
                reason,
                event_sha256,
                canonical_timestamp(recorded_at),
            ),
        )

    async def _fetchone(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> sqlite3.Row | None:
        cursor = await self._connection.execute(query, parameters)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def _get_required(self, operation_id: str) -> ExecutorSnapshot:
        return self._snapshot(await self._get_required_row(operation_id))

    async def _get_required_row(self, operation_id: str) -> sqlite3.Row:
        row = await self._fetchone(
            "SELECT * FROM execution_records WHERE operation_id = ?", (operation_id,)
        )
        if row is None:
            raise ExecutorStoreError("accepted executor record is unavailable")
        return row

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> ExecutorSnapshot:
        return ExecutorSnapshot(
            operation_id=str(row["operation_id"]),
            ticket_id=str(row["ticket_id"]),
            ticket_sha256=str(row["ticket_sha256"]),
            execution_id=str(row["execution_id"]),
            state=ExecutorEvidenceState(str(row["state"])),
            state_version=_as_int(row["state_version"]),
            evidence_generation=_as_int(row["last_evidence_generation"]),
            effective_cancel_generation=_as_int(row["effective_cancel_generation"]),
            acknowledged_cancel_generation=_as_int(row["acknowledged_cancel_generation"]),
            cancel_disposition=(
                None
                if row["cancel_disposition"] is None
                else CancelDisposition(str(row["cancel_disposition"]))
            ),
            launch_generation=_as_int(row["launch_generation"]),
            launch_committed_at=_optional_timestamp_value(row["launch_committed_at"]),
            create_receipt_disposition=CreateReceiptDisposition(
                str(row["create_receipt_disposition"])
            ),
            backend_reference=_optional_text(row["backend_reference"]),
            backend_domain_identity_sha256=_optional_text(row["backend_domain_identity_sha256"]),
            accepted_at=_timestamp(row["accepted_at"]),
            exit_code=_optional_int(row["exit_code"]),
            exit_signal=_optional_int(row["exit_signal"]),
            terminal_reason=_optional_text(row["terminal_reason"]),
            descendants_stopped=bool(row["descendants_stopped"]),
            output_finalized=bool(row["output_finalized"]),
            cleanup_complete=bool(row["cleanup_complete"]),
            terminal_evidence_sha256=_optional_text(row["terminal_evidence_sha256"]),
            cleanup_evidence_sha256=_optional_text(row["cleanup_evidence_sha256"]),
        )

    @staticmethod
    def _accepted_start_receipt(row: sqlite3.Row) -> ExecutionStartReceipt:
        return ExecutionStartReceipt(
            disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
            execution_id=str(row["execution_id"]),
            evidence_generation=_as_int(row["accepted_evidence_generation"]),
            accepted_at=_timestamp(row["accepted_at"]),
            executor_reference=str(row["accepted_executor_reference"]),
            no_accept_reference=None,
            receipt_sha256=str(row["accepted_receipt_sha256"]),
        )

    @staticmethod
    def _no_accept_start_receipt(row: sqlite3.Row) -> ExecutionStartReceipt:
        return ExecutionStartReceipt(
            disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
            execution_id=None,
            evidence_generation=_as_int(row["last_evidence_generation"]),
            accepted_at=None,
            executor_reference=None,
            no_accept_reference=str(row["seal_reference"]),
            receipt_sha256=str(row["receipt_sha256"]),
        )

    @staticmethod
    def _ticket_correlation_sha256(ticket: ExecutionTicket) -> str:
        return ticket_correlation_sha256(ticket)

    @staticmethod
    def _launch_spec(ticket: ExecutionTicket) -> dict[str, object]:
        wire = ticket.to_wire()
        wire.pop("single_use_nonce")
        wire["nonce_sha256"] = ticket.routing_identity.nonce_sha256
        return wire


async def open_executor_store(
    *,
    settings: ExecutorStoreSettings,
    identity: ExecutorStoreIdentity,
) -> SqliteExecutorEvidenceStore:
    _validate_settings(settings)
    _verify_state_path(settings.path, verify_permissions=settings.verify_permissions)
    runtime_lock = _acquire_lock(
        settings.runtime_directory,
        verify_permissions=settings.verify_permissions,
    )
    try:
        try:
            integrity_connection = sqlite3.connect(
                f"file:{quote(str(settings.path), safe='/')}?mode=ro",
                uri=True,
            )
            try:
                integrity_report = verify_executor_connection(
                    integrity_connection,
                    expected_revision=EXECUTOR_REVISION,
                )
            finally:
                integrity_connection.close()
        except (ExecutorIntegrityError, sqlite3.Error) as exc:
            raise ExecutorStoreError("executor durable evidence verification failed") from exc
        connection = await aiosqlite.connect(settings.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA synchronous=FULL")
        await connection.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
        meta_cursor = await connection.execute("SELECT * FROM executor_meta WHERE id = 1")
        meta = await meta_cursor.fetchone()
        await meta_cursor.close()
        if meta is None or _as_int(meta["schema_generation"]) != 1:
            raise ExecutorStoreError("executor metadata is absent or incompatible")
        outstanding = integrity_report.outstanding_executions
        previous_build = str(meta["build_sha256"])
        previous_profile = str(meta["profile_sha256"])
        previous_boot = str(meta["boot_id_digest"])
        initialized = previous_build != _ZERO_DIGEST or previous_profile != _ZERO_DIGEST
        if (
            outstanding
            and initialized
            and (
                previous_build != identity.build_sha256
                or previous_profile != identity.profile_sha256
                or previous_boot != identity.boot_id_digest
            )
        ):
            raise ExecutorStoreError("outstanding execution identity requires exact recovery")
        await connection.execute("BEGIN IMMEDIATE")
        await connection.execute(
            """
            UPDATE executor_meta SET supervisor_instance_id = ?,
                supervisor_generation = supervisor_generation + 1, boot_id_digest = ?,
                protocol_version = ?, build_sha256 = ?, profile_sha256 = ?,
                readiness = 'recovering', failure_reason = NULL, updated_at = ? WHERE id = 1
            """,
            (
                identity.supervisor_instance_id,
                identity.boot_id_digest,
                identity.protocol_version,
                identity.build_sha256,
                identity.profile_sha256,
                canonical_timestamp(datetime.now(UTC)),
            ),
        )
        generation_value = await _single_value(
            connection,
            "SELECT supervisor_generation FROM executor_meta WHERE id = 1",
        )
        readiness = "recovering" if outstanding else "ready"
        if outstanding:
            await connection.execute(
                "UPDATE executor_meta SET readiness='recovering', updated_at=? WHERE id=1",
                (canonical_timestamp(datetime.now(UTC)),),
            )
        else:
            await connection.execute(
                "UPDATE executor_meta SET readiness='ready', "
                "last_verified_recovery_generation=evidence_generation_high_water, "
                "updated_at=? WHERE id=1",
                (canonical_timestamp(datetime.now(UTC)),),
            )
        await connection.commit()
        return SqliteExecutorEvidenceStore(
            connection=connection,
            settings=settings,
            identity=identity,
            runtime_lock=runtime_lock,
            supervisor_generation=_as_int(generation_value),
            readiness=readiness,
        )
    except BaseException:
        runtime_lock.close()
        if "connection" in locals():
            await connection.close()
        raise


def _validate_settings(settings: ExecutorStoreSettings) -> None:
    if not 100 <= settings.busy_timeout_ms <= 60_000:
        raise ExecutorStoreError("executor busy timeout is outside the safe range")
    if not 65_536 <= settings.maximum_launch_spec_bytes <= 1_048_576:
        raise ExecutorStoreError("executor launch-spec limit is outside the safe range")
    if settings.path.name != "executor-state.sqlite3":
        raise ExecutorStoreError("executor database filename is fixed")


def _verify_state_path(path: Path, *, verify_permissions: bool) -> None:
    if path.is_symlink():
        raise ExecutorStoreError("executor database may not be a symlink")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise ExecutorStoreError("executor state directory is unavailable") from exc
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise ExecutorStoreError("executor state directory is unsafe")
    if verify_permissions and (
        parent.st_uid != os.geteuid()
        or parent.st_gid != os.getegid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ExecutorStoreError("executor state directory ownership/mode is invalid")


def _acquire_lock(path: Path, *, verify_permissions: bool) -> _StoreLock:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ExecutorStoreError("executor runtime directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ExecutorStoreError("executor runtime directory is unsafe")
    if verify_permissions and (
        metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ExecutorStoreError("executor runtime directory ownership/mode is invalid")
    descriptor = os.open(
        path / "executor-writer.lock",
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise ExecutorStoreError("executor writer or maintenance process is active") from exc
    return _StoreLock(descriptor)


async def _single_value(connection: aiosqlite.Connection, query: str) -> object:
    cursor = await connection.execute(query)
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise ExecutorStoreError("executor database query returned no row")
    return row[0]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _accepted_receipt_sha256(
    *,
    operation_id: str,
    execution_id: str,
    evidence_generation: int,
    executor_reference: str,
) -> str:
    return canonical_sha256(
        {
            "evidence_generation": evidence_generation,
            "execution_id": execution_id,
            "executor_reference": executor_reference,
            "operation_id": operation_id,
        }
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ExecutorStoreError("executor timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _optional_timestamp_value(value: object) -> datetime | None:
    return None if value is None else _timestamp(value)


def _optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else canonical_timestamp(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _as_int(value)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, bytes, bytearray)):
        raise ExecutorStoreError("executor integer field is invalid")
    return int(value)


def _enum_value(value: object) -> str | None:
    return None if value is None else str(value)


def _require_stable_evidence(current: object, proposed: object, *, name: str) -> None:
    if current is not None and proposed is not None and current != proposed:
        raise ExecutionConflictError(f"executor {name} cannot be replaced")


def _require_create_disposition_transition(
    current: CreateReceiptDisposition,
    proposed: CreateReceiptDisposition,
) -> None:
    permitted = {
        CreateReceiptDisposition.NOT_ATTEMPTED: {
            CreateReceiptDisposition.NOT_ATTEMPTED,
            CreateReceiptDisposition.COMMITTED_PENDING,
        },
        CreateReceiptDisposition.COMMITTED_PENDING: {
            CreateReceiptDisposition.COMMITTED_PENDING,
            CreateReceiptDisposition.DOMAIN_CREATED,
            CreateReceiptDisposition.NO_DOMAIN,
            CreateReceiptDisposition.AMBIGUOUS,
        },
        CreateReceiptDisposition.AMBIGUOUS: {
            CreateReceiptDisposition.AMBIGUOUS,
            CreateReceiptDisposition.DOMAIN_CREATED,
            CreateReceiptDisposition.NO_DOMAIN,
        },
        CreateReceiptDisposition.DOMAIN_CREATED: {CreateReceiptDisposition.DOMAIN_CREATED},
        CreateReceiptDisposition.NO_DOMAIN: {CreateReceiptDisposition.NO_DOMAIN},
    }
    if proposed not in permitted[current]:
        raise ExecutionConflictError("executor create receipt disposition cannot be replaced")


__all__ = [
    "EXECUTOR_REVISION",
    "ExecutorStoreError",
    "ExecutorStoreIdentity",
    "ExecutorStoreSettings",
    "SqliteExecutorEvidenceStore",
    "open_executor_store",
]

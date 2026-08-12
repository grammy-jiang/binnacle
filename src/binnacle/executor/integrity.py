"""Read-only structural and semantic verification of executor-owned evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from binnacle.domain.execution import (
    CancelDisposition,
    CreateReceiptDisposition,
    ExecutorEvidenceState,
    ExecutorSnapshot,
    TicketRoutingIdentity,
    canonical_sha256,
    require_executor_transition,
)

EXPECTED_EXECUTOR_TABLES: Final = frozenset(
    {
        "alembic_version",
        "executor_meta",
        "execution_records",
        "pending_cancel_intents",
        "no_accept_tombstones",
        "execution_streams",
        "executor_evidence_events",
    }
)


class ExecutorIntegrityError(RuntimeError):
    """Executor evidence is incomplete, contradictory, or not replay-safe."""


@dataclass(frozen=True, slots=True)
class ExecutorIntegrityReport:
    revision: str
    readiness: str
    schema_generation: int
    evidence_generation: int
    accepted_executions: int
    pending_cancels: int
    no_accept_tombstones: int
    outstanding_executions: int


def verify_executor_connection(
    connection: sqlite3.Connection,
    *,
    expected_revision: str,
) -> ExecutorIntegrityReport:
    try:
        return _verify_executor_connection(connection, expected_revision=expected_revision)
    except ExecutorIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ExecutorIntegrityError("executor evidence contains an invalid value") from exc


def _verify_executor_connection(
    connection: sqlite3.Connection,
    *,
    expected_revision: str,
) -> ExecutorIntegrityReport:
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ExecutorIntegrityError("executor SQLite integrity check failed")
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != EXPECTED_EXECUTOR_TABLES:
        raise ExecutorIntegrityError("executor database table set is incompatible")
    revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    meta = connection.execute("SELECT * FROM executor_meta WHERE id=1").fetchone()
    if revision_row is None or revision_row[0] != expected_revision or meta is None:
        raise ExecutorIntegrityError("executor database identity is incompatible")
    high_water = _integer(meta["evidence_generation_high_water"])
    if (
        _integer(meta["schema_generation"]) != 1
        or high_water < 0
        or _integer(meta["last_verified_recovery_generation"]) > high_water
        or str(meta["readiness"])
        not in {"uninitialized", "recovering", "ready", "integrity_failed"}
    ):
        raise ExecutorIntegrityError("executor metadata is contradictory")
    _verify_event_sequence(connection, high_water)
    _verify_acceptance_homes(connection)
    accepted = _verify_execution_rows(connection, high_water)
    pending = _verify_routing_rows(connection, "pending_cancel_intents", high_water)
    sealed = _verify_routing_rows(connection, "no_accept_tombstones", high_water)
    orphan_events = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM executor_evidence_events ev
            WHERE ((EXISTS (SELECT 1 FROM execution_records e
                            WHERE e.operation_id=ev.operation_id)) +
                   (EXISTS (SELECT 1 FROM pending_cancel_intents p
                            WHERE p.operation_id=ev.operation_id)) +
                   (EXISTS (SELECT 1 FROM no_accept_tombstones n
                            WHERE n.operation_id=ev.operation_id))) != 1
            """
        ).fetchone()[0]
    )
    if orphan_events:
        raise ExecutorIntegrityError("executor event has no exact retained acceptance home")
    outstanding = int(
        connection.execute(
            "SELECT COUNT(*) FROM execution_records WHERE state!='closed'"
        ).fetchone()[0]
    )
    return ExecutorIntegrityReport(
        revision=str(revision_row[0]),
        readiness=str(meta["readiness"]),
        schema_generation=1,
        evidence_generation=high_water,
        accepted_executions=accepted,
        pending_cancels=pending,
        no_accept_tombstones=sealed,
        outstanding_executions=outstanding,
    )


def _verify_event_sequence(connection: sqlite3.Connection, high_water: int) -> None:
    rows = tuple(
        connection.execute("SELECT * FROM executor_evidence_events ORDER BY evidence_generation")
    )
    if len(rows) != high_water or any(
        _integer(row["evidence_generation"]) != expected
        for expected, row in enumerate(rows, start=1)
    ):
        raise ExecutorIntegrityError("executor evidence generation sequence has a gap")
    for row in rows:
        if row["from_state"] is not None and row["to_state"] is not None:
            current = ExecutorEvidenceState(str(row["from_state"]))
            target = ExecutorEvidenceState(str(row["to_state"]))
            if current is not target:
                try:
                    require_executor_transition(current, target)
                except ValueError as exc:
                    raise ExecutorIntegrityError(
                        "executor event contains an illegal state transition"
                    ) from exc


def _verify_acceptance_homes(connection: sqlite3.Connection) -> None:
    identity_match = (
        "left_row.operation_id=right_row.operation_id OR "
        "left_row.ticket_id=right_row.ticket_id OR "
        "left_row.ticket_sha256=right_row.ticket_sha256 OR "
        "left_row.nonce_sha256=right_row.nonce_sha256"
    )
    pairs = (
        ("execution_records", "pending_cancel_intents"),
        ("execution_records", "no_accept_tombstones"),
        ("pending_cancel_intents", "no_accept_tombstones"),
    )
    for left, right in pairs:
        count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {left} left_row JOIN {right} right_row ON {identity_match}"
            ).fetchone()[0]
        )
        if count:
            raise ExecutorIntegrityError("executor acceptance identities have multiple homes")


def _verify_execution_rows(connection: sqlite3.Connection, high_water: int) -> int:
    rows = tuple(connection.execute("SELECT * FROM execution_records ORDER BY operation_id"))
    for row in rows:
        snapshot = _snapshot(row)
        launch_text = str(row["launch_spec_json"])
        launch_bytes = launch_text.encode("utf-8")
        try:
            launch_document = json.loads(launch_text)
        except json.JSONDecodeError as exc:
            raise ExecutorIntegrityError("executor launch specification is not JSON") from exc
        canonical = json.dumps(
            launch_document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if (
            canonical != launch_bytes
            or len(launch_bytes) != _integer(row["launch_spec_bytes"])
            or hashlib.sha256(launch_bytes).hexdigest() != str(row["launch_spec_sha256"])
        ):
            raise ExecutorIntegrityError("executor launch specification digest is invalid")
        accepted_generation = _integer(row["accepted_evidence_generation"])
        reference = str(row["accepted_executor_reference"])
        expected_receipt = canonical_sha256(
            {
                "evidence_generation": accepted_generation,
                "execution_id": snapshot.execution_id,
                "executor_reference": reference,
                "operation_id": snapshot.operation_id,
            }
        )
        if expected_receipt != str(row["accepted_receipt_sha256"]):
            raise ExecutorIntegrityError("executor accepted receipt is not stable")
        accepted_event = connection.execute(
            "SELECT operation_id, execution_id FROM executor_evidence_events "
            "WHERE evidence_generation=? AND event_type='ticket.accepted'",
            (accepted_generation,),
        ).fetchone()
        if (
            accepted_event is None
            or accepted_event["operation_id"] != snapshot.operation_id
            or accepted_event["execution_id"] != snapshot.execution_id
        ):
            raise ExecutorIntegrityError("executor accepted receipt has no exact event")
        _verify_row_event_head(
            connection,
            operation_id=snapshot.operation_id,
            state=snapshot.state,
            state_version=snapshot.state_version,
            last_generation=snapshot.evidence_generation,
            high_water=high_water,
        )
        streams = tuple(
            connection.execute(
                "SELECT * FROM execution_streams WHERE execution_id=? ORDER BY stream",
                (snapshot.execution_id,),
            )
        )
        if {str(stream["stream"]) for stream in streams} != {"stdout", "stderr"}:
            raise ExecutorIntegrityError("executor output stream set is incomplete")
        for stream in streams:
            name = str(stream["stream"])
            if (
                str(stream["relative_path"]) != f"{snapshot.execution_id}/{name}.bin"
                or _integer(stream["retained_bytes"]) > _integer(stream["observed_bytes"])
                or not 1 <= _integer(stream["last_evidence_generation"]) <= high_water
                or (bool(stream["finalized"]) and stream["stream_sha256"] is None)
            ):
                raise ExecutorIntegrityError("executor output evidence is contradictory")
            if snapshot.output_finalized and not bool(stream["finalized"]):
                raise ExecutorIntegrityError("executor row claims unfinalized output is final")
    return len(rows)


def _verify_routing_rows(
    connection: sqlite3.Connection,
    table: str,
    high_water: int,
) -> int:
    rows = tuple(connection.execute(f"SELECT * FROM {table} ORDER BY operation_id"))
    for row in rows:
        TicketRoutingIdentity(
            operation_id=str(row["operation_id"]),
            ticket_id=str(row["ticket_id"]),
            ticket_sha256=str(row["ticket_sha256"]),
            nonce_sha256=str(row["nonce_sha256"]),
            boot_id_digest=str(row["boot_id_digest"]),
            expires_at=_timestamp(row["ticket_expires_at"]),
            monotonic_deadline_ns=_integer(row["monotonic_deadline_ns"]),
        )
        generation = _integer(row["last_evidence_generation"])
        if not 1 <= generation <= high_water:
            raise ExecutorIntegrityError("executor routing evidence generation is invalid")
        event = connection.execute(
            "SELECT operation_id FROM executor_evidence_events WHERE evidence_generation=?",
            (generation,),
        ).fetchone()
        if event is None or str(event["operation_id"]) != str(row["operation_id"]):
            raise ExecutorIntegrityError("executor routing evidence has no exact event")
        if table == "no_accept_tombstones":
            expected = canonical_sha256(
                {
                    "closed_cancel_generation": _integer(row["sealed_cancel_generation"]),
                    "operation_id": str(row["operation_id"]),
                    "reason": str(row["reason"]),
                    "seal_reference": str(row["seal_reference"]),
                    "ticket_sha256": str(row["ticket_sha256"]),
                }
            )
            if expected != str(row["receipt_sha256"]):
                raise ExecutorIntegrityError("executor no-accept receipt is invalid")
    return len(rows)


def _verify_row_event_head(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    state: ExecutorEvidenceState,
    state_version: int,
    last_generation: int,
    high_water: int,
) -> None:
    if not 1 <= last_generation <= high_water:
        raise ExecutorIntegrityError("executor row evidence head is outside the event stream")
    last = connection.execute(
        "SELECT operation_id FROM executor_evidence_events WHERE evidence_generation=?",
        (last_generation,),
    ).fetchone()
    head = connection.execute(
        "SELECT to_state FROM executor_evidence_events "
        "WHERE operation_id=? AND to_state IS NOT NULL "
        "ORDER BY evidence_generation DESC LIMIT 1",
        (operation_id,),
    ).fetchone()
    version = int(
        connection.execute(
            "SELECT COUNT(*) FROM executor_evidence_events "
            "WHERE operation_id=? AND to_state IS NOT NULL AND from_state IS NOT to_state",
            (operation_id,),
        ).fetchone()[0]
    )
    if (
        last is None
        or str(last["operation_id"]) != operation_id
        or head is None
        or str(head["to_state"]) != state.value
        or version != state_version
    ):
        raise ExecutorIntegrityError("executor row does not match its event history")


def _snapshot(row: sqlite3.Row) -> ExecutorSnapshot:
    return ExecutorSnapshot(
        operation_id=str(row["operation_id"]),
        ticket_id=str(row["ticket_id"]),
        ticket_sha256=str(row["ticket_sha256"]),
        execution_id=str(row["execution_id"]),
        state=ExecutorEvidenceState(str(row["state"])),
        state_version=_integer(row["state_version"]),
        evidence_generation=_integer(row["last_evidence_generation"]),
        effective_cancel_generation=_integer(row["effective_cancel_generation"]),
        acknowledged_cancel_generation=_integer(row["acknowledged_cancel_generation"]),
        cancel_disposition=(
            None
            if row["cancel_disposition"] is None
            else CancelDisposition(str(row["cancel_disposition"]))
        ),
        launch_generation=_integer(row["launch_generation"]),
        launch_committed_at=(
            None if row["launch_committed_at"] is None else _timestamp(row["launch_committed_at"])
        ),
        create_receipt_disposition=CreateReceiptDisposition(str(row["create_receipt_disposition"])),
        backend_reference=_optional_text(row["backend_reference"]),
        backend_domain_identity_sha256=_optional_text(row["backend_domain_identity_sha256"]),
        accepted_at=_timestamp(row["accepted_at"]),
        exit_code=_optional_integer(row["exit_code"]),
        exit_signal=_optional_integer(row["exit_signal"]),
        terminal_reason=_optional_text(row["terminal_reason"]),
        descendants_stopped=bool(row["descendants_stopped"]),
        output_finalized=bool(row["output_finalized"]),
        cleanup_complete=bool(row["cleanup_complete"]),
        terminal_evidence_sha256=_optional_text(row["terminal_evidence_sha256"]),
        cleanup_evidence_sha256=_optional_text(row["cleanup_evidence_sha256"]),
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ExecutorIntegrityError("executor timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, bytes, bytearray)):
        raise ExecutorIntegrityError("executor integer field is invalid")
    return int(value)


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "EXPECTED_EXECUTOR_TABLES",
    "ExecutorIntegrityError",
    "ExecutorIntegrityReport",
    "verify_executor_connection",
]

"""Read-only integrity verification for isolated privileged-broker evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

PRIVILEGED_BROKER_REVISION: Final = "0001_privileged_evidence"
EXPECTED_PRIVILEGED_TABLES: Final = frozenset(
    {
        "alembic_version",
        "privileged_meta",
        "privileged_operation_bindings",
        "privileged_no_accept_tombstones",
        "privileged_subeffects",
        "privileged_evidence_events",
    }
)


class PrivilegedBrokerIntegrityError(RuntimeError):
    """Privileged evidence is incompatible, contradictory, or not replay-safe."""


@dataclass(frozen=True, slots=True)
class PrivilegedBrokerIntegrityReport:
    revision: str
    readiness: str
    schema_generation: int
    evidence_generation: int
    unresolved_bindings: int
    accepted_bindings: int
    sealed_bindings: int
    active_subeffects: int
    uncertain_subeffects: int

    @property
    def retains_authority(self) -> bool:
        return bool(
            self.unresolved_bindings
            or self.accepted_bindings
            or self.active_subeffects
            or self.uncertain_subeffects
        )


def verify_privileged_broker_connection(
    connection: sqlite3.Connection,
    *,
    expected_revision: str = PRIVILEGED_BROKER_REVISION,
) -> PrivilegedBrokerIntegrityReport:
    try:
        return _verify(connection, expected_revision=expected_revision)
    except PrivilegedBrokerIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, sqlite3.Error) as exc:
        raise PrivilegedBrokerIntegrityError(
            "privileged-broker evidence contains an invalid value"
        ) from exc


def _verify(
    connection: sqlite3.Connection,
    *,
    expected_revision: str,
) -> PrivilegedBrokerIntegrityReport:
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise PrivilegedBrokerIntegrityError("privileged-broker SQLite integrity check failed")
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != EXPECTED_PRIVILEGED_TABLES:
        raise PrivilegedBrokerIntegrityError("privileged-broker table set is incompatible")
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    meta = connection.execute("SELECT * FROM privileged_meta WHERE id=1").fetchone()
    if revision is None or revision[0] != expected_revision or meta is None:
        raise PrivilegedBrokerIntegrityError("privileged-broker identity is incompatible")
    schema_generation = _integer(meta["schema_generation"])
    high_water = _integer(meta["evidence_generation_high_water"])
    readiness = str(meta["readiness"])
    if (
        schema_generation != 1
        or high_water < 0
        or readiness
        not in {
            "uninitialized",
            "disabled",
            "recovering",
            "ready",
            "restricted_recovery",
            "integrity_failed",
        }
    ):
        raise PrivilegedBrokerIntegrityError("privileged-broker metadata is contradictory")

    events = tuple(
        connection.execute("SELECT * FROM privileged_evidence_events ORDER BY evidence_generation")
    )
    if len(events) != high_water or any(
        _integer(row["evidence_generation"]) != expected
        for expected, row in enumerate(events, start=1)
    ):
        raise PrivilegedBrokerIntegrityError("privileged evidence generation has a gap")

    bindings = tuple(
        connection.execute("SELECT * FROM privileged_operation_bindings ORDER BY operation_id")
    )
    for row in bindings:
        _verify_binding(connection, row, high_water)
    _verify_subeffects(connection, high_water)
    orphan_events = int(
        connection.execute(
            "SELECT COUNT(*) FROM privileged_evidence_events event "
            "LEFT JOIN privileged_operation_bindings binding "
            "ON binding.operation_id=event.operation_id "
            "WHERE binding.operation_id IS NULL"
        ).fetchone()[0]
    )
    if orphan_events:
        raise PrivilegedBrokerIntegrityError("privileged event has no retained binding")

    active_states = "('intent_recorded','started','reconciling','restricted_recovery')"
    active_subeffects = int(
        connection.execute(
            f"SELECT COUNT(*) FROM privileged_subeffects WHERE state IN {active_states}"
        ).fetchone()[0]
    )
    uncertain_subeffects = int(
        connection.execute(
            "SELECT COUNT(*) FROM privileged_subeffects WHERE state='uncertain'"
        ).fetchone()[0]
    )
    return PrivilegedBrokerIntegrityReport(
        revision=str(revision[0]),
        readiness=readiness,
        schema_generation=schema_generation,
        evidence_generation=high_water,
        unresolved_bindings=sum(row["acceptance_state"] == "unresolved" for row in bindings),
        accepted_bindings=sum(row["acceptance_state"] == "accepted" for row in bindings),
        sealed_bindings=sum(row["acceptance_state"] == "sealed_no_accept" for row in bindings),
        active_subeffects=active_subeffects,
        uncertain_subeffects=uncertain_subeffects,
    )


def _verify_binding(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    high_water: int,
) -> None:
    state = str(row["acceptance_state"])
    generation = _integer(row["evidence_generation"])
    tombstones = tuple(
        connection.execute(
            "SELECT * FROM privileged_no_accept_tombstones WHERE operation_id=?",
            (row["operation_id"],),
        )
    )
    if state not in {"unresolved", "accepted", "sealed_no_accept"}:
        raise PrivilegedBrokerIntegrityError("privileged acceptance state is invalid")
    if generation > high_water:
        raise PrivilegedBrokerIntegrityError("privileged acceptance exceeds evidence high-water")
    if state == "sealed_no_accept":
        if len(tombstones) != 1:
            raise PrivilegedBrokerIntegrityError("privileged no-accept binding lacks tombstone")
        tombstone = tombstones[0]
        if (
            tombstone["ticket_id"] != row["ticket_id"]
            or tombstone["ticket_sha256"] != row["ticket_sha256"]
            or _integer(tombstone["evidence_generation"]) != generation
            or tombstone["evidence_sha256"] != row["acceptance_evidence_sha256"]
        ):
            raise PrivilegedBrokerIntegrityError("privileged no-accept evidence conflicts")
    elif tombstones:
        raise PrivilegedBrokerIntegrityError("privileged tombstone has no sealed binding")


def _verify_subeffects(connection: sqlite3.Connection, high_water: int) -> None:
    del high_water
    rows = tuple(
        connection.execute(
            """
            SELECT subeffect.*, binding.acceptance_state
            FROM privileged_subeffects subeffect
            LEFT JOIN privileged_operation_bindings binding
              ON binding.operation_id=subeffect.operation_id
            ORDER BY subeffect.operation_id, subeffect.subeffect_generation
            """
        )
    )
    expected_by_operation: dict[str, int] = {}
    for row in rows:
        operation_id = str(row["operation_id"])
        expected = expected_by_operation.get(operation_id, 1)
        if _integer(row["subeffect_generation"]) != expected:
            raise PrivilegedBrokerIntegrityError("privileged subeffect generation has a gap")
        expected_by_operation[operation_id] = expected + 1
        if row["acceptance_state"] != "accepted":
            raise PrivilegedBrokerIntegrityError("privileged subeffect lacks accepted binding")


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrivilegedBrokerIntegrityError("privileged evidence integer is invalid")
    return value


__all__ = [
    "EXPECTED_PRIVILEGED_TABLES",
    "PRIVILEGED_BROKER_REVISION",
    "PrivilegedBrokerIntegrityError",
    "PrivilegedBrokerIntegrityReport",
    "verify_privileged_broker_connection",
]

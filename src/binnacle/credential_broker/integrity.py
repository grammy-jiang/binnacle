"""Read-only integrity verification for isolated credential-broker evidence."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Final

CREDENTIAL_BROKER_REVISION: Final = "0001_credential_evidence"
EXPECTED_CREDENTIAL_TABLES: Final = frozenset(
    {
        "alembic_version",
        "credential_meta",
        "credential_use_tickets",
        "credential_evidence_events",
    }
)


class CredentialBrokerIntegrityError(RuntimeError):
    """Credential evidence is incompatible, contradictory, or not replay-safe."""


@dataclass(frozen=True, slots=True)
class CredentialBrokerIntegrityReport:
    revision: str
    readiness: str
    schema_generation: int
    evidence_generation: int
    registered_tickets: int
    accepted_tickets: int
    completed_tickets: int
    uncertain_tickets: int


def verify_credential_broker_connection(
    connection: sqlite3.Connection,
    *,
    expected_revision: str = CREDENTIAL_BROKER_REVISION,
) -> CredentialBrokerIntegrityReport:
    try:
        return _verify(connection, expected_revision=expected_revision)
    except CredentialBrokerIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, sqlite3.Error) as exc:
        raise CredentialBrokerIntegrityError(
            "credential-broker evidence contains an invalid value"
        ) from exc


def _verify(
    connection: sqlite3.Connection,
    *,
    expected_revision: str,
) -> CredentialBrokerIntegrityReport:
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise CredentialBrokerIntegrityError("credential-broker SQLite integrity check failed")
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != EXPECTED_CREDENTIAL_TABLES:
        raise CredentialBrokerIntegrityError("credential-broker table set is incompatible")
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    meta = connection.execute("SELECT * FROM credential_meta WHERE id=1").fetchone()
    if revision is None or revision[0] != expected_revision or meta is None:
        raise CredentialBrokerIntegrityError("credential-broker identity is incompatible")
    high_water = _integer(meta["evidence_generation_high_water"])
    readiness = str(meta["readiness"])
    if (
        _integer(meta["schema_generation"]) != 1
        or high_water < 0
        or readiness not in {"uninitialized", "disabled", "recovering", "ready", "integrity_failed"}
    ):
        raise CredentialBrokerIntegrityError("credential-broker metadata is contradictory")

    events = tuple(
        connection.execute("SELECT * FROM credential_evidence_events ORDER BY evidence_generation")
    )
    if len(events) != high_water or any(
        _integer(row["evidence_generation"]) != expected
        for expected, row in enumerate(events, start=1)
    ):
        raise CredentialBrokerIntegrityError("credential evidence generation has a gap")
    tickets = tuple(connection.execute("SELECT * FROM credential_use_tickets ORDER BY ticket_id"))
    for row in tickets:
        _verify_ticket(row)
    orphan_events = int(
        connection.execute(
            "SELECT COUNT(*) FROM credential_evidence_events ev "
            "LEFT JOIN credential_use_tickets t ON t.ticket_id=ev.ticket_id "
            "WHERE t.ticket_id IS NULL"
        ).fetchone()[0]
    )
    if orphan_events:
        raise CredentialBrokerIntegrityError("credential event has no retained ticket")
    return CredentialBrokerIntegrityReport(
        revision=str(revision[0]),
        readiness=readiness,
        schema_generation=1,
        evidence_generation=high_water,
        registered_tickets=sum(row["state"] == "registered" for row in tickets),
        accepted_tickets=sum(row["state"] == "accepted" for row in tickets),
        completed_tickets=sum(row["state"] == "completed" for row in tickets),
        uncertain_tickets=sum(row["state"] == "uncertain" for row in tickets),
    )


def _verify_ticket(row: sqlite3.Row) -> None:
    state = str(row["state"])
    action = str(row["action"])
    if action not in {"commit_sign", "repository_ssh"} or state not in {
        "registered",
        "accepted",
        "completed",
        "uncertain",
        "revoked",
    }:
        raise CredentialBrokerIntegrityError("credential ticket state is invalid")
    response = row["retained_response"]
    response_digest = row["retained_response_sha256"]
    response_bytes = _integer(row["retained_response_bytes"])
    if response is None:
        if response_digest is not None or response_bytes != 0:
            raise CredentialBrokerIntegrityError("credential retained response is contradictory")
    else:
        if not isinstance(response, bytes) or len(response) != response_bytes:
            raise CredentialBrokerIntegrityError("credential retained response size is invalid")
        if hashlib.sha256(response).hexdigest() != response_digest:
            raise CredentialBrokerIntegrityError("credential retained response digest is invalid")
    if state == "completed" and (
        row["completed_at"] is None
        or row["evidence_sha256"] is None
        or not bool(row["cleanup_complete"])
    ):
        raise CredentialBrokerIntegrityError("completed credential ticket lacks closure")


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CredentialBrokerIntegrityError("credential evidence integer is invalid")
    return value


__all__ = [
    "CREDENTIAL_BROKER_REVISION",
    "EXPECTED_CREDENTIAL_TABLES",
    "CredentialBrokerIntegrityError",
    "CredentialBrokerIntegrityReport",
    "verify_credential_broker_connection",
]

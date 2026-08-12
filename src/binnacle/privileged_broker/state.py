"""Privileged-broker owned accept-or-seal persistence.

This module stores authority decisions only.  It does not implement a package,
systemd, runtime-selector, or other root effect backend.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sqlite3
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import quote

import aiosqlite

from binnacle.domain.privileged import (
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerNoAcceptReason,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
    canonical_sha256,
    canonical_timestamp,
)
from binnacle.ports.privileged import PrivilegedTicketVerifier
from binnacle.privileged_broker.integrity import (
    PrivilegedBrokerIntegrityError,
    verify_privileged_broker_connection,
)

_ZERO_DIGEST: Final = "0" * 64


class PrivilegedStoreError(RuntimeError):
    """Privileged evidence is unavailable, unsafe, or contradictory."""


class PrivilegedStoreConflict(PrivilegedStoreError):
    """A replay differs from the one ticket retained for an operation."""


@dataclass(frozen=True, slots=True)
class PrivilegedStoreSettings:
    path: Path = Path("/var/lib/binnacle-privileged/evidence.db")
    runtime_directory: Path = Path("/run/binnacle-privileged")
    busy_timeout_ms: int = 5_000
    verify_permissions: bool = True
    runtime_group_gid: int | None = None


@dataclass(frozen=True, slots=True)
class PrivilegedStoreIdentity:
    broker_instance_id: str
    boot_id_sha256: str
    protocol_version: str
    build_sha256: str
    profile_sha256: str

    def __post_init__(self) -> None:
        if not self.broker_instance_id or len(self.broker_instance_id) > 160:
            raise PrivilegedStoreError("privileged broker instance identity is invalid")
        if not self.protocol_version or len(self.protocol_version) > 32:
            raise PrivilegedStoreError("privileged broker protocol identity is invalid")
        for value in (self.boot_id_sha256, self.build_sha256, self.profile_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise PrivilegedStoreError("privileged broker identity digest is invalid")


@dataclass(slots=True)
class _StoreLock:
    descriptor: int

    def close(self) -> None:
        if self.descriptor < 0:
            return
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1


class SqlitePrivilegedEvidenceStore:
    """One serialized FULL transaction chooses acceptance or no-accept."""

    def __init__(
        self,
        *,
        connection: aiosqlite.Connection,
        settings: PrivilegedStoreSettings,
        identity: PrivilegedStoreIdentity,
        ticket_verifier: PrivilegedTicketVerifier,
        runtime_lock: _StoreLock,
        broker_generation: int,
        acceptance_enabled: bool,
        readiness: str,
    ) -> None:
        self._connection = connection
        self._settings = settings
        self._identity = identity
        self._ticket_verifier = ticket_verifier
        self._runtime_lock = runtime_lock
        self._broker_generation = broker_generation
        self._acceptance_enabled = acceptance_enabled
        self._readiness = readiness
        self._acceptance_gate = asyncio.Lock()
        self._closed = False

    @property
    def broker_generation(self) -> int:
        return self._broker_generation

    @property
    def readiness(self) -> str:
        return self._readiness

    async def accept_once(self, ticket: PrivilegedTicket) -> BrokerAcceptanceReceipt:
        identity = ticket.routing_identity
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._find_binding(identity)
                if retained is not None:
                    self._require_exact_identity(retained, identity)
                    state = BrokerAcceptanceState(str(retained["acceptance_state"]))
                    if state is BrokerAcceptanceState.ACCEPTED:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.RETAINED_ACCEPTED,
                        )
                        await self._connection.commit()
                        return result
                    if state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                        )
                        await self._connection.commit()
                        return result
                if not self._acceptance_enabled or self._readiness != "ready":
                    raise PrivilegedStoreError("privileged acceptance remains disabled")
                active = await self._fetchone(
                    "SELECT operation_id FROM privileged_operation_bindings "
                    "WHERE active_slot=1 AND operation_id!=? LIMIT 1",
                    (identity.operation_id,),
                )
                if active is not None:
                    raise PrivilegedStoreConflict("another privileged effect retains authority")
                self._ticket_verifier.validate(ticket)
                if retained is None:
                    await self._insert_unresolved(identity)

                now = datetime.now(UTC)
                if not identity.issued_at <= now < identity.expires_at:
                    raise PrivilegedStoreConflict("privileged ticket acceptance deadline elapsed")
                generation = await self._next_evidence_generation(now)
                evidence_sha256 = canonical_sha256(
                    {
                        "action": identity.action,
                        "disposition": "accepted",
                        "evidence_generation": generation,
                        "operation_id": identity.operation_id,
                        "target_profile_sha256": identity.target_profile_sha256,
                        "ticket_id": identity.ticket_id,
                        "ticket_sha256": identity.ticket_sha256,
                    }
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_operation_bindings
                    SET acceptance_state='accepted', evidence_generation=?,
                        acceptance_evidence_sha256=?, accepted_at=?,
                        execution_state='accepted_pre_effect',active_slot=1,updated_at=?
                    WHERE operation_id=? AND acceptance_state='unresolved'
                    """,
                    (
                        generation,
                        evidence_sha256,
                        canonical_timestamp(now),
                        canonical_timestamp(now),
                        identity.operation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("privileged acceptance winner changed")
                await cursor.close()
                await self._append_event(
                    generation=generation,
                    event_id=f"accept_{identity.ticket_sha256[:24]}",
                    operation_id=identity.operation_id,
                    event_type="ticket.accepted",
                    event_sha256=evidence_sha256,
                    recorded_at=now,
                )
                row = await self._required_binding(identity.operation_id)
                await self._connection.commit()
                return self._receipt(row, disposition=BrokerAcceptanceDisposition.ACCEPTED)
            except BaseException:
                await self._connection.rollback()
                raise

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt:
        _require_aware(trusted_time_at, "trusted seal time")
        _require_aware(retain_until, "seal retention time")
        if trusted_time_at < identity.issued_at or retain_until <= trusted_time_at:
            raise PrivilegedStoreError("privileged no-accept retention window is invalid")
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._find_binding(identity)
                if retained is not None:
                    self._require_exact_identity(retained, identity)
                    state = BrokerAcceptanceState(str(retained["acceptance_state"]))
                    if state is BrokerAcceptanceState.ACCEPTED:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.RETAINED_ACCEPTED,
                        )
                        await self._connection.commit()
                        return result
                    if state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                        )
                        await self._connection.commit()
                        return result
                else:
                    await self._insert_unresolved(identity)

                generation = await self._next_evidence_generation(trusted_time_at)
                evidence_sha256 = canonical_sha256(
                    {
                        "boot_id_sha256": self._identity.boot_id_sha256,
                        "disposition": "sealed_no_accept",
                        "evidence_generation": generation,
                        "operation_id": identity.operation_id,
                        "reason": reason,
                        "retain_until": retain_until,
                        "ticket_id": identity.ticket_id,
                        "ticket_sha256": identity.ticket_sha256,
                        "trusted_time_at": trusted_time_at,
                    }
                )
                await self._connection.execute(
                    """
                    INSERT INTO privileged_no_accept_tombstones (
                      operation_id,ticket_id,ticket_sha256,reason,boot_id_sha256,
                      evidence_generation,evidence_sha256,trusted_time_at,retain_until,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        identity.operation_id,
                        identity.ticket_id,
                        identity.ticket_sha256,
                        reason.value,
                        self._identity.boot_id_sha256,
                        generation,
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        canonical_timestamp(retain_until),
                        canonical_timestamp(trusted_time_at),
                    ),
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_operation_bindings
                    SET acceptance_state='sealed_no_accept', evidence_generation=?,
                        acceptance_evidence_sha256=?, sealed_at=?,execution_state='terminal',
                        effect_knowledge='known_no_subeffect',result_evidence_sha256=?,
                        closed_at=?,updated_at=?
                    WHERE operation_id=? AND acceptance_state='unresolved'
                    """,
                    (
                        generation,
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        canonical_timestamp(trusted_time_at),
                        identity.operation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("privileged no-accept winner changed")
                await cursor.close()
                await self._append_event(
                    generation=generation,
                    event_id=f"seal_{identity.ticket_sha256[:24]}",
                    operation_id=identity.operation_id,
                    event_type="ticket.sealed_no_accept",
                    event_sha256=evidence_sha256,
                    recorded_at=trusted_time_at,
                )
                row = await self._required_binding(identity.operation_id)
                await self._connection.commit()
                return self._receipt(
                    row,
                    disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None:
        row = await self._fetchone(
            "SELECT * FROM privileged_operation_bindings WHERE operation_id=?",
            (operation_id,),
        )
        return None if row is None else self._snapshot(row)

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

    async def _insert_unresolved(self, identity: PrivilegedTicketRoutingIdentity) -> None:
        try:
            await self._connection.execute(
                """
                INSERT INTO privileged_operation_bindings (
                  operation_id,ticket_id,ticket_sha256,ticket_nonce_sha256,action,
                  target_profile_id,target_profile_sha256,broker_profile_sha256,
                  request_fingerprint_sha256,current_state_binding_sha256,
                  policy_evidence_sha256,expires_at,acceptance_state,evidence_generation,
                  acceptance_evidence_sha256,execution_state,effect_knowledge,
                  active_slot,result_evidence_sha256,created_at,accepted_at,sealed_at,closed_at,
                  updated_at,last_reconciled_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'unresolved',0,NULL,'not_accepted','none',
                          NULL,NULL,?,NULL,NULL,NULL,?,NULL)
                """,
                (
                    identity.operation_id,
                    identity.ticket_id,
                    identity.ticket_sha256,
                    identity.ticket_nonce_sha256,
                    identity.action.value,
                    identity.target_profile_id,
                    identity.target_profile_sha256,
                    identity.broker_profile_sha256,
                    identity.request_fingerprint_sha256,
                    identity.current_state_binding_sha256,
                    identity.policy_evidence_sha256,
                    canonical_timestamp(identity.expires_at),
                    canonical_timestamp(identity.issued_at),
                    canonical_timestamp(identity.issued_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PrivilegedStoreConflict("privileged ticket identity is already bound") from exc

    async def _find_binding(
        self,
        identity: PrivilegedTicketRoutingIdentity,
    ) -> sqlite3.Row | None:
        cursor = await self._connection.execute(
            """
            SELECT * FROM privileged_operation_bindings
            WHERE operation_id=? OR ticket_id=? OR ticket_sha256=? OR ticket_nonce_sha256=?
            ORDER BY operation_id LIMIT 2
            """,
            (
                identity.operation_id,
                identity.ticket_id,
                identity.ticket_sha256,
                identity.ticket_nonce_sha256,
            ),
        )
        rows = tuple(await cursor.fetchall())
        await cursor.close()
        if len(rows) > 1:
            raise PrivilegedStoreConflict("privileged ticket identity crosses retained bindings")
        return None if not rows else rows[0]

    @staticmethod
    def _require_exact_identity(
        row: sqlite3.Row,
        identity: PrivilegedTicketRoutingIdentity,
    ) -> None:
        if (
            str(row["operation_id"]) != identity.operation_id
            or str(row["ticket_id"]) != identity.ticket_id
            or str(row["ticket_sha256"]) != identity.ticket_sha256
            or str(row["ticket_nonce_sha256"]) != identity.ticket_nonce_sha256
            or str(row["action"]) != identity.action.value
            or str(row["target_profile_id"]) != identity.target_profile_id
            or str(row["target_profile_sha256"]) != identity.target_profile_sha256
            or str(row["broker_profile_sha256"]) != identity.broker_profile_sha256
            or str(row["request_fingerprint_sha256"]) != identity.request_fingerprint_sha256
            or str(row["current_state_binding_sha256"]) != identity.current_state_binding_sha256
            or str(row["policy_evidence_sha256"]) != identity.policy_evidence_sha256
            or _timestamp(row["created_at"]) != identity.issued_at
            or _timestamp(row["expires_at"]) != identity.expires_at
        ):
            raise PrivilegedStoreConflict("privileged ticket conflicts with retained binding")

    async def _next_evidence_generation(self, recorded_at: datetime) -> int:
        row = await self._fetchone(
            "SELECT evidence_generation_high_water,updated_at FROM privileged_meta WHERE id=1"
        )
        if row is None:
            raise PrivilegedStoreError("privileged metadata singleton is absent")
        generation = _integer(row["evidence_generation_high_water"]) + 1
        metadata_time = max(recorded_at, _timestamp(row["updated_at"]))
        await self._connection.execute(
            "UPDATE privileged_meta SET evidence_generation_high_water=?,updated_at=? WHERE id=1",
            (generation, canonical_timestamp(metadata_time)),
        )
        return generation

    async def _append_event(
        self,
        *,
        generation: int,
        event_id: str,
        operation_id: str,
        event_type: str,
        event_sha256: str,
        recorded_at: datetime,
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO privileged_evidence_events (
              evidence_generation,event_id,operation_id,event_type,event_sha256,recorded_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                generation,
                event_id,
                operation_id,
                event_type,
                event_sha256,
                canonical_timestamp(recorded_at),
            ),
        )

    async def _required_binding(self, operation_id: str) -> sqlite3.Row:
        row = await self._fetchone(
            "SELECT * FROM privileged_operation_bindings WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            raise PrivilegedStoreError("privileged binding disappeared")
        return row

    async def _fetchone(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> sqlite3.Row | None:
        cursor = await self._connection.execute(query, parameters)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    def _receipt(
        row: sqlite3.Row,
        *,
        disposition: BrokerAcceptanceDisposition,
    ) -> BrokerAcceptanceReceipt:
        evidence_sha256 = row["acceptance_evidence_sha256"]
        if evidence_sha256 is None:
            raise PrivilegedStoreError("privileged decision lacks retained evidence")
        knowledge = (
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            if disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
            else PrivilegedEffectKnowledge.KNOWN_EFFECT
        )
        return BrokerAcceptanceReceipt(
            operation_id=str(row["operation_id"]),
            ticket_id=str(row["ticket_id"]),
            ticket_sha256=str(row["ticket_sha256"]),
            disposition=disposition,
            evidence_generation=_integer(row["evidence_generation"]),
            effect_knowledge=knowledge,
            evidence_sha256=str(evidence_sha256),
        )

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> BrokerBindingSnapshot:
        return BrokerBindingSnapshot(
            identity=PrivilegedTicketRoutingIdentity(
                operation_id=str(row["operation_id"]),
                ticket_id=str(row["ticket_id"]),
                ticket_sha256=str(row["ticket_sha256"]),
                ticket_nonce_sha256=str(row["ticket_nonce_sha256"]),
                action=PrivilegedAction(str(row["action"])),
                target_profile_id=str(row["target_profile_id"]),
                target_profile_sha256=str(row["target_profile_sha256"]),
                broker_profile_sha256=str(row["broker_profile_sha256"]),
                request_fingerprint_sha256=str(row["request_fingerprint_sha256"]),
                current_state_binding_sha256=str(row["current_state_binding_sha256"]),
                policy_evidence_sha256=str(row["policy_evidence_sha256"]),
                issued_at=_timestamp(row["created_at"]),
                expires_at=_timestamp(row["expires_at"]),
            ),
            acceptance_state=BrokerAcceptanceState(str(row["acceptance_state"])),
            evidence_generation=_integer(row["evidence_generation"]),
            acceptance_evidence_sha256=_optional_text(row["acceptance_evidence_sha256"]),
            execution_state=BrokerExecutionState(str(row["execution_state"])),
            effect_knowledge=PrivilegedEffectKnowledge(str(row["effect_knowledge"])),
            result_evidence_sha256=_optional_text(row["result_evidence_sha256"]),
            accepted_at=_optional_timestamp(row["accepted_at"]),
            sealed_at=_optional_timestamp(row["sealed_at"]),
            closed_at=_optional_timestamp(row["closed_at"]),
            last_reconciled_at=_optional_timestamp(row["last_reconciled_at"]),
        )


async def open_privileged_store(
    *,
    settings: PrivilegedStoreSettings,
    identity: PrivilegedStoreIdentity,
    ticket_verifier: PrivilegedTicketVerifier,
    acceptance_enabled: bool = False,
) -> SqlitePrivilegedEvidenceStore:
    _validate_settings(settings)
    _verify_state_path(settings)
    runtime_lock = _acquire_lock(settings)
    try:
        try:
            integrity_connection = sqlite3.connect(
                f"file:{quote(str(settings.path), safe='/')}?mode=ro",
                uri=True,
            )
            try:
                report = verify_privileged_broker_connection(integrity_connection)
            finally:
                integrity_connection.close()
        except (PrivilegedBrokerIntegrityError, sqlite3.Error) as exc:
            raise PrivilegedStoreError("privileged durable evidence verification failed") from exc

        connection = await aiosqlite.connect(settings.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA synchronous=FULL")
        await connection.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
        meta = await _fetchone(connection, "SELECT * FROM privileged_meta WHERE id=1")
        if meta is None or _integer(meta["schema_generation"]) != 1:
            raise PrivilegedStoreError("privileged metadata is absent or incompatible")
        initialized = str(meta["build_sha256"]) != _ZERO_DIGEST
        retained_bindings = (
            report.unresolved_bindings + report.accepted_bindings + report.sealed_bindings
        )
        if (
            initialized
            and retained_bindings
            and (
                str(meta["build_sha256"]) != identity.build_sha256
                or str(meta["profile_sha256"]) != identity.profile_sha256
                or str(meta["protocol_version"]) != identity.protocol_version
            )
        ):
            raise PrivilegedStoreError("retained privileged evidence requires exact identity")
        outstanding = await _single_integer(
            connection,
            "SELECT COUNT(*) FROM privileged_operation_bindings "
            "WHERE acceptance_state='accepted' AND execution_state!='terminal'",
        )
        readiness = (
            "restricted_recovery"
            if outstanding
            else ("ready" if acceptance_enabled else "disabled")
        )
        now = datetime.now(UTC)
        await connection.execute("BEGIN IMMEDIATE")
        await connection.execute(
            """
            UPDATE privileged_meta
            SET broker_instance_id=?,broker_generation=broker_generation+1,
                protocol_version=?,build_sha256=?,profile_sha256=?,readiness=?,
                failure_reason=NULL,updated_at=? WHERE id=1
            """,
            (
                identity.broker_instance_id,
                identity.protocol_version,
                identity.build_sha256,
                identity.profile_sha256,
                readiness,
                canonical_timestamp(now),
            ),
        )
        generation_row = await _fetchone(
            connection,
            "SELECT broker_generation FROM privileged_meta WHERE id=1",
        )
        if generation_row is None:
            raise PrivilegedStoreError("privileged broker generation is absent")
        await connection.commit()
        return SqlitePrivilegedEvidenceStore(
            connection=connection,
            settings=settings,
            identity=identity,
            ticket_verifier=ticket_verifier,
            runtime_lock=runtime_lock,
            broker_generation=_integer(generation_row["broker_generation"]),
            acceptance_enabled=acceptance_enabled,
            readiness=readiness,
        )
    except BaseException:
        runtime_lock.close()
        if "connection" in locals():
            await connection.close()
        raise


def _validate_settings(settings: PrivilegedStoreSettings) -> None:
    if settings.path != Path("/var/lib/binnacle-privileged/evidence.db") and (
        settings.verify_permissions
    ):
        raise PrivilegedStoreError("privileged evidence path is fixed")
    if settings.runtime_directory != Path("/run/binnacle-privileged") and (
        settings.verify_permissions
    ):
        raise PrivilegedStoreError("privileged runtime path is fixed")
    if not 100 <= settings.busy_timeout_ms <= 60_000:
        raise PrivilegedStoreError("privileged busy timeout is outside the safe range")


def _verify_state_path(settings: PrivilegedStoreSettings) -> None:
    path = settings.path
    try:
        parent = path.parent.lstat()
        database = path.lstat()
    except OSError as exc:
        raise PrivilegedStoreError("privileged evidence path is unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISREG(database.st_mode)
        or stat.S_ISLNK(database.st_mode)
    ):
        raise PrivilegedStoreError("privileged evidence path is unsafe")
    if settings.verify_permissions and (
        parent.st_uid != 0
        or parent.st_gid != 0
        or stat.S_IMODE(parent.st_mode) != 0o700
        or database.st_uid != 0
        or database.st_gid != 0
        or stat.S_IMODE(database.st_mode) != 0o600
    ):
        raise PrivilegedStoreError("privileged evidence ownership or mode is invalid")


def _acquire_lock(settings: PrivilegedStoreSettings) -> _StoreLock:
    try:
        metadata = settings.runtime_directory.lstat()
    except OSError as exc:
        raise PrivilegedStoreError("privileged runtime directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise PrivilegedStoreError("privileged runtime directory is unsafe")
    if settings.verify_permissions and (
        metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o750
        or settings.runtime_group_gid is None
        or metadata.st_gid != settings.runtime_group_gid
    ):
        raise PrivilegedStoreError("privileged runtime ownership or mode is invalid")
    descriptor = os.open(
        settings.runtime_directory / "broker-writer.lock",
        os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        lock_metadata = os.fstat(descriptor)
        if settings.verify_permissions and (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != 0
            or lock_metadata.st_gid != 0
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
        ):
            raise PrivilegedStoreError("privileged writer lock ownership or mode is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except PrivilegedStoreError:
        os.close(descriptor)
        raise
    except BlockingIOError as exc:
        os.close(descriptor)
        raise PrivilegedStoreError("privileged writer or maintenance process is active") from exc
    except OSError as exc:
        os.close(descriptor)
        raise PrivilegedStoreError("privileged writer lock is unavailable") from exc
    return _StoreLock(descriptor)


async def _fetchone(
    connection: aiosqlite.Connection,
    query: str,
    parameters: Sequence[object] = (),
) -> sqlite3.Row | None:
    cursor = await connection.execute(query, parameters)
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def _single_integer(connection: aiosqlite.Connection, query: str) -> int:
    row = await _fetchone(connection, query)
    if row is None:
        raise PrivilegedStoreError("privileged database query returned no row")
    return _integer(row[0])


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PrivilegedStoreError("privileged timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_timestamp(value: object) -> datetime | None:
    return None if value is None else _timestamp(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrivilegedStoreError("privileged evidence integer is invalid")
    return value


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedStoreError(f"{name} is not timezone-aware")


__all__ = [
    "PrivilegedStoreConflict",
    "PrivilegedStoreError",
    "PrivilegedStoreIdentity",
    "PrivilegedStoreSettings",
    "SqlitePrivilegedEvidenceStore",
    "open_privileged_store",
]

"""Bounded read-only verification of every durable operation-kernel store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.adapters.audit.verify import AuditChainVerifier
from binnacle.adapters.sqlite.engine import acquire_existing_runtime_lock
from binnacle.domain.audit import AuditIntegrityError, AuditRuntimeIdentity, AuditTail
from binnacle.domain.payload import is_canonical_payload_id

EXPECTED_REVISION = "0001_durable_operation_kernel"
EXPECTED_TABLES = frozenset(
    {
        "alembic_version",
        "kernel_meta",
        "controller_owners",
        "operations",
        "operation_transitions",
        "idempotency_bindings",
        "policy_decisions",
        "payload_objects",
        "operation_evidence",
    }
)


class KernelVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelVerificationPaths:
    database: Path
    audit: Path
    payload: Path
    runtime: Path


@dataclass(frozen=True, slots=True)
class DatabaseVerification:
    revision: str
    journal_mode: str
    synchronous: int
    foreign_keys: int
    busy_timeout_ms: int
    wal_autocheckpoint_pages: int
    operation_count: int
    idempotency_count: int
    payload_count: int
    audit_tail_cache: AuditTail
    audit_failure_latched: bool
    audit_failure_generation: int
    audit_recovered_generation: int
    audit_recovery_evidence_sha256: str | None
    consequential_admission_enabled: bool
    device_id: str
    audit_stream_id: str
    audit_epoch: str


@dataclass(frozen=True, slots=True)
class AuditVerification:
    tail: AuditTail
    obligation_count: int
    matched_obligations: int
    unmatched_obligations: int
    recovery_evidence_valid: bool


@dataclass(frozen=True, slots=True)
class PayloadVerification:
    metadata_count: int
    complete_count: int
    building_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class KernelVerificationReport:
    database: DatabaseVerification
    audit: AuditVerification
    payload: PayloadVerification
    reason_codes: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return not self.reason_codes

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "pass" if self.healthy else "fail",
            "availability": "available" if self.healthy else "unavailable",
            "database_healthy": "database_integrity_failed" not in self.reason_codes,
            "audit_healthy": not any(reason.startswith("audit_") for reason in self.reason_codes),
            "payload_healthy": "payload_integrity_failed" not in self.reason_codes,
            "audit_failure_latched": self.database.audit_failure_latched,
            "audit_failure_generation": self.database.audit_failure_generation,
            "audit_recovered_generation": self.database.audit_recovered_generation,
            "consequential_admission_enabled": (self.database.consequential_admission_enabled),
            "audit_obligation_count": self.audit.obligation_count,
            "obligation_count": self.audit.obligation_count,
            "audit_obligation_matched": self.audit.matched_obligations,
            "audit_obligation_unmatched": self.audit.unmatched_obligations,
            "audit_sequence": self.audit.tail.sequence,
            "database_revision": self.database.revision,
            "operation_count": self.database.operation_count,
            "idempotency_count": self.database.idempotency_count,
            "payload_count": self.payload.metadata_count,
            "reason_codes": list(self.reason_codes),
        }


async def verify_operation_kernel_read_only(
    *,
    paths: KernelVerificationPaths,
    audit_schema: dict[str, object],
    busy_timeout_ms: int,
    wal_autocheckpoint_pages: int,
) -> KernelVerificationReport:
    """Acquire the existing maintenance lock and perform zero durable writes."""

    lock = acquire_existing_runtime_lock(paths.runtime)
    try:
        connection = _open_read_only_database(paths.database)
        try:
            database, payload_rows = _verify_database(
                connection,
                database_path=paths.database,
                busy_timeout_ms=busy_timeout_ms,
                wal_autocheckpoint_pages=wal_autocheckpoint_pages,
            )
        finally:
            connection.close()
        audit = await _verify_audit(
            directory=paths.audit,
            obligation_directory=paths.database.parent / "audit-obligations",
            schema=audit_schema,
            database=database,
        )
        payload = _verify_payloads(paths.payload, payload_rows)
        reasons: list[str] = []
        if database.audit_tail_cache != audit.tail:
            reasons.append("audit_tail_cache_mismatch")
        if database.audit_failure_latched or (
            database.audit_failure_generation != database.audit_recovered_generation
        ):
            reasons.append("audit_recovery_required")
        if audit.obligation_count:
            reasons.append("audit_obligations_survive")
        if not audit.recovery_evidence_valid:
            reasons.append("audit_recovery_evidence_invalid")
        return KernelVerificationReport(database, audit, payload, tuple(sorted(set(reasons))))
    finally:
        lock.close()


def verify_database_read_only(
    *,
    database_path: Path,
    runtime_directory: Path,
    busy_timeout_ms: int,
    wal_autocheckpoint_pages: int,
) -> DatabaseVerification:
    lock = acquire_existing_runtime_lock(runtime_directory)
    try:
        connection = _open_read_only_database(database_path)
        try:
            report, _ = _verify_database(
                connection,
                database_path=database_path,
                busy_timeout_ms=busy_timeout_ms,
                wal_autocheckpoint_pages=wal_autocheckpoint_pages,
            )
            return report
        finally:
            connection.close()
    finally:
        lock.close()


def _open_read_only_database(path: Path) -> sqlite3.Connection:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise KernelVerificationError("durable database is absent") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise KernelVerificationError("durable database path is unsafe")
    wal_path = Path(f"{path}-wal")
    if wal_path.exists() and wal_path.stat().st_size:
        raise KernelVerificationError("database has an uncheckpointed WAL")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _verify_database(
    connection: sqlite3.Connection,
    *,
    database_path: Path,
    busy_timeout_ms: int,
    wal_autocheckpoint_pages: int,
) -> tuple[DatabaseVerification, tuple[sqlite3.Row, ...]]:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise KernelVerificationError("SQLite integrity check failed")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    connection.execute(f"PRAGMA wal_autocheckpoint={wal_autocheckpoint_pages}")
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != EXPECTED_TABLES:
        raise KernelVerificationError("authoritative database table set is unexpected")
    revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if revision_row is None or revision_row[0] != EXPECTED_REVISION:
        raise KernelVerificationError("Alembic revision does not match")
    _verify_database_invariants(connection)
    meta = connection.execute("SELECT * FROM kernel_meta WHERE id=1").fetchone()
    if meta is None:
        raise KernelVerificationError("kernel metadata singleton is absent")
    payload_rows = tuple(connection.execute("SELECT * FROM payload_objects ORDER BY payload_id"))
    report = DatabaseVerification(
        revision=str(revision_row[0]),
        journal_mode=_database_journal_mode(database_path),
        synchronous=int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        foreign_keys=int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
        busy_timeout_ms=int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        wal_autocheckpoint_pages=int(connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]),
        operation_count=int(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]),
        idempotency_count=int(
            connection.execute("SELECT COUNT(*) FROM idempotency_bindings").fetchone()[0]
        ),
        payload_count=len(payload_rows),
        audit_tail_cache=AuditTail(meta["audit_last_sequence"], meta["audit_last_hash"]),
        audit_failure_latched=bool(meta["audit_failure_latched"]),
        audit_failure_generation=int(meta["audit_failure_generation"]),
        audit_recovered_generation=int(meta["audit_recovered_generation"]),
        audit_recovery_evidence_sha256=meta["audit_recovery_evidence_sha256"],
        consequential_admission_enabled=bool(meta["consequential_admission_enabled"]),
        device_id=str(meta["device_id"]),
        audit_stream_id=str(meta["audit_stream_id"]),
        audit_epoch=str(meta["audit_epoch"]),
    )
    if (
        report.journal_mode.casefold() != "wal"
        or report.synchronous != 2
        or report.foreign_keys != 1
        or report.busy_timeout_ms != busy_timeout_ms
        or report.wal_autocheckpoint_pages != wal_autocheckpoint_pages
    ):
        raise KernelVerificationError(
            "SQLite durability pragmas do not match "
            f"(journal={report.journal_mode}, synchronous={report.synchronous}, "
            f"foreign_keys={report.foreign_keys}, busy_timeout={report.busy_timeout_ms}, "
            f"wal_autocheckpoint={report.wal_autocheckpoint_pages})"
        )
    return report, payload_rows


def _database_journal_mode(path: Path) -> str:
    with path.open("rb") as stream:
        header = stream.read(20)
    if len(header) != 20 or not header.startswith(b"SQLite format 3\0"):
        raise KernelVerificationError("SQLite database header is invalid")
    return "wal" if header[18:20] == b"\x02\x02" else "rollback"


def _verify_database_invariants(connection: sqlite3.Connection) -> None:
    checks = {
        "operation lifecycle snapshot": """
            SELECT COUNT(*) FROM operations
            WHERE state_version < 1 OR automatic_retry_allowed != 0
               OR state NOT IN ('received','rejected','authorised','running','paused',
                                'cancelling','cancelled','succeeded','failed','uncertain')
               OR effect_knowledge NOT IN
                  ('none','known_no_effect','known_effect','partial','uncertain')
        """,
        "initial transition": """
            SELECT COUNT(*) FROM operations o
            LEFT JOIN operation_transitions t
              ON t.operation_id=o.operation_id AND t.state_version=1
            WHERE t.operation_id IS NULL OR t.from_state IS NOT NULL OR t.to_state!='received'
        """,
        "transition head": """
            SELECT COUNT(*) FROM operations o
            WHERE NOT EXISTS (
              SELECT 1 FROM operation_transitions t
              WHERE t.operation_id=o.operation_id
                AND t.state_version=o.state_version AND t.to_state=o.state
            ) OR o.state_version != (
              SELECT COUNT(*) FROM operation_transitions t2
              WHERE t2.operation_id=o.operation_id
            )
        """,
        "policy cardinality": """
            SELECT COUNT(*) FROM operations o
            WHERE o.state!='received' AND
              (SELECT COUNT(*) FROM policy_decisions p WHERE p.operation_id=o.operation_id) != 1
        """,
        "idempotency owner shape": """
            SELECT COUNT(*) FROM idempotency_bindings
            WHERE (record_kind='full' AND
                   (owner_controller_id IS NULL OR owner_controller_epoch IS NULL))
               OR (record_kind='tombstone' AND
                   (owner_controller_id IS NOT NULL OR owner_controller_epoch IS NOT NULL))
        """,
        "trusted time ordering": """
            SELECT COUNT(*) FROM kernel_meta
            WHERE trusted_time_generation < 1
               OR audit_recovered_generation > audit_failure_generation
               OR (audit_failure_latched=1 AND
                   audit_failure_generation <= audit_recovered_generation)
               OR (consequential_admission_enabled=1 AND
                   (audit_failure_latched=1 OR
                    audit_failure_generation!=audit_recovered_generation))
        """,
    }
    for name, query in checks.items():
        if int(connection.execute(query).fetchone()[0]):
            raise KernelVerificationError(f"{name} invariant failed")


async def _verify_audit(
    *,
    directory: Path,
    obligation_directory: Path,
    schema: dict[str, object],
    database: DatabaseVerification,
) -> AuditVerification:
    _require_safe_directory(directory)
    epoch_directory = directory / "epochs" / database.audit_epoch
    _require_safe_directory(epoch_directory)
    segments = sorted(epoch_directory.glob("segment-*.jsonl"))
    if not segments:
        raise KernelVerificationError("audit journal segment is absent")
    lines: list[bytes] = []
    for segment in segments:
        info = segment.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise KernelVerificationError("audit segment path is unsafe")
        segment_lines = segment.read_bytes().splitlines(keepends=True)
        if segment_lines and not segment_lines[-1].endswith(b"\n"):
            raise AuditIntegrityError("audit journal is truncated")
        lines.extend(segment_lines)
    identity = AuditRuntimeIdentity(
        stream_id=database.audit_stream_id,
        audit_epoch=database.audit_epoch,
        segment_id="verification-only",
        boot_id="verification-only",
        device_id=database.device_id,
        server_build_sha256="0" * 64,
        tool_manifest_sha256="0" * 64,
        schema_registry_sha256="0" * 64,
        device_profile_version="verification-only",
        policy_version="verification-only",
        redaction_policy_version="verification-only",
    )
    tail = AuditChainVerifier(schema, expected_identity=identity).verify_lines(lines)
    events = [json.loads(line) for line in lines]
    _require_safe_directory(obligation_directory)
    obligations = await FileAuditObligationStore(obligation_directory).scan()
    matched = 0
    for marker in obligations:
        if _matching_obligation_event(
            events, marker.obligation_id, marker.operation_id, marker.running_state_version
        ):
            matched += 1
    recovery_valid = _recovery_evidence_valid(events, database)
    return AuditVerification(
        tail,
        len(obligations),
        matched,
        len(obligations) - matched,
        recovery_valid,
    )


def _matching_obligation_event(
    events: list[object], obligation_id: str, operation_id: str, running_version: int
) -> bool:
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        facts = event.get("safe_facts")
        if not isinstance(payload, dict) or not isinstance(facts, list):
            continue
        if (
            event.get("operation_id") == operation_id
            and obligation_id in event.get("correlation_ids", [])
            and payload.get("kind")
            in {"effect.started", "effect.observed", "effect.failed", "recovery.completed"}
            and any(
                isinstance(item, dict)
                and item.get("name") == "running_state_version"
                and item.get("value") == running_version
                for item in facts
            )
        ):
            return True
    return False


def _recovery_evidence_valid(events: list[object], database: DatabaseVerification) -> bool:
    generation = database.audit_recovered_generation
    if generation == 0:
        return True
    expected_hash = database.audit_recovery_evidence_sha256
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        facts = event.get("safe_facts")
        if not isinstance(payload, dict) or not isinstance(facts, list):
            continue
        if (
            event.get("event_hash") == expected_hash
            and payload.get("kind") == "recovery.completed"
            and payload.get("reason_code") == "audit_failure_recovered"
            and any(
                isinstance(item, dict)
                and item.get("name") == "audit_failure_generation"
                and item.get("value") == generation
                for item in facts
            )
        ):
            return True
    return False


def _verify_payloads(directory: Path, rows: tuple[sqlite3.Row, ...]) -> PayloadVerification:
    _require_safe_directory(directory)
    objects = directory / "objects"
    temporary = directory / "tmp"
    _require_safe_directory(objects)
    _require_safe_directory(temporary)
    expected_objects: set[str] = set()
    expected_temporary: set[str] = set()
    complete = 0
    building = 0
    total_bytes = 0
    for row in rows:
        payload_id = str(row["payload_id"])
        if row["relative_path"] != f"objects/{payload_id}" or not is_canonical_payload_id(
            payload_id
        ):
            raise KernelVerificationError("payload metadata path is not canonical")
        lifecycle = str(row["lifecycle"])
        count = int(row["decoded_byte_count"])
        total_bytes += count
        if lifecycle == "complete":
            path = objects / payload_id
            _verify_payload_file(path, count, str(row["sha256"]))
            expected_objects.add(path.name)
            complete += 1
        elif lifecycle == "building":
            path = temporary / f"{payload_id}.part"
            _verify_payload_file(path, count, None)
            expected_temporary.add(path.name)
            building += 1
        elif (objects / payload_id).exists() or (temporary / f"{payload_id}.part").exists():
            raise KernelVerificationError("inactive payload retains bytes")
    if _regular_entry_names(objects) != expected_objects:
        raise KernelVerificationError("payload object directory contains orphan bytes")
    if _regular_entry_names(temporary) != expected_temporary:
        raise KernelVerificationError("payload temporary directory contains orphan bytes")
    return PayloadVerification(len(rows), complete, building, total_bytes)


def _verify_payload_file(path: Path, byte_count: int, expected_digest: str | None) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise KernelVerificationError("retained payload bytes are missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise KernelVerificationError("retained payload path is unsafe")
    if info.st_size != byte_count:
        raise KernelVerificationError("retained payload size disagrees with metadata")
    if expected_digest is not None:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != expected_digest:
            raise KernelVerificationError("retained payload digest disagrees with metadata")


def _regular_entry_names(directory: Path) -> set[str]:
    names: set[str] = set()
    for path in directory.iterdir():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise KernelVerificationError("protected directory contains an unsafe entry")
        names.add(path.name)
    return names


def _require_safe_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise KernelVerificationError("required protected directory is absent") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise KernelVerificationError("protected directory path is unsafe")

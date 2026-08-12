"""Bounded read-only verification of every durable operation-kernel store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.adapters.audit.verify import AuditChainVerifier
from binnacle.adapters.sqlite.engine import acquire_existing_runtime_lock
from binnacle.domain.audit import AuditIntegrityError, AuditRuntimeIdentity, AuditTail
from binnacle.domain.payload import is_canonical_payload_id
from binnacle.domain.probe_workspace import (
    ProbeArtifact,
    ProbeArtifactState,
    ProbeOperationKind,
    ProbePathLedger,
    ProbePathSnapshot,
    operation_fingerprint_sha256,
    prepared_input_sha256,
    validate_path_snapshot,
)

EXPECTED_REVISION = "0004_execution_operations"
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
        "probe_operations",
        "probe_artifacts",
        "probe_path_ledger",
        "registered_workspaces",
        "development_sessions",
        "workspace_operations",
        "workspace_mutation_fences",
        "command_operations",
        "command_cancel_requests",
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
    probe_operation_count: int
    probe_artifact_count: int
    probe_path_count: int
    registered_workspace_count: int
    development_session_count: int
    workspace_operation_count: int
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
            "probe_workspace_healthy": "probe_integrity_failed" not in self.reason_codes,
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
            "probe_operation_count": self.database.probe_operation_count,
            "probe_artifact_count": self.database.probe_artifact_count,
            "probe_path_count": self.database.probe_path_count,
            "registered_workspace_count": self.database.registered_workspace_count,
            "development_session_count": self.database.development_session_count,
            "workspace_operation_count": self.database.workspace_operation_count,
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
    _verify_probe_invariants(connection)
    _verify_development_workspace_invariants(connection)
    _verify_command_execution_invariants(connection)
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
        probe_operation_count=int(
            connection.execute("SELECT COUNT(*) FROM probe_operations").fetchone()[0]
        ),
        probe_artifact_count=int(
            connection.execute("SELECT COUNT(*) FROM probe_artifacts").fetchone()[0]
        ),
        probe_path_count=int(
            connection.execute("SELECT COUNT(*) FROM probe_path_ledger").fetchone()[0]
        ),
        registered_workspace_count=int(
            connection.execute("SELECT COUNT(*) FROM registered_workspaces").fetchone()[0]
        ),
        development_session_count=int(
            connection.execute("SELECT COUNT(*) FROM development_sessions").fetchone()[0]
        ),
        workspace_operation_count=int(
            connection.execute("SELECT COUNT(*) FROM workspace_operations").fetchone()[0]
        ),
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
            WHERE schema_generation != 4 OR trusted_time_generation < 1
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


def _verify_development_workspace_invariants(connection: sqlite3.Connection) -> None:
    checks = {
        "registered workspace fence": """
            SELECT COUNT(*) FROM registered_workspaces w
            LEFT JOIN workspace_mutation_fences f ON f.workspace_id=w.workspace_id
            WHERE f.workspace_id IS NULL
        """,
        "development session live slot": """
            SELECT COUNT(*) FROM (
              SELECT device_id, device_epoch, workspace_id
              FROM development_sessions
              WHERE state IN ('pending','active')
              GROUP BY device_id, device_epoch, workspace_id
              HAVING COUNT(*) != 1
            )
        """,
        "development session provenance": """
            SELECT COUNT(*) FROM development_sessions s
            LEFT JOIN registered_workspaces w ON w.workspace_id=s.workspace_id
            LEFT JOIN operations o ON o.operation_id=s.begin_operation_id
            LEFT JOIN policy_decisions p ON p.operation_id=s.begin_operation_id
            WHERE w.workspace_id IS NULL OR o.operation_id IS NULL
               OR p.operation_id IS NULL
               OR s.workspace_profile_sha256!=w.profile_sha256
               OR s.workspace_root_identity_sha256!=w.root_identity_sha256
               OR s.workspace_mount_identity_sha256!=w.mount_identity_sha256
               OR s.controller_id!=o.controller_id
               OR s.controller_epoch!=o.controller_epoch
               OR s.device_id!=o.device_id OR s.device_epoch!=o.device_epoch
               OR p.decision!='allow' OR p.policy_version!=s.policy_version
               OR p.controller_id!=o.controller_id OR p.controller_epoch!=o.controller_epoch
               OR p.operation_contract!=o.operation_contract
               OR p.operation_contract_version!=o.operation_contract_version
               OR p.decided_at>s.created_at
               OR o.operation_contract!='development_session_begin'
               OR o.tool_name!='development_session_begin'
               OR o.tool_contract_version!=o.operation_contract_version
               OR o.state IN ('received','rejected')
               OR NOT EXISTS (
                   SELECT 1 FROM idempotency_bindings b WHERE b.operation_id=o.operation_id
               )
               OR EXISTS (
                   SELECT 1 FROM idempotency_bindings b
                   WHERE b.operation_id=o.operation_id
                     AND b.target_identity_sha256 IS NOT p.normalized_target_digest
               )
               OR NOT EXISTS (
                   SELECT 1 FROM operation_transitions t
                   WHERE t.operation_id=o.operation_id AND t.state_version=2
                     AND t.from_state='received' AND t.to_state='authorised'
                     AND t.effect_knowledge='none' AND t.reason_code='policy_allowed'
               )
               OR (s.activation_effect_reference IS NOT NULL
                   AND o.state NOT IN ('running','uncertain','succeeded'))
               OR (s.state='active'
                   AND o.state NOT IN ('running','uncertain','succeeded'))
               OR (o.effect_reference IS NOT NULL
                   AND o.effect_reference IS NOT s.activation_effect_reference)
               OR (o.effect_reference_digest IS NOT NULL
                   AND o.effect_reference_digest
                       IS NOT s.activation_effect_reference_sha256)
               OR (o.state='succeeded'
                   AND (o.effect_knowledge!='known_effect'
                        OR o.effect_reference IS NOT s.activation_effect_reference
                        OR o.effect_reference_digest
                           IS NOT s.activation_effect_reference_sha256))
               OR (s.activation_closure='complete'
                   AND ((s.activation_effect_reference IS NOT NULL
                         AND (o.state!='succeeded' OR o.effect_knowledge!='known_effect'
                              OR o.effect_reference IS NOT s.activation_effect_reference
                              OR o.effect_reference_digest
                                 IS NOT s.activation_effect_reference_sha256))
                        OR (s.activation_effect_reference IS NULL
                            AND (s.started_at IS NOT NULL
                                 OR o.state NOT IN ('rejected','cancelled','failed')
                                 OR o.effect_knowledge!='known_no_effect'
                                 OR o.effect_reference IS NOT NULL
                                 OR o.effect_reference_digest IS NOT NULL))))
        """,
        "workspace operation provenance": """
            SELECT COUNT(*) FROM workspace_operations wo
            LEFT JOIN development_sessions s ON s.session_id=wo.session_id
            LEFT JOIN operations o ON o.operation_id=wo.operation_id
            LEFT JOIN policy_decisions p ON p.operation_id=wo.operation_id
            LEFT JOIN registered_workspaces w ON w.workspace_id=wo.workspace_id
            LEFT JOIN workspace_mutation_fences f ON f.workspace_id=wo.workspace_id
            WHERE s.session_id IS NULL OR o.operation_id IS NULL
               OR p.operation_id IS NULL OR w.workspace_id IS NULL OR f.workspace_id IS NULL
               OR wo.workspace_id!=s.workspace_id
               OR wo.expected_mount_identity_sha256!=s.workspace_mount_identity_sha256
               OR o.controller_id!=s.controller_id OR o.controller_epoch!=s.controller_epoch
               OR o.device_id!=s.device_id OR o.device_epoch!=s.device_epoch
               OR p.decision!='allow' OR p.policy_version!=s.policy_version
               OR p.controller_id!=o.controller_id OR p.controller_epoch!=o.controller_epoch
               OR p.operation_contract!=o.operation_contract
               OR p.operation_contract_version!=o.operation_contract_version
               OR NOT EXISTS (
                   SELECT 1 FROM idempotency_bindings b WHERE b.operation_id=o.operation_id
               )
               OR EXISTS (
                   SELECT 1 FROM idempotency_bindings b
                   WHERE b.operation_id=o.operation_id
                     AND b.target_identity_sha256 IS NOT p.normalized_target_digest
               )
               OR o.operation_contract!=('workspace_' || wo.mutation_kind)
               OR o.tool_name!=o.operation_contract
               OR o.state IN ('received','rejected')
               OR (o.state IN ('authorised','running','paused','cancelling','uncertain')
                   AND f.active_operation_id!=o.operation_id)
        """,
        "workspace fence owner": """
            SELECT COUNT(*) FROM workspace_mutation_fences f
            LEFT JOIN workspace_operations wo ON wo.operation_id=f.active_operation_id
            LEFT JOIN command_operations co ON co.operation_id=f.active_operation_id
            LEFT JOIN operations o ON o.operation_id=f.active_operation_id
            WHERE f.active_operation_id IS NOT NULL
              AND (o.operation_id IS NULL
                   OR (wo.operation_id IS NULL AND co.operation_id IS NULL)
                   OR (wo.operation_id IS NOT NULL AND co.operation_id IS NOT NULL)
                   OR (wo.operation_id IS NOT NULL AND
                       (wo.workspace_id!=f.workspace_id OR
                        f.active_contract!=('workspace_' || wo.mutation_kind)))
                   OR (co.operation_id IS NOT NULL AND
                       (co.workspace_id!=f.workspace_id OR co.closure_state!='pending'))
                   OR o.operation_contract!=f.active_contract
                   OR o.state IN ('received','rejected'))
        """,
    }
    for name, query in checks.items():
        if int(connection.execute(query).fetchone()[0]):
            raise KernelVerificationError(f"{name} invariant failed")


def _verify_command_execution_invariants(connection: sqlite3.Connection) -> None:
    checks = {
        "command operation provenance": """
            SELECT COUNT(*) FROM command_operations co
            LEFT JOIN operations o ON o.operation_id=co.operation_id
            LEFT JOIN development_sessions s ON s.session_id=co.session_id
            LEFT JOIN registered_workspaces w ON w.workspace_id=co.workspace_id
            LEFT JOIN policy_decisions p ON p.policy_decision_id=co.admission_record_id
            LEFT JOIN workspace_mutation_fences f ON f.workspace_id=co.workspace_id
            WHERE o.operation_id IS NULL OR s.session_id IS NULL OR w.workspace_id IS NULL
               OR p.policy_decision_id IS NULL OR f.workspace_id IS NULL
               OR p.operation_id!=co.operation_id OR p.decision!='allow'
               OR p.controller_id!=o.controller_id OR p.controller_epoch!=o.controller_epoch
               OR p.operation_contract!=o.operation_contract
               OR p.operation_contract_version!=o.operation_contract_version
               OR p.runtime_policy_sha256!=co.policy_sha256
               OR o.controller_id!=s.controller_id OR o.controller_epoch!=co.controller_epoch
               OR o.device_id!=s.device_id OR o.device_epoch!=co.device_epoch
               OR co.workspace_id!=s.workspace_id
               OR co.workspace_profile_sha256!=s.workspace_profile_sha256
               OR co.workspace_root_identity_sha256!=s.workspace_root_identity_sha256
               OR co.workspace_mount_identity_sha256!=s.workspace_mount_identity_sha256
               OR co.workspace_profile_sha256!=w.profile_sha256
               OR co.workspace_root_identity_sha256!=w.root_identity_sha256
               OR co.workspace_mount_identity_sha256!=w.mount_identity_sha256
               OR co.development_session_state_version>s.state_version
               OR o.state IN ('received','rejected')
               OR (co.closure_state='pending' AND
                   (f.active_operation_id!=co.operation_id
                    OR f.active_contract!=o.operation_contract
                    OR f.fence_version!=co.workspace_fence_version))
               OR (co.closure_state='complete' AND f.active_operation_id=co.operation_id)
        """,
        "command cancellation provenance": """
            SELECT COUNT(*) FROM command_cancel_requests c
            LEFT JOIN command_operations co ON co.operation_id=c.command_operation_id
            LEFT JOIN operations cancel_op ON cancel_op.operation_id=c.cancel_operation_id
            WHERE co.operation_id IS NULL OR cancel_op.operation_id IS NULL
               OR c.cancel_generation<1
               OR c.cancel_generation>co.phase7_cancel_generation
               OR cancel_op.controller_epoch!=(
                    SELECT o.controller_epoch FROM operations o
                    WHERE o.operation_id=co.operation_id)
               OR cancel_op.device_epoch!=(
                    SELECT o.device_epoch FROM operations o
                    WHERE o.operation_id=co.operation_id)
        """,
        "command cancellation generation": """
            SELECT COUNT(*) FROM command_operations co
            WHERE co.phase7_cancel_generation != (
                SELECT COUNT(*) FROM command_cancel_requests c
                WHERE c.command_operation_id=co.operation_id)
               OR co.phase7_cancel_generation != COALESCE((
                SELECT MAX(c.cancel_generation) FROM command_cancel_requests c
                WHERE c.command_operation_id=co.operation_id), 0)
        """,
    }
    for name, query in checks.items():
        if int(connection.execute(query).fetchone()[0]):
            raise KernelVerificationError(f"{name} invariant failed")


def _verify_probe_invariants(connection: sqlite3.Connection) -> None:
    provenance_errors = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM probe_operations p
            LEFT JOIN operations o ON o.operation_id=p.operation_id
            LEFT JOIN probe_artifacts a ON a.artifact_id=p.artifact_id
            LEFT JOIN idempotency_bindings prepared
              ON prepared.binding_id=p.prepared_binding_id
            LEFT JOIN idempotency_bindings caller
              ON caller.binding_id=p.caller_binding_id
            WHERE o.operation_id IS NULL OR a.artifact_id IS NULL
               OR prepared.binding_id IS NULL OR caller.binding_id IS NULL
               OR prepared.operation_id!=p.operation_id OR caller.operation_id!=p.operation_id
               OR prepared.key_mode!='prepared_execution_nonce'
               OR caller.key_mode!='caller_key'
               OR a.relative_path!=p.relative_path
               OR a.content_sha256!=p.expected_content_sha256
               OR a.owner_controller_id!=o.controller_id
               OR a.owner_controller_epoch!=o.controller_epoch
               OR prepared.owner_controller_id!=o.controller_id
               OR prepared.owner_controller_epoch!=o.controller_epoch
               OR caller.owner_controller_id!=o.controller_id
               OR caller.owner_controller_epoch!=o.controller_epoch
               OR prepared.record_kind!='full' OR caller.record_kind!='full'
               OR prepared.request_fingerprint_sha256!=o.request_fingerprint_sha256
               OR caller.request_fingerprint_sha256!=o.request_fingerprint_sha256
               OR prepared.prepared_state_binding_sha256!=p.prepared_state_binding_sha256
               OR prepared.target_identity_sha256 IS NOT caller.target_identity_sha256
               OR prepared.maximum_effect_sha256 IS NOT caller.maximum_effect_sha256
               OR prepared.tool_name!=('probe_workspace_' || p.probe_operation)
               OR caller.tool_name!=('probe_workspace_' || p.probe_operation)
               OR o.operation_contract!=('probe_workspace_' || p.probe_operation)
               OR o.tool_name!=('probe_workspace_' || p.probe_operation)
               OR prepared.contract_version!='1.1' OR caller.contract_version!='1.1'
               OR o.operation_contract_version!='1.1' OR o.tool_contract_version!='1.1'
               OR (p.probe_operation='write' AND
                   (p.expected_byte_count IS NULL OR p.expected_byte_count!=a.byte_count
                    OR a.create_operation_id!=p.operation_id))
               OR (p.probe_operation='cleanup' AND p.expected_byte_count IS NOT NULL)
            """
        ).fetchone()[0]
    )
    orphan_errors = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM probe_artifacts a
            LEFT JOIN probe_path_ledger l ON l.relative_path=a.relative_path
            WHERE l.relative_path IS NULL
            """
        ).fetchone()[0]
    )
    if provenance_errors or orphan_errors:
        raise KernelVerificationError("probe provenance invariant failed")

    for probe in connection.execute("SELECT * FROM probe_operations ORDER BY operation_id"):
        _verify_probe_operation_provenance(connection, probe)

    ledgers = tuple(connection.execute("SELECT * FROM probe_path_ledger ORDER BY relative_path"))
    for ledger_row in ledgers:
        artifacts = tuple(
            connection.execute(
                "SELECT * FROM probe_artifacts WHERE relative_path=? ORDER BY path_generation",
                (ledger_row["relative_path"],),
            )
        )
        terminal: list[ProbeArtifact] = []
        active: ProbeArtifact | None = None
        for row in artifacts:
            artifact = _probe_artifact(row)
            if artifact.artifact_id == ledger_row["active_artifact_id"]:
                if active is not None:
                    raise KernelVerificationError("probe ledger has duplicate active artifacts")
                active = artifact
            elif artifact.state in {
                ProbeArtifactState.REMOVED,
                ProbeArtifactState.ABANDONED,
            }:
                terminal.append(artifact)
            else:
                raise KernelVerificationError("probe nonterminal artifact is not ledger-active")
        snapshot = ProbePathSnapshot(
            ledger=ProbePathLedger(
                relative_path=str(ledger_row["relative_path"]),
                generation_high_water=int(ledger_row["generation_high_water"]),
                terminal_history_count=int(ledger_row["terminal_history_count"]),
                terminal_history_sha256=str(ledger_row["terminal_history_sha256"]),
                active_artifact_id=ledger_row["active_artifact_id"],
                active_generation=ledger_row["active_generation"],
                active_create_operation_id=ledger_row["active_create_operation_id"],
                ledger_version=int(ledger_row["ledger_version"]),
                updated_at=_sqlite_datetime(ledger_row["updated_at"]),
            ),
            terminal_artifacts=tuple(terminal),
            active_artifact=active,
        )
        try:
            validate_path_snapshot(snapshot)
        except (TypeError, ValueError) as exc:
            raise KernelVerificationError("probe ledger history invariant failed") from exc


def _verify_probe_operation_provenance(
    connection: sqlite3.Connection,
    probe: sqlite3.Row,
) -> None:
    operation = connection.execute(
        "SELECT * FROM operations WHERE operation_id=?",
        (probe["operation_id"],),
    ).fetchone()
    prepared = connection.execute(
        "SELECT * FROM idempotency_bindings WHERE binding_id=?",
        (probe["prepared_binding_id"],),
    ).fetchone()
    caller = connection.execute(
        "SELECT * FROM idempotency_bindings WHERE binding_id=?",
        (probe["caller_binding_id"],),
    ).fetchone()
    artifact = connection.execute(
        "SELECT * FROM probe_artifacts WHERE artifact_id=?",
        (probe["artifact_id"],),
    ).fetchone()
    if operation is None or prepared is None or caller is None or artifact is None:
        raise KernelVerificationError("probe operation provenance is incomplete")
    try:
        kind = ProbeOperationKind(str(probe["probe_operation"]))
        prepared_artifact_id = (
            None if kind is ProbeOperationKind.WRITE else str(probe["artifact_id"])
        )
        input_digest = prepared_input_sha256(
            operation=kind,
            relative_path=str(probe["relative_path"]),
            expected_content_sha256=str(probe["expected_content_sha256"]),
            byte_count=(
                None if probe["expected_byte_count"] is None else int(probe["expected_byte_count"])
            ),
            artifact_id=prepared_artifact_id,
        )
        prepared_operation_id = str(prepared["prepared_operation_id"])
        target_digest = str(prepared["target_identity_sha256"])
        maximum_digest = str(prepared["maximum_effect_sha256"])
        fingerprint = operation_fingerprint_sha256(
            operation=kind,
            prepared_operation_id=prepared_operation_id,
            prepared_input_sha256=input_digest,
            relative_path=str(probe["relative_path"]),
            expected_content_sha256=str(probe["expected_content_sha256"]),
            byte_count=(
                None if probe["expected_byte_count"] is None else int(probe["expected_byte_count"])
            ),
            artifact_id=prepared_artifact_id,
            target_identity_digest=target_digest,
            maximum_effect_digest=maximum_digest,
        )
    except (TypeError, ValueError) as exc:
        raise KernelVerificationError("probe operation digest provenance is invalid") from exc
    if (
        prepared["prepared_input_sha256"] != input_digest
        or prepared["request_fingerprint_sha256"] != fingerprint
        or caller["request_fingerprint_sha256"] != fingerprint
        or operation["request_fingerprint_sha256"] != fingerprint
    ):
        raise KernelVerificationError("probe operation digest provenance is inconsistent")

    create_probe = connection.execute(
        "SELECT * FROM probe_operations WHERE operation_id=?",
        (artifact["create_operation_id"],),
    ).fetchone()
    if (
        create_probe is None
        or create_probe["probe_operation"] != ProbeOperationKind.WRITE.value
        or create_probe["artifact_id"] != artifact["artifact_id"]
        or create_probe["relative_path"] != artifact["relative_path"]
        or create_probe["expected_content_sha256"] != artifact["content_sha256"]
        or create_probe["expected_byte_count"] != artifact["byte_count"]
    ):
        raise KernelVerificationError("probe artifact creation provenance is inconsistent")
    for cleanup_operation_id in (
        artifact["active_cleanup_operation_id"],
        artifact["removed_by_cleanup_operation_id"],
    ):
        if cleanup_operation_id is None:
            continue
        cleanup_probe = connection.execute(
            "SELECT * FROM probe_operations WHERE operation_id=?",
            (cleanup_operation_id,),
        ).fetchone()
        if (
            cleanup_probe is None
            or cleanup_probe["probe_operation"] != ProbeOperationKind.CLEANUP.value
            or cleanup_probe["artifact_id"] != artifact["artifact_id"]
            or cleanup_probe["relative_path"] != artifact["relative_path"]
            or cleanup_probe["expected_content_sha256"] != artifact["content_sha256"]
        ):
            raise KernelVerificationError("probe cleanup provenance is inconsistent")


def _probe_artifact(row: sqlite3.Row) -> ProbeArtifact:
    try:
        state = ProbeArtifactState(str(row["state"]))
    except ValueError as exc:
        raise KernelVerificationError("probe artifact state is invalid") from exc
    return ProbeArtifact(
        artifact_id=str(row["artifact_id"]),
        relative_path=str(row["relative_path"]),
        path_generation=int(row["path_generation"]),
        owner_controller_id=str(row["owner_controller_id"]),
        owner_controller_epoch=int(row["owner_controller_epoch"]),
        content_sha256=str(row["content_sha256"]),
        byte_count=int(row["byte_count"]),
        state=state,
        create_operation_id=str(row["create_operation_id"]),
        active_cleanup_operation_id=row["active_cleanup_operation_id"],
        removed_by_cleanup_operation_id=row["removed_by_cleanup_operation_id"],
        created_at=_sqlite_datetime(row["created_at"]),
        updated_at=_sqlite_datetime(row["updated_at"]),
        removed_at=(None if row["removed_at"] is None else _sqlite_datetime(row["removed_at"])),
        file_identity_digest=row["file_identity_digest"],
    )


def _sqlite_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        raise KernelVerificationError("probe timestamp is invalid")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


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

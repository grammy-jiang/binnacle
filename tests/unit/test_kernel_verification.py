"""Read-only kernel-verifier success, corruption, and reporting paths."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import cast

import pytest

import binnacle.adapters.verification as verification
from binnacle.adapters.verification import (
    AuditVerification,
    DatabaseVerification,
    KernelVerificationError,
    KernelVerificationPaths,
    PayloadVerification,
)
from binnacle.domain.audit import AuditIntegrityError, AuditTail


class _Closeable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _database(**overrides: object) -> DatabaseVerification:
    values: dict[str, object] = {
        "revision": verification.EXPECTED_REVISION,
        "journal_mode": "wal",
        "synchronous": 2,
        "foreign_keys": 1,
        "busy_timeout_ms": 5_000,
        "wal_autocheckpoint_pages": 1_000,
        "operation_count": 0,
        "idempotency_count": 0,
        "payload_count": 0,
        "audit_tail_cache": AuditTail(0, None),
        "audit_failure_latched": False,
        "audit_failure_generation": 0,
        "audit_recovered_generation": 0,
        "audit_recovery_evidence_sha256": None,
        "consequential_admission_enabled": False,
        "device_id": "device-fixture",
        "audit_stream_id": "stream-fixture",
        "audit_epoch": "epoch-1",
    }
    values.update(overrides)
    return DatabaseVerification(**values)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_top_level_report_preserves_every_fail_closed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _Closeable()
    connection = _Closeable()
    database = _database(
        audit_tail_cache=AuditTail(1, "a" * 64),
        audit_failure_latched=True,
        audit_failure_generation=2,
        audit_recovered_generation=1,
    )
    audit = AuditVerification(AuditTail(2, "b" * 64), 1, 0, 1, False)
    payload = PayloadVerification(0, 0, 0, 0)
    monkeypatch.setattr(verification, "acquire_existing_runtime_lock", lambda _path: lock)
    monkeypatch.setattr(verification, "_open_read_only_database", lambda _path: connection)
    monkeypatch.setattr(verification, "_verify_database", lambda *_args, **_kwargs: (database, ()))

    async def verify_audit(**_kwargs: object) -> AuditVerification:
        return audit

    monkeypatch.setattr(verification, "_verify_audit", verify_audit)
    monkeypatch.setattr(verification, "_verify_payloads", lambda *_args: payload)
    report = await verification.verify_operation_kernel_read_only(
        paths=KernelVerificationPaths(
            tmp_path / "state.db", tmp_path / "audit", tmp_path / "payload", tmp_path / "run"
        ),
        audit_schema={},
        busy_timeout_ms=5_000,
        wal_autocheckpoint_pages=1_000,
    )
    assert report.reason_codes == (
        "audit_obligations_survive",
        "audit_recovery_evidence_invalid",
        "audit_recovery_required",
        "audit_tail_cache_mismatch",
    )
    rendered = report.as_dict()
    assert rendered["status"] == "fail"
    assert rendered["availability"] == "unavailable"
    assert rendered["audit_healthy"] is False
    assert rendered["payload_healthy"] is True
    assert rendered["consequential_admission_enabled"] is False
    assert lock.closed and connection.closed


def test_database_wrapper_closes_connection_and_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _Closeable()
    connection = _Closeable()
    database = _database()
    monkeypatch.setattr(verification, "acquire_existing_runtime_lock", lambda _path: lock)
    monkeypatch.setattr(verification, "_open_read_only_database", lambda _path: connection)
    monkeypatch.setattr(verification, "_verify_database", lambda *_args, **_kwargs: (database, ()))
    result = verification.verify_database_read_only(
        database_path=tmp_path / "state.db",
        runtime_directory=tmp_path / "run",
        busy_timeout_ms=5_000,
        wal_autocheckpoint_pages=1_000,
    )
    assert result is database
    assert lock.closed and connection.closed


def test_read_only_database_rejects_absent_unsafe_and_live_wal(tmp_path: Path) -> None:
    with pytest.raises(KernelVerificationError, match="absent"):
        verification._open_read_only_database(tmp_path / "absent.db")
    directory = tmp_path / "directory.db"
    directory.mkdir()
    with pytest.raises(KernelVerificationError, match="unsafe"):
        verification._open_read_only_database(directory)
    database = tmp_path / "state.db"
    database.write_bytes(b"not-opened")
    Path(f"{database}-wal").write_bytes(b"active")
    with pytest.raises(KernelVerificationError, match="uncheckpointed WAL"):
        verification._open_read_only_database(database)


def test_database_header_distinguishes_rollback_and_invalid_files(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"short")
    with pytest.raises(KernelVerificationError, match="header"):
        verification._database_journal_mode(invalid)
    rollback = tmp_path / "rollback.db"
    rollback.write_bytes(b"SQLite format 3\0" + b"\x00\x00\x01\x01")
    assert verification._database_journal_mode(rollback) == "rollback"


class _Result:
    def __init__(self, value: int) -> None:
        self._value = value

    def fetchone(self) -> tuple[int]:
        return (self._value,)


class _InvariantConnection:
    def __init__(self, results: list[int]) -> None:
        self._results = iter(results)

    def execute(self, _query: str) -> _Result:
        return _Result(next(self._results))


@pytest.mark.parametrize(
    ("index", "message"),
    (
        (0, "lifecycle"),
        (1, "initial transition"),
        (2, "transition head"),
        (3, "policy cardinality"),
        (4, "idempotency owner"),
        (5, "trusted time"),
    ),
)
def test_each_database_invariant_is_independently_fail_closed(index: int, message: str) -> None:
    values = [0] * 6
    values[index] = 1
    connection = cast(sqlite3.Connection, _InvariantConnection(values))
    with pytest.raises(KernelVerificationError, match=message):
        verification._verify_database_invariants(connection)
    verification._verify_database_invariants(
        cast(sqlite3.Connection, _InvariantConnection([0] * 6))
    )


def test_obligation_and_generation_event_matching_is_exact() -> None:
    event = {
        "event_hash": "a" * 64,
        "operation_id": "op-1",
        "correlation_ids": ["obl-1"],
        "payload": {"kind": "effect.observed", "reason_code": "verified"},
        "safe_facts": [
            {"name": "running_state_version", "value": 3},
            {"name": "audit_failure_generation", "value": 2},
        ],
    }
    noisy: list[object] = [None, {}, {"payload": [], "safe_facts": {}}, event]
    assert verification._matching_obligation_event(noisy, "obl-1", "op-1", 3)
    assert not verification._matching_obligation_event(noisy, "obl-2", "op-1", 3)
    assert verification._recovery_evidence_valid(noisy, _database())
    recovery = dict(event)
    recovery["payload"] = {
        "kind": "recovery.completed",
        "reason_code": "audit_failure_recovered",
    }
    assert verification._recovery_evidence_valid(
        [*noisy, recovery],
        _database(audit_recovered_generation=2, audit_recovery_evidence_sha256="a" * 64),
    )
    assert not verification._recovery_evidence_valid(
        noisy,
        _database(audit_recovered_generation=2, audit_recovery_evidence_sha256="f" * 64),
    )


def _row(**overrides: object) -> sqlite3.Row:
    values: dict[str, object] = {
        "payload_id": "payload-1",
        "relative_path": "objects/payload-1",
        "lifecycle": "deleted",
        "decoded_byte_count": 0,
        "sha256": None,
    }
    values.update(overrides)
    return cast(sqlite3.Row, values)


def _payload_directories(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    (root / "objects").mkdir(parents=True)
    (root / "tmp").mkdir()
    return root


def test_payload_scan_covers_complete_building_and_inactive_rows(tmp_path: Path) -> None:
    root = _payload_directories(tmp_path)
    (root / "objects/complete").write_bytes(b"abc")
    (root / "tmp/building.part").write_bytes(b"xy")
    rows = (
        _row(
            payload_id="complete",
            relative_path="objects/complete",
            lifecycle="complete",
            decoded_byte_count=3,
            sha256=hashlib.sha256(b"abc").hexdigest(),
        ),
        _row(
            payload_id="building",
            relative_path="objects/building",
            lifecycle="building",
            decoded_byte_count=2,
        ),
        _row(payload_id="deleted", relative_path="objects/deleted"),
    )
    assert verification._verify_payloads(root, rows) == PayloadVerification(3, 1, 1, 5)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("canonical", "canonical"),
        ("inactive", "inactive"),
        ("missing", "missing"),
        ("size", "size"),
        ("digest", "digest"),
        ("unsafe", "unsafe"),
        ("object-orphan", "orphan"),
        ("temporary-orphan", "orphan"),
    ),
)
def test_payload_scan_rejects_each_crash_or_corruption_shape(
    tmp_path: Path, mutation: str, message: str
) -> None:
    root = _payload_directories(tmp_path)
    row = _row()
    if mutation == "canonical":
        row = _row(payload_id="../escape", relative_path="objects/../escape")
    elif mutation == "inactive":
        (root / "objects/payload-1").write_bytes(b"x")
    elif mutation == "missing":
        row = _row(lifecycle="complete", decoded_byte_count=1, sha256="a" * 64)
    elif mutation == "size":
        (root / "objects/payload-1").write_bytes(b"xx")
        row = _row(lifecycle="complete", decoded_byte_count=1, sha256="a" * 64)
    elif mutation == "digest":
        (root / "objects/payload-1").write_bytes(b"x")
        row = _row(lifecycle="complete", decoded_byte_count=1, sha256="a" * 64)
    elif mutation == "unsafe":
        (root / "objects/payload-1").symlink_to(root / "tmp")
        row = _row(lifecycle="complete", decoded_byte_count=0, sha256="a" * 64)
    elif mutation == "object-orphan":
        (root / "objects/orphan").write_bytes(b"x")
    elif mutation == "temporary-orphan":
        (root / "tmp/orphan.part").write_bytes(b"x")
    with pytest.raises(KernelVerificationError, match=message):
        verification._verify_payloads(root, (row,))


def test_protected_directory_checks_reject_missing_file_and_unsafe_entry(tmp_path: Path) -> None:
    with pytest.raises(KernelVerificationError, match="absent"):
        verification._require_safe_directory(tmp_path / "missing")
    plain_file = tmp_path / "plain"
    plain_file.write_bytes(b"x")
    with pytest.raises(KernelVerificationError, match="unsafe"):
        verification._require_safe_directory(plain_file)
    directory = tmp_path / "entries"
    directory.mkdir()
    (directory / "link").symlink_to(plain_file)
    with pytest.raises(KernelVerificationError, match="unsafe entry"):
        verification._regular_entry_names(directory)


@pytest.mark.anyio
async def test_audit_scan_rejects_missing_unsafe_and_truncated_segments(
    tmp_path: Path,
) -> None:
    audit = tmp_path / "audit"
    epoch = audit / "epochs/epoch-1"
    epoch.mkdir(parents=True)
    obligations = tmp_path / "obligations"
    obligations.mkdir()
    with pytest.raises(KernelVerificationError, match="segment is absent"):
        await verification._verify_audit(
            directory=audit,
            obligation_directory=obligations,
            schema={},
            database=_database(),
        )
    segment = epoch / "segment-000001.jsonl"
    segment.symlink_to(tmp_path / "missing-target")
    with pytest.raises(KernelVerificationError, match="unsafe"):
        await verification._verify_audit(
            directory=audit,
            obligation_directory=obligations,
            schema={},
            database=_database(),
        )
    segment.unlink()
    segment.write_bytes(b"{}")
    with pytest.raises(AuditIntegrityError, match="truncated"):
        await verification._verify_audit(
            directory=audit,
            obligation_directory=obligations,
            schema={},
            database=_database(),
        )

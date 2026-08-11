"""RFC 8785 audit journal, genesis, concurrency, and corruption tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.phase4_support import audit_identity, audit_schema

from binnacle.adapters.audit.canonical import CanonicalizationError, canonicalize, sha256_hex
from binnacle.adapters.audit.journal import FileAuditJournal
from binnacle.adapters.audit.verify import AuditChainVerifier, verify_genesis_constant
from binnacle.domain.audit import (
    AUDIT_GENESIS_PREIMAGE,
    AUDIT_GENESIS_SHA256,
    AuditEventDraft,
    AuditIntegrityError,
)


def _draft(index: int) -> AuditEventDraft:
    return AuditEventDraft(
        event_id=f"event-{index}",
        recorded_at=datetime(2026, 8, 11, 0, 0, index % 60, tzinfo=UTC),
        monotonic_ns=index,
        severity="info",
        source="binnacle_system",
        payload={
            "kind": "operation.state_changed",
            "old_state": None,
            "new_state": "received",
            "state_version": 1,
            "effect_knowledge": "none",
            "result_digest": None,
            "reason_code": "operation_received",
        },
        operation_id=f"op-{index}",
    )


def test_genesis_vector_is_exact() -> None:
    verify_genesis_constant()
    assert AUDIT_GENESIS_PREIMAGE.hex() == ("62696e6e61636c652e61756469742e67656e657369732e763100")
    assert sha256_hex(AUDIT_GENESIS_PREIMAGE) == AUDIT_GENESIS_SHA256


def test_rfc8785_canonicalization_and_secret_rejection() -> None:
    assert canonicalize({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    with pytest.raises(CanonicalizationError, match="authority material"):
        canonicalize({"refresh_token": "forbidden"})
    with pytest.raises(CanonicalizationError):
        canonicalize({"payload": b"binary"})


@pytest.mark.anyio
async def test_concurrent_appends_form_one_strict_chain(tmp_path: Path, repo_root: Path) -> None:
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    assert (await journal.open()).sequence == 0
    results = await asyncio.gather(*(journal.append(_draft(index)) for index in range(20)))
    assert sorted(result.sequence for result in results) == list(range(1, 21))
    assert journal.tail.sequence == 20
    reopened = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    assert (await reopened.open()) == journal.tail
    first = json.loads(results[0].canonical_bytes)
    assert first["previous_event_hash"] == AUDIT_GENESIS_SHA256


@pytest.mark.anyio
async def test_wrong_genesis_and_hash_corruption_are_rejected(
    tmp_path: Path, repo_root: Path
) -> None:
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    await journal.open()
    result = await journal.append(_draft(1))
    event = json.loads(result.canonical_bytes)
    event["previous_event_hash"] = "f" * 64
    without_hash = dict(event)
    del without_hash["event_hash"]
    event["event_hash"] = sha256_hex(canonicalize(without_hash))
    line = canonicalize(event) + b"\n"
    verifier = AuditChainVerifier(audit_schema(repo_root))
    with pytest.raises(AuditIntegrityError, match="predecessor"):
        verifier.verify_lines([line])
    corrupted = bytearray(result.canonical_bytes + b"\n")
    corrupted[-3] = ord("x")
    with pytest.raises(AuditIntegrityError):
        verifier.verify_lines([bytes(corrupted)])


@pytest.mark.anyio
async def test_truncated_or_unsafe_journal_fails_open(tmp_path: Path, repo_root: Path) -> None:
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    await journal.open()
    await journal.append(_draft(1))
    path = tmp_path / "audit/epochs/epoch-1/segment-000001.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    reopened = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    with pytest.raises(AuditIntegrityError, match="truncated"):
        await reopened.open()


@pytest.mark.anyio
async def test_append_requires_verified_open(tmp_path: Path, repo_root: Path) -> None:
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    with pytest.raises(RuntimeError, match="opened"):
        _ = journal.tail
    with pytest.raises(RuntimeError, match="opened"):
        await journal.append(_draft(1))


@pytest.mark.anyio
async def test_reopen_rejects_foreign_stream_or_device_identity(
    tmp_path: Path, repo_root: Path
) -> None:
    identity = audit_identity()
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=identity,
        schema=audit_schema(repo_root),
    )
    await journal.open()
    await journal.append(_draft(1))
    foreign = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=replace(identity, stream_id="foreign-stream", device_id="foreign-device"),
        schema=audit_schema(repo_root),
    )
    with pytest.raises(AuditIntegrityError, match="identity"):
        await foreign.open()


@pytest.mark.anyio
async def test_segment_rotation_is_bounded_serialized_and_reopenable(
    tmp_path: Path, repo_root: Path
) -> None:
    directory = tmp_path / "audit"
    journal = FileAuditJournal(
        directory=directory,
        identity=audit_identity(),
        schema=audit_schema(repo_root),
        event_bytes_max=4_096,
        segment_bytes_max=5_000,
    )
    await journal.open()
    results = [await journal.append(_draft(index)) for index in range(8)]

    segments = sorted((directory / "epochs/epoch-1").glob("segment-*.jsonl"))
    assert len(segments) > 1
    assert all(segment.stat().st_size <= 5_000 for segment in segments)
    events = [
        json.loads(line)
        for segment in segments
        for line in segment.read_bytes().splitlines(keepends=True)
    ]
    for index, segment in enumerate(segments, start=1):
        for line in segment.read_bytes().splitlines(keepends=True):
            assert json.loads(line)["segment_id"] == f"segment-{index}"
    assert [event["sequence"] for event in events] == list(range(1, 9))
    assert journal.tail.event_hash == results[-1].event_hash

    reopened = FileAuditJournal(
        directory=directory,
        identity=audit_identity(),
        schema=audit_schema(repo_root),
        event_bytes_max=4_096,
        segment_bytes_max=5_000,
    )
    assert await reopened.open() == journal.tail


@pytest.mark.anyio
async def test_emergency_journal_is_integrity_linked_and_fails_when_bounded_capacity_exhausts(
    tmp_path: Path, repo_root: Path
) -> None:
    directory = tmp_path / "audit"
    journal = FileAuditJournal(
        directory=directory,
        identity=audit_identity(),
        schema=audit_schema(repo_root),
        emergency_bytes_max=1_024,
    )
    await journal.open()
    await journal.append_emergency(
        reason_code="audit_unavailable",
        operation_id="operation-fixture",
        source_event_id="event-fixture",
    )
    emergency = directory / "emergency/events.jsonl"
    while True:
        try:
            await journal.append_emergency(
                reason_code="audit_unavailable",
                operation_id="operation-fixture",
                source_event_id="event-fixture",
            )
        except AuditIntegrityError as exc:
            assert "exhausted" in str(exc)
            break
    assert emergency.stat().st_size <= 1_024

    reopened = FileAuditJournal(
        directory=directory,
        identity=audit_identity(),
        schema=audit_schema(repo_root),
        emergency_bytes_max=1_024,
    )
    await reopened.open()
    data = bytearray(emergency.read_bytes())
    data[-3] = ord("x")
    emergency.write_bytes(data)
    corrupted = FileAuditJournal(
        directory=directory,
        identity=audit_identity(),
        schema=audit_schema(repo_root),
        emergency_bytes_max=1_024,
    )
    with pytest.raises(AuditIntegrityError, match="emergency"):
        await corrupted.open()

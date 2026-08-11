"""Single-writer fsynced RFC 8785 audit journal."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from binnacle.adapters.audit.canonical import canonicalize, sha256_hex
from binnacle.adapters.audit.verify import AuditChainVerifier
from binnacle.domain.audit import (
    AUDIT_GENESIS_SHA256,
    AuditAppendResult,
    AuditEventDraft,
    AuditIntegrityError,
    AuditRuntimeIdentity,
    AuditTail,
)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileAuditJournal:
    """Authoritative local journal with one process-wide serialized allocator."""

    def __init__(
        self,
        *,
        directory: Path,
        identity: AuditRuntimeIdentity,
        schema: Mapping[str, object],
        event_bytes_max: int = 65_536,
    ) -> None:
        self._directory = directory
        self._identity = identity
        self._schema = schema
        self._validator = Draft202012Validator(schema)
        self._verifier = AuditChainVerifier(
            schema,
            event_bytes_max=event_bytes_max,
            expected_identity=identity,
        )
        self._event_bytes_max = event_bytes_max
        self._append_lock = asyncio.Lock()
        self._journal_path = directory / "epochs" / identity.audit_epoch / "segment-000001.jsonl"
        self._tail = AuditTail(0, None)
        self._opened = False

    @property
    def tail(self) -> AuditTail:
        if not self._opened:
            raise RuntimeError("audit journal has not been opened and verified")
        return self._tail

    async def open(self) -> AuditTail:
        async with self._append_lock:
            self._journal_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            if not self._journal_path.exists():
                descriptor = os.open(
                    self._journal_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o640,
                )
                os.close(descriptor)
                _fsync_directory(self._journal_path.parent)
            if self._journal_path.is_symlink() or not self._journal_path.is_file():
                raise AuditIntegrityError("audit journal path is unsafe")
            lines = self._journal_path.read_bytes().splitlines(keepends=True)
            if lines and not lines[-1].endswith(b"\n"):
                raise AuditIntegrityError("audit journal is truncated")
            self._tail = self._verifier.verify_lines(lines)
            self._opened = True
            return self._tail

    async def append(self, draft: AuditEventDraft) -> AuditAppendResult:
        async with self._append_lock:
            if not self._opened:
                raise RuntimeError("audit journal has not been opened and verified")
            sequence = self._tail.sequence + 1
            predecessor = self._tail.event_hash or AUDIT_GENESIS_SHA256
            event: dict[str, object] = {
                "schema_version": "1.1",
                "canonicalization": "rfc8785-jcs+sha256-v1",
                "event_id": draft.event_id,
                "stream_id": self._identity.stream_id,
                "audit_epoch": self._identity.audit_epoch,
                "segment_id": self._identity.segment_id,
                "sequence": sequence,
                "recorded_at": draft.recorded_at.isoformat().replace("+00:00", "Z"),
                "monotonic_ns": draft.monotonic_ns,
                "boot_id": self._identity.boot_id,
                "device_id": self._identity.device_id,
                "server_build_sha256": self._identity.server_build_sha256,
                "tool_manifest_sha256": self._identity.tool_manifest_sha256,
                "schema_registry_sha256": self._identity.schema_registry_sha256,
                "device_profile_version": self._identity.device_profile_version,
                "policy_version": self._identity.policy_version,
                "severity": draft.severity,
                "source": draft.source,
                "controller_id_digest": draft.controller_id_digest,
                "request_id": draft.request_id,
                "operation_id": draft.operation_id,
                "idempotency_digest": draft.idempotency_digest,
                "prepared_operation_id": draft.prepared_operation_id,
                "correlation_ids": list(draft.correlation_ids),
                "information_class": draft.information_class,
                "provenance": draft.provenance,
                "redaction_policy_version": self._identity.redaction_policy_version,
                "payload": dict(draft.payload),
                "previous_event_hash": predecessor,
                "previous_checkpoint_digest": None,
                "checkpoint_ref": None,
                "export_ref": None,
                "safe_facts": [dict(item) for item in draft.safe_facts],
            }
            event_hash = sha256_hex(canonicalize(event))
            event["event_hash"] = event_hash
            errors = tuple(self._validator.iter_errors(event))
            if errors:
                raise AuditIntegrityError("audit event does not match the frozen schema")
            canonical_bytes = canonicalize(event)
            if len(canonical_bytes) > self._event_bytes_max:
                raise AuditIntegrityError("audit event exceeds maximum bytes")
            descriptor = os.open(self._journal_path, os.O_WRONLY | os.O_APPEND)
            try:
                payload = canonical_bytes + b"\n"
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._tail = AuditTail(sequence, event_hash)
            return AuditAppendResult(sequence, event_hash, canonical_bytes)

    async def find_obligation_evidence(
        self,
        *,
        obligation_id: str,
        operation_id: str,
        running_state_version: int,
    ) -> str | None:
        async with self._append_lock:
            events = self._read_verified_events()
            for event in reversed(events):
                payload = event["payload"]
                assert isinstance(payload, dict)
                safe_facts = event["safe_facts"]
                assert isinstance(safe_facts, list)
                correlations = event["correlation_ids"]
                assert isinstance(correlations, list)
                version_matches = any(
                    isinstance(item, dict)
                    and item.get("name") == "running_state_version"
                    and item.get("value") == running_state_version
                    for item in safe_facts
                )
                if (
                    event["operation_id"] == operation_id
                    and obligation_id in correlations
                    and version_matches
                    and payload.get("kind")
                    in {
                        "effect.started",
                        "effect.observed",
                        "effect.failed",
                        "recovery.completed",
                    }
                ):
                    return str(event["event_hash"])
            return None

    async def find_generation_recovery(self, generation: int) -> str | None:
        async with self._append_lock:
            events = self._read_verified_events()
            for event in reversed(events):
                payload = event["payload"]
                assert isinstance(payload, dict)
                safe_facts = event["safe_facts"]
                assert isinstance(safe_facts, list)
                generation_matches = any(
                    isinstance(item, dict)
                    and item.get("name") == "audit_failure_generation"
                    and item.get("value") == generation
                    for item in safe_facts
                )
                if (
                    payload.get("kind") == "recovery.completed"
                    and payload.get("reason_code") == "audit_failure_recovered"
                    and generation_matches
                ):
                    return str(event["event_hash"])
            return None

    def _read_verified_events(self) -> list[dict[str, object]]:
        if not self._opened:
            raise RuntimeError("audit journal has not been opened and verified")
        lines = self._journal_path.read_bytes().splitlines(keepends=True)
        if lines and not lines[-1].endswith(b"\n"):
            raise AuditIntegrityError("audit journal is truncated")
        self._verifier.verify_lines(lines)
        events: list[dict[str, object]] = []
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AuditIntegrityError("audit event must be an object")
            events.append(value)
        return events

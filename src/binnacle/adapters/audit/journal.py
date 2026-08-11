"""Single-writer fsynced RFC 8785 audit journal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
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
from binnacle.ports.audit import AuditObligationRecovery

_SEGMENT_NAME = re.compile(r"^segment-(?P<index>[0-9]{6})\.jsonl$")
_EMERGENCY_GENESIS_SHA256 = hashlib.sha256(b"binnacle.audit.emergency.genesis.v1\0").hexdigest()
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_REASON_CODE = re.compile(r"^[a-z0-9_]{1,64}$")


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
        segment_bytes_max: int = 16 * 1024 * 1024,
        emergency_bytes_max: int = 1024 * 1024,
    ) -> None:
        if segment_bytes_max < event_bytes_max + 1:
            raise ValueError("audit segment must hold at least one maximum-sized event")
        if emergency_bytes_max < 1024:
            raise ValueError("emergency audit capacity is too small")
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
        self._segment_bytes_max = segment_bytes_max
        self._emergency_bytes_max = emergency_bytes_max
        self._append_lock = asyncio.Lock()
        self._epoch_directory = directory / "epochs" / identity.audit_epoch
        self._segment_index = 1
        self._journal_path = self._segment_path(self._segment_index)
        self._emergency_path = directory / "emergency" / "events.jsonl"
        self._emergency_tail = AuditTail(0, None)
        self._tail = AuditTail(0, None)
        self._opened = False

    @property
    def tail(self) -> AuditTail:
        if not self._opened:
            raise RuntimeError("audit journal has not been opened and verified")
        return self._tail

    async def open(self) -> AuditTail:
        async with self._append_lock:
            self._epoch_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
            segment_paths = self._discover_segments()
            if not segment_paths:
                self._create_file(self._segment_path(1), parent=self._epoch_directory)
                segment_paths = [self._segment_path(1)]
            lines = self._read_segment_lines(segment_paths)
            self._tail = self._verifier.verify_lines(lines)
            self._segment_index = len(segment_paths)
            self._journal_path = segment_paths[-1]
            self._initialize_emergency_journal()
            self._opened = True
            return self._tail

    async def append(self, draft: AuditEventDraft) -> AuditAppendResult:
        async with self._append_lock:
            if not self._opened:
                raise RuntimeError("audit journal has not been opened and verified")
            sequence = self._tail.sequence + 1
            predecessor = self._tail.event_hash or AUDIT_GENESIS_SHA256
            event = self._build_event(
                draft=draft,
                sequence=sequence,
                predecessor=predecessor,
                segment_id=self._segment_id(self._segment_index),
            )
            canonical_bytes = self._validate_and_encode(event)
            payload = canonical_bytes + b"\n"
            current_size = self._journal_path.stat().st_size
            if current_size and current_size + len(payload) > self._segment_bytes_max:
                self._rotate_segment()
                event = self._build_event(
                    draft=draft,
                    sequence=sequence,
                    predecessor=predecessor,
                    segment_id=self._segment_id(self._segment_index),
                )
                canonical_bytes = self._validate_and_encode(event)
                payload = canonical_bytes + b"\n"
            if len(payload) > self._segment_bytes_max:
                raise AuditIntegrityError("audit event cannot fit within segment bound")
            descriptor = os.open(
                self._journal_path,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._tail = AuditTail(sequence, str(event["event_hash"]))
            return AuditAppendResult(sequence, str(event["event_hash"]), canonical_bytes)

    async def append_emergency(
        self,
        *,
        reason_code: str,
        operation_id: str | None,
        source_event_id: str,
    ) -> None:
        """Append one bounded independent degradation record or fail restricted."""

        async with self._append_lock:
            if not self._opened:
                raise RuntimeError("audit journal has not been opened and verified")
            if not _REASON_CODE.fullmatch(reason_code):
                raise AuditIntegrityError("emergency audit reason code is invalid")
            sequence = self._emergency_tail.sequence + 1
            predecessor = self._emergency_tail.event_hash or _EMERGENCY_GENESIS_SHA256
            record: dict[str, object] = {
                "schema_version": "1",
                "sequence": sequence,
                "previous_record_hash": predecessor,
                "kind": "audit.storage_degraded",
                "reason_code": reason_code,
                "operation_id_digest": self._optional_digest(operation_id),
                "source_event_id_digest": self._optional_digest(source_event_id),
                "main_tail_sequence": self._tail.sequence,
                "main_tail_hash": self._tail.event_hash,
            }
            record_hash = sha256_hex(canonicalize(record))
            record["record_hash"] = record_hash
            payload = canonicalize(record) + b"\n"
            current_size = self._emergency_path.stat().st_size
            if current_size + len(payload) > self._emergency_bytes_max:
                raise AuditIntegrityError("emergency audit journal is exhausted")
            descriptor = os.open(
                self._emergency_path,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._emergency_tail = AuditTail(sequence, record_hash)

    def _build_event(
        self,
        *,
        draft: AuditEventDraft,
        sequence: int,
        predecessor: str,
        segment_id: str,
    ) -> dict[str, object]:
        event: dict[str, object] = {
            "schema_version": "1.1",
            "canonicalization": "rfc8785-jcs+sha256-v1",
            "event_id": draft.event_id,
            "stream_id": self._identity.stream_id,
            "audit_epoch": self._identity.audit_epoch,
            "segment_id": segment_id,
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
        event["event_hash"] = sha256_hex(canonicalize(event))
        return event

    def _validate_and_encode(self, event: Mapping[str, object]) -> bytes:
        if tuple(self._validator.iter_errors(event)):
            raise AuditIntegrityError("audit event does not match the frozen schema")
        canonical_bytes = canonicalize(event)
        if len(canonical_bytes) > self._event_bytes_max:
            raise AuditIntegrityError("audit event exceeds maximum bytes")
        return canonical_bytes

    def _discover_segments(self) -> list[Path]:
        segments: list[tuple[int, Path]] = []
        for path in self._epoch_directory.iterdir():
            match = _SEGMENT_NAME.fullmatch(path.name)
            if match is None:
                raise AuditIntegrityError("audit epoch contains an unexpected entry")
            if path.is_symlink() or not path.is_file():
                raise AuditIntegrityError("audit journal path is unsafe")
            segments.append((int(match.group("index")), path))
        segments.sort()
        if segments and [index for index, _ in segments] != list(range(1, len(segments) + 1)):
            raise AuditIntegrityError("audit segment sequence is not contiguous")
        return [path for _, path in segments]

    def _read_segment_lines(self, paths: list[Path]) -> list[bytes]:
        lines: list[bytes] = []
        for position, path in enumerate(paths, start=1):
            data = path.read_bytes()
            if len(data) > self._segment_bytes_max:
                raise AuditIntegrityError("audit segment exceeds configured bound")
            segment_lines = data.splitlines(keepends=True)
            if segment_lines and not segment_lines[-1].endswith(b"\n"):
                raise AuditIntegrityError("audit journal is truncated")
            if not segment_lines and position != len(paths):
                raise AuditIntegrityError("only the final audit segment may be empty")
            expected_segment_id = self._segment_id(position)
            for line in segment_lines:
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise AuditIntegrityError("audit journal contains invalid JSON") from exc
                if not isinstance(event, dict) or event.get("segment_id") != expected_segment_id:
                    raise AuditIntegrityError("audit event segment identity is inconsistent")
            lines.extend(segment_lines)
        return lines

    def _rotate_segment(self) -> None:
        self._segment_index += 1
        self._journal_path = self._segment_path(self._segment_index)
        self._create_file(self._journal_path, parent=self._epoch_directory)

    def _segment_path(self, index: int) -> Path:
        return self._epoch_directory / f"segment-{index:06d}.jsonl"

    @staticmethod
    def _segment_id(index: int) -> str:
        return f"segment-{index}"

    @staticmethod
    def _create_file(path: Path, *, parent: Path) -> None:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o640,
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(parent)

    def _initialize_emergency_journal(self) -> None:
        self._emergency_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        if not self._emergency_path.exists():
            self._create_file(self._emergency_path, parent=self._emergency_path.parent)
        if self._emergency_path.is_symlink() or not self._emergency_path.is_file():
            raise AuditIntegrityError("emergency audit journal path is unsafe")
        data = self._emergency_path.read_bytes()
        if len(data) > self._emergency_bytes_max:
            raise AuditIntegrityError("emergency audit journal exceeds configured bound")
        lines = data.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b"\n"):
            raise AuditIntegrityError("emergency audit journal is truncated")
        self._emergency_tail = self._verify_emergency_lines(lines)

    @staticmethod
    def _verify_emergency_lines(lines: list[bytes]) -> AuditTail:
        previous_hash = _EMERGENCY_GENESIS_SHA256
        expected_sequence = 1
        required = {
            "schema_version",
            "sequence",
            "previous_record_hash",
            "kind",
            "reason_code",
            "operation_id_digest",
            "source_event_id_digest",
            "main_tail_sequence",
            "main_tail_hash",
            "record_hash",
        }
        for line in lines:
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuditIntegrityError("emergency audit journal contains invalid JSON") from exc
            if not isinstance(record, dict) or set(record) != required:
                raise AuditIntegrityError("emergency audit record shape is invalid")
            if (
                record["schema_version"] != "1"
                or record["kind"] != "audit.storage_degraded"
                or record["sequence"] != expected_sequence
                or record["previous_record_hash"] != previous_hash
                or not isinstance(record["reason_code"], str)
                or not _REASON_CODE.fullmatch(record["reason_code"])
                or not isinstance(record["main_tail_sequence"], int)
                or record["main_tail_sequence"] < 0
            ):
                raise AuditIntegrityError("emergency audit record fields are invalid")
            for field in ("operation_id_digest", "source_event_id_digest", "main_tail_hash"):
                value = record[field]
                if value is not None and (
                    not isinstance(value, str) or not _DIGEST.fullmatch(value)
                ):
                    raise AuditIntegrityError("emergency audit digest is invalid")
            stated_hash = record["record_hash"]
            if not isinstance(stated_hash, str) or not _DIGEST.fullmatch(stated_hash):
                raise AuditIntegrityError("emergency audit record hash is invalid")
            preimage = dict(record)
            del preimage["record_hash"]
            if sha256_hex(canonicalize(preimage)) != stated_hash:
                raise AuditIntegrityError("emergency audit record hash is invalid")
            if canonicalize(record) + b"\n" != line:
                raise AuditIntegrityError("emergency audit record bytes are not canonical")
            previous_hash = stated_hash
            expected_sequence += 1
        return AuditTail(expected_sequence - 1, None if expected_sequence == 1 else previous_hash)

    @staticmethod
    def _optional_digest(value: str | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(
            b"binnacle.audit.emergency.reference.v1\0" + value.encode()
        ).hexdigest()

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
                    }
                ):
                    return str(event["event_hash"])
            return None

    async def find_operation_state_evidence(
        self,
        *,
        operation_id: str,
        state_version: int,
        state: str,
        effect_knowledge: str,
    ) -> str | None:
        """Find the exact fsynced lifecycle fact required before phase-specific closure."""

        async with self._append_lock:
            for event in reversed(self._read_verified_events()):
                payload = event["payload"]
                assert isinstance(payload, dict)
                safe_facts = event["safe_facts"]
                assert isinstance(safe_facts, list)
                running_version_matches = any(
                    isinstance(item, dict)
                    and item.get("name") == "running_state_version"
                    and item.get("value") == state_version
                    for item in safe_facts
                )
                lifecycle_matches = (
                    payload.get("kind") == "operation.state_changed"
                    and payload.get("state_version") == state_version
                    and payload.get("new_state") == state
                    and payload.get("effect_knowledge") == effect_knowledge
                )
                started_effect_matches = (
                    state == "running"
                    and payload.get("kind") == "effect.started"
                    and payload.get("effect_knowledge") == effect_knowledge
                    and running_version_matches
                )
                if event["operation_id"] == operation_id and (
                    lifecycle_matches or started_effect_matches
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

    async def list_obligation_recoveries(
        self, generation: int
    ) -> tuple[AuditObligationRecovery, ...]:
        """Return verified per-obligation closure progress for one failure generation."""

        async with self._append_lock:
            recoveries: dict[str, AuditObligationRecovery] = {}
            for event in self._read_verified_events():
                payload = event["payload"]
                assert isinstance(payload, dict)
                if (
                    payload.get("kind") != "recovery.completed"
                    or payload.get("phase") != "audit_obligation_closure"
                ):
                    continue
                safe_facts = event["safe_facts"]
                correlations = event["correlation_ids"]
                assert isinstance(safe_facts, list)
                assert isinstance(correlations, list)
                event_generation = self._safe_fact(safe_facts, "audit_failure_generation")
                if event_generation != generation:
                    continue
                running_version = self._safe_fact(safe_facts, "running_state_version")
                operation_id = event["operation_id"]
                if (
                    len(correlations) != 1
                    or not isinstance(correlations[0], str)
                    or not isinstance(operation_id, str)
                    or not isinstance(running_version, int)
                    or not isinstance(payload.get("reason_code"), str)
                    or not isinstance(payload.get("result_digest"), str)
                ):
                    raise AuditIntegrityError("audit obligation recovery evidence is malformed")
                recovery = AuditObligationRecovery(
                    obligation_id=correlations[0],
                    operation_id=operation_id,
                    running_state_version=running_version,
                    generation=generation,
                    effect_outcome=str(payload["reason_code"]),
                    evidence_sha256=str(payload["result_digest"]),
                    event_hash=str(event["event_hash"]),
                )
                previous = recoveries.get(recovery.obligation_id)
                if previous is not None and (
                    previous.operation_id != recovery.operation_id
                    or previous.running_state_version != recovery.running_state_version
                    or previous.effect_outcome != recovery.effect_outcome
                    or previous.evidence_sha256 != recovery.evidence_sha256
                ):
                    raise AuditIntegrityError("audit obligation recovery evidence conflicts")
                recoveries[recovery.obligation_id] = recovery
            return tuple(recoveries[key] for key in sorted(recoveries))

    async def find_generation_verification(self, generation: int) -> str | None:
        """Find already-fsynced chain verification for one recovery generation."""

        async with self._append_lock:
            for event in reversed(self._read_verified_events()):
                payload = event["payload"]
                safe_facts = event["safe_facts"]
                assert isinstance(payload, dict)
                assert isinstance(safe_facts, list)
                if (
                    payload.get("kind") == "audit.verification_passed"
                    and payload.get("reason_code") == "exact_generation_recovered"
                    and self._safe_fact(safe_facts, "audit_failure_generation") == generation
                ):
                    return str(event["event_hash"])
            return None

    @staticmethod
    def _safe_fact(safe_facts: list[object], name: str) -> object | None:
        matches = [
            item.get("value")
            for item in safe_facts
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) > 1:
            raise AuditIntegrityError("audit event contains duplicate recovery facts")
        return matches[0] if matches else None

    def _read_verified_events(self) -> list[dict[str, object]]:
        if not self._opened:
            raise RuntimeError("audit journal has not been opened and verified")
        paths = self._discover_segments()
        lines = self._read_segment_lines(paths)
        self._verifier.verify_lines(lines)
        events: list[dict[str, object]] = []
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AuditIntegrityError("audit event must be an object")
            events.append(value)
        return events

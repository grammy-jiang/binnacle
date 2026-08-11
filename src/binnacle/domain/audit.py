"""Framework-independent audit journal records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

AUDIT_GENESIS_PREIMAGE = b"binnacle.audit.genesis.v1\0"
AUDIT_GENESIS_SHA256 = "a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632"


@dataclass(frozen=True, slots=True)
class AuditRuntimeIdentity:
    stream_id: str
    audit_epoch: str
    segment_id: str
    boot_id: str
    device_id: str
    server_build_sha256: str
    tool_manifest_sha256: str
    schema_registry_sha256: str
    device_profile_version: str
    policy_version: str
    redaction_policy_version: str


@dataclass(frozen=True, slots=True)
class AuditEventDraft:
    event_id: str
    recorded_at: datetime
    monotonic_ns: int
    severity: str
    source: str
    payload: Mapping[str, object]
    information_class: str = "normal-result"
    provenance: str = "server-fact"
    controller_id_digest: str | None = None
    request_id: str | None = None
    operation_id: str | None = None
    idempotency_digest: str | None = None
    prepared_operation_id: str | None = None
    correlation_ids: tuple[str, ...] = ()
    safe_facts: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class AuditTail:
    sequence: int
    event_hash: str | None


@dataclass(frozen=True, slots=True)
class AuditAppendResult:
    sequence: int
    event_hash: str
    canonical_bytes: bytes


class AuditIntegrityError(RuntimeError):
    pass

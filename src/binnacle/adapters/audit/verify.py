"""Audit event schema and hash-chain verification."""

from __future__ import annotations

import json
from collections.abc import Mapping

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from binnacle.adapters.audit.canonical import canonicalize, sha256_hex
from binnacle.domain.audit import (
    AUDIT_GENESIS_PREIMAGE,
    AUDIT_GENESIS_SHA256,
    AuditIntegrityError,
    AuditRuntimeIdentity,
    AuditTail,
)


def verify_genesis_constant() -> None:
    if sha256_hex(AUDIT_GENESIS_PREIMAGE) != AUDIT_GENESIS_SHA256:
        raise AuditIntegrityError("compiled audit genesis vector is invalid")


class AuditChainVerifier:
    def __init__(
        self,
        schema: Mapping[str, object],
        *,
        event_bytes_max: int = 65_536,
        expected_identity: AuditRuntimeIdentity | None = None,
    ) -> None:
        self._validator = Draft202012Validator(schema)
        self._event_bytes_max = event_bytes_max
        self._expected_identity = expected_identity
        verify_genesis_constant()

    def verify_lines(self, lines: list[bytes]) -> AuditTail:
        expected_sequence = 1
        previous_hash = AUDIT_GENESIS_SHA256
        for line in lines:
            if len(line) > self._event_bytes_max + 1:
                raise AuditIntegrityError("audit event exceeds maximum bytes")
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuditIntegrityError("audit journal contains invalid JSON") from exc
            if not isinstance(event, dict):
                raise AuditIntegrityError("audit event must be an object")
            errors = sorted(self._validator.iter_errors(event), key=lambda item: list(item.path))
            if errors:
                raise AuditIntegrityError("audit event does not match the frozen schema")
            if self._expected_identity is not None and (
                event["stream_id"] != self._expected_identity.stream_id
                or event["audit_epoch"] != self._expected_identity.audit_epoch
                or event["device_id"] != self._expected_identity.device_id
            ):
                raise AuditIntegrityError("audit event durable identity is inconsistent")
            if event["sequence"] != expected_sequence:
                raise AuditIntegrityError("audit sequence is not strictly monotonic")
            if event["previous_event_hash"] != previous_hash:
                raise AuditIntegrityError("audit predecessor chain is invalid")
            stated_hash = event["event_hash"]
            preimage = dict(event)
            del preimage["event_hash"]
            if sha256_hex(canonicalize(preimage)) != stated_hash:
                raise AuditIntegrityError("audit event hash is invalid")
            if canonicalize(event) + b"\n" != line:
                raise AuditIntegrityError("audit event bytes are not canonical")
            previous_hash = stated_hash
            expected_sequence += 1
        return AuditTail(expected_sequence - 1, None if expected_sequence == 1 else previous_hash)

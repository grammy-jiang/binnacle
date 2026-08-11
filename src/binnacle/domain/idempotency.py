"""Idempotency key validation and non-disclosing ownership facts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from binnacle.domain.operation import OperationOwner

_LOWER_HEX = re.compile(r"^[0-9a-f]{32,}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]{22,}$")
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class IdempotencyKeyMode(StrEnum):
    CALLER_KEY = "caller_key"
    PREPARED_EXECUTION_NONCE = "prepared_execution_nonce"
    DERIVED_MEMBER_KEY = "derived_member_key"


class BindingRecordKind(StrEnum):
    FULL = "full"
    TOMBSTONE = "tombstone"


class IdempotencyOutcome(StrEnum):
    CREATED = "created"
    RETAINED_OPERATION = "retained_operation"
    CONFLICT = "idempotency_conflict"
    OWNER_MISMATCH = "idempotency_owner_mismatch"
    KEY_RETIRED = "idempotency_key_retired"
    PREPARED_MISMATCH = "prepared_operation_mismatch"
    PREPARED_EXPIRED = "prepared_operation_expired"
    TRUSTED_TIME_UNAVAILABLE = "trusted_time_unavailable"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    mode: IdempotencyKeyMode
    digest_sha256: str


class IdempotencyKeyError(ValueError):
    pass


def validate_and_digest_key(raw_key: str, mode: IdempotencyKeyMode) -> IdempotencyKey:
    if mode is IdempotencyKeyMode.DERIVED_MEMBER_KEY:
        raise IdempotencyKeyError("derived member keys require a reviewed parent contract")
    if _UUID4.fullmatch(raw_key):
        raise IdempotencyKeyError("UUIDv4 alone does not meet the idempotency contract")
    decoded: bytes
    if _LOWER_HEX.fullmatch(raw_key) and len(raw_key) % 2 == 0:
        decoded = bytes.fromhex(raw_key)
    elif _BASE64URL.fullmatch(raw_key) and "=" not in raw_key:
        try:
            decoded = base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4))
        except (ValueError, binascii.Error) as exc:
            raise IdempotencyKeyError("invalid base64url idempotency key") from exc
    else:
        raise IdempotencyKeyError("unsupported idempotency key encoding")
    if len(decoded) < 16:
        raise IdempotencyKeyError("idempotency key has fewer than 128 bits")
    preimage = b"binnacle.idempotency-key.v1\0" + mode.value.encode() + b"\0" + decoded
    return IdempotencyKey(mode=mode, digest_sha256=hashlib.sha256(preimage).hexdigest())


def owner_digest(owner: OperationOwner) -> str:
    value = (
        b"binnacle.operation-owner.v1\0"
        + owner.controller_id.encode()
        + b"\0"
        + str(owner.controller_epoch).encode()
    )
    return hashlib.sha256(value).hexdigest()

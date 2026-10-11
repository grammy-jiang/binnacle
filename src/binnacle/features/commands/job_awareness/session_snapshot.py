"""E2 allocation snapshot builder and three logical record pages. LAB_ONLY.

Two hash rules exist and are never compared with each other (design §2.4):
the frozen template hash (source integrity, checked before any allocation)
and the allocation snapshot hash (runtime integrity, sealed and re-verified by
the snapshot lease on every page). The template ``owner`` field is dropped.
Logical pages are not the 16 KiB physical pages and carry no ACK meaning.
"""

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import TypeGuard

from binnacle.features.commands.job_awareness.identifiers import canonical_hex, require
from binnacle.features.commands.job_awareness.models import (
    MAX_SNAPSHOT_BYTES,
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    Result,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
)

SNAPSHOT_SCHEMA = "ja-e2-alloc-snapshot-v1"
TEMPLATE_SCHEMA = "r3-synthetic-result-v1"
LOGICAL_PAGES = 3
RETENTION_MS = 86400000
MAX_VALUE_CHARS = 256
MAX_TEMPLATE_BYTES = 4096
_SLOT = re.compile(r"R3-SYN-JOB-(0[1-9]|1[0-2])")
_TEMPLATE_KEYS = frozenset(
    {"contains_real_user_data", "job_id", "nonce", "owner", "records", "schema"}
)


def valid_slot(value: object) -> TypeGuard[str]:
    return (
        type(value) is str and len(value) == 13 and _SLOT.fullmatch(value) is not None
    )


@dataclass(frozen=True)
class FrozenTemplate:
    """Public frozen fixture bytes plus their frozen hashes. No secrecy claim."""

    slot: str
    payload: bytes
    payload_sha256: str
    nonce_sha256: str

    def __post_init__(self) -> None:
        require(valid_slot(self.slot))
        require(type(self.payload) is bytes and len(self.payload) <= MAX_TEMPLATE_BYTES)
        canonical_hex(self.payload_sha256, 64)
        canonical_hex(self.nonce_sha256, 64)


@dataclass(frozen=True)
class AllocationSnapshot:
    """Private per-allocation bytes: canaries and ``alloc_tag`` are random."""

    slot: str
    data: bytes
    sha256: str
    alloc_tag: str

    def __repr__(self) -> str:
        return f"AllocationSnapshot(slot={self.slot!r}, sha256={self.sha256!r})"


def _canonical(value: object) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return text.encode("ascii")


def _template_records(template: FrozenTemplate) -> tuple[str, list[str]] | None:
    """Verify the frozen hashes, then the exact template shape."""
    digest = hashlib.sha256(template.payload).hexdigest()
    if not hmac.compare_digest(digest, template.payload_sha256):
        return None
    try:
        raw = json.loads(template.payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if type(raw) is not dict or set(raw) != _TEMPLATE_KEYS:
        return None
    nonce, records = raw["nonce"], raw["records"]
    if (
        raw["schema"] != TEMPLATE_SCHEMA
        or raw["job_id"] != template.slot
        or raw["contains_real_user_data"] is not False
        or type(nonce) is not str
        or re.fullmatch("[0-9a-f]{32}", nonce) is None
        or type(records) is not list
        or len(records) != LOGICAL_PAGES
    ):
        return None
    nonce_digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    if not hmac.compare_digest(nonce_digest, template.nonce_sha256):
        return None
    values = []
    for seq, record in enumerate(records):
        if (
            type(record) is not dict
            or set(record) != {"seq", "value"}
            or type(record["seq"]) is not int
            or record["seq"] != seq
            or type(record["value"]) is not str
            or not 1 <= len(record["value"]) <= MAX_VALUE_CHARS
            or not record["value"].isascii()
        ):
            return None
        values.append(record["value"])
    return nonce, values


def build_snapshot(template: FrozenTemplate) -> AllocationSnapshot | None:
    """Verify the frozen template, then seal fresh private items into new bytes.

    Returns None (the start is DENIED and the arm is void) on any mismatch.
    """
    if type(template) is not FrozenTemplate:
        return None
    verified = _template_records(template)
    if verified is None:
        return None
    nonce, values = verified
    alloc_tag = secrets.token_hex(16)
    data = _canonical(
        {
            "schema": SNAPSHOT_SCHEMA,
            "slot": template.slot,
            "template_sha256": template.payload_sha256,
            "nonce": nonce,
            "records": [
                {"seq": seq, "value": value, "canary": secrets.token_hex(16)}
                for seq, value in enumerate(values)
            ],
            "alloc_tag": alloc_tag,
        }
    )
    require(len(data) <= MAX_SNAPSHOT_BYTES)
    return AllocationSnapshot(
        template.slot, data, hashlib.sha256(data).hexdigest(), alloc_tag
    )


def output_snapshot(
    job: JobRef, allocation: AllocationSnapshot, now_ms: int
) -> OutputSnapshot:
    """Sealed terminal metadata for the trusted controller (exit code 0)."""
    return OutputSnapshot(
        job,
        allocation.sha256,
        len(allocation.data),
        TerminalOutcome(TerminalKind.EXIT_CODE, 0),
        now_ms,
        now_ms + RETENTION_MS,
        SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        secrets.token_hex(16),
    )


class MemoryPayload:
    """Trusted in-memory ``SealedPayload`` for one immutable allocation."""

    def __init__(self, data: bytes) -> None:
        self._data = bytes(data)

    def read(self, length: int) -> Result[bytes]:
        if type(length) is not int or length != len(self._data):
            return Failure(BoundaryError(ErrorCode.OUTPUT_CHANGED))
        return Success(bytes(self._data))

    def __repr__(self) -> str:
        return "MemoryPayload(<sealed>)"


def _parsed(verified: bytes) -> tuple[dict[str, object], list[object]] | None:
    try:
        raw = json.loads(verified.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    if type(raw) is not dict or raw.get("schema") != SNAPSHOT_SCHEMA:
        return None
    records = raw.get("records")
    if type(records) is not list or len(records) != LOGICAL_PAGES:
        return None
    return raw, records


def logical_page(verified: bytes, page: object) -> dict[str, object] | None:
    """Page ``i`` of hash-verified lease bytes: ``{slot, seq, value, canary}``.

    Page 0 also returns ``nonce`` and ``alloc_tag``. No state change.
    """
    if type(page) is not int or not 0 <= page < LOGICAL_PAGES:
        return None
    parsed = _parsed(verified)
    if parsed is None:
        return None
    raw, records = parsed
    record = records[page]
    if type(record) is not dict:
        return None
    result: dict[str, object] = {
        "slot": raw.get("slot"),
        "seq": record.get("seq"),
        "value": record.get("value"),
        "canary": record.get("canary"),
    }
    if page == 0:
        result["nonce"] = raw.get("nonce")
        result["alloc_tag"] = raw.get("alloc_tag")
    return result


def echo_matches(verified: bytes, values: object) -> bool:
    """Compare caller values with the caller's own snapshot; never reflect them."""
    parsed = _parsed(verified)
    if parsed is None or type(values) is not list or len(values) != LOGICAL_PAGES:
        return False
    expected = [r.get("value") if type(r) is dict else None for r in parsed[1]]
    return all(
        type(given) is str and type(want) is str and given == want
        for given, want in zip(values, expected, strict=True)
    )

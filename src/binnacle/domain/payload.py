"""Retained payload metadata vocabulary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_PAYLOAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def is_canonical_payload_id(payload_id: str) -> bool:
    """Return whether an identifier is safe for implementation-owned paths."""

    return _PAYLOAD_ID.fullmatch(payload_id) is not None


class PayloadKind(StrEnum):
    RESULT = "result"
    STDOUT = "stdout"
    STDERR = "stderr"
    EVIDENCE = "evidence"
    INTERNAL = "internal"


class PayloadLifecycle(StrEnum):
    BUILDING = "building"
    COMPLETE = "complete"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class PayloadMetadata:
    payload_id: str
    operation_id: str | None
    controller_id: str
    controller_epoch: int
    kind: PayloadKind
    lifecycle: PayloadLifecycle
    relative_path: str
    media_type: str
    encoding: str
    decoded_byte_count: int
    sha256: str | None
    truncated: bool
    information_class: str
    retention_class: str
    created_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    last_access_at: datetime | None = None

    def __post_init__(self) -> None:
        if not is_canonical_payload_id(self.payload_id):
            raise ValueError("payload identifier is not canonical")
        if self.relative_path != f"objects/{self.payload_id}":
            raise ValueError("payload path is not implementation-owned")
        if self.controller_epoch < 1 or self.decoded_byte_count < 0:
            raise ValueError("payload metadata counters are invalid")

"""Trusted wall-time and same-boot monotonic ordering domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class TrustedTimeSnapshot:
    wall_time: datetime
    monotonic_ns: int
    boot_id_digest: str
    wall_time_trusted: bool


@dataclass(frozen=True, slots=True)
class TrustedTimeEvidence:
    high_watermark: datetime | None
    boot_id_digest: str | None
    monotonic_ns: int | None
    generation: int


class DeadlineStatus(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DeadlineEvaluation:
    status: DeadlineStatus
    accepted_evidence: TrustedTimeEvidence | None


def evaluate_deadline(
    *,
    snapshot: TrustedTimeSnapshot,
    evidence: TrustedTimeEvidence,
    expires_at: datetime,
    registered_boot_id_digest: str,
    monotonic_deadline_ns: int,
) -> DeadlineEvaluation:
    if snapshot.monotonic_ns < 0:
        return DeadlineEvaluation(DeadlineStatus.UNAVAILABLE, None)
    if snapshot.boot_id_digest == registered_boot_id_digest:
        if snapshot.monotonic_ns >= monotonic_deadline_ns:
            return DeadlineEvaluation(DeadlineStatus.EXPIRED, evidence)
        if evidence.boot_id_digest == snapshot.boot_id_digest and (
            evidence.monotonic_ns is not None and snapshot.monotonic_ns < evidence.monotonic_ns
        ):
            return DeadlineEvaluation(DeadlineStatus.UNAVAILABLE, None)
    elif not snapshot.wall_time_trusted:
        return DeadlineEvaluation(DeadlineStatus.UNAVAILABLE, None)
    if not snapshot.wall_time_trusted:
        return DeadlineEvaluation(DeadlineStatus.UNAVAILABLE, None)
    if evidence.high_watermark is not None and snapshot.wall_time < evidence.high_watermark:
        return DeadlineEvaluation(DeadlineStatus.UNAVAILABLE, None)
    accepted = TrustedTimeEvidence(
        high_watermark=max(
            item for item in (evidence.high_watermark, snapshot.wall_time) if item is not None
        ),
        boot_id_digest=snapshot.boot_id_digest,
        monotonic_ns=snapshot.monotonic_ns,
        generation=(
            evidence.generation
            if evidence.boot_id_digest in {None, snapshot.boot_id_digest}
            else evidence.generation + 1
        ),
    )
    status = DeadlineStatus.EXPIRED if snapshot.wall_time >= expires_at else DeadlineStatus.VALID
    return DeadlineEvaluation(status, accepted)

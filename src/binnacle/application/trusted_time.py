"""Durable trusted-time high-water and deadline guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from binnacle.domain.trusted_time import (
    DeadlineEvaluation,
    TrustedTimeEvidence,
    TrustedTimeSnapshot,
    evaluate_deadline,
)
from binnacle.ports.operation_store import OperationStore
from binnacle.ports.trusted_time import TrustedTimeSource


class TrustedTimeGuard:
    def __init__(self, *, source: TrustedTimeSource, store: OperationStore) -> None:
        self._source = source
        self._store = store

    async def evaluate(
        self,
        *,
        expires_at: datetime,
        registered_boot_id_digest: str,
        monotonic_deadline_ns: int,
    ) -> DeadlineEvaluation:
        snapshot = await self._source.snapshot()
        durable = await self._store.get_trusted_time_evidence()
        result = evaluate_deadline(
            snapshot=snapshot,
            evidence=durable,
            expires_at=expires_at,
            registered_boot_id_digest=registered_boot_id_digest,
            monotonic_deadline_ns=monotonic_deadline_ns,
        )
        if result.accepted_evidence is not None:
            await self._store.store_trusted_time_evidence(result.accepted_evidence)
        return result

    async def accept_startup_snapshot(self, snapshot: TrustedTimeSnapshot) -> bool:
        """Persist a non-regressing trusted startup observation without extending a deadline."""

        durable = await self._store.get_trusted_time_evidence()
        if snapshot.monotonic_ns < 0 or not snapshot.wall_time_trusted:
            return False
        if durable.high_watermark is not None and snapshot.wall_time < durable.high_watermark:
            return False
        if (
            durable.boot_id_digest == snapshot.boot_id_digest
            and durable.monotonic_ns is not None
            and snapshot.monotonic_ns < durable.monotonic_ns
        ):
            return False
        accepted = TrustedTimeEvidence(
            high_watermark=max(
                item for item in (durable.high_watermark, snapshot.wall_time) if item is not None
            ),
            boot_id_digest=snapshot.boot_id_digest,
            monotonic_ns=snapshot.monotonic_ns,
            generation=(
                durable.generation
                if durable.boot_id_digest in {None, snapshot.boot_id_digest}
                else durable.generation + 1
            ),
        )
        await self._store.store_trusted_time_evidence(accepted)
        return True

    async def issue_deadline(self, ttl_seconds: int) -> PreparedDeadline:
        """Issue a same-boot monotonic deadline only from accepted trusted time."""

        if ttl_seconds < 1:
            raise ValueError("deadline TTL must be positive")
        snapshot = await self._source.snapshot()
        if not await self.accept_startup_snapshot(snapshot):
            raise RuntimeError("trusted time is unavailable")
        return PreparedDeadline(
            expires_at=snapshot.wall_time + timedelta(seconds=ttl_seconds),
            registered_boot_id_digest=snapshot.boot_id_digest,
            monotonic_deadline_ns=snapshot.monotonic_ns + ttl_seconds * 1_000_000_000,
        )


@dataclass(frozen=True, slots=True)
class PreparedDeadline:
    expires_at: datetime
    registered_boot_id_digest: str
    monotonic_deadline_ns: int

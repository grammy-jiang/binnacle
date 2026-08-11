"""Durable trusted-time high-water and deadline guard."""

from __future__ import annotations

from datetime import datetime

from binnacle.domain.trusted_time import DeadlineEvaluation, evaluate_deadline
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

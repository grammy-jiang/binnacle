"""Conservative replacement-application reconciliation for Phase 9 restarts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.privileged import BrokerAcceptanceState
from binnacle.ports.privileged import (
    PrivilegedApplicationRepository,
    PrivilegedBrokerPort,
    PrivilegedBrokerUnavailable,
)


class PrivilegedRestartReconciliationError(RuntimeError):
    """Retained application and broker restart evidence cannot be reconciled safely."""


class PrivilegedRestartReconciler:
    """Route retained restart operations away from generic no-effect recovery.

    This slice records exact broker observations but deliberately leaves the Phase 4
    operation and Phase 6 fence open.  Later checkpoint/audit closure is the only path
    allowed to release them.  Broker absence, an empty lookup, or a no-accept decision
    therefore remains recovery-closed rather than becoming fabricated no-effect truth.
    """

    def __init__(
        self,
        *,
        repository: PrivilegedApplicationRepository,
        broker: PrivilegedBrokerPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._broker = broker
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None:
        retained = await self._repository.get_restart(operation.operation_id)
        if retained is None:
            return None
        if retained.operation_id != operation.operation_id:
            raise PrivilegedRestartReconciliationError(
                "restart repository returned a foreign operation"
            )
        try:
            snapshot = await self._broker.get(operation.operation_id)
        except PrivilegedBrokerUnavailable:
            return operation
        if snapshot is None:
            return operation
        if snapshot.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
            return operation
        await self._repository.record_broker_snapshot(
            snapshot,
            reconciled_at=self._clock(),
        )
        return operation

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
        return ()


__all__ = [
    "PrivilegedRestartReconciler",
    "PrivilegedRestartReconciliationError",
]

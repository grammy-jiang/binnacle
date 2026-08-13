"""Conservative replacement-application reconciliation for Phase 9 restarts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.privileged import BrokerAcceptanceState, BrokerBindingSnapshot
from binnacle.domain.privileged_restart import RestartNoAcceptClosureRequest
from binnacle.ports.privileged import (
    PrivilegedApplicationRepository,
    PrivilegedBrokerPort,
    PrivilegedBrokerUnavailable,
)


class PrivilegedRestartReconciliationError(RuntimeError):
    """Retained application and broker restart evidence cannot be reconciled safely."""


class RestartNoAcceptAuditClosure(Protocol):
    """Idempotently retain/reuse audit closure for a broker-proven no-accept result."""

    async def record_no_accept(
        self,
        operation: OperationSnapshot,
        snapshot: BrokerBindingSnapshot,
    ) -> str: ...


class PrivilegedRestartReconciler:
    """Route retained restart operations away from generic no-effect recovery.

    Accepted broker observations deliberately leave the Phase 4 operation and Phase 6
    fence open. A sealed no-accept result closes them only after an explicit audit
    closure dependency returns retained evidence. Without that dependency, broker
    absence, an empty lookup, and no-accept all remain recovery-closed.
    """

    def __init__(
        self,
        *,
        repository: PrivilegedApplicationRepository,
        broker: PrivilegedBrokerPort,
        no_accept_audit_closure: RestartNoAcceptAuditClosure | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._broker = broker
        self._no_accept_audit_closure = no_accept_audit_closure
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
            if self._no_accept_audit_closure is None:
                return operation
            audit_evidence_sha256 = await self._no_accept_audit_closure.record_no_accept(
                operation,
                snapshot,
            )
            closed, _, _ = await self._repository.close_restart_no_accept(
                RestartNoAcceptClosureRequest(
                    snapshot=snapshot,
                    audit_closure_evidence_sha256=audit_evidence_sha256,
                    closed_at=self._clock(),
                )
            )
            return closed
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
    "RestartNoAcceptAuditClosure",
]

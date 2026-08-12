"""Execution-domain backends; production remains unavailable before Pi promotion."""

from __future__ import annotations

from binnacle.domain.execution import ExecutionTicket
from binnacle.ports.execution import (
    CleanupReceipt,
    DomainHandle,
    DomainSnapshot,
    SignalReceipt,
    SignalRequest,
    TerminationReceipt,
)


class ExecutionBackendUnavailable(RuntimeError):
    """No evidence-approved execution-domain backend is selected."""


class UnavailableExecutionDomainBackend:
    """Fail-closed production backend used until real Pi evidence selects a mechanism."""

    async def ready(self) -> bool:
        return False

    async def create(self, ticket: ExecutionTicket, execution_id: str) -> DomainHandle:
        del ticket, execution_id
        raise ExecutionBackendUnavailable("execution-domain backend is not promoted")

    async def inspect(self, handle: DomainHandle) -> DomainSnapshot:
        del handle
        raise ExecutionBackendUnavailable("execution-domain backend is not promoted")

    async def signal(self, handle: DomainHandle, request: SignalRequest) -> SignalReceipt:
        del handle, request
        raise ExecutionBackendUnavailable("execution-domain backend is not promoted")

    async def terminate_tree(self, handle: DomainHandle) -> TerminationReceipt:
        del handle
        raise ExecutionBackendUnavailable("execution-domain backend is not promoted")

    async def cleanup(self, handle: DomainHandle) -> CleanupReceipt:
        del handle
        raise ExecutionBackendUnavailable("execution-domain backend is not promoted")


__all__ = ["ExecutionBackendUnavailable", "UnavailableExecutionDomainBackend"]

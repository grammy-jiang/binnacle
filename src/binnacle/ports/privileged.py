"""Typed boundaries for the independent Phase 9 privileged broker."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.privileged import (
    BrokerAcceptanceReceipt,
    BrokerBindingSnapshot,
    BrokerNoAcceptReason,
    PrivilegedBrokerHello,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
)
from binnacle.domain.privileged_observation import (
    PackageInspectionResult,
    PackageTarget,
    PackageTransactionPlan,
    RestartPreflightKind,
    RestartPreflightResult,
    RuntimeIdentity,
    ServiceInspectionResult,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import (
    PrivilegedRestartCheckpointIntent,
    PrivilegedRestartPreparation,
    PrivilegedRestartRecord,
    RestartAcceptedClosureRequest,
    RestartAuthorisationRequest,
    RestartNoAcceptClosureRequest,
)
from binnacle.domain.workspace import WorkspaceFence


class PrivilegedBrokerUnavailable(RuntimeError):
    """The authenticated broker boundary cannot return trustworthy evidence."""


class PrivilegedTicketVerifier(Protocol):
    """Verify receiver-owned ticket authority before durable acceptance."""

    def validate(self, ticket: PrivilegedTicket) -> None: ...


class PrivilegedEvidenceStore(Protocol):
    """Broker-owned one-ticket-per-operation acceptance and seal evidence."""

    async def accept_once(self, ticket: PrivilegedTicket) -> BrokerAcceptanceReceipt: ...

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt: ...

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None: ...

    async def close(self) -> None: ...


class PrivilegedBrokerPort(Protocol):
    """Application-side access to the authenticated broker protocol."""

    async def hello(self) -> PrivilegedBrokerHello: ...

    async def start(
        self,
        ticket: PrivilegedTicket,
        restart_intent: PrivilegedRestartCheckpointIntent | None = None,
    ) -> BrokerAcceptanceReceipt: ...

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None: ...

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt: ...


class PackageObservationPort(Protocol):
    """Inspect and prepare one closed package transaction without mutation."""

    async def inspect(self, target: PackageTarget) -> PackageInspectionResult: ...

    async def prepare(self, targets: tuple[PackageTarget, ...]) -> PackageTransactionPlan: ...


class ServiceObservationPort(Protocol):
    """Inspect only the exact configured Binnacle service."""

    async def inspect(self) -> ServiceInspectionResult: ...


class RuntimeIdentityPort(Protocol):
    """Return the exact current application runtime identity."""

    async def current(self) -> RuntimeIdentity: ...


class RestartPreflightPort(Protocol):
    """Return advisory restart facts without reserving or authorizing a restart."""

    async def inspect(self, kind: RestartPreflightKind) -> RestartPreflightResult: ...


class RuntimeSlotInspectionPort(Protocol):
    """Inspect complete protected runtime slots without changing a selector."""

    async def inspect(self, slot_id: str) -> VerifiedRuntimeSlot: ...

    async def current(self) -> VerifiedRuntimeSlot | None: ...

    async def lkg(self) -> VerifiedRuntimeSlot | None: ...


class PrivilegedApplicationRepository(Protocol):
    """Application-owned preparation, ticket binding, fence, and reservation evidence."""

    async def store_restart_preparation(
        self,
        preparation: PrivilegedRestartPreparation,
    ) -> PrivilegedRestartPreparation: ...

    async def authorise_restart(
        self,
        request: RestartAuthorisationRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]: ...

    async def get_restart(self, operation_id: str) -> PrivilegedRestartRecord | None: ...

    async def mark_restart_dispatched(
        self,
        operation_id: str,
        *,
        dispatched_at: datetime,
    ) -> PrivilegedRestartRecord: ...

    async def record_broker_snapshot(
        self,
        snapshot: BrokerBindingSnapshot,
        *,
        reconciled_at: datetime,
    ) -> PrivilegedRestartRecord: ...

    async def restart_recovery_pending(self) -> bool: ...

    async def close_restart_no_accept(
        self,
        request: RestartNoAcceptClosureRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]: ...

    async def close_restart_accepted(
        self,
        request: RestartAcceptedClosureRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence, PrivilegedRestartRecord]: ...


__all__ = [
    "PackageObservationPort",
    "PrivilegedApplicationRepository",
    "PrivilegedBrokerPort",
    "PrivilegedBrokerUnavailable",
    "PrivilegedEvidenceStore",
    "PrivilegedTicketVerifier",
    "RestartPreflightPort",
    "RuntimeIdentityPort",
    "RuntimeSlotInspectionPort",
    "ServiceObservationPort",
]

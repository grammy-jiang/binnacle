"""Typed boundaries for the independent Phase 9 privileged broker."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

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
    RuntimeIdentity,
    ServiceInspectionResult,
    VerifiedRuntimeSlot,
)


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

    async def start(self, ticket: PrivilegedTicket) -> BrokerAcceptanceReceipt: ...

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


class RuntimeSlotInspectionPort(Protocol):
    """Inspect complete protected runtime slots without changing a selector."""

    async def inspect(self, slot_id: str) -> VerifiedRuntimeSlot: ...

    async def current(self) -> VerifiedRuntimeSlot | None: ...

    async def lkg(self) -> VerifiedRuntimeSlot | None: ...


__all__ = [
    "PackageObservationPort",
    "PrivilegedBrokerPort",
    "PrivilegedEvidenceStore",
    "PrivilegedTicketVerifier",
    "RuntimeIdentityPort",
    "RuntimeSlotInspectionPort",
    "ServiceObservationPort",
]

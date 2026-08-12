"""Typed boundaries for the independent Phase 9 privileged broker."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from binnacle.domain.privileged import (
    BrokerAcceptanceReceipt,
    BrokerBindingSnapshot,
    BrokerNoAcceptReason,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
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


__all__ = ["PrivilegedEvidenceStore", "PrivilegedTicketVerifier"]

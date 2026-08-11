"""Internal durable-kernel health state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class KernelAvailability(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KernelHealth:
    availability: KernelAvailability
    database_healthy: bool
    audit_healthy: bool
    payload_healthy: bool
    obligation_count: int
    audit_failure_latched: bool
    reason_codes: tuple[str, ...] = ()

    @property
    def consequential_admission_allowed(self) -> bool:
        return (
            self.availability is KernelAvailability.AVAILABLE
            and self.database_healthy
            and self.audit_healthy
            and self.payload_healthy
            and self.obligation_count == 0
            and not self.audit_failure_latched
        )

"""Native capability values and controlled errors; declarations grant no authority.

UNKNOWN and UNAVAILABLE never authorize an operation. LIMITED applies only
within its reviewed scope and current generation. Error codes must be sanitized
identifiers, never native stderr, secrets or arbitrary paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Capability:
    state: CapabilityState
    reason_code: str
    scope: str
    evidence_id: str | None = None


class NativeCapabilityError(RuntimeError):
    code: str
    capability: Capability

    def __init__(self, code: str, capability: Capability) -> None:
        self.code = code
        self.capability = capability
        super().__init__(code)


class CapabilityUnavailable(NativeCapabilityError): ...


class AuthorityUnknown(NativeCapabilityError): ...


class GenerationMismatch(NativeCapabilityError): ...


class PermissionDenied(NativeCapabilityError): ...


class UnsafePath(NativeCapabilityError): ...


class CursorExpired(NativeCapabilityError): ...


class BudgetExceeded(NativeCapabilityError): ...

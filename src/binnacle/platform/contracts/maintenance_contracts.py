"""Neutral, advisory-only admission and lifespan contracts for Issue #30.

No tool framework or Darwin implementation can be imported here. A drained
snapshot is a local observation, never authority to stop a service or unlink
an archived log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DrainSnapshot:
    generation: str
    pause_nonce: str | None
    in_flight: int
    drained: bool
    shutdown_authorized: bool = False

    def __post_init__(self) -> None:
        if self.shutdown_authorized:
            raise ValueError("MCP drain never authorizes producer stop")


class MCPAdmissionGate(Protocol):
    generation: str

    def snapshot(self) -> DrainSnapshot: ...

    def fence(self, *, nonce: str, generation: str) -> DrainSnapshot: ...

    def wait_drained(self, *, nonce: str, timeout: float) -> DrainSnapshot: ...


class MaintenanceSidecar(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...

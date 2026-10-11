"""Darwin observations and foreground execution declarations, without adapters.

Generation identifiers and persisted process metadata are not signal authority.
Witness/history observations cannot authorize durable job signals. Lost authority
is UNKNOWN, with membership_closed and can_signal both false.

Foreground results describe only the directly owned leader; descendants remain
unverified. Runtime execution stays UNAVAILABLE and disabled until the exact A2
implementation has R1 and CR1 approval plus B0 wiring and current owner proof.
stop_job stays UNAVAILABLE; this interface grants no full parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal, Protocol

from binnacle.platform.contracts.capability_contracts import Capability


@dataclass(frozen=True)
class OwnerGeneration:
    manager_epoch: str
    witness_epoch: str
    job_id: str


@dataclass(frozen=True)
class AuthorityObservation:
    capability: Capability
    generation: OwnerGeneration | None
    membership_closed: bool
    can_signal: bool


class OwnedWitness(Protocol):
    def observe(self, job_id: str) -> AuthorityObservation: ...
    def reconnect(self, generation: OwnerGeneration) -> AuthorityObservation: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ForegroundRequest:
    command: str
    workdir: Path
    stdin: str | None
    wait_seconds: float
    background: bool
    foreground_limit_s: float
    max_output_bytes: int


@dataclass(frozen=True)
class ForegroundResult:
    execution_id: str
    owner_generation: str
    exit_code: int | None
    signal: int | None
    output: bytes
    output_bytes: int
    truncated: bool
    duration_s: float
    descendants_unverified: Literal[True]


class ForegroundExecution(Protocol):
    def run_foreground(
        self, request: ForegroundRequest, *, cancel: Event
    ) -> ForegroundResult: ...

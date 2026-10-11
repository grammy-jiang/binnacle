"""Durable stop admission and resolution contracts, without a stop implementation.

Intent identifiers are data, not authority. Only the coordinator-issued executor
may open signals; concurrent callers join the same unresolved intent. Admission
is durable before signaling. Resolution requires target closure, terminal leader
evidence, executor quiescence, and file plus directory sync.

All readers, reapers, RPC replies and retention use the terminal guard in their
metadata transaction. Unresolved or unreadable state raises a controlled error;
None means a positively readable record without an intent or legacy uncertainty.
The frozen 1.1.0 stop_protocol governs implementations; these types do not prove
closure or authorize signaling from caller-supplied receipt booleans.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from binnacle.platform.contracts.process_contracts import JobSignalLease


@dataclass(frozen=True)
class StopIntent:
    job_id: str
    job_incarnation: str
    owner_epoch: str
    request_id: str


@dataclass(frozen=True)
class StopReceipt:
    intent: StopIntent
    state: Literal["admitted", "signaling", "closed", "unknown", "failed"]
    target_set_closed: bool
    leader_terminal: bool
    executor_quiesced: bool
    outcome_persisted: bool


class StopExecutor(Protocol):
    @property
    def intent(self) -> StopIntent: ...
    def quiesce(self) -> None: ...


@dataclass(frozen=True)
class StopAdmission:
    intent: StopIntent
    executor: StopExecutor | None


class StopCoordinator(Protocol):
    def admit(self, job_id: str) -> StopAdmission: ...
    def join(self, intent: StopIntent, *, timeout_s: float) -> StopReceipt: ...
    def open_signals(self, executor: StopExecutor) -> JobSignalLease: ...
    def observe(self, executor: StopExecutor, *, timeout_s: float) -> StopReceipt: ...
    def record(self, executor: StopExecutor, receipt: StopReceipt) -> StopReceipt: ...
    def terminal_guard(self, job_id: str) -> StopReceipt | None: ...

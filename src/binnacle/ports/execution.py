"""Typed boundaries for the independent Phase 7 execution supervisor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from binnacle.domain.execution import (
    CancelRoutingResult,
    CommandExecutionSnapshot,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorEvidenceEvent,
    ExecutorHello,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputStream,
    TicketRoutingIdentity,
)


@dataclass(frozen=True, slots=True)
class DomainHandle:
    execution_id: str
    backend_reference: str


@dataclass(frozen=True, slots=True)
class DomainSnapshot:
    backend_reference: str
    running: bool
    descendants_running: bool
    exit_code: int | None
    exit_signal: int | None
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class SignalRequest:
    cancel_generation: int
    graceful_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SignalReceipt:
    backend_reference: str
    signal_applied: bool
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class TerminationReceipt:
    backend_reference: str
    descendants_stopped: bool
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    backend_reference: str
    process_domain_removed: bool
    private_resources_removed: bool
    output_finalized: bool
    evidence_sha256: str


class ExecutionDomainBackend(Protocol):
    """Create and control one reviewed execution domain outside the application."""

    async def ready(self) -> bool: ...

    async def create(self, ticket: ExecutionTicket, execution_id: str) -> DomainHandle: ...

    async def inspect(self, handle: DomainHandle) -> DomainSnapshot: ...

    async def signal(self, handle: DomainHandle, request: SignalRequest) -> SignalReceipt: ...

    async def terminate_tree(self, handle: DomainHandle) -> TerminationReceipt: ...

    async def cleanup(self, handle: DomainHandle) -> CleanupReceipt: ...


class ExecutorEvidenceStore(Protocol):
    """Executor-owned durable single-use acceptance and lifecycle evidence."""

    async def accept_once(self, ticket: ExecutionTicket) -> ExecutionStartReceipt: ...

    async def cancel_or_attach(
        self,
        *,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
    ) -> CancelRoutingResult: ...

    async def seal_no_accept(
        self,
        *,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: datetime,
    ) -> NoAcceptSealResult: ...

    async def get(self, operation_id: str) -> ExecutorSnapshot | None: ...

    async def list(
        self,
        operation_ids: tuple[str, ...],
    ) -> tuple[ExecutorSnapshot, ...]: ...

    async def list_outstanding(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int = 256,
    ) -> tuple[ExecutorSnapshot, ...]: ...

    async def apply_event(self, event: ExecutorEvidenceEvent) -> ExecutorSnapshot: ...

    async def set_readiness(self, readiness: str) -> None: ...

    async def close(self) -> None: ...


class ExecutionSupervisorPort(Protocol):
    """Application-side view of the independently supervised execution service."""

    async def hello(self) -> ExecutorHello: ...

    async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt: ...

    async def get(self, operation_id: str) -> ExecutorSnapshot | None: ...

    async def read_output(
        self,
        operation_id: str,
        stream: OutputStream,
        offset: int,
        max_bytes: int,
    ) -> ExecutorOutputChunk: ...

    async def cancel(
        self,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
        execution_id: str | None = None,
    ) -> ExecutorCancelReceipt: ...

    async def seal_no_accept(
        self,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: datetime,
    ) -> NoAcceptSealResult: ...

    async def list(self, operation_ids: tuple[str, ...]) -> tuple[ExecutorSnapshot, ...]: ...


class CommandExecutionRepository(Protocol):
    """Application-owned authoritative command correlation and cancel delivery state."""

    async def create(
        self, ticket: ExecutionTicket, *, created_at: datetime
    ) -> CommandExecutionSnapshot: ...

    async def get(self, operation_id: str) -> CommandExecutionSnapshot | None: ...

    async def record_start_receipt(
        self,
        operation_id: str,
        *,
        receipt: ExecutionStartReceipt,
        recorded_at: datetime,
    ) -> CommandExecutionSnapshot: ...

    async def request_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        cancel_operation_id: str,
        request_fingerprint_sha256: str,
        requested_at: datetime,
    ) -> CommandExecutionSnapshot: ...

    async def acknowledge_cancel(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        receipt: ExecutorCancelReceipt,
        snapshot: ExecutorSnapshot | None,
        reconciled_at: datetime,
    ) -> CommandExecutionSnapshot: ...

    async def record_executor_snapshot(
        self,
        operation_id: str,
        *,
        expected_record_version: int,
        snapshot: ExecutorSnapshot,
        reconciled_at: datetime,
    ) -> CommandExecutionSnapshot: ...

    async def list_unclosed(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int,
    ) -> tuple[CommandExecutionSnapshot, ...]: ...


class CommandRecoveryVerifier(Protocol):
    """Prove Phase 4 will never originate call_start for one unresolved ticket."""

    async def prove_no_future_dispatch(self, record: CommandExecutionSnapshot) -> str: ...


__all__ = [
    "CleanupReceipt",
    "CommandExecutionRepository",
    "CommandRecoveryVerifier",
    "DomainHandle",
    "DomainSnapshot",
    "ExecutionDomainBackend",
    "ExecutionSupervisorPort",
    "ExecutorEvidenceStore",
    "SignalReceipt",
    "SignalRequest",
    "TerminationReceipt",
]

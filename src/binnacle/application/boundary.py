"""Cancellation-safe and audit-failure-safe consequential dispatch gates."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum

from binnacle.application.kernel_health import KernelHealth
from binnacle.domain.operation import OperationSnapshot, OperationState
from binnacle.ports.boundary import (
    BoundaryCheckResult,
    OperationBoundaryCheck,
    OperationBoundaryVerifier,
)
from binnacle.ports.effect import EffectBoundary, EffectRequest, EffectStartReceipt


class BoundaryGateError(RuntimeError):
    pass


class GateState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    TRIPPED = "tripped"


class PermitState(StrEnum):
    PRE_START = "pre_start"
    START_COMMITTED = "start_committed"
    DONE = "done"


@dataclass(slots=True, eq=False)
class ConsequentialPermit:
    permit_id: str
    generation: int
    state: PermitState = PermitState.PRE_START
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class ConsequentialTrip:
    generation: int
    reason: str
    revoked_permits: int


class ConsequentialBoundaryGate:
    """Linearize audit-failure trip against every future boundary start."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._state = GateState.CLOSED
        self._generation = 1
        self._permits: set[ConsequentialPermit] = set()

    @property
    def state(self) -> GateState:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    async def open(self) -> None:
        async with self._condition:
            if any(permit.state is PermitState.START_COMMITTED for permit in self._permits):
                raise BoundaryGateError("cannot open while starts are active")
            self._generation += 1
            self._state = GateState.OPEN

    async def close(self) -> None:
        async with self._condition:
            self._state = GateState.CLOSED
            self._generation += 1
            for permit in self._permits:
                if permit.state is PermitState.PRE_START:
                    permit.revoked = True

    async def acquire(self) -> ConsequentialPermit:
        async with self._condition:
            if self._state is not GateState.OPEN:
                raise BoundaryGateError("consequential boundary gate is not open")
            permit = ConsequentialPermit(
                permit_id=f"permit_{secrets.token_hex(12)}",
                generation=self._generation,
            )
            self._permits.add(permit)
            return permit

    async def release(self, permit: ConsequentialPermit) -> None:
        async with self._condition:
            if permit.state is PermitState.START_COMMITTED:
                raise BoundaryGateError("cannot release an active start")
            permit.state = PermitState.DONE
            self._permits.discard(permit)
            self._condition.notify_all()

    async def call_start(
        self,
        permit: ConsequentialPermit,
        boundary: EffectBoundary,
        request: EffectRequest,
    ) -> EffectStartReceipt:
        async with self._condition:
            if (
                self._state is not GateState.OPEN
                or permit not in self._permits
                or permit.revoked
                or permit.generation != self._generation
                or permit.state is not PermitState.PRE_START
            ):
                raise BoundaryGateError("consequential permit was revoked or is stale")
            permit.state = PermitState.START_COMMITTED
        return await boundary.start(request)

    async def complete_start(self, permit: ConsequentialPermit) -> None:
        """Release one start only after its immediate durable classification."""

        async with self._condition:
            if permit not in self._permits or permit.state is not PermitState.START_COMMITTED:
                raise BoundaryGateError("start completion does not match an active permit")
            permit.state = PermitState.DONE
            self._permits.discard(permit)
            self._condition.notify_all()

    async def trip(self, reason: str) -> ConsequentialTrip:
        async with self._condition:
            self._state = GateState.TRIPPED
            self._generation += 1
            revoked = 0
            for permit in self._permits:
                if permit.state is PermitState.PRE_START and not permit.revoked:
                    permit.revoked = True
                    revoked += 1
            trip = ConsequentialTrip(self._generation, reason, revoked)
            await self._condition.wait_for(
                lambda: (
                    not any(permit.state is PermitState.START_COMMITTED for permit in self._permits)
                )
            )
            return trip


@dataclass(slots=True)
class _KeyedLock:
    lock: asyncio.Lock
    users: int = 0


class DispatchHandoffGate:
    """Bounded keyed mutex shared by dispatch and cancellation."""

    def __init__(self) -> None:
        self._registry_lock = asyncio.Lock()
        self._locks: dict[str, _KeyedLock] = {}

    @property
    def entry_count(self) -> int:
        return len(self._locks)

    @asynccontextmanager
    async def hold(self, operation_id: str) -> AsyncIterator[None]:
        async with self._registry_lock:
            entry = self._locks.setdefault(operation_id, _KeyedLock(asyncio.Lock()))
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._registry_lock:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._locks.pop(operation_id, None)


HealthReader = Callable[[], Awaitable[KernelHealth]]


class FinalBoundaryService:
    """Re-read lifecycle, health, and operation-specific predicates before dispatch."""

    def __init__(
        self,
        *,
        health_reader: HealthReader,
        verifier: OperationBoundaryVerifier,
    ) -> None:
        self._health_reader = health_reader
        self._verifier = verifier

    async def verify(
        self,
        *,
        snapshot: OperationSnapshot,
        check: OperationBoundaryCheck,
    ) -> BoundaryCheckResult:
        if snapshot.state is not OperationState.RUNNING:
            return BoundaryCheckResult(False, "operation_not_running")
        if snapshot.state_version != check.expected_state_version:
            return BoundaryCheckResult(False, "operation_state_conflict")
        health = await self._health_reader()
        if not health.consequential_admission_allowed:
            return BoundaryCheckResult(False, "kernel_unavailable")
        try:
            return await self._verifier.verify(check)
        except Exception:  # noqa: BLE001 - verifier failure is a fail-closed result.
            return BoundaryCheckResult(False, "boundary_verifier_unavailable")

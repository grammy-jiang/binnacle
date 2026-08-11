"""Per-operation and global start-vs-trip gate tests."""

from __future__ import annotations

import asyncio

import pytest
from tests.phase4_support import NOW, intent, owner

from binnacle.application.boundary import (
    BoundaryGateError,
    ConsequentialBoundaryGate,
    DispatchHandoffGate,
    FinalBoundaryService,
    GateState,
)
from binnacle.application.kernel_health import KernelAvailability, KernelHealth
from binnacle.domain.operation import EffectKnowledge, OperationState, new_received_operation
from binnacle.ports.boundary import BoundaryCheckResult, OperationBoundaryCheck
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectRequest,
    EffectStartReceipt,
)


class CountingBoundary:
    def __init__(self, entered: asyncio.Event | None = None, release: asyncio.Event | None = None):
        self.count = 0
        self.entered = entered
        self.release = release

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        del request
        self.count += 1
        if self.entered:
            self.entered.set()
        if self.release:
            await self.release.wait()
        return EffectStartReceipt(
            BoundaryCrossing.CROSSED,
            EffectKnowledge.KNOWN_EFFECT,
            terminal_state=OperationState.SUCCEEDED,
        )


class AllowVerifier:
    async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult:
        del request
        return BoundaryCheckResult(True, "allowed")


@pytest.mark.anyio
async def test_gate_starts_closed_and_trip_revokes_prestart() -> None:
    gate = ConsequentialBoundaryGate()
    with pytest.raises(BoundaryGateError):
        await gate.acquire()
    await gate.open()
    permit = await gate.acquire()
    trip = await gate.trip("audit_failed")
    assert trip.revoked_permits == 1
    assert gate.state is GateState.TRIPPED
    boundary = CountingBoundary()
    with pytest.raises(BoundaryGateError):
        await gate.call_start(permit, boundary, EffectRequest("op", 1, "synthetic", {}))
    assert boundary.count == 0
    await gate.release(permit)


@pytest.mark.anyio
async def test_start_winner_is_drained_before_trip_returns() -> None:
    gate = ConsequentialBoundaryGate()
    await gate.open()
    permit = await gate.acquire()
    entered = asyncio.Event()
    release = asyncio.Event()
    boundary = CountingBoundary(entered, release)
    start_task = asyncio.create_task(
        gate.call_start(permit, boundary, EffectRequest("op", 1, "synthetic", {}))
    )
    await entered.wait()
    trip_task = asyncio.create_task(gate.trip("audit_failed"))
    await asyncio.sleep(0)
    assert not trip_task.done()
    release.set()
    await start_task
    assert not trip_task.done()
    await gate.complete_start(permit)
    await trip_task
    assert boundary.count == 1


@pytest.mark.anyio
async def test_dispatch_handoff_gate_serializes_and_cleans_entries() -> None:
    gate = DispatchHandoffGate()
    first_entered = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with gate.hold("op"):
            order.append("first")
            first_entered.set()
            await release.wait()

    async def second() -> None:
        await first_entered.wait()
        async with gate.hold("op"):
            order.append("second")

    tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
    await first_entered.wait()
    release.set()
    await asyncio.gather(*tasks)
    assert order == ["first", "second"]
    assert gate.entry_count == 0


@pytest.mark.anyio
async def test_final_boundary_checks_health_state_version_and_verifier() -> None:
    async def healthy() -> KernelHealth:
        return KernelHealth(KernelAvailability.AVAILABLE, True, True, True, 0, False)

    service = FinalBoundaryService(health_reader=healthy, verifier=AllowVerifier())
    operation = new_received_operation(owner=owner(), intent=intent(), now=NOW)
    object.__setattr__(operation, "state", OperationState.RUNNING)
    result = await service.verify(
        snapshot=operation,
        check=OperationBoundaryCheck(operation.operation_id, 1, {}),
    )
    assert result.allowed
    object.__setattr__(operation, "state", OperationState.CANCELLING)
    assert not (
        await service.verify(
            snapshot=operation,
            check=OperationBoundaryCheck(operation.operation_id, 1, {}),
        )
    ).allowed

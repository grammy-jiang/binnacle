"""Linearizable in-process MCP admission/drain; no installed middleware."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import pytest
from fastmcp.exceptions import ToolError

from binnacle.mcp.tool_admission_drain import (
    AdmissionTicket,
    DrainSnapshot,
    ToolAdmissionDrain,
    ToolAdmissionDrainMiddleware,
    ToolAdmissionPaused,
    ToolAdmissionUnknown,
)

NONCE = "a" * 32


def test_a_fresh_gate_reports_no_shutdown_authority() -> None:
    gate = ToolAdmissionDrain()
    snap = gate.snapshot()
    assert snap.generation == gate.generation
    assert snap.pause_nonce is None
    assert snap.in_flight == 0
    assert not snap.drained
    assert not snap.shutdown_authorized


def test_active_call_remains_counted_after_closing_admission() -> None:
    gate = ToolAdmissionDrain()
    first, second = gate.admit(), gate.admit()
    assert first != second
    snapshot = gate.fence(nonce=NONCE, generation=gate.generation)
    assert snapshot.in_flight == 2
    assert not snapshot.drained
    with pytest.raises(ToolAdmissionPaused):
        gate.admit()
    timed = gate.wait_drained(nonce=NONCE, timeout=0)
    assert timed.in_flight == 2 and not timed.drained
    gate.release(first)
    assert gate.snapshot().in_flight == 1
    gate.release(second)
    done = gate.wait_drained(nonce=NONCE, timeout=0)
    assert done.drained and done.in_flight == 0
    assert not done.shutdown_authorized
    with pytest.raises(ToolAdmissionPaused):
        gate.admit()  # fence remains until old process exits


def test_empty_gate_fence_is_a_local_snapshot_not_production_approval() -> None:
    gate = ToolAdmissionDrain()
    done = gate.fence(nonce=NONCE, generation=gate.generation)
    assert done.drained
    assert not done.shutdown_authorized
    assert done.pause_nonce == NONCE


@pytest.mark.parametrize("invalid", ["bad", "g" * 32, "a" * 31, "", 123, True])
def test_untrusted_nonce_is_rejected_before_closing(
    invalid: object,
) -> None:
    gate = ToolAdmissionDrain()
    with pytest.raises(ToolAdmissionUnknown, match="nonce"):
        gate.fence(nonce=cast(str, invalid), generation=gate.generation)
    ticket = gate.admit()
    gate.release(ticket)


def test_generation_change_and_double_owner_are_refused() -> None:
    gate = ToolAdmissionDrain()
    with pytest.raises(ToolAdmissionUnknown, match="generation"):
        gate.fence(nonce=NONCE, generation="b" * 32)
    first = gate.fence(nonce=NONCE, generation=gate.generation)
    second = gate.fence(nonce=NONCE, generation=gate.generation)
    assert first == second
    with pytest.raises(ToolAdmissionUnknown, match="another"):
        gate.fence(nonce="b" * 32, generation=gate.generation)


@pytest.mark.parametrize(
    "timeout", [-1, -0.01, 121, float("nan"), float("inf"), True, "1"]
)
def test_bad_drain_timeout_is_not_assumed_idle(timeout: object) -> None:
    gate = ToolAdmissionDrain()
    gate.fence(nonce=NONCE, generation=gate.generation)
    with pytest.raises(ToolAdmissionUnknown, match="timeout"):
        gate.wait_drained(nonce=NONCE, timeout=cast(float, timeout))


def test_drain_requires_exact_fenced_owner() -> None:
    gate = ToolAdmissionDrain()
    with pytest.raises(ToolAdmissionUnknown, match="not owned"):
        gate.wait_drained(nonce=NONCE, timeout=0)
    gate.fence(nonce=NONCE, generation=gate.generation)
    with pytest.raises(ToolAdmissionUnknown, match="not owned"):
        gate.wait_drained(nonce="b" * 32, timeout=0)


def test_call_token_must_be_current_owned_generation() -> None:
    gate = ToolAdmissionDrain()
    ticket = gate.admit()
    for bad in (
        AdmissionTicket("b" * 32, ticket.sequence),
        AdmissionTicket(gate.generation, ticket.sequence + 1),
        AdmissionTicket(gate.generation, True),
        "not-a-ticket",
    ):
        with pytest.raises(ToolAdmissionUnknown, match="ownership"):
            gate.release(cast(AdmissionTicket, bad))
    assert gate.snapshot().in_flight == 1
    gate.release(ticket)
    with pytest.raises(ToolAdmissionUnknown, match="ownership"):
        gate.release(ticket)


def test_duplicate_mcp_instances_never_share_admission_generation() -> None:
    before, after = ToolAdmissionDrain(), ToolAdmissionDrain()
    assert before.generation != after.generation
    ticket = before.admit()
    with pytest.raises(ToolAdmissionUnknown):
        after.release(ticket)
    before.release(ticket)


def test_local_drain_waits_for_in_progress_owner_and_unblocks_exactly_once() -> None:
    gate = ToolAdmissionDrain()
    started = threading.Event()
    finish = threading.Event()
    completed = threading.Event()

    def worker() -> None:
        token = gate.admit()
        started.set()
        assert finish.wait(timeout=6)
        gate.release(token)
        completed.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert started.wait(timeout=5)
    assert not gate.fence(nonce=NONCE, generation=gate.generation).drained
    assert not gate.wait_drained(nonce=NONCE, timeout=0.01).drained
    finish.set()
    assert gate.wait_drained(nonce=NONCE, timeout=3).drained
    assert completed.wait(timeout=5)
    thread.join(timeout=2)


def test_concurrent_calls_are_counted_before_fence_and_cannot_enter_after() -> None:
    gate = ToolAdmissionDrain()
    arrived = threading.Barrier(9, timeout=6)
    go = threading.Event()
    released: list[int] = []
    errors: list[str] = []

    def worker() -> None:
        try:
            ticket = gate.admit()
            arrived.wait()
            assert go.wait(timeout=6)
            gate.release(ticket)
            released.append(ticket.sequence)
        except (AssertionError, RuntimeError, TimeoutError) as exc:
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    arrived.wait()
    assert gate.snapshot().in_flight == 8
    gate.fence(nonce=NONCE, generation=gate.generation)
    with pytest.raises(ToolAdmissionPaused):
        gate.admit()
    go.set()
    assert gate.wait_drained(nonce=NONCE, timeout=5).drained
    for t in threads:
        t.join(timeout=4)
    assert not errors
    assert len(set(released)) == 8
    assert not any(t.is_alive() for t in threads)


def test_snapshot_constructor_must_never_be_forged_into_authority() -> None:
    with pytest.raises(ValueError, match="never authorizes"):
        DrainSnapshot("a" * 32, None, 0, True, shutdown_authorized=True)


def test_middleware_accepted_call_returns_value_and_releases_on_exit() -> None:
    gate = ToolAdmissionDrain()
    middleware = ToolAdmissionDrainMiddleware(gate)
    called = [0]

    async def downstream(_context):
        called[0] += 1
        assert gate.snapshot().in_flight == 1
        await asyncio.sleep(0)
        return {"status": "ok"}

    answer = asyncio.run(middleware.on_call_tool(cast(Any, None), downstream))
    assert answer == {"status": "ok"}
    assert called == [1]
    assert gate.snapshot().in_flight == 0


def test_middleware_denies_new_request_without_running_downstream() -> None:
    gate = ToolAdmissionDrain()
    gate.fence(nonce=NONCE, generation=gate.generation)
    middleware = ToolAdmissionDrainMiddleware(gate)

    async def downstream(_context):
        pytest.fail("rejected tools/call must never execute")

    with pytest.raises(ToolError, match="temporarily refused"):
        asyncio.run(middleware.on_call_tool(cast(Any, None), downstream))


def test_middleware_error_still_decrements_inflight_once() -> None:
    gate = ToolAdmissionDrain()
    middleware = ToolAdmissionDrainMiddleware(gate)

    async def downstream(_context):
        assert gate.snapshot().in_flight == 1
        raise RuntimeError("synthetic tool error")

    with pytest.raises(RuntimeError, match="synthetic"):
        asyncio.run(middleware.on_call_tool(cast(Any, None), downstream))
    assert gate.snapshot().in_flight == 0


def test_cancelling_accepted_async_tool_releases_it_for_drain() -> None:
    gate = ToolAdmissionDrain()
    middleware = ToolAdmissionDrainMiddleware(gate)

    async def scenario():
        entered = asyncio.Event()

        async def blocked(_context):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(middleware.on_call_tool(None, blocked))
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert gate.snapshot().in_flight == 1
        assert not gate.fence(nonce=NONCE, generation=gate.generation).drained
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.wait_drained(nonce=NONCE, timeout=0).drained

    asyncio.run(scenario())

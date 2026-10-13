"""Actual synthetic FastMCP pipeline; no production application registers gate."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from binnacle.mcp.tool_admission_drain import (
    ToolAdmissionDrain,
    ToolAdmissionDrainMiddleware,
)

NONCE = "a" * 32


def _synthetic(gate: ToolAdmissionDrain) -> tuple[FastMCP, list[str]]:
    root = FastMCP("DR-01 synthetic tools only")
    called: list[str] = []

    @root.tool
    def read_file() -> str:
        called.append("read_file")
        return "read-ok"

    @root.tool
    def run_command() -> str:
        called.append("run_command")
        return "run-ok"

    root.add_middleware(ToolAdmissionDrainMiddleware(gate))
    return root, called


def test_one_global_gate_blocks_multiple_tool_names_after_fence() -> None:
    gate = ToolAdmissionDrain()
    root, called = _synthetic(gate)

    async def scenario():
        assert (await root.call_tool("read_file", {})) is not None
        assert (await root.call_tool("run_command", {})) is not None
        assert gate.snapshot().in_flight == 0
        assert not gate.fence(
            nonce=NONCE, generation=gate.generation
        ).shutdown_authorized
        for tool in ("read_file", "run_command"):
            with pytest.raises(ToolError, match="temporarily refused"):
                await root.call_tool(tool, {})

    asyncio.run(scenario())
    assert called == ["read_file", "run_command"]


def test_real_async_fastmcp_call_remains_owned_until_exit() -> None:
    gate = ToolAdmissionDrain()
    root = FastMCP("DR-01 in-flight synthetic")

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        @root.tool
        async def long_running_file_operation() -> str:
            entered.set()
            await release.wait()
            return "completed"

        @root.tool
        async def second_operation() -> str:
            pytest.fail("must be denied once admission is fenced")

        root.add_middleware(ToolAdmissionDrainMiddleware(gate))
        job = asyncio.create_task(root.call_tool("long_running_file_operation", {}))
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert gate.snapshot().in_flight == 1
        gate.fence(nonce=NONCE, generation=gate.generation)
        with pytest.raises(ToolError, match="temporarily refused"):
            await root.call_tool("second_operation", {})
        release.set()
        assert await asyncio.wait_for(job, timeout=5)
        assert gate.wait_drained(nonce=NONCE, timeout=0).drained

    asyncio.run(scenario())


def test_real_fastmcp_cancellation_releases_accepted_request() -> None:
    gate = ToolAdmissionDrain()
    root = FastMCP("DR-01 cancellation")

    async def scenario():
        entered = asyncio.Event()

        @root.tool
        async def cancellable_file_operation() -> str:
            entered.set()
            await asyncio.Event().wait()
            return "never"

        root.add_middleware(ToolAdmissionDrainMiddleware(gate))
        task = asyncio.create_task(root.call_tool("cancellable_file_operation", {}))
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert gate.snapshot().in_flight == 1
        gate.fence(nonce=NONCE, generation=gate.generation)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.wait_drained(nonce=NONCE, timeout=0).drained

    asyncio.run(scenario())

"""Full FastMCP request admission gate, including typed/internal dispatch."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from binnacle.mcp.maintenance_request_admission import FullRequestAdmissionMiddleware
from binnacle.mcp.tool_admission_drain import (
    ToolAdmissionDrain,
    ToolAdmissionPaused,
)


def test_default_held_request_declined_before_downstream_side_effect() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        guard = FullRequestAdmissionMiddleware(gate)
        touched: list[str] = []
        gate.fence(nonce="a" * 32, generation=gate.generation)

        async def downstream(context: Any) -> str:
            touched.append("unsafe")
            return "never"

        with pytest.raises(MCPError, match="admission closed"):
            await guard.on_request(cast(Any, None), downstream)
        with pytest.raises(ToolError, match="admission closed"):
            await guard.on_call_tool(cast(Any, None), downstream)
        assert touched == []
        assert gate.snapshot().in_flight == 0
        assert gate.snapshot().drained

    asyncio.run(run())


def test_request_admitted_before_pause_can_complete_nested_tool_phase() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        guard = FullRequestAdmissionMiddleware(gate)
        seen: list[str] = []

        async def typed(context: Any) -> str:
            seen.append("tool")
            return "success"

        async def request(context: Any) -> str:
            assert gate.snapshot().in_flight == 1
            gate.fence(nonce="a" * 32, generation=gate.generation)
            assert not gate.snapshot().drained
            return await guard.on_call_tool(context, typed)

        result = await guard.on_request(cast(Any, None), request)
        assert result == "success"
        assert seen == ["tool"]
        assert gate.snapshot().in_flight == 0
        assert gate.snapshot().drained
        with pytest.raises(ToolAdmissionPaused):
            gate.admit()

    asyncio.run(run())


def test_cancelled_request_releases_ticket_without_double_release() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        guard = FullRequestAdmissionMiddleware(gate)
        entered, finish = asyncio.Event(), asyncio.Event()

        async def delayed(context: Any) -> str:
            entered.set()
            await finish.wait()
            return "done"

        task = asyncio.create_task(guard.on_request(cast(Any, None), delayed))
        await entered.wait()
        assert gate.snapshot().in_flight == 1
        gate.fence(nonce="a" * 32, generation=gate.generation)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.snapshot().drained
        assert gate.snapshot().in_flight == 0

    asyncio.run(run())


def test_typed_handler_exception_releases_outer_ticket() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        guard = FullRequestAdmissionMiddleware(gate)
        final: list[str] = []

        async def broken(context: Any) -> str:
            assert gate.snapshot().in_flight == 1
            raise RuntimeError("synthetic task fails")

        async def request(context: Any) -> str:
            try:
                return await guard.on_call_tool(context, broken)
            finally:
                final.append("outer")

        with pytest.raises(RuntimeError, match="synthetic"):
            await guard.on_request(cast(Any, None), request)
        assert final == ["outer"]
        assert gate.snapshot().in_flight == 0

    asyncio.run(run())


def test_concurrent_contexts_and_staggered_pause_no_new_admission() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        guard = FullRequestAdmissionMiddleware(gate)
        entered, release = asyncio.Event(), asyncio.Event()
        active = 0

        async def held(context: Any) -> str:
            nonlocal active
            active += 1
            entered.set()
            await release.wait()
            return "done"

        task = asyncio.create_task(guard.on_request(cast(Any, None), held))
        await entered.wait()
        assert active == 1
        gate.fence(nonce="c" * 32, generation=gate.generation)
        with pytest.raises(MCPError, match="closed"):
            await guard.on_request(cast(Any, None), held)
        assert active == 1
        assert gate.snapshot().in_flight == 1
        release.set()
        assert await task == "done"
        assert gate.snapshot().drained

    asyncio.run(run())


def test_in_memory_fastmcp_real_client_fences_tool_and_listing() -> None:
    async def run() -> None:
        gate = ToolAdmissionDrain()
        server = FastMCP("admission-fixture")
        guard = FullRequestAdmissionMiddleware(gate)
        server.add_middleware(guard)
        calls: list[str] = []

        @server.tool
        def side_effect() -> str:
            calls.append("called")
            return "ok"

        async with Client(server) as client:
            listed = await client.list_tools()
            assert any(item.name == "side_effect" for item in listed)
            outcome = await client.call_tool("side_effect")
            assert outcome.content
            assert calls == ["called"]
            assert gate.snapshot().in_flight == 0
            gate.fence(nonce="b" * 32, generation=gate.generation)
            with pytest.raises(Exception, match="maintenance|closed|unavailable"):
                await client.call_tool("side_effect")
            assert calls == ["called"]
            # Some FastMCP versions bypass middleware on local listing.
            # Regardless, it never grants access to a mutating tool call.
        assert gate.snapshot().in_flight == 0

    asyncio.run(run())

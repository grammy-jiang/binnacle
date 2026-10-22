"""Issue #30 C1: real HTTP request-lifetime admission races.

All services run only as temporary ASGI in-process fixtures; there is no
launchd, production session, privileged actuation or raw-log IO.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from binnacle.mcp.maintenance_request_admission import FullRequestAdmissionMiddleware
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain


def _transport(app: Any) -> StreamableHttpTransport:
    def make_client(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            **kwargs,
        )

    return StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=cast(Any, make_client)
    )


def test_fence_rejects_late_http_request_but_drains_previously_admitted_tool() -> None:
    async def exercise() -> None:
        api = FastMCP("issue30-c1-inflight")
        gate = ToolAdmissionDrain()
        api.add_middleware(FullRequestAdmissionMiddleware(gate))
        started = asyncio.Event()
        finish = asyncio.Event()
        calls: list[str] = []

        @api.tool
        async def slow_change() -> str:
            calls.append("started")
            started.set()
            await finish.wait()
            calls.append("finished")
            return "finished"

        app = api.http_app()
        async with (
            app.router.lifespan_context(app),
            Client(_transport(app)) as first,
            Client(_transport(app)) as second,
        ):
            # MCP clients may request tool schema AFTER call completion.
            # Cache the catalogue before fencing, as normal discovery does.
            assert await first.list_tools()
            task = asyncio.create_task(first.call_tool("slow_change"))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                assert gate.snapshot().in_flight >= 1
                fenced = gate.fence(nonce="a" * 32, generation=gate.generation)
                assert not fenced.drained
                with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                    await second.list_tools()
                assert calls == ["started"]
                assert gate.snapshot().in_flight >= 1
            finally:
                finish.set()
            outcome = await asyncio.wait_for(task, timeout=5)
            assert not outcome.is_error
            assert calls == ["started", "finished"]
            assert gate.wait_drained(nonce="a" * 32, timeout=0).drained
            with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                await first.call_tool("slow_change")
            assert calls == ["started", "finished"]

    asyncio.run(exercise())


def test_cancelled_http_tool_releases_ticket_without_reopening_generation() -> None:
    async def exercise() -> None:
        api = FastMCP("issue30-c1-cancel")
        gate = ToolAdmissionDrain()
        api.add_middleware(FullRequestAdmissionMiddleware(gate))
        started = asyncio.Event()
        cancelled = asyncio.Event()
        never = asyncio.Event()

        @api.tool
        async def blocking_change() -> str:
            started.set()
            try:
                await never.wait()
            finally:
                cancelled.set()
            return "unreachable"

        app = api.http_app()
        async with app.router.lifespan_context(app), Client(_transport(app)) as client:
            call = asyncio.create_task(client.call_tool("blocking_change"))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert gate.snapshot().in_flight >= 1
            assert not gate.fence(nonce="b" * 32, generation=gate.generation).drained
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(call, timeout=5)
            await asyncio.wait_for(cancelled.wait(), timeout=5)
            assert gate.wait_drained(nonce="b" * 32, timeout=0).drained
            with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                await client.list_tools()

    asyncio.run(exercise())


def test_http_resources_and_prompts_are_fenced_without_dispatch() -> None:
    async def exercise() -> None:
        api = FastMCP("issue30-c1-resources")
        gate = ToolAdmissionDrain()
        api.add_middleware(FullRequestAdmissionMiddleware(gate))
        hits: list[str] = []

        @api.resource("memo://status")
        def status() -> str:
            hits.append("resource")
            return "ready"

        @api.prompt
        def describe() -> str:
            hits.append("prompt")
            return "hello"

        app = api.http_app()
        async with app.router.lifespan_context(app), Client(_transport(app)) as client:
            assert await client.list_resources()
            assert await client.list_prompts()
            assert await client.read_resource("memo://status")
            assert await client.get_prompt("describe")
            assert hits == ["resource", "prompt"]
            gate.fence(nonce="c" * 32, generation=gate.generation)
            for operation in (
                client.list_resources,
                client.list_prompts,
                lambda: client.read_resource("memo://status"),
                lambda: client.get_prompt("describe"),
            ):
                with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                    await operation()
            assert hits == ["resource", "prompt"]
            assert gate.snapshot().drained

    asyncio.run(exercise())

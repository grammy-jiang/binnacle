"""Real FastMCP HTTP MCP request admission and default-off factory contract."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from binnacle import server
from binnacle.mcp.maintenance_request_admission import FullRequestAdmissionMiddleware
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain


def _make_fixture():
    api = FastMCP("issue30-request-admission")
    gate = ToolAdmissionDrain()
    api.add_middleware(FullRequestAdmissionMiddleware(gate))
    seen: list[str] = []

    @api.tool
    async def probe() -> str:
        seen.append("admitted")
        return "ok"

    return api, gate, seen


def test_real_http_mcp_tool_request_fenced_before_tool_implementation() -> None:
    async def run() -> None:
        root, gate, seen = _make_fixture()
        app = root.http_app()

        def client_factory(**kwargs):
            return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

        async with (
            app.router.lifespan_context(app),
            Client(
                StreamableHttpTransport(
                    "http://test/mcp",
                    httpx_client_factory=cast(Any, client_factory),
                )
            ) as client,
        ):
            listed = await client.list_tools()
            assert [item.name for item in listed] == ["probe"]
            outcome = await client.call_tool("probe")
            assert not outcome.is_error
            assert seen == ["admitted"]
            assert gate.snapshot().in_flight == 0
            gate.fence(nonce="a" * 32, generation=gate.generation)
            with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                await client.call_tool("probe")
            assert seen == ["admitted"]
            assert gate.snapshot().drained

    asyncio.run(run())


def test_real_http_new_listing_cannot_bypass_maintenance_gate() -> None:
    async def run() -> None:
        root, gate, _ = _make_fixture()
        app = root.http_app()

        def client_factory(**kwargs):
            return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

        async with (
            app.router.lifespan_context(app),
            Client(
                StreamableHttpTransport(
                    "http://test/mcp",
                    httpx_client_factory=cast(Any, client_factory),
                )
            ) as client,
        ):
            assert await client.list_tools()
            gate.fence(nonce="b" * 32, generation=gate.generation)
            with pytest.raises(Exception, match="closed|maintenance|unavailable"):
                await client.list_tools()

    asyncio.run(run())


def test_existing_root_factory_without_explicit_gate_remains_default_off(
    tmp_path,
    monkeypatch,
) -> None:
    token = tmp_path / "token"
    token.write_text("issue30-test-only-token")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    root = server.create_server()
    assert not any(
        isinstance(item, FullRequestAdmissionMiddleware) for item in root.middleware
    )


def test_root_factory_wires_only_explicit_gate_without_new_client_tools(
    tmp_path,
    monkeypatch,
) -> None:
    token = tmp_path / "token"
    token.write_text("issue30-test-only-token")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    gate = ToolAdmissionDrain()
    root = server.create_server(admission_gate=gate)
    matching = [
        m for m in root.middleware if isinstance(m, FullRequestAdmissionMiddleware)
    ]
    assert len(matching) == 1 and matching[0].gate is gate
    assert root.instructions
    assert not hasattr(root, "maintenance_control")
    assert gate.snapshot().pause_nonce is None

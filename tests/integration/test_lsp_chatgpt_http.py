"""Wire-level ChatGPT discovery and LSP dispatch through main MCP composition."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx2
import mcp.types
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from binnacle import server
from binnacle.features import lsp_bridge_server as bridge


def test_chatgpt_can_discover_and_call_lsp_on_authenticated_root(
    monkeypatch, tmp_path: Path
):
    state = tmp_path / "lsp"
    state.mkdir(mode=0o700)
    token = state / "token"
    token.write_text("synthetic-test-token-" + "b" * 32)
    token.chmod(0o600)
    grant = state / "grants.json"
    grant.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "grants": {"wsg_private_test": Path.home().joinpath("Projects").name},
            }
        )
    )
    grant.chmod(0o600)
    auth_file = tmp_path / "main-token"
    auth_file.write_text("synthetic-main-token")
    monkeypatch.setattr(server, "TOKEN_FILE", auth_file)
    monkeypatch.setenv("BINNACLE_LSP_BRIDGE_STATE_DIR", str(state))
    monkeypatch.setenv("BINNACLE_LSP_BRIDGE_PORT", "18767")

    forwarded = []

    class StubClient:
        def __init__(self, transport, **_kwargs):
            self.transport = transport

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def call_tool(self, name, args, **_kwargs):
            forwarded.append({"tool": name, "args": args})
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "status": "partial",
                    "reason_codes": ["index_incomplete"],
                    "definitions": [{"path": "demo/symbol.py"}],
                    "references": [],
                },
            )

    monkeypatch.setattr(bridge, "Client", StubClient)
    root = server.create_server()
    app = root.http_app()

    def http_factory(**kwargs):
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

    async def check():
        async with app.router.lifespan_context(app):
            transport = StreamableHttpTransport(
                "http://test/mcp",
                auth="synthetic-main-token",
                httpx_client_factory=http_factory,
            )
            async with Client(
                transport,
                cache=False,
                client_info=mcp.types.Implementation(
                    name="openai-mcp(ChatGPT)", version="1"
                ),
            ) as client:
                tools = await client.list_tools()
                names = [tool.name for tool in tools]
                assert "inspect_symbol" in names
                assert len(names) == 7
                assert "edit_file" not in names
                result = await client.call_tool(
                    "inspect_symbol",
                    {"path": "demo/symbol.py", "line": 7, "symbol_text": "sample"},
                )
                assert not result.is_error
                assert result.structured_content["status"] == "partial"

    asyncio.run(check())
    assert forwarded == [
        {
            "tool": "inspect_symbol",
            "args": {
                "workspace_id": "wsg_private_test",
                "path": "demo/symbol.py",
                "line": 7,
                "column": None,
                "symbol_text": "sample",
                "reference_limit": None,
                "include_hover": False,
            },
        }
    ]

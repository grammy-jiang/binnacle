"""Authenticated, uncached native HTTP identity and visibility contracts."""

import asyncio
import json

import httpx2
import mcp.types
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware

from binnacle import server

PROFILES = [
    (None, "auto", 8),
    ("openai-mcp(ChatGPT)", "auto", 6),
    ("openai-mcp", "legacy", 6),
    ("claude-code", "auto", 8),
]


@pytest.mark.parametrize(("name", "mode", "count"), PROFILES)
def test_authenticated_discovery_bare_followups_and_errors(
    tmp_path, monkeypatch, name, mode, count
):
    token = tmp_path / "token"
    token.write_text("http-test-token")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    root = server.create_server()
    app = root.http_app()
    requests, notifications, rules, sessions, messages = [], [], [], [], []

    class Inspect(Middleware):
        async def on_list_tools(self, context, call_next):
            ctx = context.fastmcp_context
            sessions.append(ctx.session_id)
            messages.append(context.message)
            # SDK characterization only: production must never manage this key.
            rules.append(await ctx.get_state("_visibility_rules"))
            return await call_next(context)

    root.add_middleware(Inspect())

    async def record(request):
        if request.method == "POST":
            requests.append(json.loads(request.content))

    def http_factory(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            event_hooks={"request": [record]},
            **kwargs,
        )

    async def receive(message):
        notifications.append(type(getattr(message, "root", message)).__name__)

    async def go():
        async with app.router.lifespan_context(app):
            transport = StreamableHttpTransport(
                "http://test/mcp",
                auth="http-test-token",
                httpx_client_factory=http_factory,
            )
            kwargs = (
                {}
                if name is None
                else {"client_info": mcp.types.Implementation(name=name, version="1")}
            )
            async with Client(
                transport,
                mode=mode,
                cache=False,
                message_handler=receive,
                **kwargs,
            ) as client:
                if count == 6:
                    # Deny before validation and before the first explicit list.
                    denial = await client.call_tool(
                        "edit_file", {}, raise_on_error=False
                    )
                    assert denial.is_error
                    assert denial.content[0].text == (
                        "Tool 'edit_file' is not available to this client."
                    )
                first = await client.list_tools()
                assert len(first) == count
                for tools in await asyncio.gather(
                    *(client.list_tools() for _ in range(3))
                ):
                    assert tools == first
                result = await client.call_tool("list_files", {"path": str(tmp_path)})
                assert not result.is_error
                error = await client.call_tool("missing", {}, raise_on_error=False)
                assert error.is_error
                assert error.content[0].text == (
                    "Tool 'missing' is not available to this client."
                    if count == 6
                    else "Unknown tool: 'missing'"
                )
                assert client.instructions == root.instructions
        assert rules and all(rule is None for rule in rules)
        assert not any("ListChanged" in event for event in notifications)
        listed = [r for r in requests if r.get("method") == "tools/list"]
        assert len(listed) >= 4  # Uncached server requests, not client cache hits.
        # FastMCP strips the modern wire metadata from listing messages after
        # hydrating the request session. Binnacle sees bare middleware followups.
        assert all(getattr(message, "params", None) is None for message in messages)
        if mode == "legacy":
            init = next(r for r in requests if r.get("method") == "initialize")
            assert init["params"]["clientInfo"]["name"] == name
            assert len(set(sessions)) == 1
        else:
            discover = next(r for r in requests if r.get("method") == "server/discover")
            identity = discover["params"]["_meta"]["io.modelcontextprotocol/clientInfo"]
            if name:
                assert identity["name"] == name
            assert len(set(sessions)) > 1

    asyncio.run(go())


def test_concurrent_http_profiles_share_root_without_policy_leak(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("http-test-token")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    root = server.create_server()
    app = root.http_app()

    def http_factory(**kwargs):
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

    async def profile(name, mode, count):
        transport = StreamableHttpTransport(
            "http://test/mcp", auth="http-test-token", httpx_client_factory=http_factory
        )
        kwargs = (
            {}
            if name is None
            else {"client_info": mcp.types.Implementation(name=name, version="1")}
        )
        async with Client(transport, mode=mode, cache=False, **kwargs) as client:
            for _ in range(3):
                assert len(await client.list_tools()) == count
                assert not (
                    await client.call_tool("list_files", {"path": str(tmp_path)})
                ).is_error

    async def go():
        async with app.router.lifespan_context(app):
            await asyncio.gather(*(profile(*p) for p in PROFILES))

    asyncio.run(go())

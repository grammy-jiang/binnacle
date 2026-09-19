"""Bearer-token auth at the HTTP edge, through the ASGI app.

Roadmap item 3 of 2026-08-31. Everything else in the suite talks to
`server.mcp` in memory and never meets `StaticTokenVerifier`; the tunnel
does, and so does every local agent. httpx2's ASGITransport drives
`server.app` without a socket.

The streamable-HTTP session manager only exists while the app's lifespan
runs (measured 2026-09-13: without it the unauthenticated request still
gets its 401, because auth sits in front, but an authenticated one raises
"task group was not initialized"). Each test therefore opens the lifespan.
"""

import asyncio
import json

import httpx2

from binnacle import server

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "asgi-test", "version": "0"},
    },
}
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def good_token() -> str:
    """The token the app loaded at import: same file, same stripping."""
    return (
        server.TOKEN_FILE.read_text(encoding="utf-8")
        .strip()
        .removeprefix("Bearer ")
        .strip()
    )


def with_app(coro_fn):
    async def go():
        async with server.app.router.lifespan_context(server.app):
            transport = httpx2.ASGITransport(app=server.app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                return await coro_fn(c)

    return asyncio.run(go())


def sse_json(body: str) -> dict:
    """First JSON-RPC message in a text/event-stream body."""
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no data: line in {body[:200]!r}")


def test_initialize_without_a_token_is_401():
    async def go(c):
        return await c.post("/mcp", json=INITIALIZE, headers=HEADERS)

    r = with_app(go)
    assert r.status_code == 401


def test_initialize_with_a_wrong_token_is_401_invalid_token():
    async def go(c):
        return await c.post(
            "/mcp", json=INITIALIZE, headers={**HEADERS, "Authorization": "Bearer nope"}
        )

    r = with_app(go)
    assert r.status_code == 401
    assert r.json().get("error") == "invalid_token"


def test_initialize_with_the_token_file_succeeds_and_tools_list_follows():
    """The tunnel's exact path: the token file's value as the bearer, then a
    second request on the session the server handed back."""

    async def go(c):
        auth = {**HEADERS, "Authorization": f"Bearer {good_token()}"}
        init = await c.post("/mcp", json=INITIALIZE, headers=auth)
        assert init.status_code == 200, init.text[:200]
        msg = sse_json(init.text)
        assert msg["id"] == 1 and "serverInfo" in msg["result"]
        session = init.headers.get("mcp-session-id")
        assert session, "server did not hand back a session id"
        session_headers = {**auth, "mcp-session-id": session}
        await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=session_headers,
        )
        tools = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=session_headers,
        )
        return msg, tools

    msg, tools = with_app(go)
    assert msg["result"]["serverInfo"]["name"] == "binnacle"
    assert tools.status_code == 200, tools.text[:200]
    names = {t["name"] for t in sse_json(tools.text)["result"]["tools"]}
    assert {"read_file", "run_command", "job_status", "stop_job"} <= names


def test_a_token_with_the_bearer_prefix_stripped_twice_still_fails():
    """Only the exact token authenticates; a doubled prefix is not the token."""

    async def go(c):
        return await c.post(
            "/mcp",
            json=INITIALIZE,
            headers={**HEADERS, "Authorization": f"Bearer Bearer {good_token()}"},
        )

    r = with_app(go)
    assert r.status_code == 401

"""Shared authenticated HTTP MCP test helpers."""

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
    return (
        server.TOKEN_FILE.read_text(encoding="utf-8")
        .strip()
        .removeprefix("Bearer ")
        .strip()
    )


def sse_json(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no data: line in {body[:200]!r}")


def with_app(coro_fn):
    async def go():
        async with server.app.router.lifespan_context(server.app):
            transport = httpx2.ASGITransport(app=server.app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await coro_fn(client)

    return asyncio.run(go())


def with_session(coro_fn, *, client_name: str = "asgi-test"):
    async def go():
        async with server.app.router.lifespan_context(server.app):
            transport = httpx2.ASGITransport(app=server.app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                auth = {
                    **HEADERS,
                    "Authorization": f"Bearer {good_token()}",
                }
                init_body = {
                    **INITIALIZE,
                    "params": {
                        **INITIALIZE["params"],
                        "clientInfo": {
                            "name": client_name,
                            "version": "1",
                        },
                    },
                }
                init = await client.post("/mcp", json=init_body, headers=auth)
                assert init.status_code == 200, init.text[:200]
                session = init.headers.get("mcp-session-id")
                assert session
                session_headers = {**auth, "mcp-session-id": session}
                initialized = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                    headers=session_headers,
                )
                assert initialized.status_code == 202
                return await coro_fn(client, session_headers)

    return asyncio.run(go())


async def http_tool_call(
    client,
    headers,
    request_id: int,
    name: str,
    arguments: dict,
):
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text[:300]
    return sse_json(response.text)

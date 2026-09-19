"""Bearer auth and HTTP session lifecycle at the ASGI edge."""

import asyncio

import httpx2

from binnacle import server
from tests.integration.http_test_support import (
    HEADERS,
    INITIALIZE,
    good_token,
    sse_json,
    with_app,
)


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


def test_version_falls_back_when_distribution_metadata_is_missing(monkeypatch):
    monkeypatch.setattr(
        server.importlib.metadata,
        "version",
        lambda name: (_ for _ in ()).throw(
            server.importlib.metadata.PackageNotFoundError(name)
        ),
    )

    assert server._version() == "?"


def test_load_token_rejects_empty_file(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("Bearer   \n")
    monkeypatch.setattr(server, "TOKEN_FILE", token)

    import pytest

    with pytest.raises(RuntimeError, match="is empty"):
        server._load_token()


def test_http_session_id_is_required_and_unknown_session_is_rejected():
    async def go():
        async with server.app.router.lifespan_context(server.app):
            transport = httpx2.ASGITransport(app=server.app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                auth = {
                    **HEADERS,
                    "Authorization": f"Bearer {good_token()}",
                }
                init = await c.post("/mcp", json=INITIALIZE, headers=auth)
                assert init.status_code == 200
                assert init.headers.get("mcp-session-id")

                request = {
                    "jsonrpc": "2.0",
                    "id": 50,
                    "method": "tools/list",
                    "params": {},
                }
                missing = await c.post("/mcp", json=request, headers=auth)
                assert missing.status_code == 400
                assert "Missing session ID" in missing.text

                unknown = await c.post(
                    "/mcp",
                    json=request,
                    headers={**auth, "mcp-session-id": "expired-session"},
                )
                assert unknown.status_code == 404
                assert "Session not found" in unknown.text

    asyncio.run(go())

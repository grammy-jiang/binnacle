"""Root liveness is intentionally unauthenticated and contains no runtime state."""

import asyncio

import httpx2

from binnacle import server
from tests.integration.http_test_support import HEADERS, INITIALIZE


def test_healthz_liveness_does_not_change_mcp_auth(monkeypatch):
    monkeypatch.setattr(server, "_load_token", lambda: "health-test-token")
    root = server.create_server()
    app = root.http_app()

    async def go():
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                health = await client.get("/healthz", headers=headers)
                assert health.status_code == 200
                assert health.headers["content-type"] == "application/json"
                assert health.content == b'{"status":"ok"}'
            assert (await client.post("/healthz")).status_code == 405
            rejected = await client.post("/mcp", json=INITIALIZE, headers=HEADERS)
            assert rejected.status_code == 401
            accepted = await client.post(
                "/mcp",
                json=INITIALIZE,
                headers={**HEADERS, "Authorization": "Bearer health-test-token"},
            )
            assert accepted.status_code == 200
        routes = [r for r in app.routes if getattr(r, "path", None) == "/healthz"]
        assert len(routes) == 1
        assert routes[0].include_in_schema is False
        assert routes[0].methods == {"GET", "HEAD"}  # Starlette adds HEAD for GET.

    asyncio.run(go())

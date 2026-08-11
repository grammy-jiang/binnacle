"""Typed helpers for real in-process Streamable HTTP integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from binnacle.adapters.mcp import RequestBodyLimitMiddleware, create_http_app
from binnacle.application import BinnacleApplication


@asynccontextmanager
async def running_http_client(
    application: BinnacleApplication,
    *,
    mode: str = "2026-07-28",
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Connect the official client to the real ASGI app without a socket."""

    app = create_http_app(application)
    if not isinstance(app, RequestBodyLimitMiddleware):
        raise TypeError("expected bounded MCP ASGI application")

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = False,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    transport = StreamableHttpTransport(
        "http://test/mcp",
        httpx_client_factory=factory,
    )
    inner_app = cast(Any, app.app)
    async with (
        inner_app.router.lifespan_context(inner_app),
        Client(transport, mode=mode) as client,
    ):
        yield client


@asynccontextmanager
async def running_raw_http_client(
    application: BinnacleApplication,
    *,
    max_request_bytes: int = 1_048_576,
) -> AsyncIterator[httpx2.AsyncClient]:
    """Connect a raw HTTP client while managing the FastMCP ASGI lifespan."""

    app = create_http_app(application, max_request_bytes=max_request_bytes)
    if not isinstance(app, RequestBodyLimitMiddleware):
        raise TypeError("expected bounded MCP ASGI application")
    inner_app = cast(Any, app.app)
    async with (
        inner_app.router.lifespan_context(inner_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        yield client

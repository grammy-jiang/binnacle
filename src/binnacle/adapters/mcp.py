"""FastMCP and Uvicorn adaptation for the zero-tool Phase 1 server."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, TypeAlias, cast

import uvicorn
from fastmcp import FastMCP

from binnacle.application import BinnacleApplication

ASGIReceive: TypeAlias = Callable[[], Awaitable[dict[str, Any]]]
ASGISend: TypeAlias = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp: TypeAlias = Callable[
    [dict[str, Any], ASGIReceive, ASGISend],
    Awaitable[None],
]


class ServerConfiguration(Protocol):
    """Read-only server values consumed by the Uvicorn adapter."""

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def workers(self) -> int: ...


def create_mcp_server(application: BinnacleApplication) -> FastMCP[None]:
    """Create a valid MCP server without operational Binnacle capabilities."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP[None]) -> AsyncIterator[None]:
        await application.start()
        try:
            yield
        finally:
            await application.stop()

    return FastMCP[None](
        name="Binnacle",
        version=application.identity.version,
        lifespan=lifespan,
    )


def create_http_app(application: BinnacleApplication) -> ASGIApp:
    """Return FastMCP's native Streamable HTTP ASGI application."""

    return cast(ASGIApp, create_mcp_server(application).http_app())


def run_http_server(
    *,
    application: BinnacleApplication,
    settings: ServerConfiguration,
) -> None:
    """Run one Uvicorn worker for the native FastMCP ASGI application."""

    uvicorn.run(
        create_http_app(application),
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
    )

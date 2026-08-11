"""HTTP surface, readiness lifecycle, and request-bound tests."""

from __future__ import annotations

from typing import Any, cast

import httpx2
import pytest
from tests.support import running_raw_http_client

from binnacle.adapters.mcp import RequestBodyLimitMiddleware, create_http_app
from binnacle.application import BinnacleApplication


@pytest.mark.anyio
async def test_health_is_minimal_200_for_started_process(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.anyio
async def test_ready_is_503_before_application_started(
    phase2_application: BinnacleApplication,
) -> None:
    app = create_http_app(phase2_application)

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reasons": ["application_not_started"],
    }


@pytest.mark.anyio
async def test_ready_is_200_with_exact_five_bindings(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.anyio
async def test_ready_returns_503_after_shutdown(
    phase2_application: BinnacleApplication,
) -> None:
    app = create_http_app(phase2_application)
    assert isinstance(app, RequestBodyLimitMiddleware)
    inner_app = cast(Any, app.app)
    transport = httpx2.ASGITransport(app=app)
    async with (
        inner_app.router.lifespan_context(inner_app),
        httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client,
    ):
        assert (await client.get("/readyz")).status_code == 200

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert phase2_application.is_ready is False


@pytest.mark.anyio
async def test_http_surface_exposes_only_three_reviewed_routes(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        for path in ("/", "/docs", "/openapi.json", "/metrics", "/admin"):
            assert (await client.get(path)).status_code == 404


@pytest.mark.anyio
async def test_oversized_mcp_request_is_rejected_before_parsing(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(
        phase2_application,
        max_request_bytes=65_536,
    ) as client:
        response = await client.post(
            "/mcp",
            content=b"x" * 65_537,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}

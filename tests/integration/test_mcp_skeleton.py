"""Regression tests for the executable MCP server boundary."""

from typing import Any, cast

import pytest
from fastmcp import FastMCP

from binnacle.adapters.mcp import (
    RequestBodyLimitMiddleware,
    create_http_app,
    create_mcp_server,
)
from binnacle.application import BinnacleApplication


def test_create_mcp_server_returns_framework_server(
    phase2_application: BinnacleApplication,
) -> None:
    server = create_mcp_server(phase2_application)

    assert isinstance(server, FastMCP)
    assert server.name == "Binnacle"


def test_http_app_can_be_constructed(
    phase2_application: BinnacleApplication,
) -> None:
    http_app = create_http_app(phase2_application)

    assert callable(http_app)


@pytest.mark.parametrize(
    "session_idle_timeout_seconds",
    [0.0, -1.0, 1_800.001, float("inf"), float("nan")],
)
def test_http_app_rejects_session_idle_timeout_outside_reviewed_range(
    phase2_application: BinnacleApplication,
    session_idle_timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError, match="session_idle_timeout_seconds"):
        create_http_app(
            phase2_application,
            session_idle_timeout_seconds=session_idle_timeout_seconds,
        )


@pytest.mark.parametrize("max_request_bytes", [65_535, 4_194_305])
def test_http_app_rejects_request_bound_outside_reviewed_range(
    phase2_application: BinnacleApplication,
    max_request_bytes: int,
) -> None:
    with pytest.raises(ValueError, match="max_request_bytes"):
        create_http_app(phase2_application, max_request_bytes=max_request_bytes)


@pytest.mark.anyio
async def test_phase2_registers_exact_compatibility_core(
    phase2_application: BinnacleApplication,
) -> None:
    server = create_mcp_server(phase2_application)

    assert [tool.name for tool in await server.list_tools()] == [
        "binnacle_probe",
        "system_inspect",
        "probe_result_formats",
        "probe_error",
        "compatibility_report",
    ]


@pytest.mark.anyio
async def test_http_lifespan_owns_internal_operation_kernel(
    phase2_application: BinnacleApplication,
) -> None:
    class KernelResource:
        closed = False

        async def close(self) -> None:
            self.closed = True

    kernel = KernelResource()
    starts = 0

    async def compose_kernel() -> KernelResource:
        nonlocal starts
        starts += 1
        return kernel

    app = create_http_app(
        phase2_application,
        operation_kernel_factory=compose_kernel,
    )
    assert isinstance(app, RequestBodyLimitMiddleware)
    inner_app = cast(Any, app.app)

    async with inner_app.router.lifespan_context(inner_app):
        assert starts == 1
        assert phase2_application.is_ready
        assert not kernel.closed

    assert kernel.closed


@pytest.mark.anyio
async def test_read_only_http_lifespan_survives_unavailable_internal_kernel(
    phase2_application: BinnacleApplication,
) -> None:
    class KernelResource:
        async def close(self) -> None:
            raise AssertionError("uncomposed kernel must not be closed")

    async def unavailable_kernel() -> KernelResource:
        raise RuntimeError("injected unavailable kernel")

    app = create_http_app(
        phase2_application,
        operation_kernel_factory=unavailable_kernel,
    )
    assert isinstance(app, RequestBodyLimitMiddleware)
    inner_app = cast(Any, app.app)

    async with inner_app.router.lifespan_context(inner_app):
        assert phase2_application.is_ready


def test_http_runner_preserves_configured_logging(
    phase2_application: BinnacleApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        observed["app"] = app
        observed.update(kwargs)

    monkeypatch.setattr("binnacle.adapters.mcp.uvicorn.run", fake_run)

    from binnacle.adapters.mcp import run_http_server
    from binnacle.config import ServerSettings

    run_http_server(
        application=phase2_application,
        settings=ServerSettings(graceful_shutdown_seconds=1.1),
    )

    assert callable(observed["app"])
    assert observed["workers"] == 1
    assert observed["log_config"] is None
    assert observed["timeout_graceful_shutdown"] == 2


def test_http_runner_forwards_session_idle_timeout(
    phase2_application: BinnacleApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_create_http_app(
        application: BinnacleApplication,
        *,
        max_request_bytes: int,
        session_idle_timeout_seconds: float,
        operation_kernel_factory: object,
    ) -> object:
        observed.update(
            application=application,
            max_request_bytes=max_request_bytes,
            session_idle_timeout_seconds=session_idle_timeout_seconds,
            operation_kernel_factory=operation_kernel_factory,
        )
        return object()

    monkeypatch.setattr("binnacle.adapters.mcp.create_http_app", fake_create_http_app)
    monkeypatch.setattr("binnacle.adapters.mcp.uvicorn.run", lambda *args, **kwargs: None)

    from binnacle.adapters.mcp import run_http_server
    from binnacle.config import ServerSettings

    run_http_server(
        application=phase2_application,
        settings=ServerSettings(session_idle_timeout_seconds=42.0),
    )

    assert observed == {
        "application": phase2_application,
        "max_request_bytes": 1_048_576,
        "session_idle_timeout_seconds": 42.0,
        "operation_kernel_factory": None,
    }


def test_http_runner_rejects_multiple_workers(
    phase2_application: BinnacleApplication,
) -> None:
    class MultipleWorkers:
        @property
        def host(self) -> str:
            return "127.0.0.1"

        @property
        def port(self) -> int:
            return 8000

        @property
        def workers(self) -> int:
            return 2

        @property
        def max_request_bytes(self) -> int:
            return 1_048_576

        @property
        def session_idle_timeout_seconds(self) -> float:
            return 300.0

        @property
        def graceful_shutdown_seconds(self) -> float:
            return 10.0

    from binnacle.adapters.mcp import run_http_server

    with pytest.raises(ValueError, match="exactly one worker"):
        run_http_server(
            application=phase2_application,
            settings=MultipleWorkers(),
        )


def test_http_runner_rejects_nonloopback(
    phase2_application: BinnacleApplication,
) -> None:
    from binnacle.adapters.mcp import run_http_server
    from binnacle.config import ServerSettings

    with pytest.raises(ValueError, match="loopback"):
        run_http_server(
            application=phase2_application,
            settings=ServerSettings(host="192.0.2.10"),
        )

"""Integration tests for the zero-capability FastMCP skeleton."""

import pytest
from fastmcp import FastMCP

from binnacle.adapters.mcp import create_http_app, create_mcp_server
from binnacle.application import BinnacleApplication
from binnacle.domain.runtime import PackageIdentity


def _application(identity: PackageIdentity) -> BinnacleApplication:
    return BinnacleApplication(identity=identity)


def test_create_mcp_server_returns_framework_server(
    package_identity: PackageIdentity,
) -> None:
    server = create_mcp_server(_application(package_identity))

    assert isinstance(server, FastMCP)
    assert server.name == "Binnacle"


def test_http_app_can_be_constructed(package_identity: PackageIdentity) -> None:
    http_app = create_http_app(_application(package_identity))

    assert callable(http_app)


@pytest.mark.anyio
async def test_phase1_registers_no_binnacle_operational_tools(
    package_identity: PackageIdentity,
) -> None:
    server = create_mcp_server(_application(package_identity))

    assert await server.list_tools() == []


def test_http_runner_preserves_configured_logging(
    package_identity: PackageIdentity,
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
        application=_application(package_identity),
        settings=ServerSettings(),
    )

    assert callable(observed["app"])
    assert observed["workers"] == 1
    assert observed["log_config"] is None


def test_http_runner_rejects_multiple_workers(
    package_identity: PackageIdentity,
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

    from binnacle.adapters.mcp import run_http_server

    with pytest.raises(ValueError, match="exactly one worker"):
        run_http_server(
            application=_application(package_identity),
            settings=MultipleWorkers(),
        )

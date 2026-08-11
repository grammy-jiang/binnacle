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

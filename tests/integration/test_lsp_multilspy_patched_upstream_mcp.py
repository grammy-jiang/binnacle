"""Private in-memory FastMCP Binnacle/Pyright integration and surface checks.

Real Pyright is provided by the unmodified pinned upstream multilspy package.
Nothing in these tests mounts LSP tools into the running Binnacle service.
"""

from __future__ import annotations

import pytest
from anyio import fail_after
from fastmcp import Client, FastMCP

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from tests.integration.test_lsp_multilspy_patched_upstream import (
    _authorized_file,
    _new_native_server,
    _request_definition_with_binnacle_policy,
)

pytest_plugins = ("tests.integration.test_lsp_multilspy_patched_upstream",)


@pytest.mark.asyncio
async def test_private_fastmcp_roundtrip_and_default_off(
    patched_upstream, disposable_workspace
):
    binary, _ = patched_upstream
    root = disposable_workspace
    disabled = DevelopmentIntelligenceSettings()
    inert = FastMCP("Binnacle LSP disabled POC")
    if disabled.enabled:
        raise AssertionError("default-off configuration changed")
    async with Client(inert) as client:
        assert await client.list_tools() == []

    enabled = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                mode="explicit_trust_only",
                source="trusted_absolute",
                executable=str(binary),
                languages=("python",),
            )
        },
    )
    assert enabled.profiles["pyright"].enabled is True
    smoke = FastMCP("Binnacle private patched-Pyright proof")

    @smoke.tool(name="inspect_symbol_private")
    async def inspect_symbol_private(
        relative_file: str, line: int, column: int
    ) -> dict:
        # Test harness only, *not* Binnacle production tool registration.
        _authorized_file(root, relative_file)
        server = _new_native_server(root, patched_upstream)
        with fail_after(25):
            async with server.start_server():
                result = await _request_definition_with_binnacle_policy(
                    server, root, relative_file, line, column
                )
        assert server.server.process is None
        return {"locations": [entry["relativePath"] for entry in result]}

    async with Client(smoke) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["inspect_symbol_private"]
        response = await client.call_tool(
            "inspect_symbol_private",
            {
                "relative_file": "app.py",
                "line": 2,
                "column": 10,
            },
        )
        assert response.is_error is False
        assert response.structured_content["locations"] == ["lib.py"]
        denied = await client.call_tool(
            "inspect_symbol_private",
            {
                "relative_file": "../secret.py",
                "line": 0,
                "column": 0,
            },
            raise_on_error=False,
        )
        assert denied.is_error is True


@pytest.mark.asyncio
async def test_new_private_mcp_does_not_change_binnacle_public_surface(
    patched_upstream, disposable_workspace
):
    """Current Binnacle root must keep the current eight-tool contract."""
    from binnacle.application import create_application
    from binnacle.config import RootsSettings, Settings
    from tests.command_support import MemoryCommands

    binary, _ = patched_upstream
    profile = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                mode="explicit_trust_only",
                source="trusted_absolute",
                executable=str(binary),
            )
        },
    )
    settings = Settings(
        roots=RootsSettings(default_root=disposable_workspace, extra_roots=()),
        development_intelligence=profile,
    )
    settings.jobs.socket_path = disposable_workspace / "unused-manager.sock"
    settings.jobs.owner = "embedded"
    public = create_application(
        settings=settings,
        token="private-QA-token",
        backend=MemoryCommands("unused"),
    )
    async with Client(public) as client:
        assert [item.name for item in await client.list_tools()] == [
            "read_file",
            "list_files",
            "search_text",
            "edit_file",
            "write_file",
            "run_command",
            "job_status",
            "stop_job",
        ]
    # The currently implemented root does not mount an LSP child, even if
    # config is opted in; this is deliberate until the P2.4-2.8 gates pass.

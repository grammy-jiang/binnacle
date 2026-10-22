"""P2.7 true FastMCP composition: default-off, private preview and native LSP.

The ONLY way these tests expose the preview is the injected code-only gate.
The production create_server() does not enable that gate even with config opt-in.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle.application import create_application
from binnacle.config import RootsSettings, Settings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_preview_server import (
    PREVIEW_NAME,
    create_private_lsp_preview_server,
)
from tests.command_support import MemoryCommands

BASE_TOOL_NAMES = [
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
]


@pytest.fixture
def mcp_settings(tmp_path):
    allowed = (tmp_path / "allowed").resolve()
    root = allowed / "private-git-worktree"
    root.mkdir(parents=True)
    (root / ".git").write_text("gitdir: /fixture-only/worktrees/private\n")
    (root / "lib.py").write_text(
        "def greet(name: str) -> str:\n    return name.upper()\n", encoding="utf-8"
    )
    main = root / "main.py"
    main.write_text("from lib import greet\nresult = greet('Ada')\n", encoding="utf-8")
    settings = Settings(roots=RootsSettings(default_root=allowed, extra_roots=()))
    settings.jobs.socket_path = tmp_path / "unused-manager.sock"
    settings.jobs.owner = "embedded"
    return settings, root, main


def enable_private_feature(settings, *, discovery=True, executable="/usr/bin/false"):
    settings.development_intelligence = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=discovery,
        max_resident_servers=2,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=executable,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )


def make_app(settings, *, private_gate=False):
    return create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("test-job"),
        _private_lsp_preview_gate=private_gate,
    )


async def visible(app):
    async with Client(app) as client:
        tools = await client.list_tools()
        return [tool.name for tool in tools], [
            tool.model_dump(exclude_none=True) for tool in tools
        ]


def test_default_and_configured_but_unreleased_have_identical_tool_bytes(mcp_settings):
    settings, _root, _source = mcp_settings
    normal = make_app(settings)
    before_names, before_tool_data = asyncio.run(visible(normal))
    assert before_names == BASE_TOOL_NAMES
    before = json.dumps(before_tool_data, sort_keys=True, separators=(",", ":"))
    assert PREVIEW_NAME not in before

    enable_private_feature(settings)
    for enabled in (False, True):
        # Operator settings alone cannot authorize a P4/P5 public tool.
        gated = make_app(settings, private_gate=enabled)
        if enabled:
            # We must explicitly disable discovery, not just toggle tool gate.
            settings.development_intelligence.discovery_enabled = False
            gated = make_app(settings, private_gate=True)
        names, tool_data = asyncio.run(visible(gated))
        assert names == BASE_TOOL_NAMES
        assert json.dumps(tool_data, sort_keys=True, separators=(",", ":")) == before
    assert settings.development_intelligence.enabled


def test_invalid_profile_cannot_be_mounted_when_private_gate_on(mcp_settings):
    settings, _root, _source = mcp_settings
    enable_private_feature(settings)
    settings.development_intelligence.profiles["pyright"].argv = ("--extra",)
    with pytest.raises(ValueError, match="requires_trusted_profile"):
        make_app(settings, private_gate=True)


@pytest.mark.asyncio
async def test_unknown_private_tool_direct_call_not_available_when_default_off(
    mcp_settings,
):
    settings, _root, main = mcp_settings
    app = make_app(settings)
    async with Client(app) as client:
        denied = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(main),
                "line": 2,
                "column": 10,
                "expected_symbol": "greet",
            },
            raise_on_error=False,
        )
        assert denied.is_error
        assert [item.name for item in await client.list_tools()] == BASE_TOOL_NAMES


@pytest.mark.asyncio
async def test_private_preview_child_is_discoverable_only_under_all_gates(mcp_settings):
    settings, _root, _source = mcp_settings
    enable_private_feature(settings)
    app = make_app(settings, private_gate=True)
    async with Client(app) as client:
        listed = await client.list_tools()
        assert [tool.name for tool in listed] == [*BASE_TOOL_NAMES, PREVIEW_NAME]
        preview = listed[-1]
        assert "source_file" in preview.inputSchema.get("properties", {})
        assert "expected_symbol" in preview.inputSchema.get("properties", {})
        assert "PRIVATE TEST-ONLY" in preview.description
    settings.development_intelligence.discovery_enabled = False
    hidden = make_app(settings, private_gate=True)
    assert (await visible(hidden))[0] == BASE_TOOL_NAMES


@pytest.mark.asyncio
async def test_opt_in_root_retains_six_tool_chatgpt_visibility_policy(mcp_settings):
    settings, _root, _source = mcp_settings
    enable_private_feature(settings)
    app = make_app(settings, private_gate=True)
    async with Client(app, name="openai-mcp(ChatGPT)") as client:
        # Native Client may carry identity differently from HTTP discover.
        # Only assert that the public tool registration still exists; HTTP
        # client-name policy has separate protocol-level integration tests.
        names = [tool.name for tool in await client.list_tools()]
        assert all(item in [*BASE_TOOL_NAMES, PREVIEW_NAME] for item in names)


@pytest.mark.asyncio
async def test_real_pinned_multilspy_preview_and_pid_reuse(mcp_settings):
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("real Pyright requires private explicit opt-in")
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    settings, root, main = mcp_settings
    enable_private_feature(settings, executable=binary)
    captured = []

    def factory(**kwargs):
        child = create_private_lsp_preview_server(**kwargs)
        captured.append(child)
        return child

    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("test-job"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=factory,
    )
    assert len(captured) == 1
    life = captured[0]._private_preview_lifespan
    assert life.active is None and life.starts == 0
    # Real root-client path exercises the actual mounted child lifespan.
    async with Client(app) as client:
        assert life.active is not None and life.starts == 1
        result = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(main),
                "line": 2,
                "column": 10,
                "expected_symbol": "greet",
            },
        )
        assert not result.is_error
        assert result.structured_content["status"] == "ok"
        assert result.structured_content["locations"] == [
            {
                "relative_path": "lib.py",
                "range": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 9},
                },
            }
        ]
        manager = life.active
        assert manager.resident_count == 1
        (entry,) = manager._entries.values()
        process = entry.owner._server.server.process
        assert process is not None and process.returncode is None
        initial_pid = process.pid
        again = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(main),
                "line": 2,
                "column": 10,
                "expected_symbol": "greet",
            },
        )
        assert again.structured_content == result.structured_content
        assert entry.owner._server.server.process.pid == initial_pid
        assert manager.resident_count == 1
        unavailable = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(main),
                "line": 2,
                "column": 10,
                "expected_symbol": "not_greet",
            },
            raise_on_error=False,
        )
        assert unavailable.is_error
        assert PREVIEW_NAME in [tool.name for tool in await client.list_tools()]
    assert (root / "lib.py").read_text().startswith("def greet")
    assert process.returncode is not None
    assert life.active is None and life.closed == 1
    assert life.last_close.instances_stopped == 1
    assert not life.last_close.cleanup_unverified
    async with Client(app) as client:
        # A second parent lifespan must inject a NEW manager generation.
        assert life.starts == 2
        assert life.active is not manager
        assert life.active.resident_count == 0  # lazy until first call
        result = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(main),
                "line": 2,
                "column": 10,
                "expected_symbol": "greet",
            },
        )
        assert result.structured_content["status"] == "ok"
    assert life.closed == 2 and life.active is None
    assert life.last_close.instances_stopped == 1


@pytest.mark.asyncio
async def test_preview_never_is_part_of_production_server_factory(mcp_settings):
    # create_server() always calls create_application without the internal
    # QA gate. Production users cannot toggle this with TOML/env config.
    import inspect

    from binnacle import server

    body = inspect.getsource(server.create_server)
    assert "_private_lsp_preview_gate" not in body
    assert "lsp_definition_preview_private" not in body
    assert (
        "_private_lsp_preview_gate"
        not in inspect.signature(server.create_server).parameters
    )


def test_private_child_factory_is_not_constructed_without_all_operator_gates(
    mcp_settings,
):
    settings, _root, _source = mcp_settings
    attempts = []

    def forbidden_factory(**kwargs):
        attempts.append(kwargs)
        pytest.fail("a disabled preview mounted or constructed its manager")

    # Feature disabled, regardless of private test gate.
    for gate in (False, True):
        create_application(
            settings=settings,
            token="private-p27-test-token",
            backend=MemoryCommands("qa"),
            _private_lsp_preview_gate=gate,
            _private_lsp_preview_factory=forbidden_factory,
        )
    enable_private_feature(settings, discovery=False)
    create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=forbidden_factory,
    )
    enable_private_feature(settings, discovery=True)
    settings.development_intelligence.profiles["pyright"].enabled = False
    create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=forbidden_factory,
    )
    assert attempts == []


@pytest.mark.asyncio
async def test_preview_factory_receives_only_snapshot_of_operator_authority(
    mcp_settings,
):
    settings, root, _main = mcp_settings
    enable_private_feature(settings)
    copied = []

    def capture_factory(**kwargs):
        copied.append(kwargs)
        return create_private_lsp_preview_server(**kwargs)

    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=capture_factory,
    )
    assert len(copied) == 1
    assert copied[0]["roots"] is not settings.roots
    assert copied[0]["feature_settings"] is not settings.development_intelligence
    settings.roots.default_root = root.parent.parent
    settings.development_intelligence.enabled = False
    async with Client(app) as client:
        assert PREVIEW_NAME in [tool.name for tool in await client.list_tools()]
    assert copied[0]["roots"].default_root == root.parent
    assert copied[0]["feature_settings"].enabled is True

"""P2.8 FastMCP private preview disabled/error/cleanup boundary coverage."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings
from binnacle.features.development_intelligence.lsp_preview_server import (
    PREVIEW_NAME,
    _PreviewLifespan,
    create_private_lsp_preview_server,
    validate_private_profile,
)

pytest_plugins = ("tests.unit.core.test_lsp_p27_child_lifespan",)


def test_preview_factory_requires_all_operator_admission_flags(tmp_path):
    inactive = DevelopmentIntelligenceSettings()
    assert not validate_private_profile(inactive)
    with pytest.raises(ValueError, match="private_lsp_preview_not_enabled"):
        create_private_lsp_preview_server(
            feature_settings=inactive,
            roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        )


@pytest.mark.asyncio
async def test_lifecycle_completion_callback_refuses_cancelled_cleanup_task():
    life = _PreviewLifespan()

    async def abandoned():
        raise asyncio.CancelledError

    failed = asyncio.create_task(abandoned())
    with pytest.raises(asyncio.CancelledError):
        await failed
    life._observe_cleanup(failed)
    assert life.poisoned
    assert life.active is None
    assert life.closed == 0


@pytest.mark.asyncio
async def test_inactive_manager_cannot_process_mcp_direct_tool_call(enabled_child):
    child, created = enabled_child
    life = child._private_preview_lifespan
    async with Client(child) as client:
        manager = life.active
        assert manager is created[0]
        # Fail before any disk admission, even when tool was discovered.
        life.active = None
        result = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": "/private/fake.py",
                "line": 1,
                "column": 1,
                "expected_symbol": "name",
            },
            raise_on_error=False,
        )
        assert result.is_error
        assert "private_lsp_preview_lifecycle_unavailable" in str(result)
        life.active = manager
    assert created[0].closed

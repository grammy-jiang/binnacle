"""Implementation gate for binnacle/visibility.py (per-client tool hiding)."""

import asyncio

import mcp.types
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from binnacle import server
from binnacle.identity import ClientIdentity
from binnacle.visibility import ClientToolVisibility

FULL = {
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
}
HIDDEN = {"edit_file", "write_file"}


def tool_names(client_info=None, mode=None) -> set:
    async def run():
        kwargs = {}
        if client_info:
            kwargs["client_info"] = mcp.types.Implementation(
                name=client_info, version="1"
            )
        if mode:
            kwargs["mode"] = mode
        async with Client(server.mcp, **kwargs) as c:
            return {t.name for t in await c.list_tools()}

    return asyncio.run(run())


def test_default_client_sees_all_eight():
    assert tool_names() == FULL


def test_chatgpt_modern_identity_sees_six():
    assert tool_names("openai-mcp(ChatGPT)") == FULL - HIDDEN


def test_chatgpt_legacy_identity_sees_six():
    assert tool_names("openai-mcp", mode="legacy") == FULL - HIDDEN


def test_other_client_unaffected():
    assert tool_names("claude-code") == FULL


def test_hidden_tool_call_is_refused():
    async def run():
        info = mcp.types.Implementation(name="openai-mcp(ChatGPT)", version="1")
        async with Client(server.mcp, client_info=info) as c:
            with pytest.raises(ToolError, match="not available"):
                await c.call_tool(
                    "edit_file",
                    {"path": "/tmp/x", "old_string": "a", "new_string": "b"},
                )
            # The visible surface still works for the same session.
            result = await c.call_tool("list_files", {"path": "/tmp"})
            assert result.structured_content is not None

    asyncio.run(run())


def test_prefix_matching_helper():
    vis = ClientToolVisibility({"openai-mcp": ("read_file",)}, ClientIdentity())
    assert vis._enabled_for("openai-mcp") == {"read_file"}
    assert vis._enabled_for("openai-mcp(ChatGPT)") == {"read_file"}
    assert vis._enabled_for("claude-code") is None  # unrestricted
    assert vis._enabled_for(None) is None

"""Fresh-root parity and native composition ownership contracts."""

import asyncio
import hashlib

import mcp.types
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from binnacle import server
from binnacle.tool_order import PublicToolOrder
from tests.contracts.surface_support import digest, served, surface
from tests.contracts.test_input_validation import text_of
from tests.contracts.test_tool_surface import INSTRUCTIONS_SHA256, SURFACE_SHA256

PROFILES = [
    (None, None, "default"),
    ("openai-mcp(ChatGPT)", None, "chatgpt"),
    ("openai-mcp", "legacy", "chatgpt"),
    ("claude-code", None, "default"),
]


@pytest.mark.parametrize(("name", "mode", "profile"), PROFILES)
def test_fresh_root_matches_pins_and_exported_wire_surface(name, mode, profile):
    tools, instructions = served(name, mode, mcp_server=server.create_server())
    expected, exported_instructions = served(name, mode)
    assert [tool.name for tool in tools] == list(SURFACE_SHA256[profile])
    assert {tool.name: digest(surface(tool)) for tool in tools} == SURFACE_SHA256[
        profile
    ]
    assert instructions is not None
    assert hashlib.sha256(instructions.encode()).hexdigest() == INSTRUCTIONS_SHA256
    assert instructions == exported_instructions
    assert [tool.model_dump(mode="json", by_alias=True) for tool in tools] == [
        tool.model_dump(mode="json", by_alias=True) for tool in expected
    ]


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        ("read_file", {}, "path"),
        ("read_file", {"path": "/tmp/unused", "unexpected": True}, "unexpected"),
        ("list_files", {"max_results": "many"}, "max_results"),
        ("search_text", {"pattern": "x", "max_results": 0}, "max_results"),
        ("run_command", {"command": "true", "wait_seconds": 51}, "wait_seconds"),
        ("job_status", {"cursor": "start"}, "cursor requires job_id"),
    ],
)
def test_fresh_root_validation_parity(tool, arguments, field):
    async def call(root):
        async with Client(root) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    fresh = asyncio.run(call(server.create_server()))
    exported = asyncio.run(call(server.mcp))
    assert fresh.is_error and exported.is_error
    assert field in text_of(fresh)
    assert fresh.content == exported.content


@pytest.mark.parametrize("mode", ["2026-07-28", "legacy"])
def test_two_roots_and_clients_keep_visibility_isolated(mode, tmp_path):
    async def go():
        chatgpt = Client(
            server.create_server(),
            mode=mode,
            client_info=mcp.types.Implementation(
                name="openai-mcp(ChatGPT)", version="1"
            ),
        )
        other = Client(
            server.create_server(),
            mode=mode,
            client_info=mcp.types.Implementation(name="claude-code", version="1"),
        )
        async with chatgpt, other:
            hidden, visible = await asyncio.gather(
                chatgpt.list_tools(), other.list_tools()
            )
            assert [tool.name for tool in hidden] == list(SURFACE_SHA256["chatgpt"])
            assert [tool.name for tool in visible] == list(SURFACE_SHA256["default"])
            for tool, arguments in (
                ("write_file", {"path": str(tmp_path / "hidden"), "content": "x"}),
                (
                    "edit_file",
                    {
                        "path": str(tmp_path / "hidden"),
                        "old_string": "a",
                        "new_string": "b",
                    },
                ),
            ):
                with pytest.raises(ToolError, match="not available"):
                    await chatgpt.call_tool(tool, arguments)
            assert not (tmp_path / "hidden").exists()
            result = await other.call_tool("list_files", {"path": str(tmp_path)})
            assert not result.is_error
            assert [tool.name for tool in await chatgpt.list_tools()] == list(
                SURFACE_SHA256["chatgpt"]
            )

    asyncio.run(go())


@pytest.mark.parametrize("migrated", [0, 1, 2, 3])
def test_native_order_transform_covers_each_partial_mount_layout(migrated):
    groups = [
        ["read_file", "list_files", "edit_file", "write_file"],
        ["search_text"],
        ["run_command", "job_status", "stop_job"],
    ]
    root = FastMCP("synthetic root")
    mounted_names = {name for group in groups[:migrated] for name in group}
    for name in SURFACE_SHA256["default"]:
        if name not in mounted_names:
            root.tool(lambda: None, name=name)
    for group in groups[:migrated]:
        child = FastMCP("synthetic child")
        for name in group:
            child.tool(lambda: None, name=name)
        root.mount(child)
    before, _ = served(mcp_server=root)
    expected = list(SURFACE_SHA256["default"])
    if migrated:
        assert [tool.name for tool in before] != expected
    root.add_transform(PublicToolOrder())
    after, _ = served(mcp_server=root)
    assert [tool.name for tool in after] == expected
    assert {tool.name: tool for tool in before} == {tool.name: tool for tool in after}

"""Native Commands registration captures one explicit backend per child."""

import asyncio

from fastmcp import Client
from fastmcp.tools.base import ToolResult

from binnacle import commands_server
from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.tools import run_command
from tests.command_support import MemoryCommands


def child(tmp_path, backend, cap=2):
    return commands_server.create_commands_server(
        backend=backend,
        roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        run_settings=RunCommandSettings(wait_default_s=cap, wait_max_s=cap),
        quiet_after_s=1,
        listing_history_limit=2,
        listing_command_preview_chars=20,
    )


def test_fake_run_factories_are_isolated_and_do_not_choose_defaults(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("default selection reached")

    for module in (commands_server, run_command):
        monkeypatch.setattr(module, "get_settings", forbidden)
        monkeypatch.setattr(module, "create_command_backend", forbidden)
    backends = [MemoryCommands("first"), MemoryCommands("second")]
    children = [
        child(tmp_path, backend, cap)
        for backend, cap in zip(backends, (2, 4), strict=True)
    ]

    async def go():
        for mcp, backend, cap in zip(children, backends, (2, 4), strict=True):
            async with Client(mcp, cache=False) as client:
                tools = await client.list_tools()
                assert all(
                    "backend" not in tool.input_schema["properties"] for tool in tools
                )
                result = await client.call_tool(
                    "run_command", {"command": "probe", "workdir": "."}
                )
                assert result.structured_content["job_id"] == backend.job_id
                assert backend.calls[0] == ("start", ("probe", tmp_path, None, cap))

    asyncio.run(go())
    assert all(len(backend.calls) == 3 for backend in backends)


def test_run_registration_resolves_implementation_at_call_time(tmp_path, monkeypatch):
    backend = MemoryCommands()
    mcp = child(tmp_path, backend)
    calls = []

    def replacement(*args, **kwargs):
        calls.append((args, kwargs))
        return ToolResult(
            content="replacement",
            structured_content={"job_id": "late", "state": "running"},
        )

    monkeypatch.setattr(run_command, "run_command_impl", replacement)

    async def go():
        async with Client(mcp, cache=False) as client:
            reply = await client.call_tool("run_command", {"command": "probe"})
            assert reply.content[0].text == "replacement"

    asyncio.run(go())
    assert calls[0][1]["backend"] is backend
    assert backend.calls == []

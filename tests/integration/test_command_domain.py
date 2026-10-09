"""Native Commands registration captures one explicit backend per child."""

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools.base import ToolResult

from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.features.commands import commands_server
from binnacle.features.commands.tools import job_status, run_command, stop_job
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

    for module in (commands_server, run_command, job_status):
        monkeypatch.setattr(module, "get_settings", forbidden)
    for module in (commands_server, run_command, job_status, stop_job):
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
                status = await client.call_tool(
                    "job_status", {"job_id": backend.job_id, "cursor": "end"}
                )
                assert (
                    status.structured_content["next_cursor"] == f"v1:{backend.job_id}:6"
                )
                assert status.structured_content["log_delta"] == ""
                stopped = await client.call_tool("stop_job", {"job_id": backend.job_id})
                repeated = await client.call_tool(
                    "stop_job", {"job_id": backend.job_id}
                )
                assert (
                    stopped.structured_content
                    == repeated.structured_content
                    == {
                        "job_id": backend.job_id,
                        "state": "exited",
                        "exit_code": None,
                        "signal": 15,
                    }
                )

    asyncio.run(go())
    assert all(len(backend.calls) == 8 for backend in backends)


@pytest.mark.parametrize(
    "module,tool,arguments",
    [
        (run_command, "run_command", {"command": "probe"}),
        (job_status, "job_status", {"job_id": "late"}),
        (stop_job, "stop_job", {"job_id": "late"}),
    ],
)
def test_registration_resolves_implementation_at_call_time(
    tmp_path, monkeypatch, module, tool, arguments
):
    backend = MemoryCommands()
    mcp = child(tmp_path, backend)
    calls = []

    def replacement(*args, **kwargs):
        calls.append((args, kwargs))
        return ToolResult(
            content="replacement",
            structured_content={"job_id": "late", "state": "running"},
        )

    monkeypatch.setattr(module, tool + "_impl", replacement)

    async def go():
        async with Client(mcp, cache=False) as client:
            reply = await client.call_tool(tool, arguments)
            assert reply.content[0].text == "replacement"

    asyncio.run(go())
    assert calls[0][1]["backend"] is backend
    assert backend.calls == []


@pytest.mark.parametrize("missing", ["both", "roots", "settings"])
def test_direct_run_registration_defaults_precedence_and_snapshot(
    tmp_path, monkeypatch, missing
):
    """The compatibility registration path selects defaults once, before calls."""
    configured, supplied = tmp_path / "configured", tmp_path / "supplied"
    configured.mkdir()
    supplied.mkdir()
    defaults = SimpleNamespace(
        roots=RootsSettings(default_root=configured, extra_roots=()),
        run_command=RunCommandSettings(wait_default_s=2, wait_max_s=2),
    )
    roots = RootsSettings(default_root=supplied, extra_roots=())
    settings = RunCommandSettings(wait_default_s=4, wait_max_s=4)
    backend = MemoryCommands()
    selections = []
    monkeypatch.setattr(run_command, "get_settings", lambda: defaults)
    monkeypatch.setattr(
        run_command,
        "create_command_backend",
        lambda: selections.append(backend) or backend,
    )
    mcp = FastMCP("direct-run-compatibility")
    run_command.register(
        mcp,
        roots=roots if missing == "settings" else None,
        settings=settings if missing == "roots" else None,
    )
    expected_root = supplied if missing == "settings" else configured
    expected_wait = 4 if missing == "roots" else 2
    defaults.roots.default_root = roots.default_root = tmp_path / "mutated"
    defaults.run_command.wait_max_s = settings.wait_max_s = 99

    def forbidden():
        raise AssertionError("registration defaults must already be captured")

    monkeypatch.setattr(run_command, "get_settings", forbidden)
    monkeypatch.setattr(run_command, "create_command_backend", forbidden)

    async def go():
        async with Client(mcp, cache=False) as client:
            tool = (await client.list_tools())[0]
            wait = tool.input_schema["properties"]["wait_seconds"]
            assert wait["default"] == wait["maximum"] == expected_wait
            await client.call_tool("run_command", {"command": "probe", "workdir": "."})

    asyncio.run(go())
    assert selections == [backend]
    assert backend.calls[0] == ("start", ("probe", expected_root, None, expected_wait))

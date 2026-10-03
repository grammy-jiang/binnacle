"""Commands adapter policy is isolated; the job backend remains process-owned."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.tools.base import ToolResult

from binnacle import command_status, commands_server, job_owner, jobs, paths
from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.tools import job_status, run_command


def fail_global():
    raise AssertionError("explicit Commands policy must not read global settings")


@pytest.fixture
def backend(monkeypatch):
    calls = []

    def start(command, workdir, stdin, wait):
        calls.append((command, workdir, stdin, wait))
        return "synthetic-job"

    monkeypatch.setattr(job_owner, "start_and_wait", start)
    monkeypatch.setattr(jobs, "job_state", lambda job_id: None)
    monkeypatch.setattr(jobs, "read_log", lambda job_id: b"")
    return calls


def test_run_policy_roots_wait_schema_and_caller_mutation(
    tmp_path, monkeypatch, backend
):
    children = []
    for cap in (2, 4):
        roots = RootsSettings(default_root=tmp_path, extra_roots=())
        settings = RunCommandSettings(
            wait_default_s=cap, wait_max_s=cap, auto_background_patterns={}
        )
        children.append(
            commands_server.create_commands_server(roots=roots, run_settings=settings)
        )
        settings.wait_default_s = settings.wait_max_s = 99
        settings.auto_background_patterns["mcp"] = (".*",)
        roots.default_root = tmp_path / "changed"
    for module in (commands_server, run_command, paths):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        for child, cap in zip(children, (2, 4), strict=True):
            async with Client(child, cache=False) as client:
                tools = {t.name: t for t in await client.list_tools()}
                parameter = tools["run_command"].input_schema["properties"][
                    "wait_seconds"
                ]
                assert parameter["default"] == parameter["maximum"] == cap
                assert (
                    tools["run_command"].input_schema["properties"]["workdir"][
                        "default"
                    ]
                    == "~/Projects"
                )
                before = len(backend)
                omitted = await client.call_tool(
                    "run_command", {"command": "probe"}, raise_on_error=False
                )
                assert (
                    omitted.is_error
                    and "outside allowed roots" in omitted.content[0].text
                )
                assert len(backend) == before
                for path in (".", str(tmp_path)):
                    result = await client.call_tool(
                        "run_command", {"command": "probe", "workdir": path}
                    )
                    assert not result.is_error
                    assert backend[-1] == ("probe", tmp_path, None, cap)
                excessive = await client.call_tool(
                    "run_command",
                    {"command": "probe", "workdir": ".", "wait_seconds": cap + 1},
                    raise_on_error=False,
                )
                assert excessive.is_error
        assert len(backend) == 4

    asyncio.run(go())


def test_status_looks_up_implementation_after_construction(tmp_path, monkeypatch):
    def old_impl(*args, **kwargs):
        raise AssertionError("registration must not freeze the implementation")

    monkeypatch.setattr(job_status, "job_status_impl", old_impl)
    child = commands_server.create_commands_server(
        roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        run_settings=RunCommandSettings(wait_default_s=2, wait_max_s=4),
        quiet_after_s=7,
        listing_history_limit=3,
        listing_command_preview_chars=16,
    )
    calls = []

    def replacement(*args, **kwargs):
        calls.append((args, kwargs))
        return ToolResult(content="replacement", structured_content={"jobs": []})

    monkeypatch.setattr(job_status, "job_status_impl", replacement)
    monkeypatch.setattr(job_status, "get_settings", fail_global)

    async def go():
        async with Client(child, cache=False) as client:
            result = await client.call_tool(
                "job_status",
                {
                    "job_id": "probe",
                    "tail_lines": 12,
                    "wait_seconds": 1,
                    "cursor": "start",
                },
            )
            assert result.content[0].text == "replacement"

    asyncio.run(go())
    backend = calls[0][1]["backend"]
    assert calls == [
        (
            ("probe", 12, 1),
            {
                "cursor": "start",
                "backend": backend,
                "quiet_after_s": 7,
                "history_limit": 3,
                "preview_chars": 16,
                "wait_max": 4,
            },
        )
    ]


def test_explicit_run_policy_keeps_process_warmup_and_owner(
    tmp_path, monkeypatch, backend
):
    from binnacle.callctx import current_client

    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    settings = RunCommandSettings(
        auto_background_patterns={"restricted": ("probe",)}, wait_max_s=3
    )
    monkeypatch.setattr(run_command, "get_settings", fail_global)
    monkeypatch.setattr(paths, "get_settings", fail_global)
    monkeypatch.setattr(jobs, "WARMUP_S", 0.125)
    token = current_client.set("restricted")
    try:
        result = run_command.run_command_impl(
            "probe", ".", 500, False, None, roots=roots, settings=settings
        )
        assert result.structured_content["background_job"]
        assert backend[-1][-1] == 0.125
    finally:
        current_client.reset(token)
    run_command.run_command_impl(
        "probe", ".", 500, False, None, roots=roots, settings=settings
    )
    assert backend[-1][-1] == 3


def test_status_factories_own_presentation_and_share_run_wait_cap(
    tmp_path, monkeypatch
):
    command = "HEAD-" + "x" * 80 + "-TAIL"
    state = {
        "job_id": "shared",
        "state": "running",
        "exit_code": None,
        "signal": None,
        "command": command,
        "workdir": str(tmp_path),
        "pid": 123,
        "pgid": 123,
        "started_at": 1.0,
        "ended_at": None,
        "runtime_s": 10.0,
        "last_output_age_s": 1.0,
        "log_bytes": 0,
        "log_path": str(tmp_path / "fake-log"),
    }
    states = [state, {**state, "job_id": "finished", "state": "exited", "exit_code": 0}]
    monkeypatch.setattr(jobs, "list_jobs", lambda: states)
    monkeypatch.setattr(jobs, "job_state", lambda job_id: state)
    monkeypatch.setattr(jobs, "read_log", lambda job_id: b"")
    monkeypatch.setattr(jobs, "job_processes", lambda pgid, max_cmd_chars=200: [])
    for module in (commands_server, run_command, job_status, paths):
        monkeypatch.setattr(module, "get_settings", fail_global)
    children = []
    for cap, quiet, history, preview in [(2, 0, 0, 8), (4, 100, 1, 16)]:
        children.append(
            commands_server.create_commands_server(
                roots=RootsSettings(default_root=tmp_path, extra_roots=()),
                run_settings=RunCommandSettings(wait_default_s=cap, wait_max_s=cap),
                quiet_after_s=quiet,
                listing_history_limit=history,
                listing_command_preview_chars=preview,
            )
        )

    async def go():
        for index, (child, cap, preview) in enumerate(
            zip(children, (2, 4), (8, 16), strict=True)
        ):
            async with Client(child, cache=False) as client:
                tools = {tool.name: tool for tool in await client.list_tools()}
                assert (
                    tools["job_status"].input_schema["properties"]["wait_seconds"][
                        "maximum"
                    ]
                    == cap
                )
                assert (
                    tools["run_command"].input_schema["properties"]["wait_seconds"][
                        "maximum"
                    ]
                    == cap
                )
                listing = (await client.call_tool("job_status", {})).structured_content[
                    "jobs"
                ]
                assert len(listing) == index + 1
                assert listing[0]["command"] == command_status._command_preview(
                    command, preview
                )
                single = (
                    await client.call_tool("job_status", {"job_id": "shared"})
                ).structured_content
                assert single["quiet"] is (index == 0)
                assert single["command"] == listing[0]["command"]
                invalid = await client.call_tool(
                    "job_status",
                    {"job_id": "shared", "wait_seconds": cap + 1},
                    raise_on_error=False,
                )
                assert invalid.is_error

    asyncio.run(go())

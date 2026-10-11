"""Linux-runnable coverage for the R4 Darwin branches of run_command and server."""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.features.commands.command_backend import (
    DarwinManagerCommandBackend,
    ManagerBindings,
)
from binnacle.features.commands.command_contracts import (
    CommandReply,
    RestrictedCommandBackend,
)
from binnacle.features.commands.tools import run_command as rc

AVAILABLE = {
    "run_command": "AVAILABLE",
    "job_status": "AVAILABLE",
    "stop_job": "AVAILABLE",
}


def manager_backend(tmp_path: Path) -> DarwinManagerCommandBackend:
    bindings = ManagerBindings(
        store=None,
        call_id=lambda: "c",
        check_partial=lambda meta: None,
        owner_lost_refusal="lost",
        unavailable="job manager unavailable",
    )
    return DarwinManagerCommandBackend(
        jobs_dir=tmp_path,
        socket_path=tmp_path / "s.sock",
        release_states=AVAILABLE,
        warmup_s=0.0,
        max_output_chars=100,
        client=None,
        bindings=bindings,
    )


def test_manager_backend_routine_reply_equals_linux_text(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, resolved, *args, backend, settings):
        seen.update(command=command, resolved=resolved, backend=backend)
        return CommandReply("Exited 0.", {"job_id": "j1", "state": "exited"})

    monkeypatch.setattr(rc.command_execution, "run_command", fake_run)
    backend = manager_backend(tmp_path)
    result = rc.run_command_impl(
        "true",
        str(tmp_path),
        1,
        False,
        None,
        roots=RootsSettings(default_root=tmp_path, allowed=[tmp_path]),
        settings=RunCommandSettings(),
        backend=backend,
    )
    assert seen["backend"] is backend and seen["resolved"] == tmp_path
    assert result.structured_content == {"job_id": "j1", "state": "exited"}
    # SD-50: routine run_command text equals Linux exactly; SD-52: the
    # descendants_unverified disclosure lives in the Darwin manager instruction
    # sentence (lane L1b), not in routine replies.
    assert result.content[0].text == "Exited 0."


@pytest.mark.parametrize(
    "states,lead",
    [
        ({"run_command": "LIMITED"}, "Foreground only on macOS"),
        ({}, "Foreground execution is unavailable on macOS."),
    ],
)
def test_restricted_registration_advertises_foreground_limits(tmp_path, states, lead):
    mcp = FastMCP("probe")
    rc.register(
        mcp,
        roots=RootsSettings(default_root=tmp_path, allowed=[tmp_path]),
        settings=RunCommandSettings(),
        backend=RestrictedCommandBackend(release_states=states),
    )

    async def tool():
        async with Client(mcp) as client:
            return {t.name: t for t in await client.list_tools()}["run_command"]

    described = asyncio.run(tool())
    assert described.description.startswith(lead)
    props = described.input_schema["properties"]
    assert "terminated" in props["wait_seconds"]["description"]
    assert "darwin_background_jobs_unavailable" in props["background"]["description"]


def test_registration_uses_settings_defaults(monkeypatch, tmp_path):
    defaults = SimpleNamespace(
        roots=RootsSettings(default_root=tmp_path, allowed=[tmp_path]),
        run_command=RunCommandSettings(),
    )
    monkeypatch.setattr(rc, "get_settings", lambda: defaults)
    mcp = FastMCP("probe")
    rc.register(mcp, backend=manager_backend(tmp_path))

    async def names():
        async with Client(mcp) as client:
            return [t.name for t in await client.list_tools()]

    assert asyncio.run(names()) == ["run_command"]


@pytest.fixture
def server_module():
    from binnacle import server

    return server


@pytest.mark.parametrize(
    "configured,effective",
    [("auto", "manager"), ("manager", "manager"), ("embedded", "embedded")],
)
def test_darwin_jobs_config_logs_owner(
    server_module, monkeypatch, caplog, configured, effective
):
    from binnacle.platform import composition

    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    settings = SimpleNamespace(jobs=SimpleNamespace(owner=configured, socket_path=None))
    with caplog.at_level(logging.INFO, logger="binnacle.server"):
        server_module._log_jobs_config(settings)
    lines = [r.getMessage() for r in caplog.records]
    assert [line.split()[1] for line in lines[:3]] == [
        "tool=run_command",
        "tool=job_status",
        "tool=stop_job",
    ]
    owner_line = lines[3]
    assert f"configured_owner={configured}" in owner_line
    assert f"effective_owner={effective}" in owner_line
    if effective == "manager":
        assert "socket=runtime-default" in owner_line
        assert "service=com.binnacle.jobs" in owner_line


def test_darwin_create_server_composes_native_tools(server_module, monkeypatch):
    from binnacle import application
    from binnacle.platform import composition

    sentinel_access, sentinel_backend = object(), object()
    captured = {}
    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    monkeypatch.setattr(
        application,
        "compose_native_tools",
        lambda *, settings: (sentinel_access, sentinel_backend),
    )

    def fake_create_application(**kwargs):
        captured.update(kwargs)
        return "root"

    monkeypatch.setattr(application, "create_application", fake_create_application)
    assert server_module.create_server() == "root"
    assert captured["file_access"] is sentinel_access
    assert captured["backend"] is sentinel_backend


def native_call(tmp_path, backend, workdir=None, background=False):
    return asyncio.run(
        rc.run_native_command_impl(
            "echo hi",
            str(workdir or tmp_path),
            2,
            background,
            None,
            None,
            roots=RootsSettings(default_root=tmp_path, allowed=[tmp_path]),
            settings=RunCommandSettings(),
            backend=backend,
        )
    )


@pytest.mark.parametrize(
    "states,provider,background,message",
    [
        ({}, object(), False, "native_capability_unavailable"),
        ({"run_command": "LIMITED"}, None, False, "foreground provider missing"),
        (
            {"run_command": "LIMITED"},
            object(),
            True,
            "darwin_background_jobs_unavailable",
        ),
    ],
)
def test_native_refusals(tmp_path, states, provider, background, message):
    backend = RestrictedCommandBackend(
        foreground_execution=provider, release_states=states
    )
    with pytest.raises(rc.ToolError, match=message):
        native_call(tmp_path, backend, background=background)


def test_native_foreground_paths(tmp_path, monkeypatch):
    backend = RestrictedCommandBackend(
        foreground_execution=object(), release_states={"run_command": "LIMITED"}
    )
    (tmp_path / "file").write_text("x")
    with pytest.raises(rc.ToolError, match="workdir_not_directory"):
        native_call(tmp_path, backend, workdir=tmp_path / "file")

    outcome = SimpleNamespace(exit_code=None, signal=None)
    requests = []

    async def fake_run(provider, request):
        requests.append(request)
        return outcome

    monkeypatch.setattr(rc.command_execution, "run_foreground_async", fake_run)
    with pytest.raises(rc.ToolError, match="darwin_foreground_completion_unknown"):
        native_call(tmp_path, backend)
    assert requests[0].workdir == tmp_path and requests[0].command == "echo hi"

    outcome.exit_code = 0
    monkeypatch.setattr(
        rc.command_execution,
        "foreground_reply",
        lambda result, *, max_output_chars, tail_lines: CommandReply(
            "Exited 0.", {"job_id": "f1", "state": "exited"}
        ),
    )
    result = native_call(tmp_path, backend)
    assert result.structured_content == {"job_id": "f1", "state": "exited"}


def test_impl_refusal_failure_and_default_settings(tmp_path, monkeypatch):
    roots = RootsSettings(default_root=tmp_path, allowed=[tmp_path])
    with pytest.raises(rc.ToolError, match="native_capability_unavailable"):
        rc.run_command_impl(
            "true",
            str(tmp_path),
            1,
            False,
            None,
            roots=roots,
            backend=RestrictedCommandBackend(),
        )

    cause = OSError("spawn")

    def failing_run(*args, **kwargs):
        raise rc.CommandFailure("job manager unavailable") from cause

    monkeypatch.setattr(rc.command_execution, "run_command", failing_run)
    monkeypatch.setattr(
        rc, "get_settings", lambda: SimpleNamespace(run_command=RunCommandSettings())
    )
    with pytest.raises(rc.ToolError, match="job manager unavailable") as caught:
        rc.run_command_impl(
            "true",
            str(tmp_path),
            1,
            False,
            None,
            roots=roots,
            backend=manager_backend(tmp_path),
        )
    assert caught.value.__cause__ is cause


@pytest.mark.parametrize("restricted", [False, True])
def test_registered_tool_calls_reach_the_impl(tmp_path, monkeypatch, restricted):
    roots = RootsSettings(default_root=tmp_path, allowed=[tmp_path])
    reply = CommandReply("done", {"job_id": "x", "state": "exited"})
    if restricted:
        backend = RestrictedCommandBackend(
            foreground_execution=object(), release_states={"run_command": "LIMITED"}
        )

        async def fake_run(provider, request):
            return SimpleNamespace(exit_code=0, signal=None)

        monkeypatch.setattr(rc.command_execution, "run_foreground_async", fake_run)
        monkeypatch.setattr(
            rc.command_execution, "foreground_reply", lambda *a, **k: reply
        )
    else:
        backend = manager_backend(tmp_path)
        monkeypatch.setattr(rc.command_execution, "run_command", lambda *a, **k: reply)
    mcp = FastMCP("probe")
    rc.register(mcp, roots=roots, settings=RunCommandSettings(), backend=backend)

    async def call():
        async with Client(mcp) as client:
            return await client.call_tool(
                "run_command", {"command": "true", "workdir": str(tmp_path)}
            )

    result = asyncio.run(call())
    assert result.structured_content == {"job_id": "x", "state": "exited"}

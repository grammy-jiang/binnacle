"""Run the real server entry decision in an isolated module object.

No live listeners or job managers: the module is imported with its in-memory
FastMCP factory, but not as main. The delayed lifespan uses a fake inner context.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import runpy
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from binnacle import server


def _test_only_server_import(monkeypatch, *, argv0: str):
    path = Path(server.__file__)
    name = "binnacle._r6w3_server_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    instance = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, instance)
    monkeypatch.setattr(sys, "argv", [argv0, "binnacle.server:app"])
    spec.loader.exec_module(instance)
    return instance


def test_uvicorn_entry_import_wraps_only_its_own_lifespan(monkeypatch):
    instance = _test_only_server_import(monkeypatch, argv0="/venv/bin/uvicorn")
    assert instance is not server
    assert instance._argv_serving_process()
    assert instance.app.router.lifespan_context is instance._lifespan
    observed = []

    @asynccontextmanager
    async def owned_lifespan(_app):
        observed.append("entered")
        yield {"owner": "fixture"}
        observed.append("exited")

    instance._inner_lifespan = owned_lifespan

    def later(delay, callback):
        observed.append(("scheduled", delay, callback))
        return SimpleNamespace(cancel=lambda: None)

    instance.asyncio = SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(call_later=later)
    )
    instance.START_CONFIRM_S = 0.05
    instance._clear_record_after_start = lambda: observed.append("cleared")

    async def probe():
        async with instance.app.router.lifespan_context(instance.app) as state:
            assert state == {"owner": "fixture"}
            observed.append("serving")

    asyncio.run(probe())
    assert observed[0] == "entered"
    assert observed[1][:2] == ("scheduled", 0.05)
    assert observed[1][2] is instance._clear_record_after_start
    assert observed[2:] == ["serving", "exited"]
    observed[1][2]()
    assert observed[-1] == "cleared"


def test_unmarked_library_import_does_not_wrap_lifespan(monkeypatch):
    instance = _test_only_server_import(monkeypatch, argv0="/venv/bin/binnacle")
    assert not instance._argv_serving_process()
    assert "_lifespan" not in vars(instance)
    assert "_inner_lifespan" not in vars(instance)


def test_linux_jobs_owner_logs_only_relevant_operating_limits(monkeypatch):
    from binnacle.features.commands import jobs
    from binnacle.platform import composition

    monkeypatch.setattr(composition, "host_os_family", lambda: "linux")
    calls = []
    monkeypatch.setattr(
        server, "_log_tool_config", lambda tool, **fields: calls.append((tool, fields))
    )
    settings = SimpleNamespace(
        jobs=SimpleNamespace(
            owner="manager",
            keep_newest=10,
            listing_history_limit=9,
            listing_command_preview_chars=55,
            max_output_chars=77,
            warmup_s=0.05,
            quiet_after_s=20.0,
        )
    )
    server._log_jobs_config(settings)
    assert len(calls) == 1
    label, fields = calls[0]
    assert label == "jobs"
    assert fields["configured_owner"] == "manager"
    assert fields["effective_owner"] == jobs.OWNER_MODE
    assert fields["keep_newest"] == 10
    assert fields["stop_sigterm_grace_s"] == jobs.STOP_SIGTERM_GRACE_S


def test_removed_configuration_warning_names_are_bounded(monkeypatch, caplog):
    original = server.get_settings()
    settings = original.model_copy(deep=True)
    settings._removed_sections = ("old_top_section",)
    settings.run_command._removed_sections = ("old_background_mode",)
    settings.jobs._removed_keys = ("old_manager_dir",)
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    monkeypatch.setattr(
        server,
        "runtime_provenance",
        lambda: SimpleNamespace(package_version="1.0.1", revision="test-fixture"),
    )
    monkeypatch.setattr(server, "_log_jobs_config", lambda _s: None)
    observed = []
    monkeypatch.setattr(
        server,
        "_log_tool_config",
        lambda tool, **fields: observed.append((tool, fields)),
    )
    with caplog.at_level(logging.INFO, logger="binnacle.server"):
        server.log_effective_config()
    for section in (
        "old_top_section",
        "run_command.old_background_mode",
        "jobs.old_manager_dir",
    ):
        assert f"section={section} reason=removed action=ignored" in caplog.text
    assert "event=config pid=" in caplog.text
    assert any(tool == "read_file" for tool, _ in observed)
    assert any(tool == "run_command" for tool, _ in observed)


def test_direct_python_entry_invokes_fake_server_only(monkeypatch):
    """Cover the actual main branch, but stub FastMCP.run before source loads."""
    from fastmcp import FastMCP

    runs = []

    def fake_run(self, *args, **kwargs):
        runs.append((self, args, kwargs))

    monkeypatch.setattr(FastMCP, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [str(Path(server.__file__))])
    runpy.run_path(str(Path(server.__file__)), run_name="__main__")
    assert len(runs) == 1
    actual, args, fields = runs[0]
    assert isinstance(actual, FastMCP)
    assert args == ()
    assert fields == {
        "transport": "http",
        "host": "127.0.0.1",
        "port": 8000,
        "show_banner": False,
    }

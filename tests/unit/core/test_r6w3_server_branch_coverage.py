"""Exercise MCP server's platform, record and ownership decision branches.

No production port, launchd label, process owner or credential file is used.
Negative startup and ASGI wire integration are covered by separate suites.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from types import SimpleNamespace

import pytest
import uvicorn

from binnacle import server
from binnacle.startup_imports import StartupImportFailed


@pytest.mark.parametrize(
    ("argv0", "serving"),
    [
        ("/usr/local/bin/uvicorn", True),
        ("/venv/bin/uvicorn", True),
        ("/site-packages/uvicorn/__main__.py", True),
        ("/site-packages/notuvicorn/__main__.py", False),
        ("/venv/bin/binnacle", False),
        ("/home/work/binnacle/server.py", False),
        ("-c", False),
    ],
)
def test_argv_only_recognizes_a_real_uvicorn_entrypoint(monkeypatch, argv0, serving):
    monkeypatch.setattr(sys, "argv", [argv0, "binnacle.server:app"])
    assert server._argv_serving_process() is serving


def test_explicit_serving_mark_short_circuits_argv_detection(monkeypatch):
    monkeypatch.setattr(server, "serving_entry_marked", lambda: True)
    monkeypatch.setattr(
        server,
        "_argv_serving_process",
        lambda: (_ for _ in ()).throw(AssertionError("argv examined")),
    )
    assert server._serving_process()


@pytest.mark.parametrize("argv_serving", [False, True])
def test_unmarked_importer_uses_argv_probe_only(monkeypatch, argv_serving):
    monkeypatch.setattr(server, "serving_entry_marked", lambda: False)
    monkeypatch.setattr(server, "_argv_serving_process", lambda: argv_serving)
    assert server._serving_process() is argv_serving


@pytest.mark.parametrize("allowed", [True, False])
def test_only_a_serving_importer_may_write_a_failed_start_record(
    monkeypatch, tmp_path, allowed
):
    from binnacle import config

    failure = StartupImportFailed("binnacle.provenance", "SyntaxError", "p.py:2")
    saved = []
    monkeypatch.setattr(server, "_serving_process", lambda: allowed)
    # The failure handler lazily reads the canonical config, not server's
    # already imported get_settings symbol. Never touch production state.
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(dir=tmp_path / "jobs")),
    )
    monkeypatch.setattr(
        server,
        "record_start_failure",
        lambda process, fault, root: saved.append((process, fault, root)),
    )
    server._record_import_failure(failure)
    assert saved == ([("mcp-server", failure, tmp_path)] if allowed else [])


def test_failed_config_import_does_not_guess_a_record_path(monkeypatch, caplog):
    from binnacle import config

    failure = StartupImportFailed("binnacle.config", "SyntaxError", "c.py:1")
    monkeypatch.setattr(server, "_serving_process", lambda: True)

    def bad_settings():
        raise RuntimeError("unavailable configured state")

    monkeypatch.setattr(config, "get_settings", bad_settings)
    with caplog.at_level(logging.ERROR, logger="binnacle.server"):
        server._record_import_failure(failure)
    assert "event=startup_import_record_error process=mcp-server" in caplog.text


def test_clearing_success_uses_only_the_configured_state_path(monkeypatch, tmp_path):
    cleared = []
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(dir=tmp_path / "jobs")),
    )
    monkeypatch.setattr(
        server, "clear_record", lambda process, root: cleared.append((process, root))
    )
    server._clear_record_after_start()
    assert cleared == [("mcp-server", tmp_path)]


def test_clearing_while_config_unavailable_does_nothing(monkeypatch):
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: (_ for _ in ()).throw(ValueError("root unavailable")),
    )
    monkeypatch.setattr(
        server,
        "clear_record",
        lambda *_args: (_ for _ in ()).throw(AssertionError("cleared no root")),
    )
    assert server._clear_record_after_start() is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Bearer available-test-token\n", "available-test-token"),
        ("raw-test-token\n", "raw-test-token"),
    ],
)
def test_token_reader_accepts_bearer_or_plaintext_fixture(
    tmp_path, monkeypatch, value, expected
):
    token = tmp_path / "only-test-owned-token"
    token.write_text(value, encoding="utf-8")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    assert server._load_token() == expected


@pytest.mark.parametrize("value", ["Bearer\n", " \n", "Bearer   \n"])
def test_token_reader_rejects_empty_or_invalid_token(tmp_path, monkeypatch, value):
    token = tmp_path / "empty-token"
    token.write_text(value, encoding="utf-8")
    monkeypatch.setattr(server, "TOKEN_FILE", token)
    with pytest.raises(RuntimeError, match="is empty"):
        server._load_token()


@pytest.mark.parametrize("family", ["linux", "darwin"])
def test_platform_factory_receives_only_its_native_command_backend(
    monkeypatch, family, tmp_path
):
    from binnacle import application
    from binnacle.features.commands import command_backend
    from binnacle.platform import composition

    calls = []
    settings = SimpleNamespace(jobs=SimpleNamespace(dir=tmp_path / "jobs"))
    monkeypatch.setattr(composition, "host_os_family", lambda: family)
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    monkeypatch.setattr(server, "_load_token", lambda: "isolated-token")
    monkeypatch.setattr(
        command_backend,
        "create_command_backend",
        lambda: calls.append("linux-backend") or "linux-backend",
    )
    monkeypatch.setattr(
        application,
        "compose_native_tools",
        lambda *, settings: (
            calls.append("darwin-tools") or ("fd-grant", "darwin-owner")
        ),
    )
    monkeypatch.setattr(
        application,
        "create_application",
        lambda **kwargs: calls.append("factory") or kwargs,
    )
    result = server.create_server()
    assert calls == (
        ["darwin-tools", "factory"]
        if family == "darwin"
        else ["linux-backend", "factory"]
    )
    assert result["token"] == "isolated-token"
    assert result["backend"] == (
        "darwin-owner" if family == "darwin" else "linux-backend"
    )
    assert result["file_access"] == ("fd-grant" if family == "darwin" else None)
    assert result["settings"] is settings
    assert result["files_factory"] is server.create_files_server
    assert result["search_factory"] is server.create_search_server
    assert result["commands_factory"] is server.create_commands_server


@pytest.mark.parametrize("owner", ["manager", "embedded"])
def test_darwin_jobs_config_discloses_correct_owner(monkeypatch, owner, caplog):
    from binnacle.platform import composition

    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    collected = []
    monkeypatch.setattr(
        server,
        "_log_tool_config",
        lambda name, **fields: collected.append((name, fields)),
    )
    settings = SimpleNamespace(jobs=SimpleNamespace(owner=owner, socket_path=None))
    with caplog.at_level(logging.INFO, logger="binnacle.server"):
        server._log_jobs_config(settings)
    assert [name for name, _ in collected] == ["run_command", "job_status", "stop_job"]
    if owner == "manager":
        assert "effective_owner=manager" in caplog.text
        assert "job manager unavailable" in caplog.text
    else:
        assert "effective_owner=embedded" in caplog.text
    assert [x["capability"] for _, x in collected]


@pytest.mark.parametrize(
    ("started", "marked", "service_app", "expected"),
    [
        (True, True, "app_object", True),
        (True, True, "binnacle.server:app", True),
        (True, True, "different-service", False),
        (True, False, "app_object", False),
        (False, True, "app_object", False),
        (True, True, None, False),
    ],
)
def test_only_our_started_uvicorn_instance_may_clear_failure_record(
    monkeypatch, started, marked, service_app, expected
):
    saved = []
    monkeypatch.setattr(server, "serving_entry_marked", lambda: marked)
    monkeypatch.setattr(
        server, "_clear_record_after_start", lambda: saved.append("cleared")
    )

    async def original(self, *_args, **_kwargs):
        self.started = started

    monkeypatch.setattr(uvicorn.Server, "startup", original)
    server._clear_record_when_server_started()
    service = server.app if service_app == "app_object" else service_app
    fake = SimpleNamespace(started=False, config=SimpleNamespace(app=service))
    asyncio.run(uvicorn.Server.startup(fake))
    assert saved == (["cleared"] if expected else [])

"""Linux-runnable coverage for the R4 Darwin manager wiring of the application."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from binnacle import application, config
from binnacle.features.commands.command_backend import DarwinManagerCommandBackend
from binnacle.features.commands.command_contracts import RestrictedCommandBackend
from binnacle.platform import composition


@pytest.fixture(autouse=True)
def _real_host_settings_cache():
    # get_settings() is cached and host-dependent: populate it on the real host
    # before any test patches platform.system, so no Darwin-shaped value leaks.
    config.get_settings()


def settings_with(tmp_path: Path, **jobs_fields):
    base = config.get_settings()
    jobs = base.jobs.model_copy(update={"dir": tmp_path, **jobs_fields})
    return base.model_copy(update={"jobs": jobs})


@pytest.fixture
def fake_client(monkeypatch):
    client = object()
    monkeypatch.setattr(composition, "create_job_client", lambda: client)
    return client


@pytest.fixture
def validated(monkeypatch):
    calls = []

    def record(states, *, owner, execution=None):
        calls.append((dict(states), owner, execution))

    monkeypatch.setattr(composition, "validate_native_command_states", record)
    return calls


def test_manager_bindings_inject_spool_and_call_context():
    from binnacle.features.commands import job_store
    from binnacle.features.commands.job_stop import raise_if_partial_signal
    from binnacle.mcp.callctx import current_call
    from binnacle.platform.contracts.process_contracts import (
        JOB_MANAGER_UNAVAILABLE,
        OWNER_LOST_STOP_REFUSED,
    )

    bindings = application.manager_bindings()
    assert bindings.store is job_store
    assert bindings.call_id == current_call.get
    assert bindings.check_partial is raise_if_partial_signal
    assert bindings.owner_lost_refusal == OWNER_LOST_STOP_REFUSED
    assert bindings.unavailable == JOB_MANAGER_UNAVAILABLE


def test_manager_backend_uses_configured_socket(tmp_path, fake_client):
    sock = tmp_path / "jobs.sock"
    settings = settings_with(tmp_path, socket_path=sock)
    backend = application._manager_command_backend(settings, {"run_command": "X"})
    assert isinstance(backend, DarwinManagerCommandBackend)
    assert backend.client is fake_client and backend.socket_path == sock
    assert backend.jobs_dir == tmp_path
    assert backend.release_states == {"run_command": "X"}
    assert backend.warmup_s == settings.jobs.warmup_s
    assert backend.max_output_chars == settings.jobs.max_output_chars


def test_manager_backend_resolves_runtime_socket_per_call(
    tmp_path, fake_client, monkeypatch
):
    from types import SimpleNamespace

    monkeypatch.setattr(
        composition,
        "create_runtime_paths",
        lambda: SimpleNamespace(jobs_socket=tmp_path / "runtime.sock"),
    )
    settings = settings_with(tmp_path, socket_path=None)
    backend = application._manager_command_backend(settings, {})
    assert backend.socket_path == tmp_path / "runtime.sock"


def test_focused_backend_off_darwin_is_inert(monkeypatch):
    monkeypatch.setattr(application.platform, "system", lambda: "Linux")
    backend = application._focused_command_backend()
    assert type(backend) is RestrictedCommandBackend
    assert backend.release_states == {}


@pytest.mark.parametrize("owner", ["auto", "manager", "embedded"])
def test_focused_backend_on_darwin_follows_owner(
    tmp_path, monkeypatch, fake_client, owner
):
    monkeypatch.setattr(application.platform, "system", lambda: "Darwin")
    settings = settings_with(tmp_path, owner=owner)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    backend = application._focused_command_backend()
    effective = application.resolve_darwin_job_owner(owner)
    scope = application.release_scope_for_owner(effective)
    states = {t: scope[t].capability.state.value for t in application._COMMAND_TOOLS}
    if effective == "manager":
        assert isinstance(backend, DarwinManagerCommandBackend)
    else:
        assert type(backend) is RestrictedCommandBackend
    assert backend.release_states == states


@pytest.mark.parametrize(
    "system,owner,expected",
    [
        ("Linux", "manager", application._LINUX_INSTRUCTIONS),
        ("Darwin", None, application._DARWIN_INSTRUCTIONS),
        ("Darwin", "embedded", application._DARWIN_INSTRUCTIONS),
        ("Darwin", "manager", application._DARWIN_MANAGER_INSTRUCTIONS),
    ],
)
def test_server_instructions_per_host_and_owner(monkeypatch, system, owner, expected):
    monkeypatch.setattr(application.platform, "system", lambda: system)
    assert application._server_instructions(owner) == expected


def test_manager_instructions_disclose_service_requirement():
    text = application._DARWIN_MANAGER_INSTRUCTIONS
    assert application.DARWIN_MANAGER_REQUIREMENT in text
    assert application.DARWIN_JOBS_DISCLOSURE in text
    assert "com.binnacle.jobs" in application.DARWIN_MANAGER_REQUIREMENT


def test_create_application_validates_manager_backend(
    tmp_path, monkeypatch, fake_client, validated
):
    monkeypatch.setattr(application.platform, "system", lambda: "Darwin")
    settings = settings_with(tmp_path, socket_path=tmp_path / "s.sock")
    states = {
        "run_command": "AVAILABLE",
        "job_status": "AVAILABLE",
        "stop_job": "AVAILABLE",
    }
    backend = application._manager_command_backend(settings, states)
    root = application.create_application(settings=settings, token="t", backend=backend)
    assert isinstance(root, FastMCP)
    assert root.instructions == application._DARWIN_MANAGER_INSTRUCTIONS
    assert validated == [(states, "manager", None)]


@pytest.mark.parametrize("explicit_owner", [None, "manager"])
def test_compose_native_tools_for_manager_owner(
    tmp_path, monkeypatch, fake_client, explicit_owner
):
    captured = {}

    def capability(*, release_scope, execution, owner):
        captured.update(execution=execution, owner=owner)
        return release_scope["read_file"].capability

    def no_foreground(**kwargs):
        pytest.fail("the manager owner composes no foreground runner")

    monkeypatch.setattr(composition, "native_file_capability", capability)
    monkeypatch.setattr(composition, "create_foreground_execution", no_foreground)
    settings = settings_with(tmp_path, owner="auto", socket_path=tmp_path / "s.sock")
    access, backend = application.compose_native_tools(
        settings=settings, owner=explicit_owner
    )
    assert isinstance(backend, DarwinManagerCommandBackend)
    assert captured == {"execution": None, "owner": "manager"}
    scope = application.release_scope_for_owner("manager")
    assert backend.release_states == {
        t: scope[t].capability.state.value for t in application._COMMAND_TOOLS
    }
    assert access is not None

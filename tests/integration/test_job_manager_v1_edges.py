"""Edge paths of the Linux v1 Job Manager: wire errors, sockets, v2 opt-in, entry."""

from __future__ import annotations

import json
import os
import runpy
import socket
import stat
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import binnacle.config
import binnacle.manager_bootstrap
import binnacle.startup_imports
from binnacle.features.commands import job_client, job_manager, jobs
from binnacle.features.commands.job_manager import JobManager
from binnacle.startup_imports import StartupImportFailed, record_path
from tests.integration.test_job_manager_v2 import _pinned_fd, _request, _send

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY

_MODULE = "binnacle.features.commands.job_manager"


@pytest.fixture()
def private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private run directory, an isolated spool and no systemd environment."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    return run


def _serve(runtime: JobManager, monkeypatch: pytest.MonkeyPatch) -> threading.Thread:
    """Serve in a thread; return once the manager reports every endpoint bound."""
    ready = threading.Event()
    monkeypatch.setattr(job_manager, "_on_started", ready.set)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    assert ready.wait(timeout=10), "job manager did not report ready"
    return thread


@pytest.fixture()
def served(
    private: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[JobManager, Path]]:
    runtime = JobManager(
        private / "jobs.sock",
        owner_instance_id="edges-owner",
        boot_id=jobs._PROCESS_BACKEND.boot_id(),
    )
    thread = _serve(runtime, monkeypatch)
    yield runtime, private / "jobs.sock"
    runtime.shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()


def _rpc(socket_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode() + b"\n")
        return json.loads(client.makefile("rb").readline())


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_eof_probe_gets_no_reply_and_is_logged(served, caplog):
    """A peer that closes before sending a byte is an identity probe, not an error."""
    _, socket_path = served
    with (
        caplog.at_level("DEBUG", logger="binnacle.job_manager"),
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client,
    ):
        client.settimeout(10)
        client.connect(str(socket_path))
        client.shutdown(socket.SHUT_WR)
        assert client.recv(64) == b""
    assert "event=job_manager_probe_closed" in _messages(caplog)
    assert not any("request_invalid" in m for m in _messages(caplog))


def test_unexpected_dispatch_failure_is_isolated(served, monkeypatch, caplog):
    """An internal error yields a generic reply; the next request is still served."""
    runtime, socket_path = served
    real_dispatch = runtime.dispatch
    failures = []

    def failing_once(request: dict[str, Any]) -> dict[str, Any]:
        if not failures:
            failures.append(request["op"])
            raise RuntimeError("secret-internal-detail")
        return real_dispatch(request)

    monkeypatch.setattr(runtime, "dispatch", failing_once)
    with caplog.at_level("ERROR", logger="binnacle.job_manager"):
        reply = _rpc(socket_path, {"version": 1, "op": "ping", "call_id": "boom-1"})
    assert reply == {"ok": False, "error": "internal job-manager error"}
    assert "secret-internal-detail" not in json.dumps(reply)
    assert any(
        "event=job_manager_request_error op=ping call=boom-1 "
        "error_class=RuntimeError" in m
        for m in _messages(caplog)
    )
    assert job_client.ping(socket_path)["owner_instance_id"] == "edges-owner"


def test_wire_rejects_bad_version_and_unknown_operation(served):
    _, socket_path = served
    assert _rpc(socket_path, {"version": 999, "op": "ping"}) == {
        "ok": False,
        "error": "unsupported job-manager protocol version",
    }
    assert _rpc(socket_path, {"version": 1, "op": "mystery"}) == {
        "ok": False,
        "error": "unknown job-manager operation 'mystery'",
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"command": 42}, "command/stdin have invalid types"),
        ({"stdin": ["not", "text"]}, "command/stdin have invalid types"),
        ({"workdir": "/nonexistent/binnacle-edges"}, "workdir is not a directory"),
        ({"wait_seconds": -1}, "wait_seconds outside manager bounds"),
        ({"wait_seconds": 10**9}, "wait_seconds outside manager bounds"),
    ],
)
def test_invalid_start_is_refused_before_any_job(served, tmp_path, changes, expected):
    _, socket_path = served
    request = {
        "version": 1,
        "op": "start",
        "command": "true",
        "workdir": str(tmp_path),
        "stdin": None,
        "wait_seconds": 0,
        "call_id": "bad-start",
    }
    request.update(changes)
    reply = _rpc(socket_path, request)
    assert reply["ok"] is False
    assert reply["error"].startswith("invalid job-manager request: ")
    assert expected in reply["error"]
    assert jobs.list_jobs() == []


def test_constructor_requires_complete_and_separate_v2_config(tmp_path):
    legacy = tmp_path / "legacy.sock"
    with pytest.raises(ValueError, match="configured together"):
        JobManager(legacy, boot_id="b", v2_allowed_roots=(tmp_path,))
    with pytest.raises(ValueError, match="separate from legacy v1 socket"):
        JobManager(
            legacy, boot_id="b", v2_socket_path=legacy, v2_allowed_roots=(tmp_path,)
        )
    runtime = JobManager(legacy, boot_id="b")
    runtime.shutdown()  # never served: a no-op, not an error
    assert runtime.server is None


def test_prepare_refuses_to_replace_a_live_manager(private, monkeypatch):
    socket_path = private / "jobs.sock"
    recovered = []
    monkeypatch.setattr(
        job_manager.job_owner,
        "recover_previous_owner",
        lambda *args: recovered.append(args) or 0,
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as live:
        live.bind(str(socket_path))
        live.listen(1)
        runtime = JobManager(socket_path, owner_instance_id="second", boot_id="b")
        with pytest.raises(RuntimeError, match="job manager already answers at"):
            runtime.prepare()
        assert stat.S_ISSOCK(socket_path.lstat().st_mode)
    assert recovered == []


def test_prepare_replaces_a_dead_socket_and_tightens_parent(private, monkeypatch):
    socket_path = private / "jobs.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as dead:
        dead.bind(str(socket_path))  # bound, never listening: connect is refused
    private.chmod(0o755)
    monkeypatch.setattr(
        job_manager.job_owner, "recover_previous_owner", lambda *args: 3
    )
    runtime = JobManager(socket_path, owner_instance_id="next", boot_id="b")
    assert runtime.prepare() == 3
    assert not socket_path.exists()
    assert stat.S_IMODE(private.stat().st_mode) == 0o700


def test_opt_in_v2_receiver_serves_and_is_torn_down(
    private, tmp_path, monkeypatch, caplog
):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "marker").write_text("EDGE-V2\n")
    legacy, v2 = private / "legacy.sock", private / "start-v2.sock"
    runtime = JobManager(
        legacy,
        owner_instance_id="edges-v2-owner",
        boot_id=jobs._PROCESS_BACKEND.boot_id(),
        v2_socket_path=v2,
        v2_allowed_roots=(root,),
    )
    caplog.set_level("INFO", logger="binnacle.job_manager")
    thread = _serve(runtime, monkeypatch)
    try:
        assert job_client.ping(legacy)["owner_instance_id"] == "edges-v2-owner"
        assert stat.S_IMODE(v2.stat().st_mode) == 0o600
        assert runtime._v2_thread is not None and runtime._v2_thread.is_alive()
        descriptor = _pinned_fd(root)
        try:
            reply = _send(v2, _request(root), (descriptor,))
        finally:
            os.close(descriptor)
        assert reply["ok"] is True, reply
        assert reply["state"] == "exited"
        assert (jobs.JOBS_DIR / reply["job_id"]).is_dir()
    finally:
        runtime.shutdown()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert any(
        "event=job_manager_start" in m and "v2_enabled=True" in m
        for m in _messages(caplog)
    )
    assert not legacy.exists() and not v2.exists()
    assert runtime._v2_thread is None and runtime._v2_server is None


def test_failed_start_hook_still_closes_a_stopped_v2_receiver(
    private, tmp_path, monkeypatch
):
    """Cleanup must not wait on a receiver thread that already ended."""
    root = tmp_path / "allowed"
    root.mkdir()
    legacy, v2 = private / "legacy.sock", private / "start-v2.sock"
    runtime = JobManager(
        legacy, boot_id="b", v2_socket_path=v2, v2_allowed_roots=(root,)
    )
    monkeypatch.setattr(
        job_manager.job_owner, "recover_previous_owner", lambda *args: 0
    )
    seen: dict[str, bool] = {}

    def failing_hook() -> None:
        assert runtime._v2_server is not None and runtime._v2_thread is not None
        seen["v2_bound"] = v2.exists()
        runtime._v2_server.shutdown()
        runtime._v2_thread.join(timeout=5)
        seen["receiver_alive"] = runtime._v2_thread.is_alive()
        raise RuntimeError("start hook failed")

    monkeypatch.setattr(job_manager, "_on_started", failing_hook)
    with pytest.raises(RuntimeError, match="start hook failed"):
        runtime.serve_forever()
    assert seen == {"v2_bound": True, "receiver_alive": False}
    assert not legacy.exists() and not v2.exists()
    assert runtime._v2_thread is None and runtime.server is None


def test_v2_without_roots_aborts_before_binding_v2(private, tmp_path, monkeypatch):
    legacy, v2 = private / "legacy.sock", private / "start-v2.sock"
    runtime = JobManager(
        legacy, boot_id="b", v2_socket_path=v2, v2_allowed_roots=(tmp_path,)
    )
    runtime.v2_allowed_roots = None  # simulate a corrupted runtime configuration
    monkeypatch.setattr(
        job_manager.job_owner, "recover_previous_owner", lambda *args: 0
    )
    started = []
    monkeypatch.setattr(job_manager, "_on_started", lambda: started.append(1))
    with pytest.raises(RuntimeError, match="configured without allowed roots"):
        runtime.serve_forever()
    assert started == []
    assert not legacy.exists() and not v2.exists()


def _failure() -> StartupImportFailed:
    return StartupImportFailed("binnacle.missing", "ImportError", "missing.py:7")


def test_import_failure_record_is_written_under_state_root(tmp_path, monkeypatch):
    state = tmp_path / "state"
    settings = SimpleNamespace(jobs=SimpleNamespace(dir=state / "jobs"))
    monkeypatch.setattr(job_manager, "get_settings", lambda: settings)
    job_manager._record_import_failure(_failure())
    record = json.loads(record_path(state, "job-manager").read_text())
    assert record["process"] == "job-manager"
    assert record["module"] == "binnacle.missing"
    assert record["error_class"] == "ImportError"
    assert record["where"] == "missing.py:7"


def test_import_failure_without_config_only_logs(tmp_path, monkeypatch, caplog):
    def broken() -> Any:
        raise ValueError("config unreadable")

    monkeypatch.setattr(job_manager, "get_settings", broken)
    monkeypatch.chdir(tmp_path)
    with caplog.at_level("ERROR", logger="binnacle.job_manager"):
        job_manager._record_import_failure(_failure())
    assert "event=startup_import_record_error process=job-manager" in _messages(caplog)
    assert list(tmp_path.iterdir()) == []


def _settings(tmp_path: Path, **jobs_fields: Any) -> SimpleNamespace:
    return SimpleNamespace(
        jobs=SimpleNamespace(dir=tmp_path / "state" / "jobs", **jobs_fields),
        roots=SimpleNamespace(canonical_allowed=(tmp_path,)),
    )


@pytest.mark.parametrize("with_v2", [False, True])
def test_main_serves_configured_sockets_and_clears_record(
    tmp_path, monkeypatch, with_v2
):
    v1, v2 = tmp_path / "v1.sock", tmp_path / "v2.sock"
    settings = _settings(
        tmp_path, socket_path=v1, v2_socket_path=v2 if with_v2 else None
    )
    stale = record_path(tmp_path / "state", "job-manager")
    stale.parent.mkdir(parents=True)
    stale.write_text("{}\n")
    imports: list[dict[str, Any]] = []
    built: list[tuple[Path, dict[str, Any]]] = []

    class FakeManager:
        def __init__(self, socket_path: Path, **kwargs: Any) -> None:
            built.append((socket_path, kwargs))

        def serve_forever(self) -> None:
            assert job_manager._on_started is not None
            job_manager._on_started()

    monkeypatch.setattr(
        job_manager, "import_manager_modules", lambda **kw: imports.append(kw)
    )
    monkeypatch.setattr(job_manager, "get_settings", lambda: settings)
    monkeypatch.setattr(job_manager, "JobManager", FakeManager)
    job_manager.main()
    assert imports[0]["process"] == "job-manager"
    assert imports[0]["on_failure"] is job_manager._record_import_failure
    expected = {"v2_socket_path": v2, "v2_allowed_roots": (tmp_path,)}
    assert built == [(v1, expected if with_v2 else {})]
    assert not stale.exists()
    assert job_manager._on_started is None


def test_main_refuses_unresolved_socket(tmp_path, monkeypatch):
    monkeypatch.setattr(job_manager, "import_manager_modules", lambda **kw: None)
    monkeypatch.setattr(
        job_manager, "get_settings", lambda: _settings(tmp_path, socket_path=None)
    )
    with pytest.raises(RuntimeError, match="did not resolve the jobs socket"):
        job_manager.main()


def test_dash_m_entry_bootstraps_linux_before_main(tmp_path, monkeypatch):
    """``python -m`` bootstraps the Linux closure first, then runs ``main``."""
    calls: list[Any] = []
    monkeypatch.setattr(
        binnacle.manager_bootstrap,
        "bootstrap_manager_entry",
        lambda system: calls.append(("bootstrap", system)),
    )
    monkeypatch.setattr(
        binnacle.startup_imports,
        "import_manager_modules",
        lambda **kw: calls.append(("imports", kw["process"])),
    )
    monkeypatch.setattr(
        binnacle.config, "get_settings", lambda: _settings(tmp_path, socket_path=None)
    )
    with (
        pytest.warns(RuntimeWarning, match="found in sys.modules"),
        pytest.raises(RuntimeError, match="did not resolve the jobs socket"),
    ):
        runpy.run_module(_MODULE, run_name="__main__")
    assert calls == [("bootstrap", "Linux"), ("imports", "job-manager")]

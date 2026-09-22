"""Small failure and entry-point edges of the durable job manager."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import job_manager
from binnacle.job_client import PROTOCOL_VERSION


def _runtime(tmp_path: Path) -> job_manager.JobManager:
    return job_manager.JobManager(
        tmp_path / "jobs.sock", owner_instance_id="owner", boot_id="boot"
    )


def test_metadata_helpers_fall_back_cleanly(monkeypatch):
    monkeypatch.setattr(
        job_manager.importlib.metadata,
        "version",
        lambda name: (_ for _ in ()).throw(
            job_manager.importlib.metadata.PackageNotFoundError(name)
        ),
    )
    assert job_manager._package_version() == "?"

    monkeypatch.setattr(
        job_manager.Path,
        "read_text",
        lambda self: (_ for _ in ()).throw(OSError("unreadable")),
    )
    assert job_manager._boot_id() == "unknown"


def test_notify_failure_is_contained(monkeypatch, caplog):
    class BrokenNotifier:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, address):
            raise OSError("notify unavailable")

    monkeypatch.setenv("NOTIFY_SOCKET", "/tmp/notify.sock")
    monkeypatch.setattr(
        job_manager.socket, "socket", lambda *args, **kwargs: BrokenNotifier()
    )
    with caplog.at_level("ERROR", logger="binnacle.job_manager"):
        job_manager._notify_systemd_ready()
    assert any(
        "event=job_manager_notify_error" in r.getMessage() for r in caplog.records
    )


def test_dispatch_rejects_bad_version_and_unknown_operation(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.dispatch({"version": 999, "op": "ping"})["ok"] is False
    response = runtime.dispatch({"version": PROTOCOL_VERSION, "op": "mystery"})
    assert response == {"ok": False, "error": "unknown job-manager operation 'mystery'"}


def test_start_validates_request_and_reports_launch_failure(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    base = {
        "command": "true",
        "workdir": str(tmp_path),
        "stdin": None,
        "wait_seconds": 0,
    }
    with pytest.raises(TypeError, match="invalid types"):
        runtime._start({**base, "command": 123})
    with pytest.raises(ValueError, match="not a directory"):
        runtime._start({**base, "workdir": str(tmp_path / "missing")})
    with pytest.raises(ValueError, match="outside manager bounds"):
        runtime._start({**base, "wait_seconds": 10_000})

    monkeypatch.setattr(
        job_manager.jobs,
        "start_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no slots")),
    )
    assert runtime._start(base) == {
        "ok": False,
        "error": "could not start job: no slots",
    }


def test_stop_validates_id_and_reports_missing_job(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    with pytest.raises(TypeError, match="job_id must be a string"):
        runtime._stop({"job_id": 123})

    monkeypatch.setattr(
        job_manager.job_owner, "mark_stop_requested", lambda job_id: None
    )
    monkeypatch.setattr(job_manager.jobs, "stop_job_embedded", lambda job_id: None)
    assert runtime._stop({"job_id": "missing"}) == {
        "ok": False,
        "error": "no job with id 'missing'",
    }


def test_prepare_removes_stale_socket_path(tmp_path, monkeypatch):
    socket_path = tmp_path / "run" / "jobs.sock"
    socket_path.parent.mkdir()
    socket_path.write_text("stale")
    runtime = job_manager.JobManager(
        socket_path, owner_instance_id="owner", boot_id="boot"
    )
    monkeypatch.setattr(
        job_manager.job_owner, "recover_previous_owner", lambda *args: 0
    )

    assert runtime.prepare() == 0
    assert not socket_path.exists()


def test_shutdown_without_server_is_noop_and_main_uses_configured_socket(
    tmp_path, monkeypatch
):
    runtime = _runtime(tmp_path)
    runtime.shutdown()

    called = []

    class FakeManager:
        def __init__(self, socket_path):
            called.append(socket_path)

        def serve_forever(self):
            called.append("served")

    socket_path = tmp_path / "configured.sock"
    monkeypatch.setattr(
        job_manager,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(socket_path=socket_path)),
    )
    monkeypatch.setattr(job_manager, "JobManager", FakeManager)
    job_manager.main()
    assert called == [socket_path, "served"]

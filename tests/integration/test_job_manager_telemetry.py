"""Telemetry-specific checks for the durable job manager."""

import json
import threading
import time
from pathlib import Path

import pytest

from binnacle import job_client, jobs
from binnacle.job_manager import JobManager


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    socket_path = tmp_path / "run" / "jobs.sock"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    runtime = JobManager(
        socket_path, owner_instance_id="owner-new", boot_id="boot-current"
    )
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    for _ in range(200):
        if socket_path.exists():
            break
        time.sleep(0.005)
    assert socket_path.exists()
    yield runtime, socket_path, store
    for state in jobs.list_jobs():
        if state["state"] == "running":
            try:
                job_client.stop(socket_path, state["job_id"])
            except job_client.JobManagerError:
                pass
    runtime.shutdown()
    thread.join(timeout=3)


def _unfinished(store: Path, name: str, *, boot: str, owner: str) -> None:
    directory = store / name
    directory.mkdir(parents=True)
    (directory / "out.log").write_text("partial")
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "command": "sleep 99",
                "workdir": "/tmp",
                "pid": 999999,
                "pgid": 999999,
                "started_at": 1.0,
                "owner_instance_id": owner,
                "boot_id": boot,
            }
        )
    )


def test_manager_lifecycle_logs_are_directly_correlatable(manager, caplog):
    _, socket_path, _ = manager
    with caplog.at_level("INFO"):
        response = job_client.start(
            socket_path,
            command="printf telemetry",
            workdir=Path("/tmp"),
            stdin=None,
            wait_seconds=5,
            call_id="telemetry-call",
        )
    job_id = response["job_id"]
    state = jobs.job_state(job_id)
    assert state is not None
    assert state["call_id"] == "telemetry-call"
    assert state["owner"] == "manager"
    assert state["owner_instance_id"] == "owner-new"
    assert len(state["command_hash"]) == 12

    start_line = next(
        r.getMessage()
        for r in caplog.records
        if f"event=job_start job_id={job_id}" in r.getMessage()
    )
    exit_line = next(
        r.getMessage()
        for r in caplog.records
        if f"event=job_exit job_id={job_id}" in r.getMessage()
    )
    timing = next(
        r.getMessage()
        for r in caplog.records
        if f"event=job_owner_timing op=start call=telemetry-call job_id={job_id}"
        in r.getMessage()
    )
    assert "call=telemetry-call owner=manager owner_instance=owner-new" in start_line
    assert f"command_hash={state['command_hash']}" in start_line
    assert "call=telemetry-call owner=manager owner_instance=owner-new" in exit_line
    assert "launch_ms=" in timing and "impl_ms=" in timing and "state=exited" in timing


def test_stop_and_disconnect_logs_keep_operation_correlation(manager, caplog):
    _, socket_path, _ = manager
    started = job_client.start(
        socket_path,
        command="sleep 30",
        workdir=Path("/tmp"),
        stdin=None,
        wait_seconds=0.05,
        call_id="origin-call",
    )
    job_id = started["job_id"]
    with caplog.at_level("INFO"):
        stopped = job_client.stop(socket_path, job_id, call_id="stop-call")
    assert stopped["state"] == "exited"
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        f"event=job_stop_requested job_id={job_id} call=stop-call "
        "origin_call=origin-call" in line
        for line in messages
    )
    assert any(
        f"event=job_owner_timing op=stop call=stop-call job_id={job_id}" in line
        for line in messages
    )


def test_recovery_log_links_original_and_new_owner(tmp_path, monkeypatch, caplog):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    _unfinished(store, "recoverlog001", boot="boot-a", owner="owner-a")
    meta_path = store / "recoverlog001" / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta.update(call_id="origin-call", command_hash="abcdef123456")
    meta_path.write_text(json.dumps(meta))
    runtime = JobManager(
        tmp_path / "run" / "jobs.sock",
        owner_instance_id="owner-b",
        boot_id="boot-a",
    )
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        assert runtime.prepare() == 1
    line = next(
        record.getMessage()
        for record in caplog.records
        if "event=job_interrupted job_id=recoverlog001" in record.getMessage()
    )
    assert "reason=owner_restart" in line
    assert "call=origin-call" in line
    assert "previous_owner=owner-a" in line
    assert "current_owner=owner-b" in line
    assert "command_hash=abcdef123456" in line

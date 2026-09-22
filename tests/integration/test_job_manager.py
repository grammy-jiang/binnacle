"""The local durable job manager as an isolated AF_UNIX runtime."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle import job_client, jobs
from binnacle.job_manager import JobManager
from tests.integration.job_test_support import run, status, stop


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    socket_path = tmp_path / "run" / "jobs.sock"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    runtime = JobManager(
        socket_path,
        owner_instance_id="owner-new",
        boot_id="boot-current",
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
    assert not thread.is_alive()


def test_ping_reports_protocol_and_owner(manager):
    _, socket_path, _ = manager
    response = job_client.ping(socket_path)
    assert response["version"] == 1
    assert response["owner_instance_id"] == "owner-new"
    assert response["boot_id"] == "boot-current"


def test_fast_command_finishes_inside_start_request(manager):
    _, socket_path, _ = manager
    response = job_client.start(
        socket_path,
        command="printf manager-fast",
        workdir=Path("/tmp"),
        stdin=None,
        wait_seconds=5,
        call_id="manager-test-call",
    )
    assert response["state"] == "exited"
    state = jobs.job_state(response["job_id"])
    assert state is not None
    assert state["exit_code"] == 0
    assert state["termination_reason"] == "normal_exit"
    assert state["owner_instance_id"] == "owner-new"
    assert jobs.read_log(response["job_id"]) == b"manager-fast"


def test_shell_dollar_expansion_keeps_normal_bash_semantics(manager):
    _, socket_path, _ = manager
    response = job_client.start(
        socket_path,
        command='printf "%s" "$HOME"',
        workdir=Path("/tmp"),
        stdin=None,
        wait_seconds=5,
        call_id="shell-semantics",
    )
    assert response["state"] == "exited"
    assert jobs.read_log(response["job_id"]).decode() == str(Path.home())


def test_large_stdin_is_delivered_without_pipe_deadlock(manager):
    _, socket_path, store = manager
    body = "x" * 200_000
    response = job_client.start(
        socket_path,
        command="wc -c",
        workdir=Path("/tmp"),
        stdin=body,
        wait_seconds=5,
        call_id="large-stdin",
    )
    assert response["state"] == "exited"
    assert jobs.read_log(response["job_id"]).decode().strip() == str(len(body))
    assert (store / response["job_id"] / "stdin").read_text() == body


def test_background_job_is_owned_reaped_and_stoppable(manager):
    _, socket_path, _ = manager
    response = job_client.start(
        socket_path,
        command="sleep 30",
        workdir=Path("/tmp"),
        stdin=None,
        wait_seconds=0.05,
        call_id="background-stop",
    )
    job_id = response["job_id"]
    assert response["state"] == "running"
    assert jobs.job_state(job_id)["state"] == "running"

    stopped = job_client.stop(socket_path, job_id)
    assert stopped["state"] == "exited"
    final = jobs.job_state(job_id)
    assert final is not None
    assert final["state"] == "exited"
    assert final["signal"] == 15
    assert final["exit_code"] is None
    assert final["termination_reason"] == "stop_requested"


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


def test_prepare_classifies_previous_owner_on_same_boot(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    _unfinished(store, "oldowner0001", boot="boot-a", owner="owner-a")
    runtime = JobManager(
        tmp_path / "run" / "jobs.sock",
        owner_instance_id="owner-b",
        boot_id="boot-a",
    )

    assert runtime.prepare() == 1
    state = jobs.job_state("oldowner0001")
    assert state is not None and state["state"] == "exited"
    assert state["exit_code"] is None and state["signal"] is None
    assert state["termination_reason"] == "owner_restart"


def test_prepare_classifies_previous_boot(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    _unfinished(store, "oldboot00001", boot="boot-old", owner="owner-a")
    runtime = JobManager(
        tmp_path / "run" / "jobs.sock",
        owner_instance_id="owner-b",
        boot_id="boot-new",
    )

    assert runtime.prepare() == 1
    state = jobs.job_state("oldboot00001")
    assert state is not None and state["termination_reason"] == "host_reboot"


def test_prepare_leaves_legacy_records_for_legacy_reader(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    directory = store / "legacy000001"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps(
            {"command": "x", "workdir": "/tmp", "pid": 999999, "started_at": 1.0}
        )
    )
    runtime = JobManager(
        tmp_path / "run" / "jobs.sock",
        owner_instance_id="owner-b",
        boot_id="boot-new",
    )

    assert runtime.prepare() == 0
    assert jobs.job_state("legacy000001")["state"] == "unknown"


def test_unavailable_socket_is_a_manager_error(tmp_path):
    with pytest.raises(job_client.JobManagerError, match="unavailable"):
        job_client.ping(tmp_path / "missing.sock")


def test_job_start_log_keeps_mcp_call_id(manager, caplog):
    _, socket_path, _ = manager
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        response = job_client.start(
            socket_path,
            command="true",
            workdir=Path("/tmp"),
            stdin=None,
            wait_seconds=5,
            call_id="call-linked-123",
        )
    assert response["state"] == "exited"
    assert any(
        "event=job_start" in record.getMessage()
        and "call=call-linked-123" in record.getMessage()
        for record in caplog.records
    )


def test_socket_permissions_are_private(manager):
    _, socket_path, _ = manager
    assert os.stat(socket_path).st_mode & 0o777 == 0o600


def test_mcp_job_tools_keep_contract_through_manager(manager, monkeypatch):
    _, socket_path, _ = manager
    monkeypatch.setattr(jobs, "OWNER_MODE", "manager")
    monkeypatch.setattr(jobs, "MANAGER_SOCKET", socket_path)
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)

    fast = run("printf through-manager")
    assert fast["state"] == "exited"
    assert fast["exit_code"] == 0
    assert fast["output"] == "through-manager"
    assert fast["background_job"] is False

    background = run("sleep 30", background=True)
    assert background["state"] == "running"
    assert background["background_job"] is True
    current = status(background["job_id"])
    assert current["state"] == "running"
    final = stop(background["job_id"])
    assert final["state"] == "exited"
    assert final["signal"] == 15


def test_run_command_reports_manager_unavailable_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OWNER_MODE", "manager")
    monkeypatch.setattr(jobs, "MANAGER_SOCKET", tmp_path / "missing.sock")
    with pytest.raises(
        ToolError, match="Could not start the job.*job manager unavailable"
    ):
        run("true")

"""The local durable job manager as an isolated AF_UNIX runtime."""

from __future__ import annotations

import json
import os
import socket
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
        try:
            job_client.ping(socket_path)
        except job_client.JobManagerError:
            time.sleep(0.005)
        else:
            break
    else:
        pytest.fail("job manager did not become ready")
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


def test_mcp_job_tools_keep_contract_through_manager(manager, monkeypatch, caplog):
    _, socket_path, _ = manager
    monkeypatch.setattr(jobs, "OWNER_MODE", "manager")
    monkeypatch.setattr(jobs, "MANAGER_SOCKET", socket_path)
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)

    with caplog.at_level("INFO"):
        fast = run("printf through-manager")
    assert fast["state"] == "exited"
    assert fast["exit_code"] == 0
    assert fast["output"] == "through-manager"
    assert fast["background_job"] is False
    dispatch = next(
        record.getMessage()
        for record in caplog.records
        if "event=run_command_dispatch" in record.getMessage()
    )
    assert "owner=manager owner_instance=owner-new" in dispatch
    assert "handoff_reason=synchronous" in dispatch

    background = run("sleep 30", background=True)
    assert background["state"] == "running"
    assert background["background_job"] is True
    current = status(background["job_id"])
    assert current["state"] == "running"
    final = stop(background["job_id"])
    assert final["state"] == "exited"
    assert final["signal"] == 15


def test_run_command_reports_manager_unavailable_cleanly(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(jobs, "OWNER_MODE", "manager")
    monkeypatch.setattr(jobs, "MANAGER_SOCKET", tmp_path / "missing.sock")
    with (
        caplog.at_level("WARNING", logger="binnacle.run_command"),
        pytest.raises(
            ToolError, match="Could not start the job.*job manager unavailable"
        ),
    ):
        run("true")
    line = next(
        record.getMessage()
        for record in caplog.records
        if "event=run_command_dispatch_error" in record.getMessage()
    )
    assert "owner=manager" in line
    assert "error_class=JobManagerError" in line
    assert "command_hash=" in line and "owner_roundtrip_ms=" in line


def test_two_manager_stop_requests_agree(manager):
    _, socket_path, _ = manager
    started = job_client.start(
        socket_path,
        command="sleep 30",
        workdir=Path("/tmp"),
        stdin=None,
        wait_seconds=0.05,
        call_id="double-stop",
    )
    job_id = started["job_id"]
    barrier = threading.Barrier(3)
    results = []
    errors = []

    def do_stop():
        try:
            barrier.wait()
            results.append(job_client.stop(socket_path, job_id))
        except Exception as exc:  # noqa: BLE001 - the test records both callers
            errors.append(exc)

    threads = [threading.Thread(target=do_stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2 and all(r["state"] == "exited" for r in results)
    final = jobs.job_state(job_id)
    assert final is not None and final["termination_reason"] == "stop_requested"


def test_interrupted_job_has_useful_public_summary(tmp_path, monkeypatch):
    from binnacle.tools import job_status as status_tool
    from binnacle.tools import stop_job as stop_tool

    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    _unfinished(store, "interrupted01", boot="boot-a", owner="owner-a")
    runtime = JobManager(
        tmp_path / "run" / "jobs.sock",
        owner_instance_id="owner-b",
        boot_id="boot-a",
    )
    assert runtime.prepare() == 1

    status_result = status_tool.job_status_impl("interrupted01", 20)
    assert "interrupted (owner_restart)" in str(status_result.content)
    stop_result = stop_tool.stop_job_impl("interrupted01")
    assert "interrupted (owner_restart)" in str(stop_result.content)


def test_systemd_notify_ready_uses_notify_socket(tmp_path, monkeypatch):
    from binnacle import job_manager as manager_module

    path = tmp_path / "notify.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(str(path))
    listener.settimeout(1)
    monkeypatch.setenv("NOTIFY_SOCKET", str(path))
    try:
        manager_module._notify_systemd_ready()
        payload = listener.recv(200)
    finally:
        listener.close()
    assert b"READY=1" in payload
    assert b"Binnacle job manager ready" in payload


def test_owner_auto_selects_manager_only_for_managed_deployment(monkeypatch):
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "auto")
    monkeypatch.delenv("BINNACLE_MANAGED_DEPLOYMENT", raising=False)
    assert jobs._resolve_owner_mode() == "embedded"
    monkeypatch.setenv("BINNACLE_MANAGED_DEPLOYMENT", "1")
    assert jobs._resolve_owner_mode() == "manager"


def test_explicit_owner_setting_overrides_managed_marker(monkeypatch):
    monkeypatch.setenv("BINNACLE_MANAGED_DEPLOYMENT", "1")
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "embedded")
    assert jobs._resolve_owner_mode() == "embedded"
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "manager")
    assert jobs._resolve_owner_mode() == "manager"


def test_disconnected_client_does_not_dump_handler_traceback(manager, caplog):
    _, socket_path, _ = manager
    request = {
        "version": 1,
        "op": "start",
        "command": "sleep 0.1",
        "workdir": "/tmp",
        "stdin": None,
        "wait_seconds": 1,
        "call_id": "disconnect-test",
    }
    wire = json.dumps(request).encode() + b"\n"
    with caplog.at_level("INFO", logger="binnacle.job_manager"):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(socket_path))
        client.sendall(wire)
        client.shutdown(socket.SHUT_RDWR)
        client.close()
        for _ in range(100):
            if any(
                "event=job_manager_client_disconnected" in record.getMessage()
                for record in caplog.records
            ):
                break
            time.sleep(0.01)
    assert any(
        "event=job_manager_client_disconnected op=start call=disconnect-test job_id="
        in record.getMessage()
        for record in caplog.records
    )


def test_invalid_manager_request_logs_operation_and_call(manager, caplog):
    _, socket_path, _ = manager
    request = {"version": 1, "op": "stop", "call_id": "bad-call"}
    with (
        caplog.at_level("WARNING", logger="binnacle.job_manager"),
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client,
    ):
        client.connect(str(socket_path))
        client.sendall(json.dumps(request).encode() + b"\n")
        response = json.loads(client.makefile("rb").readline())
    assert response["ok"] is False
    assert any(
        "event=job_manager_request_invalid op=stop call=bad-call error_class=KeyError"
        in record.getMessage()
        for record in caplog.records
    )


def test_non_object_json_is_reported_as_invalid_request(manager, caplog):
    _, socket_path, _ = manager
    with (
        caplog.at_level("WARNING", logger="binnacle.job_manager"),
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client,
    ):
        client.connect(str(socket_path))
        client.sendall(b"[]\n")
        response = json.loads(client.makefile("rb").readline())
    assert response["ok"] is False
    assert any(
        "event=job_manager_request_invalid op=? call=- error_class=TypeError"
        in record.getMessage()
        for record in caplog.records
    )

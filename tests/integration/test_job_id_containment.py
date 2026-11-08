"""A job_id is a spool path component: only ``new_job_id``'s shape may name a job.

Regression for the v1 ``stop`` path traversal: ``{"op": "stop", "job_id":
"../outside/victim"}`` used to resolve ``meta.json`` outside the job spool and
write ``stop_requested`` into it. Every entry point must refuse such an id
before a path is built, and no file outside the spool may change.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.features.commands import job_client, job_owner, job_store, jobs
from binnacle.features.commands.job_manager import JobManager
from tests.integration.job_test_support import status, stop

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY

REFUSAL = "invalid job-manager request: job_id must be 12 lowercase hex"
ABSOLUTE = object()  # replaced by the victim's absolute directory at run time
INVALID_JOB_IDS = {
    "dotdot_traversal": "../outside/victim",
    "absolute_path": ABSOLUTE,
    "uppercase_hex": "0123456789AB",
    "eleven_chars": "0123456789a",
    "thirteen_chars": "0123456789abc",
    "trailing_newline": "0123456789ab\n",
    "non_str_int": 123,
    "non_str_null": None,
    "non_str_list": ["0123456789ab"],
}
STRING_IDS = {k: v for k, v in INVALID_JOB_IDS.items() if not k.startswith("non_str")}
RECORD = {
    "command": "sleep 60",
    "workdir": "/tmp",
    "pid": 999_999_999,  # above any pid_max: a regression can never signal it
    "started_at": 1.0,
    "schema_version": 2,
    "owner_instance_id": "owner-new",
}


def _resolve(job_id: object, victim: Path) -> object:
    return str(victim) if job_id is ABSOLUTE else job_id


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Content and mtime of every regular file under ``root``."""
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture()
def victim(tmp_path, monkeypatch) -> Path:
    """A complete job record next to (not inside) the spool, plus one real job."""
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    outside = tmp_path / "outside" / "victim"
    outside.mkdir(parents=True)
    (outside / "meta.json").write_text(json.dumps(RECORD))
    (outside / "out.log").write_text("outside log")
    (store / "0123456789ab").mkdir(parents=True)
    job_store.write_meta(store, "0123456789ab", {**RECORD, "exit_code": 0})
    return outside


@pytest.fixture()
def manager(tmp_path, monkeypatch, victim):
    socket_path = tmp_path / "run" / "jobs.sock"
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    runtime = JobManager(
        socket_path, owner_instance_id="owner-new", boot_id="containment-boot"
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
    yield socket_path
    runtime.shutdown()
    thread.join(timeout=3)
    assert not thread.is_alive()


def _raw_request(socket_path: Path, request: dict) -> dict:
    """Send one v1 line as-is; job_client would type-check the id first."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(10)
        conn.connect(str(socket_path))
        conn.sendall(json.dumps(request).encode() + b"\n")
        return json.loads(conn.makefile("rb").readline())


@pytest.mark.parametrize("job_id", INVALID_JOB_IDS.values(), ids=INVALID_JOB_IDS)
def test_v1_stop_refuses_invalid_job_id_without_touching_files(
    manager, victim, tmp_path, caplog, job_id
):
    before = _snapshot(tmp_path)
    request = {
        "version": job_client.PROTOCOL_VERSION,
        "op": "stop",
        "job_id": _resolve(job_id, victim),
        "call_id": "containment",
    }
    with caplog.at_level("WARNING", logger="binnacle.job_manager"):
        reply = _raw_request(manager, request)
    assert reply == {"ok": False, "error": REFUSAL}
    assert _snapshot(tmp_path) == before
    assert "stop_requested" not in json.loads((victim / "meta.json").read_text())
    assert any(
        "event=job_manager_request_invalid op=stop call=containment "
        "error_class=InvalidJobId" in record.getMessage()
        for record in caplog.records
    )


def test_v1_stop_of_valid_absent_id_still_reports_missing_job(manager):
    reply = _raw_request(
        manager,
        {"version": 1, "op": "stop", "job_id": "fedcba987654", "call_id": "x"},
    )
    assert reply == {"ok": False, "error": "no job with id 'fedcba987654'"}


@pytest.mark.parametrize("job_id", STRING_IDS.values(), ids=STRING_IDS)
def test_store_helpers_refuse_invalid_job_id(victim, tmp_path, job_id):
    store, job_id = jobs.JOBS_DIR, _resolve(job_id, victim)
    before = _snapshot(tmp_path)
    assert not job_store.is_valid_job_id(job_id)
    with pytest.raises(job_store.InvalidJobId, match="job_id must be 12 lowercase"):
        job_store.job_dir(store, job_id)
    with pytest.raises(job_store.InvalidJobId):
        job_store.write_meta(store, job_id, {**RECORD, "stop_requested": True})
    assert job_store.read_meta(store, job_id) is None
    assert job_store.read_log(store, job_id) == b""
    with pytest.raises(job_store.JobGone):
        job_store.read_log_range(store, job_id, 0, 100)
    assert job_store.mark_signal_delivery_partial(store, job_id) is False
    job_owner.mark_stop_requested(job_id)
    assert jobs.job_state(job_id) is None
    assert jobs.processes_for_job(job_id) == []
    assert job_owner.stop_job(job_id) is None
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("job_id", STRING_IDS.values(), ids=STRING_IDS)
def test_mcp_job_tools_treat_invalid_job_id_as_unknown(victim, tmp_path, job_id):
    job_id = _resolve(job_id, victim)
    before = _snapshot(tmp_path)
    with pytest.raises(ToolError, match="No job with id"):
        status(job_id)
    with pytest.raises(ToolError, match="No job with id"):
        status(job_id, cursor="start")
    with pytest.raises(ToolError, match="No job with id"):
        stop(job_id)
    assert _snapshot(tmp_path) == before


def test_valid_ids_and_listing_are_unchanged(victim):
    assert job_store.is_valid_job_id(job_store.new_job_id())
    assert job_store.list_job_ids(jobs.JOBS_DIR) == ["0123456789ab"]
    assert [state["job_id"] for state in jobs.list_jobs()] == ["0123456789ab"]

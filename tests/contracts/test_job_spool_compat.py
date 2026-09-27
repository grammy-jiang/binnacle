"""A job spool written in an earlier format stays readable.

tests/contracts/fixtures/job_spool/2026-09-28/ is a spool in the format of
2026-09-28, as the job manager writes it in production (``owner`` manager,
``schema_version`` 2): one finished job and one record of a job that was
still running. The values are synthetic; the key set, the key order and the
JSON form are the writer's (``jobs.start_job`` and ``jobs.record_exit``).
The pids are above the kernel's PID_MAX_LIMIT, so no live process can own
them. ``*.log`` is in .gitignore: the fixture's out.log files are tracked
with ``git add -f``.

The tests copy the spool to a tmp directory and read it through the MCP
client: job_status on each job, and the listing.

Rule: never edit a dated fixture. When the spool format changes, add a new
dated directory beside it (and tests for it) and keep every old one: each
must stay readable by the current code.
"""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle import jobs, server
from binnacle.job_process import _proc_starttime

FIXTURE = Path(__file__).parent / "fixtures" / "job_spool" / "2026-09-28"
FINISHED = "3f9a1c2b7d10"
RUNNING = "8e2d4f6a1b3c"


@pytest.fixture()
def spool(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    shutil.copytree(FIXTURE, root)
    monkeypatch.setattr(jobs, "JOBS_DIR", root)
    return root


def call(name: str, **arguments) -> tuple[dict, str]:
    async def go():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    result = asyncio.run(go())
    assert result.structured_content is not None
    text = "".join(getattr(part, "text", "") for part in result.content)
    return result.structured_content, text


def test_finished_job_reads_as_exited(spool):
    status, text = call("job_status", job_id=FINISHED)
    assert status["state"] == "exited"
    assert (status["exit_code"], status["signal"]) == (0, None)
    assert status["runtime_s"] == 1.5
    assert status["log_tail"] == "fixture: finished job"
    assert status["log_bytes"] == len("fixture: finished job\n")
    assert status["command"] == "printf 'fixture: finished job\\n'"
    assert status["workdir"] == "/tmp/binnacle-spool-fixture"
    assert status["processes"] == []
    assert text == f"Job {FINISHED} exited 0 after 1.5 s."


def test_running_record_without_its_process_reads_as_unknown(spool):
    status, text = call("job_status", job_id=RUNNING)
    assert status["state"] == "unknown"
    assert text == (
        f"Job {RUNNING} state unknown: its process is gone and no exit status "
        "was recorded."
    )
    assert (status["exit_code"], status["signal"]) == (None, None)
    assert status["log_tail"] == "" and status["processes"] == []
    assert status["command"] == "sleep 3600"


def test_listing_reads_both_records_newest_first(spool):
    rows = call("job_status")[0]["jobs"]
    assert [(r["job_id"], r["state"], r["exit_code"]) for r in rows] == [
        (RUNNING, "unknown", None),
        (FINISHED, "exited", 0),
    ]
    assert [r["started_at"] for r in rows] == [1790500100.5, 1790500000.25]


def test_running_record_of_a_live_process_reads_as_running(spool):
    """The same record, pointed at a live process, is a running job."""
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        path = spool / RUNNING / "meta.json"
        meta = json.loads(path.read_text())
        meta.update(pid=proc.pid, pgid=proc.pid, starttime=_proc_starttime(proc.pid))
        path.write_text(json.dumps(meta))
        status, _ = call("job_status", job_id=RUNNING)
        assert status["state"] == "running"
        assert [p["pid"] for p in status["processes"]] == [proc.pid]
        rows = call("job_status")[0]["jobs"]
        assert [(r["job_id"], r["state"]) for r in rows] == [
            (RUNNING, "running"),
            (FINISHED, "exited"),
        ]
    finally:
        proc.kill()
        proc.wait()

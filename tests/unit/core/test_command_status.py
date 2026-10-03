"""Explicit-backend status behavior, including cursor identity and wait ordering."""

import pytest

from binnacle import command_status, jobs
from binnacle.command_contracts import CommandFailure
from binnacle.job_store import JobGone
from tests.command_support import MemoryCommands


def status(backend, job_id="fixed", **kwargs):
    return command_status.job_status(
        job_id,
        100,
        backend=backend,
        quiet_after_s=2,
        history_limit=1,
        preview_chars=20,
        wait_max=2,
        **kwargs,
    )


def test_fake_status_does_not_read_store_or_scan_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real engine reached")

    for name in (
        "job_state",
        "read_log",
        "read_log_range",
        "job_processes",
        "await_exit",
        "list_jobs",
    ):
        monkeypatch.setattr(jobs, name, forbidden)
    backend = MemoryCommands()
    reply = status(backend, wait_seconds=9)
    assert backend.calls == [
        ("state", "fixed"),
        ("wait", "fixed", 2),
        ("log", "fixed"),
        ("processes", 42, 200),
    ]
    assert reply.payload["quiet"] is True
    assert reply.payload["wait_requested_s"] == 9
    assert reply.payload["wait_effective_s"] == 2
    assert reply.payload["log_tail"] == "ready"
    assert reply.payload["processes"] == [
        {"pid": 42, "state": "S", "etime_s": 3, "cpu_s": 0, "cmd": "probe"}
    ]
    assert reply.summary.startswith(
        "Job fixed running but quiet for 2.0 s (3.0 s total)."
    )


def test_fake_listing_keeps_running_jobs_and_bounded_history():
    backend = MemoryCommands()
    backend.rows = [
        {**backend.state, "job_id": "old", "state": "exited"},
        backend.state,
        {**backend.state, "job_id": "omitted", "state": "unknown"},
    ]
    reply = status(backend, None)
    assert [row["job_id"] for row in reply.payload["jobs"]] == ["old", "fixed"]
    assert (
        reply.summary
        == "2 of 3 job(s) shown, newest first: all 1 running plus up to 1 recent non-running jobs."
    )
    assert backend.calls == [("list",)]


def test_cursor_uses_byte_offsets_and_defers_running_utf8_suffix():
    backend = MemoryCommands()
    backend.output = b"A\xf0\x9f"
    reply = status(backend, cursor="start")
    assert reply.payload["log_delta"] == "A"
    assert reply.payload["delta_start"] == 0
    assert reply.payload["delta_end"] == 1
    assert reply.payload["next_cursor"] == "v1:fixed:1"
    assert reply.payload["has_more"] is False
    assert "log_tail" not in reply.payload
    backend.state["state"] = "exited"
    final = status(backend, cursor=reply.payload["next_cursor"])
    assert final.payload["log_delta"] == "\ufffd"
    assert final.payload["delta_end"] == 3
    assert final.payload["processes"] == []


@pytest.mark.parametrize(
    "cursor,message",
    [
        ("wrong", "Invalid cursor: expected 'start', 'end', or v1:<job_id>:<offset>."),
        ("v1:other:0", "cursor belongs to job other, not fixed"),
        ("v1:fixed:99", "cursor beyond end of output"),
    ],
)
def test_exact_cursor_failures(cursor, message):
    with pytest.raises(CommandFailure) as caught:
        status(MemoryCommands(), cursor=cursor)
    assert str(caught.value) == message


def test_cursor_requires_job_before_backend_access():
    backend = MemoryCommands()
    with pytest.raises(CommandFailure, match="^cursor requires job_id$"):
        status(backend, None, cursor="start")
    assert backend.calls == []


def test_job_gone_keeps_its_identity_and_translates_without_cause(monkeypatch):
    backend = MemoryCommands()
    failure = JobGone("fixed")

    def gone(*args):
        raise failure

    monkeypatch.setattr(backend, "read_log_range", gone)
    with pytest.raises(CommandFailure) as caught:
        status(backend, cursor="start")
    assert (
        str(caught.value)
        == "No job with id 'fixed'. Call job_status without a job_id to list recent jobs."
    )
    assert caught.value.__context__ is failure
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_missing_after_positive_wait_is_the_same_unknown_job_error(monkeypatch):
    backend = MemoryCommands()
    monkeypatch.setattr(backend, "await_exit", lambda *args: None)
    with pytest.raises(CommandFailure) as caught:
        status(backend, wait_seconds=1)
    assert (
        str(caught.value)
        == "No job with id 'fixed'. Call job_status without a job_id to list recent jobs."
    )
    assert backend.calls == [("state", "fixed")]

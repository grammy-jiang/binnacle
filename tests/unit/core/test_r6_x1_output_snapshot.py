"""r6 X1: Linux output and output_bytes describe ONE log snapshot (SD-67).

The Linux engine measures the log size in ``jobs.job_state`` and the tools
read the text afterwards, so a burst landing between the two made a reply's
byte count disagree with its text. The durable backend now pins the next log
read of a job to the size its state measured (append-only prefix), as r5 L2c
did for the Darwin manager. A hook appends to the log right after every size
read, so each test forces the race deterministically on every OS.
"""

import json
import time
from pathlib import Path

import pytest

from binnacle.config import RunCommandSettings
from binnacle.features.commands import (
    command_execution,
    command_status,
    job_owner,
    jobs,
)
from binnacle.features.commands.command_backend import DurableCommandBackend

JOB = "aaaaaaaaaaaa"
OTHER = "bbbbbbbbbbbb"


def _spool(root: Path, job_id: str, text: bytes) -> Path:
    directory = root / job_id
    directory.mkdir(parents=True)
    meta = {
        "command": "burst",
        "workdir": "/tmp",
        "pid": 7,
        "started_at": time.time(),
        "ended_at": time.time(),
        "exit_code": 0,
    }
    (directory / "meta.json").write_text(json.dumps(meta))
    (directory / "out.log").write_bytes(text)
    return directory / "out.log"


@pytest.fixture
def burst(tmp_path, monkeypatch):
    """A spooled job whose log grows by one burst after every size read."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    log = _spool(tmp_path / "jobs", JOB, b"m1\n")
    measure = jobs.job_state
    bursts = iter(range(2, 1000))

    def racing_state(job_id):
        state = measure(job_id)
        with log.open("ab") as out:
            out.write(f"m{next(bursts)}\n".encode())  # lands before the text read
        return state

    monkeypatch.setattr(jobs, "job_state", racing_state)
    return log


def _status(job_id, **kwargs):
    return command_status.job_status(
        job_id,
        10_000,
        backend=DurableCommandBackend(),
        quiet_after_s=2,
        history_limit=1,
        preview_chars=20,
        wait_max=2,
        **kwargs,
    ).payload


def test_run_command_output_bytes_counts_its_own_output(burst, monkeypatch):
    monkeypatch.setattr(job_owner, "start_and_wait", lambda *args: JOB)
    payload = command_execution.run_command(
        "burst",
        Path("/tmp"),
        5,
        False,
        None,
        backend=DurableCommandBackend(),
        settings=RunCommandSettings(),
    ).payload
    assert payload["state"] == "exited"
    assert payload["output_bytes"] == len(payload["output"].encode()) == 3
    assert payload["output"] == "m1\n"
    assert payload["truncated"] is False
    assert burst.read_bytes() == b"m1\nm2\n"  # the burst landed, unreported


@pytest.mark.parametrize(
    "wait_seconds,size,tail",
    [(0, 3, "m1"), (1, 6, "m1\nm2")],  # a wait measures again: its state wins
)
def test_job_status_tail_is_the_log_its_bytes_measure(burst, wait_seconds, size, tail):
    payload = _status(JOB, wait_seconds=wait_seconds)
    assert payload["log_bytes"] == size
    assert payload["log_tail"] == tail


def test_job_status_cursors_end_where_their_bytes_end(burst):
    start = _status(JOB, cursor="start")
    assert (start["delta_start"], start["delta_end"], start["log_bytes"]) == (0, 3, 3)
    assert start["log_delta"] == "m1\n"
    assert start["has_more"] is False
    following = _status(JOB, cursor=start["next_cursor"])  # m2 is on disk now
    assert (following["delta_start"], following["delta_end"]) == (3, 6)
    assert following["log_bytes"] == 6
    assert following["log_delta"] == "m2\n"
    end = _status(JOB, cursor="end")
    assert (end["delta_start"], end["delta_end"], end["log_bytes"]) == (9, 9, 9)


def test_log_reads_return_the_prefix_their_state_measured(tmp_path, monkeypatch):
    """The pairing itself: only the next read of that same job is pinned."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    log = _spool(tmp_path / "jobs", JOB, b"m1\n")
    _spool(tmp_path / "jobs", OTHER, b"b\n")
    backend = DurableCommandBackend()
    assert backend.job_state(JOB)["log_bytes"] == 3
    with log.open("ab") as out:
        out.write(b"m2\n")
    assert backend.read_log(JOB) == b"m1\n"
    assert backend.read_log(JOB) == b"m1\nm2\n"  # consumed: unpaired
    backend.job_state(JOB)
    with log.open("ab") as out:
        out.write(b"m3\n")
    assert backend.read_log_range(JOB, 3, 100) == (b"m2\n", 6)
    assert backend.await_exit(JOB, 0)["log_bytes"] == 9  # a waited state pins too
    with log.open("ab") as out:
        out.write(b"m4\n")
    assert backend.read_log(JOB) == b"m1\nm2\nm3\n"
    backend.job_state(OTHER)  # another job's state never pins this one
    assert backend.read_log_range(JOB, 0, 100) == (b"m1\nm2\nm3\nm4\n", 12)
    backend.job_state(JOB)
    log.write_bytes(b"")  # not append-only any more: never invent a prefix
    assert backend.read_log_range(JOB, 0, 100) == (b"", 0)
    assert backend.read_log(JOB) == b""

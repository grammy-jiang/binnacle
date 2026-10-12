"""r6 W2 X1e (SD-74): the snapshot size is a value, never backend state.

Closes SR5-F3, RX1-F1 and SR6-N2. Both command backends (the Linux
``DurableCommandBackend`` and the Darwin ``DarwinManagerCommandBackend``,
here over the real spool store and a fake manager client) keep no per-thread
or per-instance size. The tools pass the ``log_bytes`` of the state they
render to the log read. These tests fail against the thread-local pins:
two jobs measured on one thread before one read, and a state that no read
of its job followed, both changed what a later read returned.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from binnacle.config import RunCommandSettings
from binnacle.features.commands import (
    command_backend,
    command_execution,
    command_status,
    jobs,
)
from binnacle.features.commands.command_backend import (
    DarwinManagerCommandBackend,
    DurableCommandBackend,
)
from binnacle.features.commands.command_contracts import (
    read_log_range_snapshot,
    read_log_snapshot,
    snapshot_size,
)

A, B = "aaaaaaaaaaaa", "bbbbbbbbbbbb"
BIG = 10_000_000
DARWIN_FIELDS = {
    "jobs_dir",
    "_socket_path",
    "release_states",
    "warmup_s",
    "max_output_chars",
    "client",
    "bindings",
}


class _ReachableClient:
    """The manager answers; start and stop are never called here."""

    def ping(self, socket_path):
        return {"ok": True}


def _spool(root: Path, job_id: str, text: bytes) -> Path:
    directory = root / job_id
    directory.mkdir(parents=True)
    now = time.time()
    meta = {
        "command": "burst",
        "workdir": "/tmp",
        "pid": 7,
        "started_at": now,
        "ended_at": now,
        "exit_code": 0,
    }
    (directory / "meta.json").write_text(json.dumps(meta))
    (directory / "out.log").write_bytes(text)
    return directory / "out.log"


def _grow(log: Path, line: bytes) -> None:
    with log.open("ab") as out:
        out.write(line)


@pytest.fixture(params=["linux", "darwin"])
def spool(request, tmp_path, monkeypatch):
    """(backend, logs) over one temp job spool, for each backend class."""
    root = tmp_path / "jobs"
    logs = {A: _spool(root, A, b"a1\n"), B: _spool(root, B, b"b1\nb2\n")}
    if request.param == "linux":
        monkeypatch.setattr(jobs, "JOBS_DIR", root)
        return DurableCommandBackend(), logs
    from binnacle.application import manager_bindings

    backend = DarwinManagerCommandBackend(
        jobs_dir=root,
        socket_path=tmp_path / "jobs.sock",
        release_states={},
        warmup_s=0.25,
        max_output_chars=50_000_000,
        client=_ReachableClient(),
        bindings=manager_bindings(),
    )
    return backend, logs


def _fields(backend) -> dict:
    return dict(vars(backend)) if hasattr(backend, "__dict__") else {}


def test_backends_hold_no_snapshot_state(spool):
    backend, _ = spool
    assert not hasattr(command_backend, "threading")
    if isinstance(backend, DurableCommandBackend):
        assert DurableCommandBackend.__slots__ == ()
        assert not hasattr(backend, "__dict__")
    else:
        assert set(vars(backend)) == DARWIN_FIELDS
    before = _fields(backend)
    backend.job_state(A)
    backend.await_exit(B, 0)
    backend.list_jobs()
    backend.read_log(A)
    backend.read_log_range(B, 0, BIG)
    if isinstance(backend, DarwinManagerCommandBackend):
        backend.stop_job(A)  # exited: a state read, no RPC
    assert _fields(backend) == before
    assert not any(isinstance(v, threading.local) for v in before.values())


def test_no_state_call_changes_a_later_read(spool):
    """A state that no read of its job followed cannot leak (stale pin)."""
    backend, logs = spool
    backend.job_state(A)
    backend.job_state(B)
    backend.await_exit(A, 0)
    backend.list_jobs()
    _grow(logs[A], b"a2\n")
    _grow(logs[B], b"b3\n")
    with ThreadPoolExecutor(max_workers=1) as worker:
        for read in (lambda f, *a: f(*a), lambda f, *a: worker.submit(f, *a).result()):
            assert read(backend.read_log, A) == b"a1\na2\n"
            assert read(backend.read_log, B) == b"b1\nb2\nb3\n"
            assert read(backend.read_log_range, A, 0, BIG) == (b"a1\na2\n", 6)
            assert read(backend.read_log_range, B, 3, BIG) == (b"b2\nb3\n", 9)


def _interleave(monkeypatch, backend, logs) -> list[str]:
    """Measuring A also measures B on the SAME thread, then both logs grow.

    With a thread-local pin, B's state replaced A's pin, so A's read was
    unpinned and returned the bursts its log_bytes never counted.
    """
    measured: list[str] = []
    cls = type(backend)
    original = cls.job_state

    def interleaved(self, job_id):
        state = original(self, job_id)
        measured.append(job_id)
        if job_id == A:
            original(self, B)
            measured.append(B)
        _grow(logs[A], b"a-burst\n")
        _grow(logs[B], b"b-burst\n")
        return state

    monkeypatch.setattr(cls, "job_state", interleaved)
    monkeypatch.setattr(cls, "start_and_wait", lambda self, *args: A)
    return measured


def _status(backend, job_id, **kwargs) -> dict:
    return command_status.job_status(
        job_id,
        BIG,
        backend=backend,
        quiet_after_s=2,
        history_limit=1,
        preview_chars=20,
        wait_max=2,
        **kwargs,
    ).payload


def test_two_interleaved_jobs_on_one_thread_keep_their_own_snapshot(spool, monkeypatch):
    backend, logs = spool
    measured = _interleave(monkeypatch, backend, logs)

    run = command_execution.run_command(
        "burst",
        Path("/tmp"),
        5,
        False,
        None,
        backend=backend,
        settings=RunCommandSettings(),
    ).payload
    assert (run["output"], run["output_bytes"]) == ("a1\n", 3)

    tail = _status(backend, A)
    assert (tail["log_tail"], tail["log_bytes"]) == ("a1\na-burst", 11)

    start = _status(backend, A, cursor="start")
    assert (start["delta_start"], start["delta_end"], start["log_bytes"]) == (0, 19, 19)
    assert start["log_delta"] == "a1\na-burst\na-burst\n"
    assert start["has_more"] is False

    end = _status(backend, A, cursor="end")
    assert (end["delta_start"], end["delta_end"], end["log_bytes"]) == (27, 27, 27)

    assert measured == [A, B] * 4
    final = logs[A].read_bytes()
    assert final == b"a1\n" + b"a-burst\n" * 4  # every reply was a strict prefix


def test_snapshot_size_accepts_only_a_measured_integer():
    assert snapshot_size({"log_bytes": 7}) == 7
    assert snapshot_size({"log_bytes": 0}) == 0
    assert snapshot_size({"log_bytes": None}) is None
    assert snapshot_size({"log_bytes": "7"}) is None
    assert snapshot_size({}) is None
    assert snapshot_size(None) is None


def test_snapshot_reads_never_invent_a_prefix(spool):
    backend, logs = spool
    _grow(logs[A], b"a2\n")
    assert read_log_snapshot(backend, A, None) == b"a1\na2\n"
    assert read_log_snapshot(backend, A, 3) == b"a1\n"
    assert read_log_range_snapshot(backend, A, 0, BIG, 3) == (b"a1\n", 3)
    assert read_log_range_snapshot(backend, A, 0, 0, 3) == (b"", 3)  # "end" seed
    # A cursor beyond the measured size reads the open file as it is.
    assert read_log_range_snapshot(backend, A, 4, BIG, 3) == (b"2\n", 6)
    logs[A].write_bytes(b"")  # truncated: not append-only, the open size wins
    assert read_log_range_snapshot(backend, A, 0, BIG, 3) == (b"", 0)

"""RL1 (DARWIN-FOLLOWUP-reaper-blocking-lock): a held jobs-dir ``.lock`` never
stalls reaping. The reaper's record acquire is bounded; a busy lock queues the
exit for the per-job retry, exactly as an OSError does. Portable: the reference
owner and ``fcntl.flock`` behave the same on Linux and Darwin (no A3 IPC).
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import pytest

from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    req,
)

HOLD_S = 4.0  # the external holder keeps .lock this long at most
PROMPT_S = 2.0  # every exit is reaped well inside the hold

# An independent process (not this manager) holds <jobs_dir>/.lock LOCK_EX until
# its stdin closes, or HOLD_S at most; it never needs a signal to end.
HOLDER = """
import fcntl, os, select, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
select.select([sys.stdin], [], [], float(sys.argv[2]))
"""

# Exits with $2 once the go file $1 exists; gives up after ~30 s (97).
GATED = (
    "i=0; while [ ! -e {go} ] && [ $i -lt 3000 ]; do sleep 0.01; i=$((i+1)); "
    "done; [ -e {go} ] && exit {code}; exit 97"
)


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


@contextmanager
def external_lock_holder(jobs_dir):
    """Spawn the holder; release it by closing stdin; only its exact pid."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(jobs_dir / ".lock"), str(HOLD_S)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline() == b"held\n"
        yield holder
    finally:
        release(holder)


def release(holder):
    if holder.stdin is not None and not holder.stdin.closed:
        holder.stdin.close()
    try:
        holder.wait(timeout=HOLD_S + 5)
    except subprocess.TimeoutExpired:  # our own Popen child: exact pid only
        holder.kill()
        holder.wait()
    if holder.stdout is not None:
        holder.stdout.close()


@pytest.fixture
def reaping(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "EXIT_RETRY_S", 0.05)
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,), name="rp")
    reaper.start()
    try:
        yield owner, manager
    finally:
        halt.set()
        reaper.join(timeout=HOLD_S + 5)
        manager.close()
    assert not reaper.is_alive()


def gated(tmp_path, name, code):
    return GATED.format(go=tmp_path / f"go-{name}", code=code)


def rlock_held_elsewhere(manager):
    if not manager._lock.acquire(blocking=False):
        return True
    manager._lock.release()
    return False


def assert_not_exited_yet(manager, jobs_dir, job_ids):
    for job_id in job_ids:
        assert not svc._terminal(meta_of(jobs_dir, job_id))  # no false exit
        assert manager.state(job_id) == "unknown"  # never "exited" before durable


def test_held_jobs_lock_never_stalls_reaping(tmp_path, reaping):
    owner, manager = reaping
    jobs_dir = tmp_path / "jobs"
    codes = {"a": 3, "b": 4, "c": 5, "d": 6}
    jobs = {
        n: manager.handle(req(tmp_path, gated(tmp_path, n, c)))["job_id"]
        for n, c in codes.items()
    }
    control = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    with external_lock_holder(jobs_dir) as holder:
        held_at = time.monotonic()
        (tmp_path / "go-a").touch()  # the reaper now tries to record "a"
        assert wait_for(lambda: jobs["a"] not in owner.live, PROMPT_S)
        for name in "bcd":
            (tmp_path / f"go-{name}").touch()
        # Base: the reaper blocks in record_exit("a") on the flock; b-d stay
        # unreaped until the holder lets go.
        assert wait_for(lambda: set(owner.live) == {control}, PROMPT_S)
        assert time.monotonic() - held_at < HOLD_S  # reaped while still held
        assert holder.poll() is None
        assert wait_for(lambda: set(manager._unrecorded) == set(jobs.values()))
        assert_not_exited_yet(manager, jobs_dir, jobs.values())
        assert manager.state(control) == "running"
    # The lock frees: every queued exit becomes durable, none lost or doubled.
    assert wait_for(lambda: not manager._unrecorded)
    for name, job_id in jobs.items():
        meta = meta_of(jobs_dir, job_id)
        assert (meta["exit_code"], meta["termination_reason"]) == (
            codes[name],
            "normal_exit",
        )
        assert manager.state(job_id) == "exited"
    assert owner.released == set(jobs.values())  # released only once durable
    assert not svc._terminal(meta_of(jobs_dir, control))  # no false exit
    assert manager.state(control) == "running"
    late = manager.handle(req(tmp_path, "exit 9"))["job_id"]
    assert wait_for(lambda: "exit_code" in meta_of(jobs_dir, late))
    assert meta_of(jobs_dir, late)["exit_code"] == 9


def test_handler_blocked_in_transaction_never_stalls_reaping(tmp_path, reaping):
    # A handler waiting on the flock holds the manager RLock; the reaper's
    # bounded acquire must give up on the RLock too, and queue without it.
    owner, manager = reaping
    jobs_dir = tmp_path / "jobs"
    first = manager.handle(req(tmp_path, gated(tmp_path, "x", 7)))["job_id"]
    second = manager.handle(req(tmp_path, gated(tmp_path, "y", 8)))["job_id"]
    replies = []
    with external_lock_holder(jobs_dir):
        start = threading.Thread(
            target=lambda: replies.append(manager.handle(req(tmp_path, "exit 2")))
        )
        start.start()  # blocks in _launch's _transaction, holding the RLock
        assert wait_for(lambda: rlock_held_elsewhere(manager)) and not replies
        (tmp_path / "go-x").touch()
        assert wait_for(lambda: first not in owner.live, PROMPT_S)
        (tmp_path / "go-y").touch()
        assert wait_for(lambda: second not in owner.live, PROMPT_S)
        assert wait_for(lambda: {first, second} <= set(manager._unrecorded))
        assert_not_exited_yet(manager, jobs_dir, (first, second))
        assert not replies  # the handler path is unchanged: it still waits
    start.join(timeout=HOLD_S + 5)
    assert replies and replies[0]["ok"] is True
    assert wait_for(lambda: not manager._unrecorded)
    for job_id, code in ((first, 7), (second, 8)):
        assert meta_of(jobs_dir, job_id)["exit_code"] == code
    late = replies[0]["job_id"]
    assert wait_for(lambda: "exit_code" in meta_of(jobs_dir, late))
    assert meta_of(jobs_dir, late)["exit_code"] == 2


def test_busy_lost_record_is_kept_until_durable(tmp_path):
    # persist_lost runs on the reaper thread: a busy lock keeps the loss for
    # the next pass instead of blocking, and never drops it.
    owner = ReferenceOwner()
    jobs_dir = tmp_path / "jobs"
    manager = manager_for(owner, jobs_dir)
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    lost = [job_id]
    owner.take_lost = lambda: [lost.pop()] if lost else []
    owner.release = lambda job: None
    try:
        with external_lock_holder(jobs_dir):
            started = time.monotonic()
            assert manager.persist_lost(svc.REAPER_LOCK_WAIT_S) == 1
            assert time.monotonic() - started < 1.0  # bounded, not blocked
            assert "authority" not in meta_of(jobs_dir, job_id)
            assert manager.persist_lost(svc.REAPER_LOCK_WAIT_S) == 0
        assert manager.persist_lost(svc.REAPER_LOCK_WAIT_S) == 0
        meta = meta_of(jobs_dir, job_id)
        assert (meta["authority"], meta["termination_reason"]) == (
            "UNKNOWN",
            "owner_restart",
        )
    finally:
        manager.close()

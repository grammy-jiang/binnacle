"""RLF2 (R-RL1-F2, SD-83 c): close() persists BOTH queues, once, without a deadlock.

An external process holds ``<jobs_dir>/.lock`` until the reaper has queued exits
in ``_unrecorded`` and a loss is pending in ``_lost_pending``; the reaper is then
halted and joined, the holder released, and ``close()`` runs. Every exit must be
durable with its exact code, every loss recorded once, nothing ``exited`` before
it is durable. Portable like the RL1 tests: the reference owner and
``fcntl.flock`` behave the same on Linux and Darwin.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    req,
)
from tests.platform.darwin.test_r6w3_rl1_reaper_lock import GATED, HOLDER, wait_for

HOLD_S = 30.0  # a backstop only: the holder ends when its stdin closes
CLOSE_BOUND_S = 15.0  # close() must finish well inside this: no deadlock
EXITS = {"a": 3, "b": 4, "c": 5}


@contextmanager
def lock_holder(jobs_dir):
    """An independent process holds .lock LOCK_EX; only its exact Popen pid."""
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


def terminal_writes(manager, monkeypatch):
    """Count every meta.json write that makes a record terminal, per job."""
    writes: dict[str, list[dict]] = {}
    original = manager._write_meta

    def counting(job_id, meta):
        if svc._terminal(meta):
            writes.setdefault(job_id, []).append(dict(meta))
        original(job_id, meta)

    monkeypatch.setattr(manager, "_write_meta", counting)
    return writes


def test_close_persists_queued_exits_and_pending_losses(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "EXIT_RETRY_S", 0.05)
    jobs_dir = tmp_path / "jobs"
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, jobs_dir), threading.Event()
    writes = terminal_writes(manager, monkeypatch)
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,), name="rp")
    reaper.start()
    holder, lost_pid = None, None
    try:
        jobs = {
            name: manager.handle(
                req(
                    tmp_path,
                    GATED.format(go=tmp_path / f"go-{name}", code=code),
                )
            )["job_id"]
            for name, code in EXITS.items()
        }
        lost = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
        control = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
        with owner.cond:  # the owner lost the lost job's process (ECHILD-like)
            lost_pid = owner.live.pop(lost)
        handed_over: list[str] = []  # the loss is reported only once the lock is held
        owner.take_lost = lambda: [handed_over.pop()] if handed_over else []

        with lock_holder(jobs_dir) as holder:
            handed_over.append(lost)
            for name in EXITS:
                (tmp_path / f"go-{name}").touch()
            # The reaper reaps every exit but cannot record: all of them queue,
            # and the loss stays pending (persist_lost ran on the busy lock).
            assert wait_for(lambda: set(manager._unrecorded) == set(jobs.values()))
            assert wait_for(lambda: manager._lost_pending == [lost])
            assert holder.poll() is None
            halt.set()
            reaper.join(timeout=10)
            assert not reaper.is_alive()
            # Nothing is durable, and nothing claims "exited" before it is.
            assert not writes
            for job_id in (*jobs.values(), lost):
                assert not svc._terminal(meta_of(jobs_dir, job_id))
                assert manager.state(job_id) == "unknown"
            assert manager.state(control) == "running"
            assert set(manager._unrecorded) == set(jobs.values())
            assert manager._lost_pending == [lost]
        # The holder is gone: close() now runs with both queues non-empty.
        closed: list = []
        closer = threading.Thread(
            target=lambda: closed.append(manager.close()), name="cl", daemon=True
        )
        started = time.monotonic()
        closer.start()
        closer.join(timeout=CLOSE_BOUND_S)
        assert not closer.is_alive(), "close() deadlocked"
        assert time.monotonic() - started < CLOSE_BOUND_S
    finally:
        halt.set()
        reaper.join(timeout=10)
        if holder is not None:
            release(holder)
        manager.close()
        if lost_pid is not None:  # our recorded pid, never a pattern: reap it
            try:
                os.killpg(lost_pid, signal.SIGKILL)
                os.waitpid(lost_pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass

    assert not manager._unrecorded  # every queued exit became durable
    for name, job_id in jobs.items():
        meta = meta_of(jobs_dir, job_id)
        assert (meta["exit_code"], meta["termination_reason"]) == (
            EXITS[name],
            "normal_exit",
        )
        assert manager.state(job_id) == "exited"
    loss = meta_of(jobs_dir, lost)  # the loss: UNKNOWN authority, no exit invented
    assert (loss["authority"], loss["termination_reason"]) == (
        "UNKNOWN",
        "owner_restart",
    )
    assert loss["exit_code"] is None and manager.state(lost) == "unknown"
    stopped = meta_of(jobs_dir, control)  # the still-live job close() terminated
    assert stopped["termination_reason"] == "owner_restart"
    # Each record was written terminal exactly once: no double record anywhere.
    assert {job: len(w) for job, w in writes.items()} == dict.fromkeys(
        (*jobs.values(), lost, control), 1
    )
    again = [meta_of(jobs_dir, j) for j in (*jobs.values(), lost, control)]
    manager.persist_lost()  # idempotent: the pending loss is already terminal
    assert manager.retry_unrecorded() == 0
    assert again == [meta_of(jobs_dir, j) for j in (*jobs.values(), lost, control)]
    assert {job: len(w) for job, w in writes.items()} == dict.fromkeys(
        (*jobs.values(), lost, control), 1
    )

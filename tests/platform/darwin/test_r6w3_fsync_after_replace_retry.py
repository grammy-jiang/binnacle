"""R6W3 P2: a replaced terminal JSON is NOT durable until directory fsync.

Synthetic EIO is injected on the directory descriptor after the actual
test-owned os.replace. No production jobs, sockets, signals or credentials.
Retry must fsync and log one durable exit even when the JSON is already
visible as terminal. It must never release ownership before confirmed sync.
"""

from __future__ import annotations

import errno
import os
import stat
import threading
from contextlib import contextmanager

import pytest

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    write_record,
)


@pytest.mark.parametrize("initial_sync_failures", [1, 2])
def test_terminal_replace_then_fsync_eio_retries_to_durable_once(
    tmp_path, monkeypatch, initial_sync_failures
):
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "test-owned-jobs")
    job_id = "fsyncretry123"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )

    events = []
    monkeypatch.setattr(
        svc,
        "log_job_exit",
        lambda _logger, name, meta, directory: events.append((name, meta, directory)),
    )
    original_fsync = os.fsync
    syncs = []
    remaining = [initial_sync_failures]

    def injected_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            syncs.append(fd)
            if remaining[0] > 0:
                remaining[0] -= 1
                raise OSError(errno.EIO, "synthetic directory fsync error")
        original_fsync(fd)

    monkeypatch.setattr(svc.os, "fsync", injected_fsync)
    assert manager.record_exit(exited) is False
    # Atomic replace is visible but durability is NOT yet confirmed.
    assert meta_of(manager.jobs_dir, job_id)["exit_code"] == 0
    assert job_id in manager._unrecorded
    assert job_id not in owner.released
    assert events == []
    assert manager.state(job_id) == "unknown"  # visible is not durable
    assert manager.job_counts() == (0, 1)
    assert manager.handle({"version": 1, "op": "stop", "job_id": job_id}) == {
        "ok": True,
        "job_id": job_id,
        "state": "unknown",
    }
    assert len(syncs) == 1

    for _ in range(initial_sync_failures - 1):
        assert manager.retry_unrecorded() == 1
        assert job_id in manager._unrecorded
        assert job_id not in owner.released
        assert events == []
        assert manager.state(job_id) == "unknown"

    assert manager.retry_unrecorded() == 0
    assert len(syncs) == initial_sync_failures + 1
    assert job_id not in manager._unrecorded
    assert job_id in owner.released
    assert manager.state(job_id) == "exited"
    assert manager.job_counts() == (0, 0)
    assert len(events) == 1
    assert events[0][0] == job_id
    assert events[0][1]["termination_reason"] == "normal_exit"
    assert events[0][2] == manager.jobs_dir / job_id

    # Duplicate reaper/close notification is idempotent: no second log/ack.
    assert manager.record_exit(exited)
    assert len(events) == 1
    assert len(syncs) == initial_sync_failures + 1
    assert manager.retry_unrecorded() == 0


def test_failed_sync_enqueues_before_writer_lock_released(tmp_path, monkeypatch):
    """The replay marker must be published atomically with a failed commit."""
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "serial-owned-jobs")
    job_id = "concurrent123"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    original_fsync = os.fsync
    failed = [False]

    def fsync_once(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed[0]:
            failed[0] = True
            raise OSError(errno.EIO, "synthetic post-replace failure")
        return original_fsync(fd)

    monkeypatch.setattr(svc.os, "fsync", fsync_once)
    entered, allowed = threading.Event(), threading.Event()
    real_queue = manager._queue
    result = []

    def hold_first_queue(item):
        if threading.current_thread() is worker:
            entered.set()
            assert allowed.wait(5), "the test's queue gate was never released"
        return real_queue(item)

    monkeypatch.setattr(manager, "_queue", hold_first_queue)
    worker = threading.Thread(
        target=lambda: result.append(manager.record_exit(exited)),
        name="test-owned-writer",
    )
    worker.start()
    try:
        assert entered.wait(5), "fsync failure did not reach the retry queue"
        # The other writer must not see the replaced terminal JSON while the
        # first writer has not atomically marked its directory fsync failure.
        acquired = manager._lock.acquire(blocking=False)
        if acquired:
            manager._lock.release()
        assert not acquired, "transaction was unlocked before failed sync queued"
    finally:
        allowed.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert result == [False]
    assert manager._is_queued(job_id)
    assert manager.state(job_id) == "unknown"
    assert manager.retry_unrecorded() == 0
    assert not manager._is_queued(job_id)
    assert manager.state(job_id) == "exited"


def test_two_writers_racing_failed_sync_never_resurrect_pending_exit(
    tmp_path, monkeypatch
):
    """A duplicate writer can finish before the first catches OSError."""
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "race-owned-jobs")
    job_id = "concurrent-next"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    fsync = os.fsync
    failed = [False]

    def injected(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed[0]:
            failed[0] = True
            raise OSError(errno.EIO, "test-owned once-only sync error")
        fsync(fd)

    monkeypatch.setattr(svc.os, "fsync", injected)
    results = {"first": [], "second": []}
    events = []
    monkeypatch.setattr(
        svc, "log_job_exit", lambda *_args: events.append("durable_terminal")
    )
    hold, allowed, attempted = (threading.Event(), threading.Event(), threading.Event())
    original_queue = manager._queue

    def delaying_queue(value):
        if threading.current_thread() is first:
            hold.set()
            assert allowed.wait(5)
        return original_queue(value)

    monkeypatch.setattr(manager, "_queue", delaying_queue)
    first = threading.Thread(
        target=lambda: results["first"].append(manager.record_exit(exited))
    )
    second = threading.Thread(
        target=lambda: (
            attempted.set(),
            results["second"].append(manager.record_exit(exited)),
        )
    )
    first.start()
    try:
        assert hold.wait(5)
        second.start()
        assert attempted.wait(5)
    finally:
        allowed.set()
        first.join(timeout=5)
        second.join(timeout=5)
    assert not first.is_alive() and not second.is_alive()
    assert results == {"first": [False], "second": [True]}
    assert manager.retry_unrecorded() == 0
    assert manager.state(job_id) == "exited"
    assert len(events) == 1
    assert owner.released == {job_id}


def test_stale_lock_timeout_cannot_resurrect_already_acknowledged_exit(
    tmp_path, monkeypatch
):
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "test-owned-timeout")
    job_id = "expired-writer"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    logged = []
    monkeypatch.setattr(svc, "log_job_exit", lambda *_: logged.append(job_id))
    held, resume = threading.Event(), threading.Event()
    actual_queue = manager._queue
    actual_transaction = manager._transaction
    results = []

    @contextmanager
    def test_transaction(wait_s=None):
        if threading.current_thread() is timed_out:
            raise BlockingIOError(errno.EAGAIN, "synthetic lock timeout")
        with actual_transaction(wait_s):
            yield

    def hold_queue(value):
        if threading.current_thread() is timed_out:
            held.set()
            assert resume.wait(5), "test timed out before releasing stale writer"
        return actual_queue(value)

    monkeypatch.setattr(manager, "_transaction", test_transaction)
    monkeypatch.setattr(manager, "_queue", hold_queue)
    timed_out = threading.Thread(
        target=lambda: results.append(manager.record_exit(exited, wait_s=0.01)),
        name="test-owned-expired-writer",
    )
    timed_out.start()
    try:
        assert held.wait(5), "timed out writer must reach queue gate"
        assert manager.record_exit(exited) is True
        assert logged == [job_id]
        assert job_id in owner.released
        assert manager.state(job_id) == "exited"
    finally:
        resume.set()
        timed_out.join(timeout=5)
    assert not timed_out.is_alive()
    assert results == [False]
    assert not manager._is_queued(job_id)
    assert manager.retry_unrecorded() == 0
    assert manager.state(job_id) == "exited"
    assert logged == [job_id]


def test_prune_never_deletes_terminal_json_pending_directory_sync(
    tmp_path, monkeypatch
):
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "test-owned-retention", keep=1)
    job_id = "pending-prune"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    original = os.fsync
    failed = [False]
    logged = []

    def fail_directory_once(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed[0]:
            failed[0] = True
            raise OSError(errno.EIO, "test-owned durability failure")
        return original(fd)

    monkeypatch.setattr(svc.os, "fsync", fail_directory_once)
    monkeypatch.setattr(svc, "log_job_exit", lambda *_args: logged.append(job_id))
    assert manager.record_exit(exited) is False
    directory = manager.jobs_dir / job_id
    assert directory.is_dir()
    assert manager.state(job_id) == "unknown"
    assert job_id not in owner.released
    assert manager._is_queued(job_id)

    # Launch's retention runs while holding the same writer transaction.
    with manager._transaction():
        manager._prune(reserve=1)
    assert directory.is_dir(), "a queued exit is not safely deletable"
    assert manager.retry_unrecorded() == 0
    assert manager.state(job_id) == "exited"
    assert logged == [job_id]

    # Only now may retention remove the confirmed terminal record.
    with manager._transaction():
        manager._prune(reserve=1)
    assert not directory.exists()
    assert not manager._is_queued(job_id)
    assert logged == [job_id]
    manager._queue(exited)
    assert not manager._is_queued(job_id), "late stale notification revived exit"


def test_visible_terminal_before_directory_sync_is_still_unknown(tmp_path, monkeypatch):
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "test-owned-before-sync")
    job_id = "visible-before-sync"
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    original = os.fsync
    entered, resume = threading.Event(), threading.Event()
    logged = []
    monkeypatch.setattr(svc, "log_job_exit", lambda *_: logged.append(job_id))

    def held_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            entered.set()
            assert resume.wait(5), "test-owned sync gate held too long"
        return original(fd)

    monkeypatch.setattr(svc.os, "fsync", held_sync)
    finished = []
    worker = threading.Thread(
        target=lambda: finished.append(manager.record_exit(exited)),
        name="test-owned-syncer",
    )
    worker.start()
    try:
        assert entered.wait(5)
        assert meta_of(manager.jobs_dir, job_id)["exit_code"] == 0
        assert manager.state(job_id) == "unknown"
        assert manager.job_counts() == (0, 1)
        assert (
            manager.handle({"version": 1, "op": "stop", "job_id": job_id})["state"]
            == "unknown"
        )
        assert not owner.released
        assert logged == []
    finally:
        resume.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert finished == [True]
    assert manager.state(job_id) == "exited"
    assert logged == [job_id]

"""Final P2 repros: pending metadata read, bounded completion memory, owner ack.

All I/O uses pytest-owned directories. Synthetic failures never touch launchd
services, real jobs or the production state root.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import threading

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    write_record,
)


def _owned_exit(tmp_path, *, owner=None, job_id="state-review001"):
    owner = owner or ReferenceOwner()
    manager = manager_for(owner, tmp_path / "review-jobs")
    exited = pc.OwnedJobExit(job_id, 0, None, "normal_exit")
    owner.exits[job_id] = exited
    write_record(
        manager.jobs_dir,
        job_id,
        owner_instance_id=owner.owner_instance_id,
        boot_id=manager.boot_id,
    )
    return manager, owner, exited


def _fail_directory_sync_once(monkeypatch):
    original = os.fsync
    failed = [False]

    def sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed[0]:
            failed[0] = True
            raise OSError(errno.EIO, "test-only EIO after replace")
        return original(fd)

    monkeypatch.setattr(svc.os, "fsync", sync)


def test_pending_exit_survives_transient_unreadable_meta(tmp_path, monkeypatch, caplog):
    manager, owner, exited = _owned_exit(tmp_path)
    _fail_directory_sync_once(monkeypatch)
    emitted = []
    monkeypatch.setattr(
        svc,
        "log_job_exit",
        lambda _logger, job_id, meta, directory: emitted.append(job_id),
    )
    assert manager.record_exit(exited) is False
    assert manager._is_queued(exited.job_id)
    assert meta_of(manager.jobs_dir, exited.job_id)["exit_code"] == 0

    original = manager._meta
    calls = [0]

    def unavailable_once(job_id):
        calls[0] += 1
        if calls[0] == 1:
            return None  # read_meta catches OSError as None
        return original(job_id)

    monkeypatch.setattr(manager, "_meta", unavailable_once)
    with caplog.at_level(logging.WARNING):
        assert manager.retry_unrecorded() >= 1
    assert manager._is_queued(exited.job_id), "transient read lost a pending fsync"
    assert exited.job_id not in owner.released
    assert manager.state(exited.job_id) == "unknown"
    assert emitted == []
    assert manager.retry_unrecorded() == 0
    assert not manager._is_queued(exited.job_id)
    assert exited.job_id in owner.released
    assert emitted == [exited.job_id]
    assert manager.state(exited.job_id) == "exited"


def test_completion_replay_cache_stays_bounded_under_many_successes(tmp_path):
    manager, _, _ = _owned_exit(tmp_path)
    for index in range(10_000):
        manager._dequeue(f"test-{index:05}", committed=True)
    assert len(manager._acknowledged_exits) <= 2_048, (
        "one completed ID per job leaks memory indefinitely"
    )


def test_release_os_error_logs_terminal_once_and_retries_ack(
    tmp_path, monkeypatch, caplog
):
    manager, owner, exited = _owned_exit(tmp_path)
    original_release = owner.release
    called = []

    def fail_once(job_id):
        called.append(job_id)
        if len(called) == 1:
            raise OSError(errno.EIO, "test-only failed release")
        return original_release(job_id)

    monkeypatch.setattr(owner, "release", fail_once)
    emitted = []
    monkeypatch.setattr(
        svc, "log_job_exit", lambda _logger, job_id, *_: emitted.append(job_id)
    )
    with caplog.at_level(logging.WARNING):
        assert manager.record_exit(exited) is True
    assert manager.state(exited.job_id) == "exited"
    assert emitted == [exited.job_id]
    assert exited.job_id not in owner.released
    assert manager.retry_unrecorded() == 0
    assert exited.job_id in owner.released
    assert emitted == [exited.job_id]
    assert called == [exited.job_id, exited.job_id]
    assert "test-only failed release" not in caplog.text


def test_stale_writer_pin_survives_bounded_history_eviction(tmp_path, monkeypatch):
    """More than 2k successful jobs cannot evict an in-flight stale writer."""
    manager, _, exited = _owned_exit(tmp_path)
    gate, resume = threading.Event(), threading.Event()
    original_queue = manager._queue
    outcomes = []

    def queue_delayed(item):
        if threading.current_thread() is blocked:
            gate.set()
            assert resume.wait(5), "stale writer did not resume"
        return original_queue(item)

    real_transaction = manager._transaction

    from contextlib import contextmanager

    @contextmanager
    def artificial_busy(wait_s=None):
        if threading.current_thread() is blocked:
            raise BlockingIOError(errno.EAGAIN, "synthetic lock deadline")
        with real_transaction(wait_s):
            yield

    monkeypatch.setattr(manager, "_queue", queue_delayed)
    monkeypatch.setattr(manager, "_transaction", artificial_busy)
    blocked = threading.Thread(
        target=lambda: outcomes.append(manager.record_exit(exited, wait_s=0.001))
    )
    blocked.start()
    try:
        assert gate.wait(5)
        assert manager.record_exit(exited) is True
        # Commits by other concurrently active jobs exceed the cache limit,
        # yet this job stays pinned by its unfinished attempt.
        for i in range(4_500):
            manager._dequeue(f"new-job-{i:05}", committed=True)
        assert exited.job_id in manager._acknowledged_exits
    finally:
        resume.set()
        blocked.join(timeout=5)
    assert not blocked.is_alive()
    assert outcomes == [False]
    assert not manager._is_queued(exited.job_id)
    assert manager.state(exited.job_id) == "exited"
    assert len(manager._acknowledged_exits) <= 2_048
    assert manager._active_attempts == {}


def test_reaper_batch_pins_direct_queue_even_under_history_churn(tmp_path, monkeypatch):
    """Reaper's busy path is also in-flight, not a stale naked queue call."""
    manager, owner, exited = _owned_exit(tmp_path)
    first = pc.OwnedJobExit("preceding-busy", 1, None, "normal_exit")
    began, resume = threading.Event(), threading.Event()
    real_queue = manager._queue
    completed = []

    def hold_queue(item):
        if threading.current_thread() is worker and item.job_id == exited.job_id:
            began.set()
            assert resume.wait(5)
        return real_queue(item)

    def record(_item, _wait_s):
        return None  # first lock busy: the remainder is queued, not blocked

    monkeypatch.setattr(manager, "_queue", hold_queue)
    worker = threading.Thread(
        target=lambda: (
            manager._process_reaped_batch((first, exited), record, 0.05),
            completed.append(True),
        )
    )
    worker.start()
    try:
        assert began.wait(5)
        assert manager.record_exit(exited)
        for i in range(4_500):
            manager._dequeue(f"reaped-other-{i:05}", committed=True)
        assert exited.job_id in manager._acknowledged_exits
    finally:
        resume.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert completed == [True]
    assert manager.state(exited.job_id) == "exited"
    assert not manager._is_queued(exited.job_id)
    assert exited.job_id in owner.released
    assert len(manager._acknowledged_exits) <= 2_048


def test_reaper_retries_owner_ack_even_when_no_unsynced_exits(tmp_path, monkeypatch):
    manager, owner, exited = _owned_exit(tmp_path)
    called = []
    original = owner.release

    def one_error(job_id):
        called.append(job_id)
        if len(called) == 1:
            raise OSError(errno.EIO, "test-only ack error")
        return original(job_id)

    monkeypatch.setattr(owner, "release", one_error)
    assert manager.record_exit(exited)
    assert manager._ack_pending == {exited.job_id}
    assert not manager._unrecorded
    stop = threading.Event()

    def reap(_timeout):
        stop.set()
        return []

    monkeypatch.setattr(owner, "reap_exits", reap)
    monkeypatch.setattr(manager, "persist_lost", lambda *_args: 0)
    manager.reap_forever(stop)
    assert manager._ack_pending == set()
    assert exited.job_id in owner.released
    assert called == [exited.job_id, exited.job_id]

"""Independent P2 regression: snapshot pin and durable owner ack backpressure.

Only synthetic test-owned manager objects are created. The retry operation
uses memory-only fake records and never writes or releases production jobs.
"""

from __future__ import annotations

from collections import OrderedDict

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_queue as queue
from tests.platform.darwin.test_job_manager_service import ReferenceOwner, manager_for


def _manager(tmp_path):
    return manager_for(ReferenceOwner(), tmp_path / "synthetic-jobs")


def test_pending_retry_snapshot_pins_every_exit_before_processing(
    tmp_path, monkeypatch
):
    manager = _manager(tmp_path)
    last = "queued-00999"
    jobs = [
        pc.OwnedJobExit(f"queued-{i:05}", 0, None, "normal_exit") for i in range(1_000)
    ]
    manager._unrecorded = {item.job_id: item for item in jobs}
    manager._acknowledged_exits = OrderedDict([(last, None)])
    # 3x the recent history limit: eviction MUST preserve the still-pending
    # final writer from this batch, even if thousands of other commits occur.
    seen = []

    def process(item, _wait_s):
        seen.append(item.job_id)
        if item.job_id == last:
            manager._queue(item)  # stale timeout from snapshot after commit
            return None
        if item.job_id == jobs[0].job_id:
            # Another writer commits J early, after the retry snapshot was
            # captured but before most of the 5k unrelated commits.
            manager._dequeue(last, committed=True)
        manager._dequeue(item.job_id, committed=True)
        for j in range(5):
            manager._dequeue(f"completed-{item.job_id}-{j}", committed=True)
        return True

    monkeypatch.setattr(manager, "_record_guarded", process)
    assert manager.retry_unrecorded() == 0
    assert len(seen) == len(jobs)
    assert seen[-1] == last
    assert last not in manager._unrecorded
    assert manager._active_attempts == {}
    assert len(manager._acknowledged_exits) <= queue.ACK_HISTORY_LIMIT


def test_permanent_ack_failures_trigger_bounded_fail_closed(tmp_path, caplog):
    manager = _manager(tmp_path)
    assert not manager.stopping.is_set()
    # Direct synthetic ack failures must not scale the in-memory set with the
    # lifetime job count, even if an erroneous caller keeps submitting.
    for i in range(queue.ACK_BACKLOG_LIMIT + 25):
        manager._ack_later(f"failed-ack-{i:05}")
    assert len(manager._ack_pending) == queue.ACK_BACKLOG_LIMIT
    assert manager.stopping.is_set()
    assert "event=job_release_backlog_exceeded" in caplog.text


def test_ack_retry_is_bounded_and_backed_off(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    clock = [10_000.0]
    monkeypatch.setattr(queue.time, "monotonic", lambda: clock[0])
    attempts = []

    def failed(_job):
        attempts.append(_job)
        raise OSError("synthetic persistent owner failure")

    monkeypatch.setattr(manager.owner, "release", failed)
    for i in range(queue.ACK_RETRY_BATCH * 3):
        manager._ack_later(f"failed-ack-{i:05}")
    previous = len(attempts)
    manager._retry_acks()
    assert len(attempts) - previous <= queue.ACK_RETRY_BATCH
    first = attempts[0]
    # Newly failed ack is deferred; immediate rapid reaper ticks cannot emit
    # another attempt for the same ID, or spin through the entire backlog.
    manager._retry_acks()
    assert attempts.count(first) == 1
    assert len(manager._ack_pending) == queue.ACK_RETRY_BATCH * 3
    clock[0] += 60.0
    manager._retry_acks()
    assert attempts.count(first) >= 2
    assert not manager.stopping.is_set()

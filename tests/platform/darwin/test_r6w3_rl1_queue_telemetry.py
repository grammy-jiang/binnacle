"""R-RL1-F1/F5: queued exit observability and bounded lock backoff."""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

from binnacle.diagnostics.job_manager_doctor import check_job_manager
from binnacle.platform.darwin import job_manager_records as records
from tests.platform.darwin.test_job_manager_service import ReferenceOwner, manager_for


def test_pending_queue_ages_once_and_does_not_count_a_reregistered_exit(tmp_path):
    manager = manager_for(ReferenceOwner(), tmp_path / "jobs")
    try:
        exited = SimpleNamespace(job_id="a")
        manager._queue(exited)
        seen = manager.handle({"version": 1, "op": "ping"})
        assert seen["unrecorded_exits"] == 1
        assert isinstance(seen["manager_python_version"], str)
        assert type(seen["manager_waitid_available"]) is bool
        assert isinstance(seen["oldest_unrecorded_age_s"], float)
        started = manager._unrecorded_since["a"]
        manager._queue(exited)
        assert manager._unrecorded_since["a"] == started
        manager._queue(SimpleNamespace(job_id="b"))
        summary = manager.handle({"version": 1, "op": "ping"})
        assert summary["unrecorded_exits"] == 2
        assert summary["oldest_unrecorded_age_s"] >= seen["oldest_unrecorded_age_s"]
        manager._dequeue("a")
        manager._dequeue("b")
        empty = manager.handle({"version": 1, "op": "ping"})
        assert empty["unrecorded_exits"] == 0
        assert empty["oldest_unrecorded_age_s"] is None
    finally:
        manager.close()


def test_one_busy_record_does_not_lose_the_rest_and_logs_reason(
    tmp_path, monkeypatch, caplog
):
    manager = manager_for(ReferenceOwner(), tmp_path / "jobs")
    stopped = threading.Event()
    exits = [SimpleNamespace(job_id="a"), SimpleNamespace(job_id="b")]
    seen = []

    def reap(_timeout):
        stopped.set()
        return exits

    def record(exited, wait):
        seen.append(exited.job_id)
        manager._queue(exited)

    monkeypatch.setattr(manager.owner, "reap_exits", reap)
    monkeypatch.setattr(manager, "_record_guarded", record)
    monkeypatch.setattr(manager, "persist_lost", lambda *_: 0)
    # Retry should not accidentally mark the undurable exit durable in this test.
    monkeypatch.setattr(manager, "retry_unrecorded", lambda *_: 2)
    try:
        with caplog.at_level(logging.WARNING, logger="binnacle.job_manager"):
            manager.reap_forever(stopped)
        assert seen == ["a"]
        assert set(manager._unrecorded) == {"a", "b"}
        assert "event=job_exit_unrecorded job_id=b reason=busy" in caplog.text
        assert manager.handle({"version": 1, "op": "ping"})["unrecorded_exits"] == 2
    finally:
        manager.close()


def test_doctor_exposes_queue_without_claiming_an_exit(tmp_path):
    class Inspector:
        def status(self, _unit):
            return SimpleNamespace(state="active", restart_count=0)

    checks, unit = check_job_manager(
        "com.binnacle.jobs",
        tmp_path / "socket",
        Inspector(),
        ping=lambda _: {
            "owner_instance_id": "owner",
            "package_version": "1.0.1",
            "revision": "abc123",
            "unrecorded_exits": 2,
            "oldest_unrecorded_age_s": 4.25,
        },
        expected_revision="abc123",
    )
    assert unit == "com.binnacle.jobs"
    pending = [c for c in checks if "queued but not yet durable" in c.detail]
    assert len(pending) == 1
    assert pending[0].status == "warn"
    assert "do not restart" in pending[0].hint


def test_bounded_lock_backoff_never_waits_past_deadline(tmp_path, monkeypatch):
    ticks = [0.0]
    sleeps = []

    def clock():
        return ticks[0]

    def nap(seconds):
        assert seconds > 0
        sleeps.append(seconds)
        ticks[0] += seconds

    def held(_fd, _operation):
        raise BlockingIOError(11, "synthetic busy lock")

    monkeypatch.setattr(records.time, "monotonic", clock)
    monkeypatch.setattr(records.time, "sleep", nap)
    monkeypatch.setattr(records.fcntl, "flock", held)
    with (
        pytest.raises(BlockingIOError),
        records._flock_bounded(tmp_path / "locked", 0.10),
    ):
        pytest.fail("synthetic lock unexpectedly acquired")
    assert len(sleeps) >= 4
    assert max(sleeps) > records.LOCK_POLL_S
    assert sum(sleeps) <= 0.101
    assert ticks[0] <= 0.101


def test_lock_refuses_a_retry_after_sleeping_past_deadline(tmp_path, monkeypatch):
    ticks, calls = [0.0], [0]

    def flock(_fd, _op):
        calls[0] += 1
        if calls[0] == 1:
            raise BlockingIOError(11, "busy")

    def nap(seconds):
        ticks[0] += seconds + 0.2

    monkeypatch.setattr(records.time, "monotonic", lambda: ticks[0])
    monkeypatch.setattr(records.time, "sleep", nap)
    monkeypatch.setattr(records.fcntl, "flock", flock)
    with (
        pytest.raises(BlockingIOError),
        records._flock_bounded(tmp_path / "late", 0.01),
    ):
        pytest.fail("past-deadline acquire returned success")
    assert calls == [1]


def test_lock_rechecks_a_delayed_success(tmp_path, monkeypatch):
    ticks, calls = [0.0], [0]

    def flock(_fd, _op):
        calls[0] += 1
        if calls[0] == 1:
            raise BlockingIOError(11, "busy")
        ticks[0] = 0.2  # lock grant occurred after the caller's deadline

    monkeypatch.setattr(records.time, "monotonic", lambda: ticks[0])
    monkeypatch.setattr(
        records.time, "sleep", lambda seconds: ticks.__setitem__(0, ticks[0] + seconds)
    )
    monkeypatch.setattr(records.fcntl, "flock", flock)
    with (
        pytest.raises(BlockingIOError),
        records._flock_bounded(tmp_path / "late-success", 0.02),
    ):
        pytest.fail("late lock success became a durable record")
    assert calls == [2]

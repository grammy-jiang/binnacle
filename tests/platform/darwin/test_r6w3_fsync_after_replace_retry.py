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

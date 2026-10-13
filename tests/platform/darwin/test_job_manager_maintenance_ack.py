"""Authenticated Manager ping augmentation is coherent with job-start lock.

The real production Manager leaves this hook disabled. Only fake Jobs owners
and private test directories are used; no launchd or real Job is touched.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from pathlib import Path

import pytest

from binnacle.platform.darwin.job_manager_maintenance_fence import ManagerStartFence
from binnacle.platform.darwin.job_manager_service import PROTOCOL_VERSION
from tests.platform.darwin.test_job_manager_maintenance_fence import (
    NONCE,
    _launch,
    _manager,
    _record,
    _write,
)


def _enable(mgr, root: Path) -> ManagerStartFence:
    fence = ManagerStartFence(
        root, owner_instance_id=mgr.owner_instance_id, pid=os.getpid()
    )
    mgr.maintenance_fence = fence.refusal
    mgr.maintenance_probe = lambda reply: fence.synchronized_ping(mgr, reply)
    return fence


def _ping(mgr) -> dict:
    return mgr.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})


def test_default_off_ping_schema_is_unchanged(tmp_path: Path) -> None:
    mgr, _, root = _manager(tmp_path)
    mgr.maintenance_fence = None
    assert mgr.maintenance_probe is None
    root.rmdir()
    response = _ping(mgr)
    assert response["ok"] is True
    assert "maintenance_admission" not in response
    assert response["running_jobs"] == 0
    assert response["unknown_jobs"] == 0


def test_enabled_without_request_exposes_absent_not_approved(tmp_path: Path) -> None:
    mgr, _, root = _manager(tmp_path)
    _enable(mgr, root)
    reply = _ping(mgr)
    assert reply["ok"] is True
    assert reply["maintenance_admission"] == {"state": "absent", "nonce": None}
    assert reply["running_jobs"] == 0


def test_pause_ack_requires_exact_manager_nonce_and_owner(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    _write(root, owner.owner_instance_id)
    reply = _ping(mgr)
    assert reply["maintenance_admission"] == {"state": "paused", "nonce": NONCE}
    assert reply["owner_instance_id"] == owner.owner_instance_id
    assert reply["pid"] == os.getpid()
    assert reply["running_jobs"] == 0
    assert reply["unknown_jobs"] == 0
    denied = _launch(mgr, tmp_path)
    assert isinstance(denied, dict)
    assert denied["code"] == "maintenance_paused"
    assert owner.spawned == []


def test_corrupt_or_foreign_request_is_unknown_in_ack_and_rejected_on_start(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    _write(root, owner.owner_instance_id, nonce="x" * 32)
    reply = _ping(mgr)
    assert reply["maintenance_admission"] == {"state": "unknown", "nonce": None}
    refused = _launch(mgr, tmp_path)
    assert isinstance(refused, dict)
    assert refused["code"] == "maintenance_state_unknown"
    assert not owner.spawned


def test_manager_ping_counts_reflect_jobs_spawned_before_pause(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    assert isinstance(_launch(mgr, tmp_path), str)
    _write(root, owner.owner_instance_id)
    response = _ping(mgr)
    assert response["maintenance_admission"]["state"] == "paused"
    assert response["running_jobs"] == 1
    assert response["unknown_jobs"] == 0
    assert len(owner.spawned) == 1
    # The pause refuses a second job but doesn't terminate the first one.
    denied = _launch(mgr, tmp_path)
    assert isinstance(denied, dict)
    assert denied["code"] == "maintenance_paused"
    assert len(owner.spawned) == 1


def test_ping_recomputes_stale_counts_under_manager_creation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mgr, owner, root = _manager(tmp_path)
    fence = _enable(mgr, root)
    original_counts = mgr.job_counts
    reads = [0]

    def changing():
        reads[0] += 1
        lock = mgr.jobs_dir / ".lock"
        if reads[0] >= 2:
            with lock.open("r+b") as other, pytest.raises(BlockingIOError):
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return (100, 3) if reads[0] == 1 else original_counts()

    monkeypatch.setattr(mgr, "job_counts", changing)
    response = _ping(mgr)
    assert reads == [2]
    assert response["running_jobs"] == 0
    assert response["unknown_jobs"] == 0
    assert response["maintenance_admission"]["state"] == "absent"
    assert fence.owner_instance_id == owner.owner_instance_id


def test_ping_with_wrong_manager_incarnation_never_acknowledges_pause(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _write(root, owner.owner_instance_id)
    impostor = ManagerStartFence(root, owner_instance_id="f" * 32, pid=os.getpid())
    mgr.maintenance_probe = lambda reply: impostor.synchronized_ping(mgr, reply)
    response = _ping(mgr)
    assert response["maintenance_admission"] == {"state": "unknown", "nonce": None}
    assert response["running_jobs"] == 0


def test_ping_joins_external_transaction_after_pause_published(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    started = threading.Event()
    finished = threading.Event()
    answers: list[dict] = []

    with mgr._transaction():

        def ping_worker():
            started.set()
            try:
                answers.append(_ping(mgr))
            finally:
                finished.set()

        thread = threading.Thread(target=ping_worker, daemon=True)
        thread.start()
        assert started.wait(timeout=3)
        _write(root, owner.owner_instance_id)
        assert not finished.wait(timeout=0.08)
    assert finished.wait(timeout=3)
    thread.join(timeout=3)
    assert answers[0]["maintenance_admission"] == {"state": "paused", "nonce": NONCE}


def test_ping_probe_rejection_cannot_be_converted_to_success(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    path = root / "request.json"
    path.write_bytes(b"broken state")
    path.chmod(0o600)
    result = _ping(mgr)
    assert result["ok"] is True  # authenticated RPC succeeded
    assert result["maintenance_admission"]["state"] == "unknown"
    assert result["maintenance_admission"]["nonce"] is None
    assert isinstance(_launch(mgr, tmp_path), dict)
    assert not owner.spawned


def test_dispatch_unsupported_op_cannot_mutate_pause_state(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    path = _write(root, owner.owner_instance_id)
    existing = path.read_bytes()
    response = mgr.dispatch({"version": PROTOCOL_VERSION, "op": "maintenance_resume"})
    assert not response["ok"]
    assert path.read_bytes() == existing


def test_resume_after_external_removal_only_changes_next_ping(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    marker = _write(root, owner.owner_instance_id)
    assert _ping(mgr)["maintenance_admission"]["state"] == "paused"
    marker.unlink()
    assert _ping(mgr)["maintenance_admission"]["state"] == "absent"
    assert isinstance(_launch(mgr, tmp_path), str)


def test_controller_publishes_private_request_atomically_under_jobs_lock(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _enable(mgr, root)
    target = root / "request.json"
    data = json.dumps(_record(owner.owner_instance_id)).encode()
    with mgr._transaction():
        temp = root / ".request-fixture.tmp"
        temp.write_bytes(data)
        temp.chmod(0o600)
        os.replace(temp, target)
        assert target.read_bytes() == data
    result = _ping(mgr)
    assert result["maintenance_admission"] == {"state": "paused", "nonce": NONCE}
    assert result["running_jobs"] == 0

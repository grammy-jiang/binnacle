"""Fail-closed, transaction-scoped Jobs Manager maintenance reader.

No real launchd, Jobs Manager process, Binnacle job or production lock is used.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin.job_manager_maintenance_fence import (
    MaintenanceObservation,
    ManagerStartFence,
)
from binnacle.platform.darwin.job_manager_service import DarwinJobManager

NONCE = "a" * 32


class FakeJobOwner:
    def __init__(self) -> None:
        self.owner_instance_id = uuid.uuid4().hex
        self.spawned: list[str] = []

    def spawn(self, job_id, argv, *, workdir, env, stdin, output):
        self.spawned.append(job_id)
        return pc.OwnedJobProcess(
            job_id,
            12000 + len(self.spawned),
            12000 + len(self.spawned),
            1,
            self.owner_instance_id,
            "boot",
        )

    def authority(self, job_id):
        return pc.OwnedJobObservation(job_id, "OWNED", True, "fixture")


def _manager(tmp_path: Path) -> tuple[DarwinJobManager, FakeJobOwner, Path]:
    jobs = tmp_path / "jobs"
    jobs.mkdir(mode=0o700)
    owner = FakeJobOwner()
    manager = DarwinJobManager(
        owner=cast(Any, owner),
        jobs_dir=jobs,
        boot_id="boot",
        wait_max_s=12,
        keep_newest=50,
    )
    fence_root = tmp_path / "maintenance"
    fence_root.mkdir(mode=0o700)
    manager.maintenance_fence = ManagerStartFence(
        fence_root, owner_instance_id=owner.owner_instance_id, pid=os.getpid()
    ).refusal
    return manager, owner, fence_root


def _record(owner: str, **changed: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "version": 1,
        "nonce": NONCE,
        "owner_instance_id": owner,
        "pid": os.getpid(),
        "until": time.time() + 80,
        "scope": "jobs",
    }
    obj.update(changed)
    return obj


def _write(root: Path, owner: str, **changed: object) -> Path:
    path = root / "request.json"
    path.write_text(json.dumps(_record(owner, **changed)), encoding="utf-8")
    path.chmod(0o600)
    return path


def _launch(manager: DarwinJobManager, working: Path):
    return manager._launch("synthetic", working, None, "-", working)


def _no_job_was_reserved(manager: DarwinJobManager, owner: FakeJobOwner) -> None:
    assert not owner.spawned
    assert not any(p.is_dir() for p in manager.jobs_dir.iterdir())


def test_default_off_manager_does_not_use_any_fence(tmp_path: Path) -> None:
    mgr, owner, fence_root = _manager(tmp_path)
    mgr.maintenance_fence = None
    fence_root.rmdir()
    assert isinstance(_launch(mgr, tmp_path), str)
    assert len(owner.spawned) == 1


def test_missing_request_on_explicit_private_fence_is_legacy_start(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    assert not (root / "request.json").exists()
    assert isinstance(_launch(mgr, tmp_path), str)
    assert len(owner.spawned) == 1


def test_valid_pause_refuses_before_prune_or_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _write(root, owner.owner_instance_id)

    def unexpected_prune(*args, **kwargs):
        pytest.fail("paused launch must not touch durable job history")

    monkeypatch.setattr(mgr, "_prune", unexpected_prune)
    response = _launch(mgr, tmp_path)
    assert isinstance(response, dict)
    assert response == {
        "ok": False,
        "code": "maintenance_paused",
        "error": "job manager maintenance: new starts temporarily refused",
        "retryable": True,
    }
    _no_job_was_reserved(mgr, owner)


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"version": 2}, "unknown"),
        ({"version": True}, "unknown"),
        ({"nonce": "x" * 32}, "unknown"),
        ({"nonce": "A" * 32}, "unknown"),
        ({"owner_instance_id": "b" * 32}, "unknown"),
        ({"owner_instance_id": True}, "unknown"),
        ({"pid": 12345}, "unknown"),
        ({"pid": True}, "unknown"),
        ({"scope": "mcp"}, "unknown"),
        ({"until": time.time() + 700}, "unknown"),
        ({"until": time.time() - 700}, "unknown"),
        ({"until": "later"}, "unknown"),
        ({"until": True}, "unknown"),
        ({"unexpected": True}, "unknown"),
    ],
)
def test_bad_request_cannot_be_mistaken_for_absent(
    tmp_path: Path, changed: dict[str, object], reason: str
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _write(root, owner.owner_instance_id, **changed)
    response = _launch(mgr, tmp_path)
    assert isinstance(response, dict)
    assert response["code"] == "maintenance_state_unknown"
    assert reason in response["error"]
    _no_job_was_reserved(mgr, owner)


@pytest.mark.parametrize("bytes_", [b"", b"x" * 513, b"{", b"[]", b'{"a":1,"a":2}'])
def test_malformed_request_is_unknown_and_blocks_job_creation(
    tmp_path: Path, bytes_: bytes
) -> None:
    mgr, owner, root = _manager(tmp_path)
    path = root / "request.json"
    path.write_bytes(bytes_)
    path.chmod(0o600)
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    _no_job_was_reserved(mgr, owner)


@pytest.mark.parametrize("damage", ["symlink", "hardlink", "public", "directory"])
def test_unsafe_request_identity_never_allows_a_start(
    tmp_path: Path, damage: str
) -> None:
    mgr, owner, root = _manager(tmp_path)
    path = root / "request.json"
    other = root / "private-foreign.json"
    other.write_text(json.dumps(_record(owner.owner_instance_id)))
    other.chmod(0o600)
    if damage == "symlink":
        path.symlink_to(other)
    elif damage == "hardlink":
        os.link(other, path)
    elif damage == "directory":
        path.mkdir()
    else:
        _write(root, owner.owner_instance_id).chmod(0o644)
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    _no_job_was_reserved(mgr, owner)


def test_unknown_when_fence_directory_is_missing_or_public(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    root.rmdir()
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    root.mkdir(mode=0o700)
    root.chmod(0o755)
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    _no_job_was_reserved(mgr, owner)


def test_symlinked_fence_root_is_unknown(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    real = root.with_name("real-fence")
    root.rename(real)
    root.symlink_to(real, target_is_directory=True)
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    _no_job_was_reserved(mgr, owner)


@pytest.mark.parametrize("pid_delta", [-1, 1])
def test_reader_must_be_bound_to_current_process_pid(
    tmp_path: Path, pid_delta: int
) -> None:
    mgr, owner, root = _manager(tmp_path)
    _write(root, owner.owner_instance_id)
    mgr.maintenance_fence = ManagerStartFence(
        root,
        owner_instance_id=owner.owner_instance_id,
        pid=os.getpid() + pid_delta,
    ).refusal
    response = _launch(mgr, tmp_path)
    assert (
        isinstance(response, dict) and response["code"] == "maintenance_state_unknown"
    )
    _no_job_was_reserved(mgr, owner)


@pytest.mark.parametrize("state", ["bogus", "absent", "unknown"])
def test_forged_observation_cannot_hold_a_nonce(state: str) -> None:
    if state == "bogus":
        with pytest.raises(ValueError, match="unknown"):
            MaintenanceObservation(state)
    else:
        with pytest.raises(ValueError, match="nonce"):
            MaintenanceObservation(state, nonce=NONCE)


def test_reader_checks_under_same_job_transaction_flock(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    fence = ManagerStartFence(
        root, owner_instance_id=owner.owner_instance_id, pid=os.getpid()
    )
    count = [0]

    def verify_lock():
        count[0] += 1
        lock = mgr.jobs_dir / ".lock"
        with lock.open("r+b") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fence.refusal()

    mgr.maintenance_fence = verify_lock
    assert isinstance(_launch(mgr, tmp_path), str)
    assert count == [1]
    assert len(owner.spawned) == 1


def test_writer_creating_request_inside_same_transaction_lock_wins_race(
    tmp_path: Path,
) -> None:
    mgr, owner, root = _manager(tmp_path)
    opened = threading.Event()
    finished = threading.Event()
    output: list[object] = []

    with mgr._transaction():

        def newcomer():
            opened.set()
            try:
                output.append(_launch(mgr, tmp_path))
            finally:
                finished.set()

        other = threading.Thread(target=newcomer, daemon=True)
        other.start()
        assert opened.wait(timeout=3)
        # The maintenance controller would publish exactly while holding
        # the manager's same .lock: a new start cannot pass before release.
        _write(root, owner.owner_instance_id)
        assert not finished.wait(timeout=0.08)
    assert finished.wait(timeout=3)
    other.join(timeout=3)
    assert len(output) == 1
    assert isinstance(output[0], dict)
    assert output[0]["code"] == "maintenance_paused"
    _no_job_was_reserved(mgr, owner)


def test_request_removed_after_maintenance_resumes_job_creation(tmp_path: Path) -> None:
    mgr, owner, root = _manager(tmp_path)
    request = _write(root, owner.owner_instance_id)
    assert isinstance(_launch(mgr, tmp_path), dict)
    request.unlink()
    assert isinstance(_launch(mgr, tmp_path), str)
    assert len(owner.spawned) == 1


def test_same_name_request_swapped_during_read_refuses_instead_of_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader pins opened FD and later matches it to the original name."""
    from binnacle.platform.darwin import job_manager_maintenance_fence as policy

    mgr, owner, root = _manager(tmp_path)
    original = _write(root, owner.owner_instance_id)
    original_read = os.read
    changes = [0]

    def swap(fd: int, maximum: int) -> bytes:
        data = original_read(fd, maximum)
        if changes[0] == 0:
            changes[0] += 1
            original.rename(root / "old-generation.json")
            original.write_bytes(data)  # identical bytes do NOT prove inode
            original.chmod(0o600)
        return data

    with monkeypatch.context() as m:
        m.setattr(policy.os, "read", swap)
        outcome = _launch(mgr, tmp_path)
    assert changes == [1]
    assert isinstance(outcome, dict)
    assert outcome["code"] == "maintenance_state_unknown"
    _no_job_was_reserved(mgr, owner)


def test_external_process_publishes_request_under_exact_job_transaction_lock(
    tmp_path: Path,
) -> None:
    """A real second process wins the serialized request-vs-start race."""
    import subprocess
    import sys

    mgr, owner, root = _manager(tmp_path)
    with mgr._transaction():
        pass  # Ensure the exact jobs/.lock exists before external acquisition.
    lock = mgr.jobs_dir / ".lock"
    ready = root / "writer-ready"
    destination = root / "request.json"
    body = json.dumps(_record(owner.owner_instance_id))
    script = (
        "import fcntl,os,sys,time\n"
        "from pathlib import Path\n"
        "lock,ready,target,body=map(str,sys.argv[1:5])\n"
        "with open(lock,'rb+') as fd:\n"
        " fcntl.flock(fd.fileno(),fcntl.LOCK_EX)\n"
        " Path(ready).write_text('locked')\n"
        " time.sleep(.5)\n"
        " temp=Path(target+'.owned.tmp')\n"
        " temp.write_text(body)\n"
        " temp.chmod(0o600)\n"
        " os.replace(temp,target)\n"
        " fcntl.flock(fd.fileno(),fcntl.LOCK_UN)\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            script,
            str(lock),
            str(ready),
            str(destination),
            body,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    outcome: list[object] = []
    thread: threading.Thread | None = None
    try:
        until = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < until:
            time.sleep(0.02)
        assert ready.exists()
        thread = threading.Thread(
            target=lambda: outcome.append(_launch(mgr, tmp_path)),
            daemon=True,
        )
        thread.start()
        time.sleep(0.08)
        assert not outcome, "job launch must wait for producer transaction"
        _, err = process.communicate(timeout=8)
        assert process.returncode == 0, err
        thread.join(timeout=4)
        assert not thread.is_alive()
        assert len(outcome) == 1
        assert isinstance(outcome[0], dict)
        assert outcome[0]["code"] == "maintenance_paused"
        _no_job_was_reserved(mgr, owner)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if thread is not None:
            thread.join(timeout=4)

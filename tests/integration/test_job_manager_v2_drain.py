"""Bounded Manager v2 start-admission pause/drain, not a new command tool."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from binnacle.features.commands import job_client, jobs
from binnacle.features.commands.job_manager_v2_drain import _MARKER
from tests.integration.test_job_manager_v2 import (
    _pinned_fd,
    _record_ids,
    _request,
    _send,
)

# Reuse the original strictly isolated Manager fixture, without duplicating
# startup/shutdown code or adding any production socket tests.
pytest_plugins = ["tests.integration.test_job_manager_v2"]

_NONCE = "1234567890abcdef1234567890abcdef"


def _control(
    run: Path, op: str, nonce: str = _NONCE, fds: tuple[int, ...] = ()
) -> dict:
    return _send(run / "start-v2.sock", {"version": 2, "op": op, "nonce": nonce}, fds)


def test_pause_is_durable_and_fences_both_existing_v1_and_v2_starts(running_owner):
    _, root, _, run, store = running_owner
    first = _control(run, "pause_starts")
    assert first["ok"] and first["starts_paused"]
    assert first["owner_cgroup_verified"] is False
    assert first["safe_to_stop"] is False  # pytest has no delegated owner cgroup
    assert first["active_jobs"] == []
    assert _control(run, "pause_starts")["ok"]  # idempotent same nonce
    marker = store.parent / "v2-start-receipts" / _MARKER
    assert marker.is_file() and marker.stat().st_mode & 0o077 == 0
    assert _NONCE not in marker.read_text()  # only nonce digest is persisted
    with pytest.raises(job_client.JobManagerError):
        job_client.start(
            run / "legacy-v1.sock",
            command="cat marker",
            workdir=root,
            stdin=None,
            wait_seconds=1.0,
            call_id="blocked-v1",
        )
    fd = _pinned_fd(root)
    try:
        refusal = _send(
            run / "start-v2.sock", _request(root, call_id="blocked-v2"), (fd,)
        )
    finally:
        os.close(fd)
    assert refusal["ok"] is False and not _record_ids(store)
    assert (
        _control(run, "resume_starts", "ffffffffffffffffffffffffffffffff")["ok"]
        is False
    )
    assert marker.exists()
    assert _control(run, "resume_starts")["ok"] is True
    assert not marker.exists()
    fd = _pinned_fd(root)
    try:
        accepted = _send(
            run / "start-v2.sock", _request(root, call_id="after-resume"), (fd,)
        )
    finally:
        os.close(fd)
    assert accepted["ok"] is True and len(_record_ids(store)) == 1
    assert job_client.ping(run / "legacy-v1.sock")["version"] == 1


def test_pause_waits_for_inflight_v2_launch_to_persist_before_admitting_drain(
    running_owner, monkeypatch
):
    """No polling race: pause's owner lock follows an ongoing Popen launch."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _, root, _, run, store = running_owner
    started = Event()
    release = Event()
    original = jobs._PROCESS_BACKEND.launch_pinned

    def delayed_launch(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5), "isolation test launch was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(jobs._PROCESS_BACKEND, "launch_pinned", delayed_launch)

    def send_start():
        fd = _pinned_fd(root)
        try:
            return _send(
                run / "start-v2.sock",
                _request(
                    root,
                    command="sleep 0.3; cat marker",
                    wait_seconds=0,
                    call_id="inflight-start-before-pause",
                ),
                (fd,),
            )
        finally:
            os.close(fd)

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_start = executor.submit(send_start)
        assert started.wait(timeout=3)
        pending_pause = executor.submit(_control, run, "pause_starts")
        try:
            # The pause operation must wait until start_job's shared lock
            # leaves the durable job record fully written.
            time.sleep(0.05)
            assert not pending_pause.done(), "pause passed an in-flight start"
        finally:
            release.set()
        reply = pending_start.result(timeout=6)
        drained = pending_pause.result(timeout=6)

    assert reply["ok"] is True
    assert drained["ok"] is True and drained["starts_paused"]
    assert len(_record_ids(store)) == 1
    assert (store / reply["job_id"] / "meta.json").is_file()
    rejected = _control(run, "resume_starts", nonce="ffffffffffffffffffffffffffffffff")
    assert rejected["ok"] is False
    assert _control(run, "pause_starts")["ok"] is True


def test_pause_cannot_interrupt_v2_receipt_reservation_before_spawn(
    running_owner, monkeypatch
):
    """A pause cannot strand a fresh pending receipt between reserve/Popen."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from binnacle.features.commands import job_manager_v2_receipts as receipts

    _, root, _, run, store = running_owner
    reserved = Event()
    release = Event()
    reserve_original = receipts.reserve

    def suspended_reservation(payload):
        result = reserve_original(payload)
        reserved.set()  # O_EXCL+fsync has just succeeded.
        assert release.wait(timeout=5), "test reservation never released"
        return result

    monkeypatch.setattr(receipts, "reserve", suspended_reservation)

    def submit():
        fd = _pinned_fd(root)
        try:
            return _send(
                run / "start-v2.sock",
                _request(
                    root,
                    command="sleep 0.15; cat marker",
                    wait_seconds=0,
                    call_id="reservation-atomic-pause",
                ),
                (fd,),
            )
        finally:
            os.close(fd)

    with ThreadPoolExecutor(max_workers=2) as workers:
        request = workers.submit(submit)
        assert reserved.wait(timeout=3)
        pause = workers.submit(_control, run, "pause_starts")
        try:
            time.sleep(0.06)
            assert not pause.done(), "pause slipped between receipt and child launch"
        finally:
            release.set()
        started = request.result(timeout=6)
        paused = pause.result(timeout=6)

    assert started["ok"] and paused["ok"]
    assert len(_record_ids(store)) == 1
    assert paused["pending_receipts"] == 0
    assert paused["starts_paused"] is True
    assert (store / started["job_id"] / "meta.json").is_file()


def test_pause_reports_running_job_until_finished(running_owner):
    _, root, _, run, store = running_owner
    fd = _pinned_fd(root)
    try:
        begin = _send(
            run / "start-v2.sock",
            _request(
                root,
                command="sleep 0.6; cat marker",
                wait_seconds=0.0,
                call_id="pause-with-active",
            ),
            (fd,),
        )
    finally:
        os.close(fd)
    assert begin["ok"] and begin["state"] in ("running", "exited")
    paused = _control(run, "pause_starts")
    assert paused["ok"] and paused["starts_paused"]
    assert not paused["safe_to_stop"]
    assert paused["active_jobs"] == [{"job_id": begin["job_id"], "state": "running"}]
    for _ in range(100):
        state = jobs.job_state(begin["job_id"])
        if state and state["state"] == "exited":
            break
        time.sleep(0.02)
    ready = _control(run, "pause_starts")
    assert ready["ok"] and not ready["active_jobs"]
    assert ready["safe_to_stop"] is False  # no kernel cgroup proof in pytest
    assert (store / begin["job_id"] / "out.log").read_text() == "AUTHORIZED_ONLY\n"


def test_pending_v2_receipt_prevents_safe_stop_even_without_job_metadata(running_owner):
    from binnacle.features.commands import job_manager_v2_receipts as receipts

    _, root, _, run, store = running_owner
    payload = _request(root, call_id="ambiguous-prelaunch-receipt")
    is_new, _ = receipts.reserve(payload)
    assert is_new and not _record_ids(store)
    paused = _control(run, "pause_starts")
    assert paused["ok"] and paused["starts_paused"]
    assert paused["active_jobs"] == []
    assert paused["pending_receipts"] == 1
    assert paused["safe_to_stop"] is False


def test_unsafe_maintenance_request_with_an_fd_fails_closed(running_owner):
    _, root, _, run, store = running_owner
    fd = _pinned_fd(root)
    try:
        refused = _control(run, "pause_starts", fds=(fd,))
        assert refused["ok"] is False
        assert not (store.parent / "v2-start-receipts" / _MARKER).exists()
    finally:
        os.close(fd)
    bad = _control(run, "pause_starts", nonce="x")
    assert bad["ok"] is False
    assert not _record_ids(store)


def test_corrupt_maintenance_marker_blocks_old_and_new_starts(running_owner):
    _, root, _, run, store = running_owner
    folder = store.parent / "v2-start-receipts"
    folder.mkdir(mode=0o700, exist_ok=True)
    (folder / _MARKER).write_text("not a valid marker")
    fd = _pinned_fd(root)
    try:
        blocked = _send(
            run / "start-v2.sock", _request(root, call_id="corrupt-pause"), (fd,)
        )
    finally:
        os.close(fd)
    assert blocked["ok"] is False
    with pytest.raises(job_client.JobManagerError):
        job_client.start(
            run / "legacy-v1.sock",
            command="cat marker",
            workdir=root,
            stdin=None,
            wait_seconds=0,
            call_id="corrupt-v1",
        )
    assert not _record_ids(store)


def test_unknown_job_state_prevents_claiming_safe_stop(running_owner):
    _, root, _, run, store = running_owner
    job = "abc123abc123"
    directory = store / job
    directory.mkdir(parents=True)
    (directory / "out.log").write_text("")
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "command": "unknown",
                "workdir": str(root),
                "pid": 99999998,
                "starttime": 1,
                "started_at": 100.0,
                "owner_instance_id": "stale",
            }
        )
    )
    paused = _control(run, "pause_starts")
    assert paused["ok"] and not paused["safe_to_stop"]
    assert paused["active_jobs"] == [{"job_id": job, "state": "unknown"}]

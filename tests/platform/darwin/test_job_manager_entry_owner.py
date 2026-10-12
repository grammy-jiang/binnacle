"""J1r manager handoff and J1g repairs behind the com.binnacle.jobs entry point.

Split from test_job_manager_entry.py (r6 T1): durable-record release, reaper
faults, close() budgets over the real J1 owner, and the P2 F1/F3 repairs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from unittest import mock

import pytest

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_group_fence as fence
from binnacle.platform.darwin import job_manager_procinfo as procinfo
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin import job_process_owner as jpo
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner
from tests import signal_safety
from tests.platform.darwin.test_job_manager_resilience import (
    lock_open_fails,
    procargs,
    wait_for,
)
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    req,
    stop_req,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin J1 owner, A3")


def test_release_only_after_the_terminal_record_is_durable(tmp_path, monkeypatch):
    # J1r handoff 1: release() acknowledges a durable record, never before.
    owner = ReferenceOwner()
    released = []
    owner.release = released.append
    manager = manager_for(owner, tmp_path / "jobs")
    job_id = manager.handle(req(tmp_path, "exit 3"))["job_id"]
    exited = pc.OwnedJobExit(job_id, 3, None, "normal_exit")
    with lock_open_fails(monkeypatch, threading.current_thread().name):
        assert manager.record_exit(exited) is False
    assert released == []
    assert manager.record_exit(exited) and released == [job_id]
    assert meta_of(tmp_path / "jobs", job_id)["exit_code"] == 3
    os.waitpid(owner.live.pop(job_id), 0)


def test_reference_owner_release_matches_the_j1_owner(tmp_path):
    # RJ1D2-F3: the test double refuses ids it never spawned, as J1 does.
    owner = ReferenceOwner()
    with pytest.raises(pc.UnverifiedJobProcess, match="darwin_job_not_owned"):
        owner.release("0" * 12)
    manager = manager_for(owner, tmp_path / "jobs")
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    with pytest.raises(ValueError, match="darwin_job_not_terminal"):
        owner.release(job_id)
    manager.close()
    owner.release(job_id)  # terminal and recorded: acknowledged
    assert owner.released == {job_id}


def test_reaper_fault_records_no_exit_and_ends_the_reaper(tmp_path):
    # J1r handoff 3: JobOwnerLost means authority UNKNOWN, never an exit.
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "jobs")

    def lost(*_args):
        raise pc.JobOwnerLost("darwin_job_reaper_failed")

    owner.wait = owner.reap_exits = lost
    reply = manager.handle(req(tmp_path, "true", wait=1))
    assert reply["ok"] is True
    assert not svc._terminal(meta_of(tmp_path / "jobs", reply["job_id"]))
    manager.reap_forever(threading.Event())  # returns: serving then stops
    os.waitpid(owner.live.pop(reply["job_id"]), 0)


def test_persistent_reap_failure_stops_the_manager(tmp_path, monkeypatch):
    # RJ1D-F1 (3): never retry a failing reaper forever; stop, restart, D-1.
    owner, calls = ReferenceOwner(), []

    def broken(timeout):
        calls.append(timeout)
        raise ValueError("kqueue poll failed")

    owner.reap_exits = broken
    monkeypatch.setattr(svc, "REAP_FAILURE_LIMIT", 3)
    manager_for(owner, tmp_path / "jobs").reap_forever(threading.Event())
    assert len(calls) == 3


@NATIVE
def test_real_owner_persists_background_exits_while_serving(tmp_path):
    # RJ1D-F1 (5): the composed owner (start_reaper=False) and reap_forever
    # persist and release every background exit before any close().

    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    try:
        jobs = [
            manager.handle(req(tmp_path, "sleep 0.2; exit 3"))["job_id"]
            for _ in range(30)
        ]

        def done():
            return all(svc._terminal(meta_of(tmp_path / "jobs", j)) for j in jobs)

        assert wait_for(done, timeout=20)
        assert {meta_of(tmp_path / "jobs", j)["exit_code"] for j in jobs} == {3}
        assert {manager.state(j) for j in jobs} == {"exited"}
        assert not owner.reaper_running
    finally:
        halt.set()
        reaper.join()
        closed = manager.close()
    assert closed == ()  # all released after their durable records


@NATIVE
def test_close_persists_every_unreleased_exit_and_many_jobs_in_budget(
    tmp_path, monkeypatch
):
    # J1r handoff 2 / CR0 point 3 / R-J3-F3: reaped exits whose persistence
    # failed are written by close() with their own reason; running jobs get
    # owner_restart; more than 4 groups stop inside launchd ExitTimeOut.

    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    manager = manager_for(owner, tmp_path / "jobs")
    manager.grace = (svc.STOP_SIGTERM_GRACE_S, svc.STOP_SIGKILL_GRACE_S)
    halt = threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,), name="rp")
    with lock_open_fails(monkeypatch, "rp"):
        reaper.start()
        short = [manager.handle(req(tmp_path, f"exit {n}"))["job_id"] for n in (3, 4)]
        running = [
            manager.handle(req(tmp_path, "sleep 60"))["job_id"] for _ in range(6)
        ]
        assert wait_for(lambda: all(j in manager._unrecorded for j in short))
        halt.set()
        reaper.join()
    manager._unrecorded.clear()  # only owner.close() still holds these exits
    started = time.monotonic()
    manager.close()
    assert time.monotonic() - started < 17.0  # JOBS_EXIT_TIMEOUT_S floor
    for job_id, code in zip(short, (3, 4), strict=True):
        meta = meta_of(tmp_path / "jobs", job_id)
        assert (meta["exit_code"], meta["termination_reason"]) == (code, "normal_exit")
    for job_id in running:
        meta = meta_of(tmp_path / "jobs", job_id)
        assert (meta["signal"], meta["termination_reason"]) == (None, "owner_restart")
        assert "authority" not in meta


@pytest.fixture
def owned_j1g(tmp_path):
    """P2 pre-review repairs (R4 J1g-a2, SD-49); parser units in resilience."""

    owner = DarwinJobProcessOwner(
        boot_id="b",
        start_reaper=False,
        stop_sigterm_grace_s=0.5,
        stop_sigkill_grace_s=0.5,
    )
    files = [(tmp_path / name).open("w+b") for name in ("stdin", "out.log")]
    recorded: list[tuple[int, tuple[int, int]]] = []

    def spawn(job_id, script):
        env, argv = {"PATH": "/usr/bin:/bin"}, ["/bin/sh", "-c", script]
        started = owner.spawn(
            job_id, argv, workdir=tmp_path, env=env, stdin=files[0], output=files[1]
        )
        recorded.append((started.pid, signal_safety.observe(started.pid).birth))
        return started

    yield owner, spawn, recorded
    owner.close()
    for pid, birth in recorded:  # RULE-NO-PKILL: exact verified (pid, birth) only
        record = signal_safety.observe(pid)
        if record is not None and record.birth == birth and record.state != 5:
            signal_safety.kill_verified(pid, birth)
    for handle in files:
        handle.close()


@NATIVE
def test_f1_job_status_keeps_empty_argv_and_never_shows_env(
    tmp_path, monkeypatch, caplog
):

    secret = os.urandom(16).hex()
    monkeypatch.setenv("R_TEST_SECRET", secret)  # the manager passes os.environ on
    caplog.set_level("DEBUG")
    owner = DarwinJobProcessOwner(boot_id="b", stop_sigterm_grace_s=0.5)
    manager = svc.DarwinJobManager(
        owner=owner,
        jobs_dir=tmp_path / "jobs",
        boot_id="b",
        wait_max_s=5,
        keep_newest=9,
    )
    code = "import time; time.sleep(30)"
    argv = [sys.executable, "-c", code, "", "", "tail"]
    try:  # manager.close() stops only the group it spawned
        replies = [
            manager.handle(req(tmp_path, f"exec {argv[0]} -c '{code}' '' '' tail"))
        ]
        ask = {"version": 1, "op": "processes", "max_cmd_chars": 4096}
        ask["job_id"] = replies[0]["job_id"]

        def listed():
            replies.append(manager.handle(ask))
            return [p.get("cmd") for p in replies[-1]["processes"]] == [" ".join(argv)]

        assert wait_for(listed)  # (a) empty fields kept, exactly argc taken
        replies.append(manager.handle({"version": 1, "op": "ping"}))
        replies.append(manager.handle(stop_req(replies[0]["job_id"])))
    finally:
        manager.close()
    output = json.dumps(replies)
    assert secret not in output + caplog.text  # (b) no job_status, no log line
    assert "R_TEST_SECRET" not in output + caplog.text and "PATH=" not in output


@NATIVE
def test_f1_argc_beyond_fields_falls_back_to_comm(owned_j1g, monkeypatch):
    owner, spawn, _ = owned_j1g
    spawn("job-c", "exec sleep 30")
    assert wait_for(lambda: owner.processes("job-c")[0].get("cmd") == "sleep 30")
    real, short = procinfo._sysctl, procargs(9, b"/bin/sleep", b"sleep", b"30")
    monkeypatch.setattr(
        procinfo, "_sysctl", lambda mib, n: short if mib[1] == 49 else real(mib, n)
    )
    assert owner.processes("job-c")[0]["cmd"] == "sleep"  # (c) comm, fail closed


@NATIVE
def test_f3_fenced_job_stays_transient_and_loses_only_on_proof(
    owned_j1g, monkeypatch, caplog
):

    owner, spawn, recorded = owned_j1g
    leader = spawn("job-f", "sleep 30 & exit 0").pid
    assert wait_for(lambda: owner.reap_exits(0) or owner._jobs["job-f"].exit)
    (member,) = [
        m for m in jpo._process_records(2, leader) if m.pid != leader and m.state != 5
    ]
    recorded.append((member.pid, member.birth))
    real = owner._child_record_or_raise
    failing = mock.Mock(side_effect=OSError("injected sysctl failure"))
    monkeypatch.setattr(owner, "_child_record_or_raise", failing)
    for _ in range(10 * fence.OBSERVATION_FAILURE_LIMIT):
        owner.reap_exits(0)
    assert failing.call_count >= 30 and not owner._jobs["job-f"].lost  # transient
    moved = real(leader)._replace(birth=(0, 0))  # proven identity change
    monkeypatch.setattr(owner, "_child_record_or_raise", lambda pid: moved)
    owner.reap_exits(0)
    job = owner._jobs["job-f"]  # recorded, kept UNKNOWN, never adopted
    assert job.lost and job.reason_code == "darwin_exclusive_reaper_required"
    assert owner.authority("job-f").authority == "UNKNOWN"
    assert "event=darwin_fenced_job_lost job_id=job-f" in caplog.text
    monkeypatch.setattr(owner, "_child_record_or_raise", real)
    with mock.patch.object(os, "killpg") as killpg:
        owner.close()
    assert killpg.call_count == 0  # never signalled without proof
    assert signal_safety.kill_verified(member.pid, member.birth)
    os.waitpid(leader, 0)  # the test's own zombie child (not a signal)

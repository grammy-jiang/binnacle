"""SD-43 (J1g): leader-exit fence, stopping event, transient observation, guards.

JCRP-F1 pins the Linux semantics (features/commands/jobs.py job_state,
job_stop.stop_embedded, command_status.py): a leader exit is recorded as
``exited`` while background members of its group keep running; job_status
lists processes only while ``running``; stop_job after the exit returns the
exited state and signals nothing. close() still stops the fenced group.

Teardown signals only exact recorded (pid, birth) through tests/signal_safety
(RULE-NO-PKILL): these tests run as the same UID beside production.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest import mock

import pytest

from binnacle.platform.contracts.process_contracts import (
    JobOwnerLost,
    OwnedJobExit,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin import job_group_fence as fence
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin import job_manager_procinfo as procinfo
from binnacle.platform.darwin import job_manager_records as job_records
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin import job_process_owner as jpo
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner
from tests import signal_safety

native = pytest.mark.skipif(
    sys.platform != "darwin" or not hasattr(os, "waitid"), reason="Darwin job owner"
)

GRACES = {"stop_sigterm_grace_s": 0.5, "stop_sigkill_grace_s": 0.5}


@pytest.fixture
def spool(tmp_path):
    stdin = (tmp_path / "stdin").open("w+b")
    output = (tmp_path / "out.log").open("w+b")
    yield tmp_path, stdin, output
    stdin.close()
    output.close()


@pytest.fixture
def owned():
    """Owners created here; close() at teardown stops whatever they own."""
    created: list[DarwinJobProcessOwner] = []

    def make(**kw):
        owner = DarwinJobProcessOwner(boot_id="b", **{**GRACES, **kw})
        created.append(owner)
        return owner

    yield make
    for owner in created:
        owner.close()


@pytest.fixture
def recorded():
    """Exact (pid, birth) records; teardown kills only verified survivors."""
    records: list[tuple[int, tuple[int, int]]] = []
    yield records
    for pid, birth in records:
        record = signal_safety.observe(pid)
        if record is not None and record.birth == birth and record.state != 5:
            signal_safety.kill_verified(pid, birth)


def _spawn(owner, job_id, script, spool):
    root, stdin, output = spool
    return owner.spawn(
        job_id,
        ["/bin/sh", "-c", script],
        workdir=root,
        env={"PATH": "/usr/bin:/bin"},
        stdin=stdin,
        output=output,
    )


def _live_members(leader):
    return [
        m for m in jpo._process_records(2, leader) if m.pid != leader and m.state != 5
    ]


def _await(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def _alive_exact(pid, birth):
    record = signal_safety.observe(pid)
    return record is not None and record.birth == birth and record.state != 5


# --- JCRP-F1: the zombie leader fences a live background member ----------------


@native
def test_leader_exit_keeps_background_member_and_fence(owned, spool, recorded):
    owner = owned()
    started = _spawn(owner, "job-bg", "sleep 30 & echo done; exit 3", spool)
    exited = owner.wait("job-bg", 5)
    assert exited == OwnedJobExit("job-bg", 3, None, "normal_exit")
    assert _await(lambda: _live_members(started.pid))
    (member,) = _live_members(started.pid)
    recorded.append((member.pid, member.birth))
    # The member survives the leader exit (Linux parity), the leader is our
    # unreaped zombie and still holds the pgid.
    time.sleep(0.3)
    assert _alive_exact(member.pid, member.birth)
    leader = signal_safety.observe(started.pid)
    assert leader is not None and leader.state == 5 and leader.group == started.pid
    observed = owner.authority("job-bg")
    assert (observed.authority, observed.alive) == ("OWNED", False)
    # Linux stop_job after a leader exit signals nothing.
    with pytest.raises(UnverifiedJobProcess, match="darwin_job_leader_exited"):
        owner.signal_owned_group("job-bg", "terminate")
    assert _alive_exact(member.pid, member.birth)
    # F6: the fenced group is listed read-only; the command is never invented.
    listing = owner.processes("job-bg")
    by_pid = {item["pid"]: item for item in listing}
    assert by_pid[member.pid]["cmd"] == "sleep 30"
    assert list(by_pid[member.pid]) == ["pid", "state", "etime_s", "cmd"]  # no ppid
    assert by_pid[member.pid]["state"] in {"?", "S"}  # SRUN is R or S (SD-59)
    assert by_pid[started.pid]["state"] == "Z"
    # A persisted exit is acked; the fenced job stays in the scans.
    owner.release("job-bg")
    assert "job-bg" in owner._jobs
    exits = owner.close()  # TERM, grace, KILL, grace, then reap the leader
    assert all(e.job_id != "job-bg" for e in exits)  # acked: not re-returned
    assert not _alive_exact(member.pid, member.birth)
    assert signal_safety.observe(started.pid) is None  # reaped: fence closed


@native
def test_fenced_leader_is_reaped_once_the_group_empties(owned, spool):
    owner = owned()
    started = _spawn(owner, "job-short", "sleep 0.6 & exit 0", spool)
    assert owner.wait("job-short", 5) is not None
    assert signal_safety.observe(started.pid) is not None  # fence held
    assert _await(lambda: signal_safety.observe(started.pid) is None)
    observed = owner.authority("job-short")
    assert (observed.authority, observed.alive) == ("UNKNOWN", False)
    assert observed.reason_code == "darwin_job_reaped"


@native
def test_leader_exit_signals_nothing_and_reap_path_has_no_killpg(
    owned, spool, recorded
):
    owner = owned()
    with mock.patch.object(jpo.os, "killpg", wraps=os.killpg) as killpg:
        started = _spawn(owner, "job-q", "sleep 30 & exit 0", spool)
        assert owner.wait("job-q", 5) is not None
        assert _await(lambda: _live_members(started.pid))
        time.sleep(0.3)  # several reaper ticks with a live member
        assert killpg.call_count == 0  # F1/F5: the reap path never signals
    for member in _live_members(started.pid):
        recorded.append((member.pid, member.birth))


# --- JCRP-F5: group == pid and != getpgrp() at every killpg ---------------------


@native
@pytest.mark.parametrize("bad_group", ["moved", "own"])
def test_killpg_guard_refuses_unverified_group(owned, spool, recorded, bad_group):
    owner = owned()
    started = _spawn(owner, "job-g", "sleep 30", spool)
    record = signal_safety.observe(started.pid)
    recorded.append((started.pid, record.birth))
    group = os.getpgrp() if bad_group == "own" else started.pid + 1
    forged = record._replace(group=group)
    real = jpo._process_records

    def records(kind, ident):
        if kind == 1 and ident == started.pid:
            return [forged]
        return real(kind, ident)

    with (
        mock.patch.object(jpo, "_process_records", records),
        mock.patch.object(jpo.os, "killpg") as killpg,
    ):
        with pytest.raises(UnverifiedJobProcess, match="darwin_job_group_unverified"):
            owner.signal_owned_group("job-g", "terminate")
        assert killpg.call_count == 0
    observed = owner.authority("job-g")
    assert observed.reason_code == "darwin_job_group_unverified"
    assert owner.take_lost() == ["job-g"]  # F3: the manager persists UNKNOWN


@native
def test_close_applies_the_killpg_guard(owned, spool, recorded):
    owner = owned()
    started = _spawn(owner, "job-c", "sleep 30", spool)
    record = signal_safety.observe(started.pid)
    recorded.append((started.pid, record.birth))
    forged = record._replace(group=os.getpgrp())
    real = jpo._process_records

    def records(kind, ident):
        if kind == 1 and ident == started.pid:
            return [forged]
        return real(kind, ident)

    with (
        mock.patch.object(jpo, "_process_records", records),
        mock.patch.object(jpo.os, "killpg") as killpg,
    ):
        assert owner.close() == ()
        assert all(call.args[0] != os.getpgrp() for call in killpg.call_args_list)
        assert killpg.call_count == 0


# --- JCRP-F3: transient observation failure -------------------------------------


@native
def test_transient_observation_failure_is_retried_then_lost(owned, spool, recorded):
    owner = owned(start_reaper=False)
    started = _spawn(owner, "job-t", "sleep 30", spool)
    record = signal_safety.observe(started.pid)
    recorded.append((started.pid, record.birth))
    real = jpo._process_records
    failing = {"on": True}

    def records(kind, ident):
        if failing["on"] and kind == 1 and ident == started.pid:
            raise OSError("injected sysctl failure")
        return real(kind, ident)

    with mock.patch.object(jpo, "_process_records", records):
        for _ in range(3 * fence.OBSERVATION_FAILURE_LIMIT):  # F2: request burst
            observed = owner.authority("job-t")
            assert observed.authority == "UNKNOWN"
            assert observed.reason_code == "darwin_job_observation_retry"
            assert owner.processes("job-t") == []  # request path: never counted
        assert not owner._jobs["job-t"].lost
        failing["on"] = False
        owner.reap_exits(0)  # the next reaper tick retries and recovers
        assert owner.authority("job-t").authority == "OWNED"
        failing["on"] = True
        owner.authority("job-t")  # schedules a tick retry; counts nothing
        for _ in range(fence.OBSERVATION_FAILURE_LIMIT - 1):
            owner.reap_exits(0)
        assert not owner._jobs["job-t"].lost  # two consecutive tick failures
        owner.reap_exits(0)  # third consecutive tick failure: lost
    observed = owner.authority("job-t")
    assert observed.reason_code == "darwin_job_observation_failed"
    assert owner.take_lost() == ["job-t"]
    with pytest.raises(JobOwnerLost):
        owner.wait("job-t", 0)


@native
def test_manager_persists_an_owner_loss_as_unknown(tmp_path, recorded):
    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=False, **GRACES)
    jobs = tmp_path / "jobs"
    manager = svc.DarwinJobManager(
        owner=owner, jobs_dir=jobs, boot_id="b", wait_max_s=50, keep_newest=50
    )
    try:
        reply = manager.handle(_start(tmp_path, "sleep 30"))
        job_id = reply["job_id"]
        meta = job_records.read_meta(jobs, job_id)
        record = signal_safety.observe(meta["pid"])
        recorded.append((meta["pid"], record.birth))
        real = jpo._process_records

        def records(kind, ident):
            if kind == 1 and ident == meta["pid"]:
                raise OSError("injected")
            return real(kind, ident)

        with mock.patch.object(jpo, "_process_records", records):
            for _ in range(fence.OBSERVATION_FAILURE_LIMIT + 1):
                owner.reap_exits(0)  # only reaper ticks count (PRE-J1g-F2)
                owner.authority(job_id)
        assert manager.persist_lost() == 1
        meta = job_records.read_meta(jobs, job_id)
        assert meta["authority"] == "UNKNOWN"
        assert meta["termination_reason"] == "owner_restart"
        assert manager.state(job_id) == "unknown"  # D-1, never exited
    finally:
        manager.close()


# --- JCRP-F2: stopping releases waiting handlers --------------------------------


def _start(workdir, command, wait=0.0):
    return {
        "version": 1,
        "op": "start",
        "command": command,
        "stdin": None,
        "workdir": str(workdir),
        "wait_seconds": wait,
    }


@native
def test_stopping_releases_a_50s_start_and_close_fits_exit_timeout(tmp_path):
    from binnacle.deployment.darwin import plist as plan

    owner = DarwinJobProcessOwner(boot_id="b")
    jobs = tmp_path / "jobs"
    manager = svc.DarwinJobManager(
        owner=owner, jobs_dir=jobs, boot_id="b", wait_max_s=50, keep_newest=50
    )
    replies: list[dict] = []
    handler = threading.Thread(
        target=lambda: replies.append(manager.handle(_start(tmp_path, "sleep 60", 50)))
    )
    handler.start()
    assert _await(lambda: any(jobs.glob("*/meta.json")))
    time.sleep(0.3)
    began = time.monotonic()
    manager.stopping.set()  # what SIGTERM does through serve_job_manager's stop
    handler.join(5)
    released = time.monotonic() - began
    assert not handler.is_alive() and released < 1.0
    (reply,) = replies
    assert reply["ok"] is True and reply["state"] == "running"  # auto-backgrounded
    manager.close()
    total = time.monotonic() - began
    assert total < plan.JOBS_EXIT_TIMEOUT_S
    meta = job_records.read_meta(jobs, reply["job_id"])
    assert (meta["signal"], meta["termination_reason"]) == (None, "owner_restart")


@native
def test_stopping_stop_returns_current_state(tmp_path, recorded):
    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=True, **GRACES)
    jobs = tmp_path / "jobs"
    manager = svc.DarwinJobManager(
        owner=owner,
        jobs_dir=jobs,
        boot_id="b",
        wait_max_s=50,
        keep_newest=50,
        grace=(30.0, 30.0),
    )
    try:
        job_id = manager.handle(_start(tmp_path, "trap '' TERM; sleep 60"))["job_id"]
        meta = job_records.read_meta(jobs, job_id)
        recorded.append((meta["pid"], signal_safety.observe(meta["pid"]).birth))
        time.sleep(0.2)
        replies: list[dict] = []
        stopper = threading.Thread(
            target=lambda: replies.append(
                manager.handle({"version": 1, "op": "stop", "job_id": job_id})
            )
        )
        stopper.start()
        time.sleep(0.3)
        began = time.monotonic()
        manager.stopping.set()
        stopper.join(5)
        assert not stopper.is_alive() and time.monotonic() - began < 1.0
        assert replies[0] == {"ok": True, "job_id": job_id, "state": "running"}
    finally:
        manager.close()


@native
def test_serve_job_manager_shares_stop_as_the_stopping_event(tmp_path):
    manager = mock.Mock(spec=["stopping", "jobs_dir", "recover", "reap_forever"])
    manager.jobs_dir = tmp_path
    stop = threading.Event()
    with (
        mock.patch.object(entry, "jobs_dir_writer", side_effect=RuntimeError("held")),
        pytest.raises(RuntimeError, match="held"),
    ):
        entry.serve_job_manager(
            manager, socket_path=tmp_path / "s", lease=None, stop=stop
        )
    assert manager.stopping is stop


# --- JCRP-N7 and N4 ----------------------------------------------------------------


@native
def test_released_table_is_bounded_oldest_first(owned, spool, monkeypatch):
    monkeypatch.setattr(fence, "RELEASED_LIMIT", 2)
    owner = owned()
    for n in range(3):
        _spawn(owner, f"job-r{n}", f"exit {n}", spool)
        assert owner.wait(f"job-r{n}", 5) is not None
        assert _await(lambda n=n: owner._jobs[f"job-r{n}"].reaped)
        owner.release(f"job-r{n}")
    assert list(owner._released) == ["job-r1", "job-r2"]


@native
def test_sentinel_groups_the_manager_did_not_spawn_survive_close(
    owned, spool, recorded
):
    # R-J1d3 mandatory negative test: a same-UID group/session this owner did
    # not spawn, and a child in the owner's own group, survive close().
    env = dict(os.environ)
    own_session = os.posix_spawn("/bin/sleep", ["/bin/sleep", "917"], env, setsid=True)
    own_group = os.posix_spawn("/bin/sleep", ["/bin/sleep", "918"], env)
    sentinels = []
    for pid in (own_session, own_group):
        record = signal_safety.observe(pid)
        sentinels.append((pid, record.birth))
        recorded.append((pid, record.birth))
    try:
        owner = owned()
        bg = _spawn(owner, "job-s1", "sleep 30 & exit 0", spool)
        _spawn(owner, "job-s2", "sleep 30", spool)
        assert owner.wait("job-s1", 5) is not None
        assert _await(lambda: _live_members(bg.pid))
        owner.close()
        assert not _live_members(bg.pid) if signal_safety.observe(bg.pid) else True
        for pid, birth in sentinels:
            assert _alive_exact(pid, birth), f"sentinel {pid} was signalled"
    finally:
        for pid, birth in sentinels:
            signal_safety.kill_verified(pid, birth)
            if signal_safety.observe(pid) is not None:
                os.waitpid(pid, 0)  # our own direct child: reap it


@native
def test_stop_owned_after_leader_exit_mirrors_linux(tmp_path, recorded):
    # Linux stop_embedded: a non-running state is returned without a signal.
    owner = DarwinJobProcessOwner(boot_id="b", **GRACES)
    jobs = tmp_path / "jobs"
    manager = svc.DarwinJobManager(
        owner=owner, jobs_dir=jobs, boot_id="b", wait_max_s=50, keep_newest=50
    )
    try:
        reply = manager.handle(_start(tmp_path, "sleep 30 & exit 0", wait=5))
        job_id = reply["job_id"]
        assert reply["state"] == "exited"
        meta = job_records.read_meta(jobs, job_id)
        assert _await(lambda: _live_members(meta["pid"]))
        (member,) = _live_members(meta["pid"])
        recorded.append((member.pid, member.birth))
        stopped = manager.handle({"version": 1, "op": "stop", "job_id": job_id})
        assert stopped == {"ok": True, "job_id": job_id, "state": "exited"}
        assert _alive_exact(member.pid, member.birth)
        listing = manager.handle({"version": 1, "op": "processes", "job_id": job_id})
        assert listing == {"ok": True, "job_id": job_id, "processes": []}
    finally:
        manager.close()
    assert not _alive_exact(member.pid, member.birth)
    assert job_records.read_meta(jobs, job_id)["termination_reason"] == "normal_exit"


@native
def test_processes_uses_comm_only_when_procargs_is_denied(owned, spool, recorded):
    owner = owned()
    started = _spawn(owner, "job-p", "exec sleep 30", spool)
    record = signal_safety.observe(started.pid)
    recorded.append((started.pid, record.birth))
    assert _await(lambda: owner.processes("job-p", 5)[0]["cmd"] == "sleep")
    with mock.patch.object(procinfo, "command_line", return_value=None):
        (item,) = owner.processes("job-p")
    assert item["state"] in {"?", "S"}  # Darwin p_stat: SRUN (R or S) or SSLEEP
    assert item["etime_s"] >= 0
    assert {**item, "state": "-", "etime_s": 0} == {
        "pid": started.pid,
        "state": "-",
        "etime_s": 0,
        "cmd": "sleep",  # kinfo_proc comm, never an invented argv
    }
    assert owner.processes("job-unknown") == []

"""Deterministic coverage of the job store's stop and prune edge paths.

Why this file exists (2026-09-24): `src/binnacle/jobs.py` sat at 204 of 225
statements-plus-branches (90.67%) against a 90.00% policy target, and two of
those items -- the `except ProcessLookupError` around the SIGTERM in
`stop_job_embedded` -- were only ever reached when two concurrent stop
requests happened to race in the right order. On GitHub's runners that
order came up in 5 of 8 jobs on one commit; the other 3 read 89.78% and
failed the policy. These tests reach every stop and prune edge on purpose,
with fake records and monkeypatched process calls, so the module's coverage
no longer depends on thread scheduling.
"""

import json
import logging
import os
import signal

import pytest

from binnacle import jobs as jobstore

#: A pid no live process should have; nothing here signals it for real.
FAKE_PID = 4_190_001


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "store")
    return tmp_path / "store"


def _record(name: str, meta: dict) -> None:
    d = jobstore.JOBS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "out.log").write_text("")


def _job(**extra: object) -> dict:
    base: dict = {
        "command": "sleep 30",
        "workdir": "/tmp",
        "pid": FAKE_PID,
        "pgid": FAKE_PID,
        "started_at": 1.0,
    }
    base.update(extra)
    return base


def _fake_await(calls: list[float], result: dict | None):
    def await_exit(job_id: str, timeout: float) -> dict | None:
        calls.append(timeout)
        return result

    return await_exit


# -- stop_job_embedded: the states that never signal -------------------------


def test_stop_of_an_unknown_job_id_returns_none(store):
    assert jobstore.stop_job_embedded("nosuchjob00") is None


def test_stop_of_an_exited_job_returns_its_record_without_signaling(store, monkeypatch):
    _record("exited000001", _job(exit_code=0, ended_at=2.0))
    monkeypatch.setattr(
        jobstore, "_signal_job", lambda *a: pytest.fail("must not signal")
    )
    assert jobstore.stop_job_embedded("exited000001")["state"] == "exited"


def test_stop_of_an_orphaned_job_returns_unknown_when_nobody_asked_to_stop_it(
    store, monkeypatch
):
    """Process gone, exit never recorded, no stop on record: there is nothing
    to wait for, so the transient "unknown" is what the caller gets."""
    _record("orphan000001", _job())
    monkeypatch.setattr(jobstore, "_pid_alive", lambda pid, starttime=None: False)
    monkeypatch.setattr(jobstore, "await_exit", lambda *a: pytest.fail("must not wait"))
    assert jobstore.stop_job_embedded("orphan000001")["state"] == "unknown"


def test_stop_of_an_orphaned_job_with_a_pending_stop_waits_for_the_record(
    store, monkeypatch
):
    """A stop was already requested and the process is gone: the reaper is
    about to write the exit, so bridge that window instead of saying unknown."""
    _record("orphan000002", _job(stop_requested=True))
    monkeypatch.setattr(jobstore, "_pid_alive", lambda pid, starttime=None: False)
    waits: list[float] = []
    settled = {"state": "exited", "signal": 15}
    monkeypatch.setattr(jobstore, "await_exit", _fake_await(waits, settled))
    assert jobstore.stop_job_embedded("orphan000002") is settled
    assert waits == [jobstore.STOP_SIGKILL_GRACE_S]


# -- stop_job_embedded: the group dies under the signal ------------------------


def test_stop_whose_group_vanished_before_sigterm_falls_through_to_the_record(
    store, monkeypatch
):
    """The lines that used to be covered only when two stops raced: the
    process group is gone between the "running" read and the killpg."""
    _record("racing000001", _job())
    monkeypatch.setattr(jobstore, "_pid_alive", lambda pid, starttime=None: True)
    signals: list[int] = []

    def gone(pgid: int, strays: set[int], sig: int) -> None:
        signals.append(sig)
        raise ProcessLookupError

    monkeypatch.setattr(jobstore, "_signal_job", gone)
    waits: list[float] = []
    settled = {"state": "exited", "signal": 15}
    monkeypatch.setattr(jobstore, "await_exit", _fake_await(waits, settled))
    assert jobstore.stop_job_embedded("racing000001") is settled
    assert signals == [signal.SIGTERM]
    assert waits == [jobstore.STOP_SIGKILL_GRACE_S]


def test_stop_escalates_to_sigkill_and_tolerates_a_group_that_died_meanwhile(
    store, monkeypatch, caplog
):
    _record("stubborn0001", _job())
    monkeypatch.setattr(jobstore, "_pid_alive", lambda pid, starttime=None: True)
    signals: list[int] = []

    def signal_job(pgid: int, strays: set[int], sig: int) -> None:
        signals.append(sig)
        if sig == signal.SIGKILL:
            raise ProcessLookupError  # died between the SIGTERM grace and now

    monkeypatch.setattr(jobstore, "_signal_job", signal_job)
    waits: list[float] = []
    settled = {"state": "exited", "signal": 9}
    answers = iter(({"state": "running"}, settled))

    def await_exit(job_id: str, timeout: float) -> dict | None:
        waits.append(timeout)
        return next(answers)

    monkeypatch.setattr(jobstore, "await_exit", await_exit)
    with caplog.at_level(logging.WARNING, logger="binnacle.jobs"):
        assert jobstore.stop_job_embedded("stubborn0001") is settled
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert waits == [jobstore.STOP_SIGTERM_GRACE_S, jobstore.STOP_SIGKILL_GRACE_S]
    assert any("event=job_stop_escalate" in r.getMessage() for r in caplog.records)


def test_a_stray_descendant_that_exited_first_is_skipped(monkeypatch):
    """_signal_job: the setsid()'d child collected before the signal may be
    gone by the time its turn comes; that is not an error."""
    groups: list[tuple[int, int]] = []
    monkeypatch.setattr(
        jobstore, "signal_group", lambda pgid, sig: groups.append((pgid, sig))
    )
    killed: list[int] = []

    def kill(pid: int, sig: int) -> None:
        killed.append(pid)
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", kill)
    jobstore._signal_job(FAKE_PID, {FAKE_PID + 1}, signal.SIGTERM)
    assert groups == [(FAKE_PID, signal.SIGTERM)] and killed == [FAKE_PID + 1]


# -- _prune: the store that cannot be listed, and garbage that must go --------


def test_prune_returns_quietly_when_the_store_cannot_be_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "never-created")
    jobstore._prune()  # FileNotFoundError from iterdir is swallowed


def test_prune_treats_a_raising_record_as_garbage_and_keeps_going_past_a_stuck_dir(
    store, monkeypatch
):
    """Three things the prune loop must survive in one pass: a half-written
    record (`read_meta` rejects it, so it is deletable, not immortal), a
    record whose state read raises `KeyError` (the guard in the loop), and a
    directory that will not go (removal returns False and the pass moves on
    to the next entry). Only the newest record and the stuck one remain."""
    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 1)
    names = (
        "newest000001",
        "halfwritten1",
        "raises000001",
        "stuck0000001",
        "old000000001",
    )
    _record("newest000001", _job(exit_code=0, ended_at=2.0))
    _record("halfwritten1", {"command": "x"})  # parses, but incomplete
    _record("raises000001", _job(exit_code=1, ended_at=2.0))
    _record("stuck0000001", _job(exit_code=1, ended_at=2.0))
    _record("old000000001", _job(exit_code=1, ended_at=2.0))
    for i, name in enumerate(names):
        stamp = 1_700_000_000 - i * 60
        os.utime(store / name, (stamp, stamp))
    real_state = jobstore.job_state

    def job_state(job_id: str) -> dict | None:
        if job_id == "raises000001":
            raise KeyError("pid")  # meta parsed but incomplete, killed mid-write
        return real_state(job_id)

    monkeypatch.setattr(jobstore, "job_state", job_state)
    real_remove = jobstore._remove_job_dir
    monkeypatch.setattr(
        jobstore,
        "_remove_job_dir",
        lambda d: False if d.name == "stuck0000001" else real_remove(d),
    )
    jobstore._prune()
    assert sorted(p.name for p in store.iterdir()) == ["newest000001", "stuck0000001"]

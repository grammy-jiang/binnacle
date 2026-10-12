"""Darwin durable-job owner: sole kqueue reaper, owned-pgid signals, no adoption.

Every child here is spawned by the owner under test and is reaped by it or by
close(). Descendants that escape the group use a hard self-timeout; they are
never recovered by numeric signal.
"""

from __future__ import annotations

import inspect
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from binnacle.platform.contracts.capability_contracts import CapabilityUnavailable
from binnacle.platform.contracts.process_contracts import (
    DarwinJobOwner,
    JobOwnerLost,
    OwnedJobExit,
    OwnedJobObservation,
    OwnedJobProcess,
    ProcessHandle,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin import job_process_owner
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner
from binnacle.platform.darwin.process_backend import OwnedProcessHandle

# Per-test gate: the portable contract/handle tests below also run on Linux.
native = pytest.mark.skipif(
    sys.platform != "darwin", reason="Darwin-native job owner probe"
)


@pytest.fixture
def spool(tmp_path):
    stdin = (tmp_path / "stdin").open("w+b")
    output = (tmp_path / "out.log").open("w+b")
    yield tmp_path, stdin, output
    stdin.close()
    output.close()


@pytest.fixture
def owner():
    created = DarwinJobProcessOwner(
        boot_id="test-boot", stop_sigterm_grace_s=1.0, stop_sigkill_grace_s=1.0
    )
    yield created
    created.close()


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


def _await_zombie(pid):
    deadline = time.monotonic() + 5
    while job_process_owner._process_records(1, pid)[0].state != 5:  # SZOMB
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_owner_satisfies_frozen_protocol_members():
    frozen = {
        name
        for name in vars(DarwinJobOwner)
        if not name.startswith("_") and name != "owner_instance_id"
    }
    for name in frozen | {"owner_instance_id"}:
        assert hasattr(DarwinJobProcessOwner, name), name
    for name in frozen:
        expected = inspect.signature(getattr(DarwinJobOwner, name))
        actual = inspect.signature(getattr(DarwinJobProcessOwner, name))
        assert list(actual.parameters) == list(expected.parameters), name


def test_linux_stop_grace_constants_are_pinned():
    # jobs.py needs a composed host to import; pin to the Linux source text.
    source = (
        Path(__file__).parents[3] / "src/binnacle/features/commands/jobs.py"
    ).read_text()
    for name in ("STOP_SIGTERM_GRACE_S", "STOP_SIGKILL_GRACE_S"):
        found = re.search(rf"^{name} = ([0-9.]+)", source, re.MULTILINE)
        assert found is not None, name
        assert getattr(job_process_owner, name) == float(found.group(1))


def test_birth_token_encodes_kinfo_starttime():
    assert job_process_owner.birth_token((1_700_000_000, 123_456)) == (
        1_700_000_000_123_456
    )


def test_owner_refuses_off_darwin(monkeypatch):
    monkeypatch.setattr(job_process_owner, "_is_darwin", lambda: False)
    with pytest.raises(CapabilityUnavailable, match="native_capability_unavailable"):
        DarwinJobProcessOwner(boot_id="b", start_reaper=False)


class _ExitSource:
    """Stands in for the owner's reaper condition; no process exists."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def wait(self, job_id, timeout):
        self.calls.append((job_id, timeout))
        return self.result

    def exit_for(self, job_id):
        return self.result


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (OwnedJobExit("j", 7, None, "normal_exit"), 7),
        (OwnedJobExit("j", None, signal.SIGTERM, "stop_requested"), -signal.SIGTERM),
    ],
)
def test_owned_process_handle_maps_reaper_exit(result, code):
    source = _ExitSource(result)
    handle = OwnedProcessHandle(source, "j", 4242)
    assert (handle.pid, handle.returncode, handle.wait(3)) == (4242, code, code)
    assert source.calls == [("j", 3)]


def test_owned_process_handle_timeout_keeps_subprocess_contract():
    handle = OwnedProcessHandle(_ExitSource(None), "j", 4242)
    assert handle.returncode is None
    with pytest.raises(subprocess.TimeoutExpired):
        handle.wait(0.01)


def test_owned_process_handle_never_reports_codeless_exit():
    handle = OwnedProcessHandle(
        _ExitSource(OwnedJobExit("j", None, None, "normal_exit")), "j", 4242
    )
    with pytest.raises(JobOwnerLost):
        handle.wait(1)


@native
def test_spawn_sets_session_leader_cwd_and_reaper_serves_wait(owner, spool):
    root, _, output = spool
    started = _spawn(owner, "job-a", 'pwd; echo "$$ $(ps -o pgid= -p $$)"', spool)
    assert isinstance(started, OwnedJobProcess)
    assert started.pgid == started.pid
    assert started.owner_instance_id == owner.owner_instance_id
    assert started.boot_id == "test-boot"
    assert started.birth > 0
    assert owner.reaper_running
    result = owner.wait("job-a", 5)
    assert result is not None
    assert (result.exit_code, result.signal) == (0, None)
    assert result.termination_reason == "normal_exit"
    lines = Path(output.name).read_text().split()
    assert Path(lines[0]).resolve() == root.resolve()
    assert lines[1] == lines[2] == str(started.pid)
    # Reaped by the sole reaper: the fence is closed, authority is UNKNOWN.
    observed = owner.authority("job-a")
    assert (observed.authority, observed.alive) == ("UNKNOWN", False)
    with pytest.raises(UnverifiedJobProcess, match="already_reaped"):
        owner.signal_owned_group("job-a", "terminate")


@native
def test_process_handle_wait_is_served_by_reaper_condition(owner, spool):
    _spawn(owner, "job-h", "sleep 0.3; exit 7", spool)
    handle = owner.handle("job-h")
    assert isinstance(handle, OwnedProcessHandle)
    handle_protocol: ProcessHandle = handle
    assert handle_protocol.returncode is None
    with pytest.raises(subprocess.TimeoutExpired):
        handle.wait(0.01)
    assert handle.wait(5) == 7
    assert handle.returncode == 7
    with pytest.raises(CapabilityUnavailable, match="darwin_job_reaper_running"):
        owner.reap_exits(0)  # one reap driver only (RJ1D-F1)


@native
def test_exit_before_registration_is_pending_not_lost(spool, monkeypatch):
    created = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    try:
        original = created._arm_exit_watch_locked

        def late_arm(job):
            deadline = time.monotonic() + 5
            # The leader becomes our zombie before NOTE_EXIT is registered.
            while time.monotonic() < deadline:
                records = job_process_owner._process_records(1, job.pid)
                if records and records[0].state == 5:
                    break
                time.sleep(0.01)
            original(job)

        monkeypatch.setattr(created, "_arm_exit_watch_locked", late_arm)
        _spawn(created, "job-e", "exit 3", spool)
        assert created.authority("job-e").authority == "OWNED"
        exits = created.reap_exits(0)
        assert [(e.job_id, e.exit_code) for e in exits] == [("job-e", 3)]
    finally:
        created.close()


@native
def test_stop_signals_only_owned_group_and_records_stop_requested(owner, spool):
    from tests.platform.darwin.test_job_manager_resilience import wait_for

    started = _spawn(owner, "job-s", "sleep 30 & sleep 30; wait", spool)

    def forked():  # live group members other than the leader
        records = job_process_owner._process_records(2, started.pid)
        return [m for m in records if m.pid != started.pid and m.state != 5]

    assert wait_for(lambda: len(forked()) >= 2, timeout=10)  # no fixed sleep
    members = forked()
    assert owner.authority("job-s").authority == "OWNED"
    owner.signal_owned_group("job-s", "terminate")
    result = owner.wait("job-s", 5)
    assert result is not None
    assert result.signal == signal.SIGTERM
    assert result.termination_reason == "stop_requested"
    # Orphaned members exit after the leader is reaped (launchd reaps them).
    assert wait_for(lambda: not any(_alive(m.pid) for m in members), timeout=10)


@native
def test_unowned_and_disk_identities_are_never_adopted(owner, spool):
    foreign = subprocess.Popen(["/bin/sleep", "5"])
    try:
        for job_id in ("job-missing", str(foreign.pid)):
            observed = owner.authority(job_id)
            assert (observed.authority, observed.alive) == ("UNKNOWN", None)
            with pytest.raises(UnverifiedJobProcess, match="not_owned"):
                owner.signal_owned_group(job_id, "kill")
            with pytest.raises(UnverifiedJobProcess, match="not_owned"):
                owner.wait(job_id, 0)
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait()
    assert not hasattr(owner, "adopt")


@native
def test_duplicate_writer_is_refused(owner, spool):
    _spawn(owner, "job-d", "sleep 5", spool)
    with pytest.raises(ValueError, match="already_owned"):
        _spawn(owner, "job-d", "true", spool)
    assert owner.authority("job-d").authority == "OWNED"


@native
def test_foreign_reap_echild_becomes_unknown_never_exited(spool):
    created = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    try:
        started = _spawn(created, "job-x", "exit 0", spool)
        # A competing waiter breaks the exclusive-reaper contract.
        os.waitpid(started.pid, 0)
        assert created.reap_exits(1) == []
        observed = created.authority("job-x")
        assert (observed.authority, observed.alive) == ("UNKNOWN", None)
        assert observed.reason_code == "darwin_exclusive_reaper_required"
        with pytest.raises(JobOwnerLost):
            created.wait("job-x", 0)
        with pytest.raises(UnverifiedJobProcess):
            created.signal_owned_group("job-x", "kill")
    finally:
        assert created.close() == ()


# The straggler-kill pin is replaced by test_j1g_leader_fence.py (SD-43 F1).


@native
def test_close_kills_reaps_and_returns_owner_restart(spool):
    created = DarwinJobProcessOwner(
        boot_id="b", stop_sigterm_grace_s=0.5, stop_sigkill_grace_s=1.0
    )
    stubborn = _spawn(created, "job-t", "trap '' TERM; sleep 30 & wait", spool)
    polite = _spawn(created, "job-p", "sleep 30", spool)
    time.sleep(0.2)
    members = job_process_owner._process_records(2, stubborn.pid)
    exits = created.close()
    assert {e.job_id: e.termination_reason for e in exits} == {
        "job-t": "owner_restart",
        "job-p": "owner_restart",
    }
    assert not created.reaper_running
    for pid in (stubborn.pid, polite.pid, *(m.pid for m in members)):
        assert not _alive(pid)
    with pytest.raises(Exception, match="closing"):
        _spawn(created, "job-late", "true", spool)


@native
def test_close_without_reaper_thread_drives_sole_reap(spool):
    created = DarwinJobProcessOwner(
        boot_id="b",
        stop_sigterm_grace_s=0.5,
        stop_sigkill_grace_s=0.5,
        start_reaper=False,
    )
    started = _spawn(created, "job-n", "sleep 30", spool)
    _await_zombie(_spawn(created, "job-z", "exit 5", spool).pid)  # event unconsumed
    exits = created.close()
    assert [(e.job_id, e.signal, e.termination_reason) for e in exits] == [
        ("job-n", signal.SIGTERM, "owner_restart"),
        ("job-z", None, "normal_exit"),  # exited before close began (RJ1D-F4)
    ]
    assert not _alive(started.pid)


@native
@pytest.mark.filterwarnings("ignore:This process .* multi-threaded:DeprecationWarning")
def test_forked_child_inherits_no_authority(owner, spool):
    _spawn(owner, "job-f", "sleep 5", spool)
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:  # pragma: no cover - forked child reports through the pipe
        os.close(reader)
        try:
            owner.signal_owned_group("job-f", "kill")
            verdict = b"signalled"
        except JobOwnerLost:
            verdict = b"lost"
        except BaseException:  # noqa: BLE001 - report any other outcome
            verdict = b"other"
        os.write(writer, verdict)
        os._exit(0)
    os.close(writer)
    verdict = os.read(reader, 32)
    os.close(reader)
    os.waitpid(child, 0)
    assert verdict == b"lost"
    assert owner.authority("job-f").authority == "OWNED"


@native
def test_refuses_when_sigchld_is_not_default():
    previous = signal.signal(signal.SIGCHLD, lambda *_: None)
    try:
        with pytest.raises(Exception, match="darwin_exclusive_reaper_required"):
            DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_owned_process_handle_exit_reaped_after_timeout_is_an_exit():
    # wait() timed out, then the reaper reaped before exit_for() (RJ1-F1).
    source = mock.Mock(**{"wait.return_value": None})
    source.exit_for.return_value = OwnedJobExit("j", 7, None, "normal_exit")
    assert OwnedProcessHandle(source, "j", 4242).wait(0.01) == 7


@native
@pytest.mark.parametrize("built_in", [True, False])
@pytest.mark.parametrize("recovers", [True, False])
def test_reaper_fault_wakes_waiters_and_close_still_reaps(spool, built_in, recovers):
    graces = {"stop_sigterm_grace_s": 0.3, "stop_sigkill_grace_s": 0.3}
    created = DarwinJobProcessOwner(boot_id="b", start_reaper=built_in, **graces)
    started = _spawn(created, "job-f", "sleep 30 & sleep 0.5; exit 4", spool)
    created._poll_exit_events = mock.Mock(side_effect=ValueError("injected"))
    if not built_in:  # the caller-driven reap faults the owner too (RJ1D-F2)
        with pytest.raises(ValueError, match="injected"):
            created.reap_exits(0)
        with pytest.raises(JobOwnerLost, match="darwin_job_reaper_failed"):
            created.reap_exits(0)
    outcome = []

    def waiter():
        with pytest.raises(JobOwnerLost, match="darwin_job_reaper_failed"):
            created.wait("job-f", None)
        outcome.append("raised")

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    thread.join(5)
    assert outcome == ["raised"], "wait() hung or returned on a dead reaper"
    if created._reaper is not None:
        created._reaper.join(1)  # it ends once the fault is recorded
    assert not created.reaper_running
    unknown = OwnedJobObservation("job-f", "UNKNOWN", None, "darwin_job_reaper_failed")
    assert created.authority("job-f") == unknown
    with pytest.raises(Exception, match="darwin_job_reaper_failed"):
        _spawn(created, "job-late", "true", spool)
    _await_zombie(started.pid)  # exited leader; its group member still runs
    group = job_process_owner._process_records(2, started.pid)
    members = [m.pid for m in group if m.pid != started.pid]
    if recovers:
        del created._poll_exit_events  # close() drives the sole reap pass itself
    exits = created.close()  # a persistent fault cannot reap: UNKNOWN, no exit
    assert [(e.job_id, e.exit_code, e.termination_reason) for e in exits] == (
        [("job-f", 4, "normal_exit")] if recovers else []
    )
    assert members and not any(_alive(pid) for pid in members)  # RJ1D2-F1


@native
def test_close_returns_unreleased_exits_and_release_keeps_the_id(owner, spool):
    for n in range(3):
        _spawn(owner, f"job-r{n}", f"exit {n + 1}", spool)
    for n in range(3):
        assert owner.wait(f"job-r{n}", 5) is not None
    running = _spawn(owner, "job-live", "sleep 30", spool)
    with pytest.raises(ValueError, match="darwin_job_not_terminal"):
        owner.release("job-live")
    with pytest.raises(UnverifiedJobProcess, match="darwin_job_not_owned"):
        owner.release("job-unknown")
    owner.release("job-r0")
    owner.release("job-r0")  # idempotent after persistence
    assert "job-r0" not in owner._jobs  # out of the per-tick scans (RJ1-F4)
    assert owner.exit_for("job-r0") == OwnedJobExit("job-r0", 1, None, "normal_exit")
    assert owner.wait("job-r0", 0) == owner.exit_for("job-r0")
    assert owner.authority("job-r0").reason_code == "darwin_job_reaped"
    with pytest.raises(ValueError, match="darwin_job_already_owned"):
        _spawn(owner, "job-r0", "true", spool)
    exits = owner.close()  # earlier exits keep their Linux reason (RJ1-F8)
    assert {e.job_id: (e.exit_code, e.termination_reason) for e in exits} == {
        "job-r1": (2, "normal_exit"),
        "job-r2": (3, "normal_exit"),
        "job-live": (None, "owner_restart"),
    }
    assert not _alive(running.pid)


@native
def test_job_signal_dispositions_are_reset_like_linux(spool):
    _root, _stdin, output = spool
    previous = signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    created = DarwinJobProcessOwner(boot_id="b")
    try:
        # SIGXFSZ is SIG_IGN in every Python process; Popen restores it.
        xfsz = "ulimit -f 1; dd if=/dev/zero of=big bs=1024 count=8 2>/dev/null"
        _spawn(created, "job-xfsz", xfsz + "; echo rc=$?", spool)
        assert created.wait("job-xfsz", 10) is not None
        _spawn(created, "job-usr1", "kill -USR1 $$; exit 0", spool)
        result = created.wait("job-usr1", 10)
    finally:
        created.close()
        signal.signal(signal.SIGUSR1, previous)
    output.seek(0)
    assert b"rc=153" in output.read()  # 128 + SIGXFSZ: killed, not EFBIG
    assert result == OwnedJobExit("job-usr1", None, signal.SIGUSR1, "signal")


@native
def test_stop_racing_the_leaders_own_exit_is_delivered(spool, monkeypatch):
    created = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    real_killpg = os.killpg
    raced = []

    def leader_exits_first(pgid, number):
        if raced:
            return real_killpg(pgid, number)
        raced.append(pgid)
        os.kill(pgid, signal.SIGKILL)
        _await_zombie(pgid)
        raise ProcessLookupError

    try:
        _spawn(created, "job-z", "sleep 30", spool)
        monkeypatch.setattr(os, "killpg", leader_exits_first)
        created.signal_owned_group("job-z", "terminate")  # no false partial
        assert raced
        reaped = created.reap_exits(2)
    finally:
        exits = created.close()
    assert [(e.signal, e.termination_reason) for e in reaped] == [
        (signal.SIGKILL, "stop_requested")
    ]
    assert exits == tuple(reaped)  # not released yet: close() still returns it

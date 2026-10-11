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
import time
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import CapabilityUnavailable
from binnacle.platform.contracts.process_contracts import (
    DarwinJobOwner,
    JobOwnerLost,
    OwnedJobExit,
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
    started = _spawn(owner, "job-s", "sleep 30 & sleep 30; wait", spool)
    time.sleep(0.2)
    members = job_process_owner._process_records(2, started.pid)
    assert len(members) >= 2
    assert owner.authority("job-s").authority == "OWNED"
    owner.signal_owned_group("job-s", "terminate")
    result = owner.wait("job-s", 5)
    assert result is not None
    assert result.signal == signal.SIGTERM
    assert result.termination_reason == "stop_requested"
    assert all(not _alive(m.pid) for m in members if m.pid != started.pid)


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


@native
def test_straggler_in_owned_group_is_terminated_before_reap(owner, spool):
    started = _spawn(owner, "job-g", "sleep 30 & exit 0", spool)
    result = owner.wait("job-g", 5)
    assert result is not None
    assert result.termination_reason == "normal_exit"
    assert job_process_owner._process_records(2, started.pid) == []


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
    exits = created.close()
    assert [(e.job_id, e.signal, e.termination_reason) for e in exits] == [
        ("job-n", signal.SIGTERM, "owner_restart")
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

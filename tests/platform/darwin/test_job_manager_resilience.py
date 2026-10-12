"""J2r repairs: reaper survival (R-J2-F1), close and partial-stop durability,
Linux-parity texts (F2, F6) and prior-boot recovery (STEER-10, RJ2D-F3).
Portable: no A3 IPC is needed.
"""

from __future__ import annotations

import errno
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.features.commands import job_client, job_store
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import (
    BudgetExceeded,
    Capability,
    CapabilityState,
)
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_job_manager_service import (
    LABEL,
    SRC,
    Err,
    ReferenceOwner,
    client,
    manager_for,
    meta_of,
    req,
    stop_req,
    write_record,
)


@pytest.fixture
def jobs_dir(tmp_path):
    return tmp_path / "jobs"


@pytest.fixture
def live(jobs_dir):
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, jobs_dir), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    yield owner, manager
    halt.set()
    reaper.join()
    manager.close()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


@contextmanager
def lock_open_fails(monkeypatch, thread_name, error=errno.EMFILE):
    """Inject OSError at the jobs-dir ``.lock`` os.open of one thread only."""
    real_open, armed, hits = os.open, threading.Event(), []

    def flaky_open(path, flags, *args, **kwargs):
        here = threading.current_thread().name == thread_name
        if armed.is_set() and here and Path(os.fspath(path)).name == ".lock":
            hits.append(error)
            raise OSError(error, os.strerror(error))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(svc.os, "open", flaky_open)
    armed.set()
    try:
        yield armed, hits
    finally:
        armed.clear()


def test_partial_delivery_is_persisted_and_refused(
    tmp_path, jobs_dir, live, monkeypatch
):
    owner, manager = live
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    calls = []

    def partial(job, intent):
        calls.append(intent)
        raise pc.JobSignalDeliveryError("EPERM member")

    monkeypatch.setattr(owner, "signal_owned_group", partial)
    error = manager.handle(stop_req(job_id))["error"]
    assert error.startswith("job stop partially failed: EPERM member")
    assert meta_of(jobs_dir, job_id)["stop_signal_partial"] is True
    again = manager.handle(stop_req(job_id))["error"]
    assert again.startswith("job stop partially failed: ") and len(calls) == 2


def test_unpersisted_partial_marker_uses_linux_text(tmp_path, jobs_dir, live):
    # R-J2-F2: job_stop.persist_partial_or_raise maps the OSError to this text.
    assert "partial stop not persisted" in (SRC / "job_stop.py").read_text()
    owner, manager = live
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    real_write = manager._write_meta

    def no_space(job, meta):
        if meta.get(svc.PARTIAL_SIGNAL_FIELD):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(job, meta)

    def partial(job, intent):
        raise pc.JobSignalDeliveryError("EPERM member")

    manager._write_meta, owner.signal_owned_group = no_space, partial
    reply = manager.handle(stop_req(job_id))
    error = "job stop partially failed: partial stop not persisted"
    assert reply == {"ok": False, "error": error}
    assert svc.PARTIAL_SIGNAL_FIELD not in meta_of(jobs_dir, job_id)


def test_retention_close_and_writer_singleton(tmp_path, jobs_dir):
    owner = ReferenceOwner()
    manager = manager_for(owner, jobs_dir, keep=1)  # reserve 1 -> keep 0
    write_record(jobs_dir, "u" * 12, authority="UNKNOWN", exit_code=None)
    write_record(jobs_dir, "t" * 12, exit_code=0)
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    lost = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    assert set(job_store.list_job_ids(jobs_dir)) == {job_id, lost, "u" * 12}
    lost_pid = owner.live.pop(lost)  # simulate a group the owner cannot reap
    try:
        assert [e.job_id for e in manager.close()] == [job_id]
    finally:
        os.killpg(lost_pid, signal.SIGKILL)
        os.waitpid(lost_pid, 0)
    meta, unreaped = meta_of(jobs_dir, job_id), meta_of(jobs_dir, lost)
    assert (meta["signal"], meta["termination_reason"]) == (None, "owner_restart")
    assert "authority" not in meta
    assert unreaped["authority"] == "UNKNOWN"  # never reported exited
    with svc.jobs_dir_writer(jobs_dir), pytest.raises(RuntimeError, match="owns"):
        svc.jobs_dir_writer(jobs_dir).__enter__()


def test_reaper_survives_lock_open_oserror_and_retries(tmp_path, jobs_dir, monkeypatch):
    # R-J2-F1: an OSError from record_exit's lock open must not kill the reaper,
    # drop the exit or let a dead leader read as running or exited.
    monkeypatch.setattr(svc, "EXIT_RETRY_S", 0.05)
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, jobs_dir), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,), name="rp")
    try:
        first = manager.handle(req(tmp_path, "sleep 0.3"))["job_id"]
        with lock_open_fails(monkeypatch, "rp") as (armed, hits):
            reaper.start()
            assert wait_for(lambda: first not in owner.live)  # leader reaped
            assert wait_for(lambda: first in manager._unrecorded)
            # The child exits only after handle() returned, so only the reaper
            # ("rp", where the lock open fails) can see this exit; a fast exit
            # could otherwise be recorded by the handler thread (gate flake).
            # Bounded: without the go file the child gives up after ~30 s (97).
            gated = (
                "i=0; while [ ! -e go-second ] && [ $i -lt 3000 ]; do sleep 0.01; "
                "i=$((i+1)); done; [ -e go-second ] && exit 4; exit 97"
            )
            second = manager.handle(req(tmp_path, gated))["job_id"]
            (tmp_path / "go-second").touch()
            assert wait_for(lambda: second in manager._unrecorded)
            failed = len(hits)
            assert wait_for(lambda: len(hits) >= failed + 4)  # retries keep failing
            assert reaper.is_alive()
            for job_id in (first, second):
                assert not svc._terminal(meta_of(jobs_dir, job_id))  # no false exit
                assert manager.state(job_id) == "unknown"  # never "running"
            armed.clear()  # the lock opens again: the queued exits become durable
            assert wait_for(lambda: not manager._unrecorded)
        assert reaper.is_alive()
        assert meta_of(jobs_dir, first)["exit_code"] == 0
        assert meta_of(jobs_dir, second)["exit_code"] == 4
        assert manager.state(first) == manager.state(second) == "exited"
        third = manager.handle(req(tmp_path, "exit 5"))["job_id"]
        assert wait_for(lambda: "exit_code" in meta_of(jobs_dir, third))
        assert meta_of(jobs_dir, third)["exit_code"] == 5  # later exits persisted
    finally:
        halt.set()
        if reaper.is_alive():
            reaper.join()
        manager.close()


def test_close_persists_queued_exits_before_returning(tmp_path, jobs_dir, monkeypatch):
    # CR0 point 3 / STEER-01: every known exit is durable before close() returns.
    owner = ReferenceOwner()
    manager = manager_for(owner, jobs_dir)
    queued = manager.handle(req(tmp_path, "exit 7"))["job_id"]
    running = manager.handle(req(tmp_path, "sleep 30"))["job_id"]

    def reaped():
        owner.reap_exits(0)
        return queued in owner.exits

    assert wait_for(reaped)
    with lock_open_fails(monkeypatch, threading.current_thread().name):
        assert manager.record_exit(owner.exits[queued]) is False
    assert [e.job_id for e in manager.close()] == [running]
    assert not manager._unrecorded
    assert meta_of(jobs_dir, queued)["exit_code"] == 7
    meta = meta_of(jobs_dir, running)
    assert (meta["signal"], meta["termination_reason"]) == (None, "owner_restart")


def test_exit_still_unpersisted_at_close_becomes_unknown(
    tmp_path, jobs_dir, monkeypatch
):
    owner = ReferenceOwner()
    manager = manager_for(owner, jobs_dir)
    job_id = manager.handle(req(tmp_path, "true"))["job_id"]

    def reaped():
        owner.reap_exits(0)
        return job_id in owner.exits

    assert wait_for(reaped)
    exited = owner.exits[job_id]
    with lock_open_fails(monkeypatch, threading.current_thread().name):
        assert manager.record_exit(exited) is False  # returns, never raises
        assert manager.retry_unrecorded() == 1
        assert manager.state(job_id) == "unknown"
    real_write = manager._write_meta

    def exit_write_fails(job, meta):
        if meta.get("authority") != "UNKNOWN" and svc._terminal(meta):
            raise OSError(errno.EIO, "I/O error")
        return real_write(job, meta)

    monkeypatch.setattr(manager, "_write_meta", exit_write_fails)
    manager.close()  # the exit is still not durable: UNKNOWN, never exited
    meta = meta_of(jobs_dir, job_id)
    assert (meta["authority"], meta["exit_code"]) == ("UNKNOWN", None)
    assert meta["termination_reason"] == "owner_restart"
    assert manager.state(job_id) == "unknown"


def test_dead_reaper_stops_serving_instead_of_serving_blind(jobs_dir, monkeypatch):
    from binnacle.platform.darwin import ipc_transport

    manager = manager_for(ReferenceOwner(), jobs_dir)
    stop, served = threading.Event(), []
    lease = ServiceLease(os.getuid(), LABEL, "g" * 32, 0, 0)

    def blind_serve(socket_path, *, lease, handler, stop):
        served.append(stop.wait(10))

    def broken_reaper(halt):
        raise RuntimeError("reaper bug")

    monkeypatch.setattr(ipc_transport, "serve_authenticated", blind_serve)
    monkeypatch.setattr(manager, "reap_forever", broken_reaper)
    with pytest.raises(RuntimeError, match="job_manager_reaper_stopped"):
        entry.serve_job_manager(
            manager, socket_path=jobs_dir / "s", lease=lease, stop=stop
        )
    assert served == [True] and stop.is_set()  # serving ended because of the reaper


def test_response_timeout_uses_linux_text_without_replay(monkeypatch):
    # R-J2-F6: the Linux client's response timeout text, and no request replay.
    from binnacle.platform.darwin import generation_runtime, ipc_transport

    with tempfile.TemporaryDirectory(prefix="r4-j2-", dir="/tmp") as short:
        sock = Path(short) / "jobs.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(sock))
            server.listen(1)
            with pytest.raises(Err) as linux:
                job_client._request(sock, {"version": 1}, timeout_s=0.2)
    sent = []

    class SlowChannel:
        def request(self, payload, *, timeout_s):
            sent.append(payload)
            code = "ipc_request_timeout_outcome_unknown"
            raise BudgetExceeded(code, Capability(CapabilityState.UNKNOWN, code, ""))

        def close(self):
            pass

    monkeypatch.setattr(generation_runtime, "discover_service_lease", lambda **k: k)
    monkeypatch.setattr(
        ipc_transport, "connect_authenticated", lambda *a, **k: SlowChannel()
    )
    with pytest.raises(Err) as darwin:
        client().stop(sock, "0" * 12)
    assert (
        str(darwin.value)
        == str(linux.value)
        == (f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: timed out")
    )
    assert len(sent) == 1  # a dispatched request is never replayed


def session():
    return str(uuid.uuid4()).upper()  # the kern.bootsessionuuid form


def booted(jobs_dir, boot):
    kw = {"wait_max_s": 50, "keep_newest": 50}
    return svc.DarwinJobManager(
        owner=ReferenceOwner(), jobs_dir=jobs_dir, boot_id=boot, **kw
    )


def test_prior_boot_records_are_finalised_like_linux_and_not_counted(jobs_dir):
    # STEER-10: a provably earlier boot's jobs are gone (design section 7).
    now, prior = session(), session()
    v2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": prior}
    write_record(jobs_dir, "a" * 12, **v2)  # unfinished
    write_record(jobs_dir, "b" * 12, **v2, stop_requested=True)
    lost = {"exit_code": None, "signal": None, "ended_at": 2.0, "authority": "UNKNOWN"}
    write_record(jobs_dir, "c" * 12, **v2, **lost, termination_reason="owner_restart")
    write_record(jobs_dir, "d" * 12, **v2, exit_code=0, termination_reason="signal")
    manager = booted(jobs_dir, now)
    assert (manager.recover(), manager.recover()) == (3, 0)
    reasons = {}
    for job_id in ("a" * 12, "b" * 12, "c" * 12):
        meta = meta_of(jobs_dir, job_id)
        assert "authority" not in meta and meta["pid"] == 31337
        assert (meta["exit_code"], meta["signal"]) == (None, None)
        reasons[job_id[0]] = meta["termination_reason"]
        assert manager.state(job_id) == "exited"
    assert reasons == {"a": "host_reboot", "b": "stop_requested", "c": "host_reboot"}
    assert meta_of(jobs_dir, "d" * 12)["termination_reason"] == "signal"  # untouched
    assert manager.job_counts() == (0, 0)  # a quiet window is reachable again
    assert manager.handle(stop_req("a" * 12))["state"] == "exited"


def test_same_boot_and_unprovable_records_stay_unknown_and_counted(jobs_dir):
    # STEER-10 (2): a manager crash in this boot is D-1; no proof, no finalising.
    now = session()
    v2 = {"schema_version": 2, "owner_instance_id": "old"}
    write_record(jobs_dir, "a" * 12, **v2, boot_id=now)  # same boot
    write_record(jobs_dir, "b" * 12, **v2)  # the record has no boot id
    write_record(jobs_dir, "c" * 12, **v2, boot_id="1791391931.519537-25FECA3D")
    manager = booted(jobs_dir, now)
    assert (manager.recover(), manager.recover()) == (3, 0)
    reasons = {}
    for job_id in ("a" * 12, "b" * 12, "c" * 12):
        meta = meta_of(jobs_dir, job_id)
        assert meta["authority"] == "UNKNOWN" and manager.state(job_id) == "unknown"
        reasons[job_id[0]] = meta["termination_reason"]
        refused = {"ok": False, "error": pc.OWNER_LOST_STOP_REFUSED}
        assert manager.handle(stop_req(job_id)) == refused
    assert reasons == {"a": "owner_restart", "b": "host_reboot", "c": "host_reboot"}
    assert manager.job_counts() == (0, 3)


def test_unreadable_current_boot_identity_fails_closed(jobs_dir):
    # STEER-10 (1): without a readable current boot, no record is provably gone.
    v2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": session()}
    write_record(jobs_dir, "a" * 12, **v2)
    for current in ("", "unreadable", session().lower()):
        assert not entry.prior_boot(v2, current)
    manager = booted(jobs_dir, "")
    assert manager.recover() == 1
    assert meta_of(jobs_dir, "a" * 12)["authority"] == "UNKNOWN"
    assert manager.job_counts() == (0, 1)
    assert booted(jobs_dir, session()).recover() == 1  # finalised once provable
    assert "authority" not in meta_of(jobs_dir, "a" * 12)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin libproc")
def test_verified_teardown_signal_skips_stale_or_reused_targets():
    from tests import signal_safety as safety

    proc = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    try:
        record = safety.observe(proc.pid)
        assert record and record.parent == os.getpid() and record.group == proc.pid
        stale = (record.birth[0] - 5, record.birth[1])  # same pid, other birth
        before = len(safety.SKIPPED)
        assert not safety.kill_verified(proc.pid, stale, group=True)
        assert not safety.kill_verified(proc.pid, record.birth, parent=1)
        assert len(safety.SKIPPED) >= before + 2
        assert proc.poll() is None  # nothing was signalled
        assert safety.kill_verified(
            proc.pid, record.birth, group=True, parent=os.getpid()
        )
        proc.wait(timeout=5)
        assert proc.returncode == -signal.SIGKILL
        assert not safety.kill_verified(proc.pid, record.birth, group=True)  # gone
    finally:
        if proc.poll() is None:
            proc.kill()  # own unreaped child
            proc.wait()


# --- P2 pre-review repairs (R4 J1g-a2, SD-49) -------------------------------


def procargs(argc, path, *fields, pad=None):
    """A KERN_PROCARGS2 buffer: argc, exec path, 8-byte NUL padding, strings."""
    pad = (-(len(path) + 1)) % 8 if pad is None else pad  # native: path + NUL
    head = argc.to_bytes(4, sys.byteorder) + path + b"\0" * (1 + pad)
    return head + b"".join(field + b"\0" for field in fields)


@pytest.mark.parametrize(
    ("buffer", "expected"),
    [
        (procargs(3, b"/bin/x", b"x", b"", b"tail", b"K=v"), "x  tail"),
        (procargs(1, b"/bin/x", b"x", b"SECRET=1", b"P=2"), "x"),
        (procargs(2, b"/bin/x", b"", b"a", b"K=v"), None),  # empty argv[0]
        (procargs(1, b"/bin/x", b"x", pad=2), None),  # misaligned padding
        (procargs(3, b"/bin/x", b"x", b"K=v"), None),  # argc > fields present
        (procargs(3, b"/bin/x", b"x", b"\xff", b"K=v"), None),  # undecodable
        (procargs(1, b"/bin/x")[:-1] + b"x", None),  # no argv terminator
        (b"\x01\x00", None),  # short buffer
    ],
)
def test_procargs2_parse_is_argv_only_and_fails_closed(monkeypatch, buffer, expected):
    """PRE-J1g-F1: never a field past argv (envp); any doubt -> None (comm)."""
    monkeypatch.setattr(entry, "_sysctl", lambda mib, limit: buffer)
    assert entry.command_line(1, 4096) == expected
    padded = procargs(1, b"/x", b"ab" * 9)
    monkeypatch.setattr(entry, "_sysctl", lambda mib, limit: padded)
    assert entry.command_line(1, 5) == "ababa"  # bounded after the join


def test_start_refused_once_the_manager_is_stopping(tmp_path, jobs_dir):
    """PRE-J1g-F6: no job is launched into close() (owner_closing parity)."""
    owner = ReferenceOwner()
    manager = manager_for(owner, jobs_dir)
    manager.stopping.set()
    try:
        reply = manager.handle(req(tmp_path, "sleep 30"))
        assert reply == {
            "ok": False,
            "error": "could not start job: job manager stopping",
        }
        assert not any(jobs_dir.glob("*/meta.json"))
    finally:
        manager.close()


def test_manager_entry_refuses_without_waitid(monkeypatch, caplog):
    """JCR-F1: no os.waitid (macOS Python < 3.13) -> refuse before any lease."""
    from unittest import mock

    from binnacle.platform.darwin import job_group_fence as fence

    monkeypatch.delattr(os, "waitid", raising=False)
    lease, owner = mock.Mock(), mock.Mock()
    monkeypatch.setattr(entry, "open_service_lease", lease)
    monkeypatch.setattr(entry, "compose_owner", owner)
    assert entry.main([]) == entry.EX_CONFIG
    assert fence.WAITID_REQUIRED in caplog.text
    assert not lease.called and not owner.called  # no lease, no owner, no spawn

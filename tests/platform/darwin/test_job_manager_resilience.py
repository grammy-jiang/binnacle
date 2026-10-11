"""J2r repairs: reaper survival (R-J2-F1), close and partial-stop durability,
and Linux-parity texts (F2, F6). Portable: no A3 IPC is needed.
"""

from __future__ import annotations

import errno
import os
import signal
import socket
import tempfile
import threading
import time
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
    assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")
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
            second = manager.handle(req(tmp_path, "exit 4"))["job_id"]
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
    assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")


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

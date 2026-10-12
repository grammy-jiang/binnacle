"""Darwin Job Manager RPC v1 over A3; a reference owner stands in for J1."""

from __future__ import annotations

import ast
import inspect
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

from binnacle.features.commands import job_client, job_store
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import job_manager_client as jm_client
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin import job_manager_records as records
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin.generation_runtime import (
    discover_service_lease,
    open_service_lease,
)

NATIVE = pytest.mark.skipif(
    sys.platform != "darwin" or not hasattr(os, "waitid"), reason="Darwin A3 IPC"
)
LABEL = "com.binnacle.r4test.jobs"
SRC = Path(__file__).resolve().parents[3] / "src/binnacle/features/commands"
Err = job_client.JobManagerError


class ReferenceOwner:
    def __init__(self):
        self.owner_instance_id = uuid.uuid4().hex
        self.cond, self.closing = threading.Condition(), set()
        self.live, self.exits, self.released = {}, {}, set()

    def spawn(self, job_id, argv, *, workdir, env, stdin, output):
        shim = 'cd "$1" || exit 127; shift; exec "$@"'
        dups = [(os.POSIX_SPAWN_DUP2, stdin.fileno(), 0)]
        dups += [(os.POSIX_SPAWN_DUP2, output.fileno(), n) for n in (1, 2)]
        args = ["/bin/sh", "-c", shim, "sh", str(workdir), *argv]
        sigdef = (signal.SIGPIPE, signal.SIGTERM, signal.SIGINT, signal.SIGCHLD)
        # pgid == pid; posix_spawn setsid is NotImplemented on Linux CPython
        kw = {"file_actions": dups, "setpgroup": 0, "setsigdef": sigdef}
        pid = os.posix_spawn(args[0], args, dict(env), **kw)
        with self.cond:
            self.live[job_id] = pid
        return pc.OwnedJobProcess(job_id, pid, pid, 1, self.owner_instance_id, "b")

    def _reap_locked(self):
        reaped = []
        for job_id, pid in tuple(self.live.items()):
            try:
                done, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:  # ECHILD: UNKNOWN, never exited
                del self.live[job_id]
                continue
            if done:
                del self.live[job_id]
                code = os.waitstatus_to_exitcode(status)
                reason = "signal" if code < 0 else "normal_exit"
                reason = "owner_restart" if job_id in self.closing else reason
                sig = -code if code < 0 else None
                exited = pc.OwnedJobExit(job_id, None if sig else code, sig, reason)
                self.exits[job_id] = exited
                reaped.append(exited)
        self.cond.notify_all()
        return reaped

    def reap_exits(self, timeout):
        time.sleep(min(timeout or 0, 0.02))
        with self.cond:
            return self._reap_locked()

    def wait(self, job_id, timeout):
        with self.cond:
            self.cond.wait_for(lambda: job_id in self.exits, timeout)
            return self.exits.get(job_id)

    def signal_owned_group(self, job_id, intent):
        with self.cond:
            if job_id not in self.live:
                raise pc.UnverifiedJobProcess(job_id)
            sig = signal.SIGTERM if intent == "terminate" else signal.SIGKILL
            os.killpg(self.live[job_id], sig)  # unreaped leader holds the pgid

    def release(self, job_id):  # J1 1.2.0-additive ack of a durable record
        with self.cond:
            if job_id not in self.live and job_id not in self.exits:
                raise pc.UnverifiedJobProcess("darwin_job_not_owned")  # as J1
            if job_id in self.live:
                raise ValueError("darwin_job_not_terminal")
            self.released.add(job_id)

    def authority(self, job_id):
        with self.cond:
            if job_id in self.live:
                return Owned(job_id, "OWNED", True, "owned")
        return Owned(job_id, "UNKNOWN", None, "not_owned")

    def close(self):
        with self.cond:
            self.closing.update(self.live)
            for pid in self.live.values():
                os.killpg(pid, signal.SIGTERM)
        closed, deadline = [], time.monotonic() + 2
        while self.live and time.monotonic() < deadline:
            closed += self.reap_exits(0.05)
        return closed


@pytest.fixture
def jobs_dir(tmp_path):
    return tmp_path / "jobs"


def manager_for(owner, jobs_dir, keep=50):
    kw = {"boot_id": "boot", "wait_max_s": 50, "keep_newest": keep, "grace": (0.5, 0.5)}
    return svc.DarwinJobManager(owner=owner, jobs_dir=jobs_dir, **kw)


def write_record(jobs_dir, job_id, **meta):
    (jobs_dir / job_id).mkdir(parents=True)
    base = {"command": "sleep 30", "workdir": "/", "pid": 31337, "started_at": 1.0}
    (jobs_dir / job_id / "meta.json").write_text(json.dumps({**base, **meta}))


def meta_of(jobs_dir, job_id):
    return json.loads((jobs_dir / job_id / "meta.json").read_text())


def req(workdir, command="true", wait=0.0, stdin=None, **extra):
    base = {"version": 1, "op": "start", "command": command, "stdin": stdin}
    return {**base, "workdir": str(workdir), "wait_seconds": wait, **extra}


def stop_req(job_id):
    return {"version": 1, "op": "stop", "job_id": job_id}


Owned = pc.OwnedJobObservation


def lit(name, key):
    body = ast.parse((SRC / name).read_text()).body
    found = {
        t.id: n.value for n in body if isinstance(n, ast.Assign) for t in n.targets
    }
    return ast.literal_eval(found[key])


def test_restated_values_equal_linux_source():
    assert svc.STOP_SIGTERM_GRACE_S == lit("jobs.py", "STOP_SIGTERM_GRACE_S")
    assert svc.STOP_SIGKILL_GRACE_S == lit("jobs.py", "STOP_SIGKILL_GRACE_S")
    assert dict(svc.ENV_OVERRIDES) == lit("jobs.py", "_ENV_OVERRIDES")
    assert records.META_REQUIRED == lit("job_store.py", "META_REQUIRED")
    assert svc.PARTIAL_SIGNAL_FIELD == lit("job_stop.py", "PARTIAL_SIGNAL_FIELD")
    assert svc.PARTIAL_SIGNAL_MESSAGE == lit("job_stop.py", "PARTIAL_SIGNAL_MESSAGE")
    assert svc.PROTOCOL_VERSION == lit("job_client.py", "PROTOCOL_VERSION") == 1
    for name in ("ping", "start", "stop"):
        method = inspect.signature(getattr(jm_client.DarwinJobClient, name))
        linux = inspect.signature(getattr(job_client, name)).parameters.values()
        assert list(method.parameters.values())[1:] == list(linux)


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


TEXTS = (
    "wait_seconds outside manager bounds|workdir is not a directory: |no job with id|"
    "command/stdin have invalid types|job_id must be a string|could not start job: |"
    "job stop partially failed: |internal job-manager error|invalid job-manager request"
)


def test_dispatch_objects_equal_linux_manager_text(tmp_path, jobs_dir, live):
    owner, manager = live
    linux = (SRC / "job_manager.py").read_text()
    assert all(text in linux for text in TEXTS.split("|"))
    pong = manager.handle({"version": 1, "op": "ping"})
    keys = {"ok", "version", "owner_instance_id", "boot_id", "pid", "revision"}
    assert set(pong) == keys | {"package_version", "running_jobs", "unknown_jobs"}
    version = manager.handle({"version": 2, "op": "ping"})["error"]
    assert version == "unsupported job-manager protocol version"
    unknown = manager.handle({"version": 1, "op": "x"})["error"]
    assert unknown == "unknown job-manager operation 'x'"
    bad = [req(tmp_path / "gone"), req(tmp_path, wait=51), req(tmp_path, wait=1e999)]
    bad += [req(tmp_path, command=["x"]), {"version": 1, "op": "stop"}, stop_req(3)]
    for request in bad:
        error = manager.handle(request)["error"]
        assert error.startswith("invalid job-manager request: ")
    assert job_store.list_job_ids(jobs_dir) == []
    owner.spawn = lambda *a, **k: (_ for _ in ()).throw(OSError(24, "Too many"))
    failed = manager.handle(req(tmp_path))["error"]
    assert failed == "could not start job: [Errno 24] Too many"
    assert job_store.list_job_ids(jobs_dir) == []  # reservation removed


def test_start_exit_and_stop_term_then_kill(tmp_path, jobs_dir, live):
    owner, manager = live
    done = manager.handle(req(tmp_path, "cat; exit 3", wait=5, stdin="x"))
    meta = job_store.read_meta(jobs_dir, done["job_id"])
    assert meta == records.read_meta(jobs_dir, done["job_id"])
    assert (done["state"], meta["exit_code"], meta["pgid"]) == (
        "exited",
        3,
        meta["pid"],
    )
    assert (meta["schema_version"], meta["owner"]) == (2, "manager")
    assert meta["owner_instance_id"] == owner.owner_instance_id
    assert meta["termination_reason"] == "normal_exit" and "signal" not in meta
    names = sorted(p.name for p in (jobs_dir / done["job_id"]).iterdir())
    assert names == ["meta.json", "out.log", "stdin"]
    assert job_store.read_log_range(jobs_dir, done["job_id"], 0, 9) == (b"x", 1)
    job_id = manager.handle(req(tmp_path, "trap '' TERM; sleep 30", wait=0.3))["job_id"]
    reply = manager.handle(stop_req(job_id))
    assert reply == {"ok": True, "job_id": job_id, "state": "exited"}
    meta = meta_of(jobs_dir, job_id)
    assert (meta["stop_requested"], meta["signal"]) == (True, 9)  # TERM ignored
    assert meta["termination_reason"] == "stop_requested"
    assert manager.handle(stop_req(job_id)) == reply  # idempotent
    assert manager.handle(stop_req("../etc"))["error"] == "no job with id '../etc'"


def test_recovery_marks_foreign_records_unknown_without_adoption(jobs_dir):
    v2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": "boot"}
    write_record(jobs_dir, "a" * 12, **v2)
    write_record(jobs_dir, "b" * 12, **{**v2, "boot_id": "prev"})
    write_record(jobs_dir, "c" * 12, **v2, stop_requested=True)
    write_record(jobs_dir, "d" * 12, **v2, exit_code=0)
    write_record(jobs_dir, "e" * 12)  # legacy embedded record: not ours to judge
    owner = ReferenceOwner()
    owner.signal_owned_group = None  # any signal attempt would fail the test
    manager = manager_for(owner, jobs_dir)
    refused = {"ok": False, "error": pc.OWNER_LOST_STOP_REFUSED}
    assert manager.handle(stop_req("a" * 12)) == refused  # before recovery too
    assert (manager.recover(), manager.recover()) == (3, 0)
    reasons = {}
    for job_id in ("a" * 12, "b" * 12, "c" * 12):
        meta = meta_of(jobs_dir, job_id)
        assert meta["authority"] == "UNKNOWN" and meta["pid"] == 31337
        assert meta["exit_code"] is None and meta["signal"] is None
        reasons[job_id[0]] = meta["termination_reason"]
        assert manager.state(job_id) == "unknown"
        assert manager.handle(stop_req(job_id)) == refused
    assert reasons == {"a": "owner_restart", "b": "host_reboot", "c": "stop_requested"}
    assert "authority" not in meta_of(jobs_dir, "d" * 12)
    assert "authority" not in meta_of(jobs_dir, "e" * 12)
    assert not manager.record_exit(pc.OwnedJobExit("e" * 12, 0, None, "normal_exit"))


@pytest.fixture
def runtime():
    with tempfile.TemporaryDirectory(prefix="r4-j2-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        yield base


def new_lease(root):
    return open_service_lease(root=root, label=LABEL, generation=secrets.token_hex(16))


def client(error_type=Err):
    return jm_client.DarwinJobClient(label=LABEL, error_type=error_type)


def wait_published(sock, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with suppress(Err):
            return client().ping(sock)
        time.sleep(0.02)
    return client().ping(sock)


def run(sock, command, workdir, wait=0.2, stdin=None):
    kw = {"command": command, "workdir": workdir, "stdin": stdin}
    return client().start(sock, wait_seconds=wait, call_id="c", **kw)


@contextmanager
def serving(base, jobs=None, name="jobs.sock"):
    manager = manager_for(ReferenceOwner(), jobs or base / "jobs")
    stop, errors, sock = threading.Event(), [], base / "rt" / name

    def serve():
        try:
            lease = new_lease(base / "rt")
            entry.serve_job_manager(manager, socket_path=sock, lease=lease, stop=stop)
        except Exception as exc:  # noqa: BLE001 - surfaced by the test
            errors.append(exc)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        wait_published(sock)
        yield sock, manager, errors
    finally:
        stop.set()
        thread.join(15)
        assert not thread.is_alive(), "manager failed to drain and close"


def group_gone(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def serve_once(manager, root):
    lease, stop = new_lease(root), threading.Event()
    sock = root / "jobs.sock"
    return entry.serve_job_manager(manager, socket_path=sock, lease=lease, stop=stop)


@NATIVE
def test_rpc_v1_over_authenticated_ipc_end_to_end(runtime, tmp_path):
    with serving(runtime) as (sock, manager, errors):
        lease = discover_service_lease(root=sock.parent, label=LABEL, name=sock.name)
        assert lease.label == LABEL
        with pytest.raises(NativeCapabilityError, match="generation_mismatch"):
            discover_service_lease(root=sock.parent, label=LABEL + ".x", name=sock.name)
        done = run(sock, "echo hi; echo err >&2; exit 3", tmp_path, wait=5)
        meta = meta_of(manager.jobs_dir, done["job_id"])
        assert done["state"] == "exited" and meta["exit_code"] == 3
        assert (
            manager.jobs_dir / done["job_id"] / "out.log"
        ).read_text() == "hi\nerr\n"
        running = run(sock, "sleep 30", tmp_path)
        assert running["state"] == "running"  # wait expiry continues, never kills
        pgid = meta_of(manager.jobs_dir, running["job_id"])["pgid"]
        stopped = client().stop(sock, running["job_id"], call_id="c-stop")
        assert stopped == {"ok": True, "job_id": running["job_id"], "state": "exited"}
        meta = meta_of(manager.jobs_dir, running["job_id"])
        assert (meta["signal"], meta["termination_reason"]) == (15, "stop_requested")
        assert group_gone(pgid)
        with pytest.raises(Err, match="no job with id"):
            client().stop(sock, "0" * 12)
    assert not (errors or sock.exists() or sock.with_name("jobs.sock.auth").exists())
    with pytest.raises(NativeCapabilityError, match="ipc_endpoint_unpublished"):
        discover_service_lease(root=sock.parent, label=LABEL, name=sock.name)


@NATIVE
def test_client_discovers_a_non_default_socket_basename(runtime, tmp_path):
    # R-J2-F3: the client reads '<socket basename>.auth', as the manager publishes.
    with serving(runtime, name="mgr.sock") as (sock, manager, errors):
        assert sock.with_name("mgr.sock.auth").exists()
        assert not sock.with_name("jobs.sock.auth").exists()
        pong = client().ping(sock)
        assert pong["owner_instance_id"] == manager.owner_instance_id
        lease = discover_service_lease(root=sock.parent, label=LABEL, name=sock.name)
        assert lease.label == LABEL
        with pytest.raises(NativeCapabilityError, match="ipc_endpoint_unpublished"):
            discover_service_lease(root=sock.parent, label=LABEL, name="jobs.sock")
        assert run(sock, "exit 6", tmp_path, wait=5)["state"] == "exited"
    assert not (errors or sock.exists() or sock.with_name("mgr.sock.auth").exists())


@NATIVE
def test_manager_stop_kills_and_records_owned_groups_no_orphans(runtime, tmp_path):
    # R4-REQ-J1J2-no-orphans; an MCP server restart is only a new client.
    with serving(runtime) as (sock, manager, errors):
        job = run(sock, "sleep 60 & wait", tmp_path)
        pgid = meta_of(manager.jobs_dir, job["job_id"])["pgid"]
        assert client().ping(sock)["owner_instance_id"] == manager.owner_instance_id
        assert manager.state(job["job_id"]) == "running"
    meta = meta_of(manager.jobs_dir, job["job_id"])
    # Linux job_owner._record_interruption: no exit status, reason owner_restart.
    got = (meta["exit_code"], meta["signal"], meta["termination_reason"])
    assert got == (None, None, "owner_restart")
    assert "authority" not in meta and not errors
    assert group_gone(pgid)  # no untracked survivor in the owned group


@NATIVE
def test_peer_uid_and_hmac_refusals_never_dispatch(runtime, tmp_path, monkeypatch):
    from binnacle.platform.darwin import ipc_transport as ipc

    with serving(runtime) as (sock, manager, errors):
        real_peer = ipc._peer
        monkeypatch.setattr(ipc, "_peer", lambda c: (os.getuid() + 1, real_peer(c)[1]))
        with pytest.raises(jm_client.DarwinJobManagerError) as refused:
            client(None).ping(sock)
        message = str(refused.value)
        assert message.startswith(f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: ")
        with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
            run(sock, "touch x", tmp_path)
        monkeypatch.setattr(ipc, "_peer", real_peer)
        auth = sock.with_name("jobs.sock.auth")
        original = auth.read_bytes()
        auth.write_text(json.dumps({**json.loads(original), "key": "0" * 64}))
        with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
            run(sock, "touch x", tmp_path)
        auth.write_bytes(original)
        lease = discover_service_lease(root=sock.parent, label=LABEL, name=sock.name)
        channel = ipc.connect_authenticated(sock, lease=lease, timeout_s=2)
        forged = {"sequence": 0, "kind": "rpc", "proof": "0" * 64}
        forged["payload"] = req(tmp_path, "touch x", wait=1)
        ipc._send(channel.conn, forged, time.monotonic() + 2)
        assert channel.conn.recv(1) == b""  # dropped undispatched
        channel.close()
        assert job_store.list_job_ids(manager.jobs_dir) == []
    assert not (tmp_path / "x").exists() and not errors


@NATIVE
def test_duplicate_starters_never_write_or_recover(runtime, tmp_path):
    with serving(runtime) as (sock, manager, errors):
        job = run(sock, "sleep 30", tmp_path, wait=0.1)
        before = meta_of(manager.jobs_dir, job["job_id"])
        loser = manager_for(ReferenceOwner(), runtime / "other-jobs")
        with pytest.raises(NativeCapabilityError, match="ipc_duplicate_starter"):
            serve_once(loser, sock.parent)  # same root: A3 kernel lease refuses
        (runtime / "rt2").mkdir(mode=0o700)
        rival = manager_for(ReferenceOwner(), manager.jobs_dir)
        with pytest.raises(RuntimeError, match="already owns"):
            serve_once(rival, runtime / "rt2")  # same jobs dir: writer lock refuses
        assert meta_of(manager.jobs_dir, job["job_id"]) == before  # no recovery ran
        assert manager.state(job["job_id"]) == "running"
        assert not (runtime / "rt2/jobs.sock").exists()
        assert client().ping(sock)["owner_instance_id"] == manager.owner_instance_id
    assert not errors
    previous = signal.signal(signal.SIGCHLD, lambda *_: None)
    try:
        with pytest.raises(RuntimeError, match="darwin_exclusive_reaper_required"):
            serve_once(manager_for(ReferenceOwner(), runtime / "j3"), runtime / "rt")
    finally:
        signal.signal(signal.SIGCHLD, previous)


@NATIVE
def test_killed_manager_jobs_become_unknown_and_endpoint_reclaimed(runtime, tmp_path):
    root, jobs = runtime / "rt", runtime / "jobs"
    argv = [sys.executable, __file__, str(root), str(jobs)]
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    from tests import signal_safety as safety

    pgid = birth = None
    try:
        assert wait_published(root / "jobs.sock", timeout=20)["pid"] == child.pid
        job = run(root / "jobs.sock", "sleep 30", tmp_path, wait=0.1)
        pgid = meta_of(jobs, job["job_id"])["pgid"]
        leader = safety.observe(pgid)  # the reference owner's meta birth is a stub
        assert leader and leader.group == pgid and leader.parent == child.pid
        birth = leader.birth
        child.kill()
        child.communicate(timeout=5)
        assert (root / "jobs.sock").exists()  # journalled stale endpoint remains
        with serving(runtime) as (sock, manager, errors):
            meta = meta_of(jobs, job["job_id"])
            assert (meta["authority"], meta["exit_code"]) == ("UNKNOWN", None)
            assert meta["termination_reason"] == "owner_restart"
            assert manager.state(job["job_id"]) == "unknown"
            with pytest.raises(Err, match=pc.OWNER_LOST_STOP_REFUSED):
                client().stop(sock, job["job_id"])
            assert not group_gone(pgid)  # never signalled: no adoption
        assert not errors
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        if pgid is not None and birth is not None and not group_gone(pgid):
            # Leader was reparented to launchd; pgid may be recycled: verify first.
            safety.kill_verified(pgid, birth, group=True, parent=1)


def _main():
    root, jobs = Path(sys.argv[1]), Path(sys.argv[2])  # child for the kill -9 test
    return serve_once(manager_for(ReferenceOwner(), jobs), root)


if __name__ == "__main__":
    raise SystemExit(_main())

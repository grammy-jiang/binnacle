"""Native Darwin IPC negatives plus portable private-root contract tests."""

from __future__ import annotations

import dataclasses
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import ipc_transport as ipc
from binnacle.platform.darwin.generation_runtime import (
    open_service_lease,
    resolve_runtime_paths,
    validate_lease,
)

NATIVE = pytest.mark.skipif(
    sys.platform != "darwin", reason="Darwin getpeereid/LOCAL_PEERPID native contract"
)
LABEL = "com.binnacle.r3test.ipc"


@pytest.fixture
def runtime():
    with tempfile.TemporaryDirectory(
        prefix="bna3-", dir=Path(tempfile.gettempdir()).resolve()
    ) as value:
        root = Path(value)
        root.chmod(0o700)
        yield root


def lease_for(root):
    return open_service_lease(root=root, label=LABEL, generation=secrets.token_hex(16))


def connect_when_ready(path, lease, *, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return ipc.connect_authenticated(path, lease=lease, timeout_s=0.5)
        except NativeCapabilityError:
            time.sleep(0.02)
    pytest.fail("authenticated readiness deadline expired")


@contextmanager
def serving(root):
    lease = lease_for(root)
    stop = threading.Event()
    calls, errors = [], []

    def handler(payload):
        calls.append(dict(payload))
        return {"ok": True, "payload": dict(payload)}

    def run():
        try:
            ipc.serve_authenticated(
                root / "jobs.sock", lease=lease, handler=handler, stop=stop
            )
        except (OSError, NativeCapabilityError) as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        channel = connect_when_ready(root / "jobs.sock", lease)
        channel.close()
        yield lease, calls, errors
    finally:
        stop.set()
        thread.join(4)
        assert not thread.is_alive(), "server failed to quiesce"


def test_private_root_and_replaced_inode(runtime, monkeypatch):
    lease = lease_for(runtime)
    monkeypatch.setenv("BINNACLE_RUNTIME_DIR", str(runtime))
    assert resolve_runtime_paths().jobs_socket == runtime / "jobs.sock"
    moved = runtime.with_name(runtime.name + "-moved")
    runtime.rename(moved)
    runtime.mkdir(mode=0o700)
    try:
        with pytest.raises(NativeCapabilityError):
            validate_lease(runtime, lease)
    finally:
        runtime.rmdir()
        moved.rename(runtime)


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_nonprivate_root_refused(runtime, mode):
    runtime.chmod(mode)
    with pytest.raises(NativeCapabilityError):
        lease_for(runtime)


def test_symlink_ancestor_and_overlong_path_refused(runtime, monkeypatch):
    real = runtime / "real"
    real.mkdir(mode=0o700)
    alias = runtime / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(NativeCapabilityError):
        lease_for(alias)
    monkeypatch.setenv("BINNACLE_RUNTIME_DIR", str(runtime / ("x" * 104)))
    with pytest.raises(NativeCapabilityError):
        resolve_runtime_paths()


@NATIVE
def test_mutual_authentication_and_unchanged_rpc_payload(runtime):
    with serving(runtime) as (lease, calls, errors):
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        payload = {"version": 1, "op": "ping", "opaque": [1, None, "value"]}
        assert channel.request(payload, timeout_s=1) == {"ok": True, "payload": payload}
        channel.close()
        assert calls == [payload]  # transport readiness never dispatches RPC
    assert not errors
    assert not (runtime / "jobs.sock").exists()
    assert not (runtime / "jobs.sock.auth").exists()
    assert (runtime / "manager.lock").exists()  # retained to prevent split locks


@NATIVE
def test_wrong_generation_secret_peer_and_unauthenticated_requests(runtime):
    with serving(runtime) as (lease, calls, errors):
        wrong = dataclasses.replace(lease, generation=secrets.token_hex(16))
        with pytest.raises(NativeCapabilityError):
            ipc.connect_authenticated(runtime / "jobs.sock", lease=wrong, timeout_s=1)
        auth = runtime / "jobs.sock.auth"
        original = auth.read_bytes()
        for field, replacement in (
            ("key", secrets.token_hex(32)),
            ("pid", os.getpid() + 100000),
        ):
            value = json.loads(original)
            value[field] = replacement
            auth.write_text(json.dumps(value))
            with pytest.raises(NativeCapabilityError):
                ipc.connect_authenticated(
                    runtime / "jobs.sock", lease=lease, timeout_s=1
                )
            auth.write_bytes(original)
        for hello in (
            {"version": 1, "op": "stop"},
            {
                "version": 1,
                "generation": wrong.generation,
                "nonce": secrets.token_hex(32),
            },
        ):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.connect(str(runtime / "jobs.sock"))
                ipc._send(conn, hello, time.monotonic() + 1)
                assert conn.recv(1) == b""
        assert not calls
    assert not errors


@NATIVE
def test_authenticated_replay_is_not_dispatched_twice(runtime):
    with serving(runtime) as (lease, calls, errors):
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        payload = {"version": 1, "op": "sentinel"}
        value = [channel.transcript, channel.sequence, "rpc", payload]
        envelope = {
            "sequence": channel.sequence,
            "kind": "rpc",
            "payload": payload,
            "proof": ipc._proof(channel.key, "request", value),
        }
        ipc._send(channel.conn, envelope, time.monotonic() + 1)
        assert ipc._receive(channel.conn, time.monotonic() + 1)["payload"]["ok"]
        ipc._send(channel.conn, envelope, time.monotonic() + 1)
        assert channel.conn.recv(1) == b""
        channel.close()
        assert calls == [payload]
    assert not errors


@NATIVE
@pytest.mark.parametrize("kind", ["file", "socket", "symlink", "auth"])
def test_stale_foreign_endpoint_not_unlinked(runtime, kind):
    endpoint = runtime / ("jobs.sock.auth" if kind == "auth" else "jobs.sock")
    sentinel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if kind == "socket":
            sentinel.bind(str(endpoint))
        elif kind == "symlink":
            endpoint.symlink_to(runtime / "missing")
        else:
            endpoint.write_bytes(b"foreign sentinel")
        before = endpoint.lstat()
        with pytest.raises(NativeCapabilityError):
            ipc.serve_authenticated(
                runtime / "jobs.sock",
                lease=lease_for(runtime),
                handler=lambda p: p,
                stop=threading.Event(),
            )
        assert endpoint.lstat().st_ino == before.st_ino
        if kind in ("file", "auth"):
            assert endpoint.read_bytes() == b"foreign sentinel"
    finally:
        sentinel.close()


@NATIVE
def test_socket_pathname_replacement_fences_owner_and_preserves_foreign(runtime):
    with serving(runtime) as (lease, calls, errors):
        path = runtime / "jobs.sock"
        path.rename(runtime / "old.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as foreign:
            foreign.bind(str(path))
            before = path.lstat()
            with pytest.raises(NativeCapabilityError):
                ipc.connect_authenticated(path, lease=lease, timeout_s=1)
            deadline = time.monotonic() + 3
            while not errors and time.monotonic() < deadline:
                time.sleep(0.02)
            assert errors
            assert path.lstat().st_ino == before.st_ino
            assert not calls
    assert errors[0].code in (
        "ipc_cleanup_identity_changed",
        "ipc_endpoint_unavailable",
    )


def child_command(root, lease, mode="serve", gate="-"):
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        mode,
        str(root),
        lease.label,
        lease.generation,
        gate,
    ]


@NATIVE
def test_two_starters_one_owner_and_loser_cannot_dispatch(runtime):
    lease = lease_for(runtime)
    gate = runtime / "start"
    children = [
        subprocess.Popen(
            child_command(runtime, lease, gate=str(gate)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    try:
        gate.touch()
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        assert channel.request({"version": 1, "op": "ping"}, timeout_s=1)["pid"] in [
            p.pid for p in children
        ]
        channel.close()
        deadline = time.monotonic() + 3
        while all(p.poll() is None for p in children) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert sorted(p.poll() == 3 for p in children) == [False, True]
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()  # only this test's directly owned subprocess
            child.communicate(timeout=5)
    assert sorted(p.returncode for p in children) == [0, 3]
    assert not (runtime / "jobs.sock").exists()


@NATIVE
def test_frontend_crash_leaves_manager_generation_live(runtime):
    with serving(runtime) as (lease, calls, errors):
        crashed = subprocess.run(
            child_command(runtime, lease, "crash-client"),
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert crashed.returncode == 23
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        assert channel.request({"version": 1, "op": "after-crash"}, timeout_s=1)["ok"]
        channel.close()
        assert [p["op"] for p in calls] == ["before-crash", "after-crash"]
    assert not errors


@NATIVE
def test_unrelated_same_uid_process_receives_no_application_bytes(runtime):
    lease = lease_for(runtime)
    child = subprocess.Popen(
        child_command(runtime, lease, "foreign"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while not (runtime / "foreign.ready").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        info = (runtime / "jobs.sock").stat()
        # Credentials name this process, but the listener is another native PID.
        auth = {
            "key": secrets.token_hex(32),
            "pid": os.getpid(),
            "uid": lease.uid,
            "generation": lease.generation,
            "label": lease.label,
            "device": info.st_dev,
            "inode": info.st_ino,
        }
        path = runtime / "jobs.sock.auth"
        path.write_text(json.dumps(auth))
        path.chmod(0o600)
        with pytest.raises(NativeCapabilityError):
            ipc.connect_authenticated(runtime / "jobs.sock", lease=lease, timeout_s=1)
        output, error = child.communicate(timeout=3)
        assert child.returncode == 0, error
        assert output == b"0\n"
    finally:
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=3)


@NATIVE
def test_crashed_manager_stale_endpoint_cannot_be_adopted(runtime):
    lease = lease_for(runtime)
    child = subprocess.Popen(
        child_command(runtime, lease), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        channel.close()
        child.kill()  # owned direct child: simulate an unclean manager crash
        child.communicate(timeout=3)
        inode = (runtime / "jobs.sock").stat().st_ino
        auth = (runtime / "jobs.sock.auth").read_bytes()
        with pytest.raises(NativeCapabilityError, match="stale_endpoint"):
            ipc.serve_authenticated(
                runtime / "jobs.sock",
                lease=lease_for(runtime),
                handler=lambda p: p,
                stop=threading.Event(),
            )
        assert (runtime / "jobs.sock").stat().st_ino == inode
        assert (runtime / "jobs.sock.auth").read_bytes() == auth
    finally:
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=3)


@NATIVE
def test_server_rejects_wrong_uid_before_handshake(runtime, monkeypatch):
    """Injected credential negative complements the native same-UID PID case."""
    with serving(runtime) as (lease, calls, errors):
        real_peer = ipc._peer
        monkeypatch.setattr(
            ipc, "_peer", lambda conn: (lease.uid + 1, real_peer(conn)[1])
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(1)
            conn.connect(str(runtime / "jobs.sock"))
            assert conn.recv(1) == b""
        assert not calls
    assert not errors


@NATIVE
def test_delayed_executor_retains_singleton_until_quiescent(runtime):
    lease = lease_for(runtime)
    stop, entered, release = threading.Event(), threading.Event(), threading.Event()
    replies, errors = [], []

    def handler(payload):
        entered.set()
        assert release.wait(3)
        return {"ok": True}

    def serve():
        try:
            ipc.serve_authenticated(
                runtime / "jobs.sock", lease=lease, handler=handler, stop=stop
            )
        except NativeCapabilityError as exc:
            errors.append(exc)

    server = threading.Thread(target=serve)
    server.start()
    channel = connect_when_ready(runtime / "jobs.sock", lease)

    def request():
        replies.append(channel.request({"op": "delayed"}, timeout_s=2))

    caller = threading.Thread(target=request)
    caller.start()
    try:
        assert entered.wait(1)
        stop.set()
        with pytest.raises(NativeCapabilityError, match="duplicate_starter"):
            ipc.serve_authenticated(
                runtime / "jobs.sock",
                lease=lease_for(runtime),
                handler=lambda p: p,
                stop=threading.Event(),
            )
        assert server.is_alive()
    finally:
        release.set()
        caller.join(3)
        channel.close()
        server.join(3)
    assert not caller.is_alive() and not server.is_alive()
    assert replies == [{"ok": True}] and not errors
    with serving(runtime) as (_, calls, errors):
        with pytest.raises(NativeCapabilityError):
            ipc.connect_authenticated(runtime / "jobs.sock", lease=lease, timeout_s=1)
        assert not calls
    assert not errors


@NATIVE
def test_malformed_proof_cannot_crash_manager(runtime):
    with serving(runtime) as (lease, calls, errors):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(runtime / "jobs.sock"))
            deadline = time.monotonic() + 1
            hello = {
                "version": 1,
                "generation": lease.generation,
                "nonce": secrets.token_hex(32),
            }
            ipc._send(conn, hello, deadline)
            ipc._receive(conn, deadline)
            ipc._send(conn, {"proof": "\u2603" * 64}, deadline)
            assert conn.recv(1) == b""
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        channel.close()
        assert not calls
    assert not errors


def _main():
    mode, root_arg, label, generation, gate = sys.argv[1:]
    root = Path(root_arg)
    lease = open_service_lease(root=root, label=label, generation=generation)
    if mode == "foreign":
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(root / "jobs.sock"))
            (root / "jobs.sock").chmod(0o600)
            listener.listen(1)
            (root / "foreign.ready").touch()
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(2)
                print(len(conn.recv(1024)), flush=True)
        return 0
    if mode == "crash-client":
        channel = ipc.connect_authenticated(
            root / "jobs.sock", lease=lease, timeout_s=2
        )
        channel.request({"version": 1, "op": "before-crash"}, timeout_s=2)
        os._exit(23)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while gate != "-" and not Path(gate).exists():
        time.sleep(0.01)
    try:
        ipc.serve_authenticated(
            root / "jobs.sock",
            lease=lease,
            handler=lambda p: {"ok": True, "pid": os.getpid(), "payload": dict(p)},
            stop=stop,
        )
    except NativeCapabilityError as exc:
        print(exc.code, flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

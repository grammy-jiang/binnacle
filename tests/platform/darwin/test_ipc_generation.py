"""Native Darwin IPC negatives plus portable private-root contract tests."""

from __future__ import annotations

import dataclasses
import json
import os
import resource
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import ipc_transport as ipc
from binnacle.platform.darwin.generation_runtime import (
    open_service_lease,
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


def attempt_start(root, lease=None):
    stopped = threading.Event()
    stopped.set()
    ipc.serve_authenticated(
        root / "jobs.sock",
        lease=lease or lease_for(root),
        handler=lambda p: p,
        stop=stopped,
    )


@contextmanager
def serving(root, *, handler=None, stop=None):
    lease = lease_for(root)
    stop = stop or threading.Event()
    calls, errors = [], []

    def default_handler(payload):
        calls.append(dict(payload))
        time.sleep(payload.get("delay", 0))
        if payload.get("raise"):
            raise KeyError("private handler details")
        if "response" in payload:
            response = {"nan": float("nan"), "huge": "x" * 1048576}.get(
                payload["response"], None
            )
            for _ in range(40 if payload["response"] == "deep" else 0):
                response = [response]
            return {"result": response}
        return {"ok": True, "payload": dict(payload)}

    def run():
        try:
            ipc.serve_authenticated(
                root / "jobs.sock",
                lease=lease,
                handler=handler or default_handler,
                stop=stop,
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
        assert not calls
    assert not errors


@NATIVE
@pytest.mark.parametrize("reconnect", [False, True])
def test_authenticated_replay_is_not_dispatched_twice(runtime, reconnect):
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
        if reconnect:
            channel.close()
            channel = connect_when_ready(runtime / "jobs.sock", lease)
        ipc._send(channel.conn, envelope, time.monotonic() + 1)
        assert channel.conn.recv(1) == b""
        channel.close()
        assert calls == [payload]
    assert not errors


def foreign_entry(path, kind):
    if kind == "socket":
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as foreign:
            foreign.bind(str(path))
        path.chmod(0o600)
    elif kind == "symlink":
        path.symlink_to(path.with_name("missing"))
    elif kind != "missing-lock":
        path.write_bytes(b"foreign sentinel")
        path.chmod(0o600)


@NATIVE
@pytest.mark.parametrize("kind", ["file", "socket", "symlink", "auth"])
def test_stale_foreign_endpoint_not_unlinked(runtime, kind):
    endpoint = runtime / ("jobs.sock.auth" if kind == "auth" else "jobs.sock")
    foreign_entry(endpoint, kind)
    before = endpoint.lstat()
    with pytest.raises(NativeCapabilityError):
        attempt_start(runtime)
    assert endpoint.lstat() == before
    if kind in ("file", "auth"):
        assert endpoint.read_bytes() == b"foreign sentinel"


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


@contextmanager
def owned_child(root, lease, mode="serve", gate="-"):
    child = subprocess.Popen(
        child_command(root, lease, mode, gate),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=3)


def wait_path(path, child):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert (child is None or child.poll() is None) and time.monotonic() < deadline
        time.sleep(0.02)


@NATIVE
def test_two_starters_one_owner_and_loser_cannot_dispatch(runtime):
    lease = lease_for(runtime)
    gate = runtime / "start"
    with ExitStack() as stack:
        children = [
            stack.enter_context(owned_child(runtime, lease, gate=str(gate)))
            for _ in range(2)
        ]
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
    assert sorted(p.returncode for p in children) == [0, 3]
    assert not (runtime / "jobs.sock").exists()


@NATIVE
@pytest.mark.parametrize(
    "replacement",
    [None, "socket", "file", "symlink", "auth", "lock", "missing-lock"],
)
@pytest.mark.parametrize("recovery", ["token", "lease"])
def test_crashed_manager_recovery_preserves_replacements(
    runtime, replacement, recovery
):
    lease = lease_for(runtime)
    with owned_child(runtime, lease) as child:
        channel = connect_when_ready(runtime / "jobs.sock", lease)
        authority = ipc.capture_recovery_authority(channel)
        with pytest.raises(NativeCapabilityError):
            ipc.recover_stale_endpoint(authority)
        channel.close()
        child.kill()  # owned direct child: simulate an unclean manager crash
        child.communicate(timeout=3)
        with pytest.raises(NativeCapabilityError, match="not_authenticated"):
            ipc.recover_stale_endpoint(dataclasses.replace(authority))

        def recover():
            if recovery == "token":
                ipc.recover_stale_endpoint(authority)
            else:
                attempt_start(runtime)

        if replacement:
            path = runtime / {
                "auth": "jobs.sock.auth",
                "lock": "manager.lock",
                "missing-lock": "manager.lock",
            }.get(replacement, "jobs.sock")
            path.rename(path.with_name(path.name + ".old"))
            foreign_entry(path, replacement)
            before = path.lstat() if path.is_symlink() or path.exists() else None
            with pytest.raises(NativeCapabilityError):
                recover()
            if before:
                assert path.lstat() == before
            assert path.with_name(path.name + ".old").exists()
        else:
            recover()
            with serving(runtime) as (successor, _, errors):
                assert successor.generation != lease.generation
            assert not errors


@NATIVE
@pytest.mark.parametrize("fault", ["missing", "generation", "proof", "uid"])
def test_untrusted_handshake_never_dispatches(runtime, monkeypatch, fault):
    with serving(runtime) as (lease, calls, errors):
        if fault == "uid":
            real_peer = ipc._peer
            monkeypatch.setattr(
                ipc, "_peer", lambda conn: (lease.uid + 1, real_peer(conn)[1])
            )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(1)
            conn.connect(str(runtime / "jobs.sock"))
            if fault != "uid":
                hello = {
                    "version": 1,
                    "generation": lease.generation,
                    "nonce": secrets.token_hex(32),
                }
                if fault == "generation":
                    hello["generation"] = secrets.token_hex(16)
                if fault == "missing":
                    hello = {"version": 1, "op": "stop"}
                deadline = time.monotonic() + 1
                ipc._send(conn, hello, deadline)
                if fault == "proof":
                    ipc._receive(conn, deadline)
                    ipc._send(conn, {"proof": "\u2603" * 64}, deadline)
            assert conn.recv(1) == b""
        monkeypatch.undo()
        connect_when_ready(runtime / "jobs.sock", lease).close()
        assert not calls
    assert not errors


@NATIVE
@pytest.mark.parametrize(
    "mode",
    [
        "no-handshake",
        "sigterm",
        "witness",
        "child",
        "high-fd",
        "bind",
        "journal",
        "publish",
    ],
)
def test_tokenless_owner_death_and_high_fds(runtime, mode):
    lease = lease_for(runtime)
    with ExitStack() as stack:
        child = stack.enter_context(owned_child(runtime, lease, mode))
        wait_path(runtime / "manager.ready", child)
        if mode == "witness":
            witness = stack.enter_context(owned_child(runtime, lease, "witness-client"))
            wait_path(runtime / "witness.ready", witness)
            witness.kill()
            witness.wait(timeout=3)
        if mode == "high-fd":
            channel = connect_when_ready(runtime / "jobs.sock", lease)
            assert channel.request({}, timeout_s=1)["ok"]
            channel.close()
        with pytest.raises(NativeCapabilityError, match="duplicate_starter"):
            attempt_start(runtime)
        child.send_signal(signal.SIGTERM if mode == "sigterm" else signal.SIGKILL)
        child.wait(timeout=3)
        # Startup obtains authority from the lock; no recovery token is passed.
        with serving(runtime) as (_, calls, errors):
            with pytest.raises(NativeCapabilityError):
                ipc.connect_authenticated(
                    runtime / "jobs.sock", lease=lease, timeout_s=1
                )
            assert not calls
        assert not errors
        if mode == "child":
            assert not (runtime / "child.done").exists()
            (runtime / "child.exit").touch()
            wait_path(runtime / "child.done", None)


def _main():
    mode, root_arg, label, generation, gate = sys.argv[1:]
    root = Path(root_arg)
    lease = open_service_lease(root=root, label=label, generation=generation)
    if mode == "orphan":
        deadline = time.monotonic() + 10
        while not (root / "child.exit").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        (root / "child.done").touch()
        return 0
    if mode == "foreign":
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(root / "jobs.sock"))
            (root / "jobs.sock").chmod(0o600)
            listener.listen(1)
            info = (root / "jobs.sock").stat()
            auth = {
                "key": secrets.token_hex(32),
                "pid": os.getppid(),
                "uid": lease.uid,
                "generation": generation,
                "label": label,
                "device": info.st_dev,
                "inode": info.st_ino,
            }
            (root / "jobs.sock.auth").write_text(json.dumps(auth))
            (root / "jobs.sock.auth").chmod(0o600)
            (root / "foreign.ready").touch()
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(2)
                print(len(conn.recv(1024)), flush=True)
        return 0
    if mode in ("crash-client", "witness-client"):
        channel = ipc.connect_authenticated(
            root / "jobs.sock", lease=lease, timeout_s=2
        )
        if mode == "crash-client":
            channel.request({"version": 1, "op": "before-crash"}, timeout_s=2)
            os._exit(23)
        authority = ipc.capture_recovery_authority(channel)
        (root / "witness.ready").touch()
        while authority:
            time.sleep(0.05)
    if mode == "high-fd":
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 2048), hard))
        padding = []
        while not padding or padding[-1] < 1100:
            padding.append(os.open(os.devnull, os.O_RDONLY))

    def pause_after(function):
        def wrapped(*args, **kwargs):
            function(*args, **kwargs)
            (root / "manager.ready").touch()
            while True:
                time.sleep(0.02)

        return wrapped

    if mode == "bind":
        socket.socket.bind = pause_after(socket.socket.bind)
    elif mode == "journal":
        ipc._record_endpoint = pause_after(ipc._record_endpoint)
    elif mode == "publish":
        ipc._publish_entry = pause_after(ipc._publish_entry)
    original_listen = socket.socket.listen

    def listen(listener, backlog):
        original_listen(listener, backlog)
        if mode == "child":
            subprocess.Popen(child_command(root, lease, "orphan"), close_fds=False)
        (root / "manager.ready").touch()

    socket.socket.listen = listen
    stop = threading.Event()
    if mode != "sigterm":
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

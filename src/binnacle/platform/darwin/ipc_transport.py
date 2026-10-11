"""Darwin-only mutual authentication around unchanged RPC v1 objects.

Length-prefixed envelope v1 is intentionally incompatible with Linux framing.
Each connection proves a fresh two-nonce HMAC transcript. Every request and
response is bound to that transcript and a monotonic sequence number. Secrets
are private runtime files, never arguments or diagnostics. UID credentials plus
this secret protect a cooperative account, not malicious same-UID code.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import select
import socket
import struct
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

from binnacle.platform.contracts.capability_contracts import (
    BudgetExceeded,
    Capability,
    CapabilityState,
    CapabilityUnavailable,
    NativeCapabilityError,
    PermissionDenied,
)
from binnacle.platform.contracts.native_service_contracts import (
    AuthenticatedChannel,
    ServiceLease,
)
from binnacle.platform.darwin.generation_runtime import (
    EndpointRecovery,
    _credentials,
    _endpoint,
    _identity,
    _lock_root,
    _remember_endpoint,
    bounded_json,
    check_socket_path,
    unlink_owned,
    validate_lease,
)
from binnacle.platform.darwin.generation_runtime import (
    recover_stale_endpoint as recover_stale_endpoint,  # noqa: PLC0414 - public recovery API
)

_MAX_FRAME = 1024 * 1024
_LOG = logging.getLogger(__name__)
_MAX_CLIENTS = 16
_SCOPE = "Darwin authenticated IPC; cooperative UID; no process signal authority"


def _refuse(code: str = "ipc_authentication_refused") -> PermissionDenied:
    return PermissionDenied(code, Capability(CapabilityState.UNKNOWN, code, _SCOPE))


def _native() -> None:
    if sys.platform != "darwin":
        raise CapabilityUnavailable(
            "darwin_ipc_unavailable",
            Capability(CapabilityState.UNAVAILABLE, "darwin_ipc_unavailable", _SCOPE),
        )


def _peer(conn: socket.socket) -> tuple[int, int]:
    # Public Darwin getpeereid(3) and sys/un.h SOL_LOCAL/LOCAL_PEERPID.
    _native()
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    getpeereid = libc.getpeereid
    getpeereid.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    getpeereid.restype = ctypes.c_int
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if getpeereid(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        raise _refuse("ipc_peer_unavailable")
    pid = struct.unpack("i", conn.getsockopt(0, 2, 4))[0]
    return uid.value, pid


def _deadline(timeout_s: float) -> float:
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
        raise _refuse("ipc_timeout_invalid")
    return time.monotonic() + timeout_s


def _remaining(conn: socket.socket, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    conn.settimeout(remaining)


def _encode(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _send(conn: socket.socket, value: Mapping[str, object], deadline: float) -> None:
    data = _encode(dict(value))
    if len(data) > _MAX_FRAME:
        raise _refuse("ipc_frame_too_large")
    _remaining(conn, deadline)
    conn.sendall(struct.pack("!I", len(data)) + data)


def _read_exact(conn: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        _remaining(conn, deadline)
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise _refuse("ipc_connection_closed")
        data.extend(chunk)
    return bytes(data)


def _receive(
    conn: socket.socket, deadline: float, *, limit: int = _MAX_FRAME
) -> dict[str, Any]:
    size = struct.unpack("!I", _read_exact(conn, 4, deadline))[0]
    if size > limit:
        raise _refuse("ipc_frame_too_large")
    return bounded_json(_read_exact(conn, size, deadline))


def _proof(key: bytes, purpose: str, value: object) -> str:
    return hmac.new(
        key, purpose.encode() + b"\0" + _encode(value), hashlib.sha256
    ).hexdigest()


def _verify(key: bytes, purpose: str, value: object, supplied: object) -> None:
    if (
        not isinstance(supplied, str)
        or len(supplied) != 64
        or not supplied.isascii()
        or not hmac.compare_digest(_proof(key, purpose, value), supplied)
    ):
        raise _refuse()


def _nonce(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise _refuse()
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise _refuse() from exc
    return value


class _Channel:
    def __init__(
        self, conn: socket.socket, key: bytes, transcript: list[object]
    ) -> None:
        self.conn = conn
        self.key = key
        self.transcript = transcript
        self.sequence = 0
        self.recovery: EndpointRecovery | None = None

    def _exchange(
        self, kind: str, payload: Mapping[str, object], timeout_s: float
    ) -> Mapping[str, object]:
        deadline = _deadline(timeout_s)
        value = [self.transcript, self.sequence, kind, dict(payload)]
        try:
            _send(
                self.conn,
                {
                    "sequence": self.sequence,
                    "kind": kind,
                    "payload": dict(payload),
                    "proof": _proof(self.key, "request", value),
                },
                deadline,
            )
            reply = _receive(self.conn, deadline)
            response = reply.get("payload")
            _verify(self.key, "response", [value, response], reply.get("proof"))
            if not isinstance(response, dict):
                raise _refuse()
            self.sequence += 1
            return response
        except TimeoutError as exc:
            self.close()
            code = "ipc_request_timeout_outcome_unknown"
            raise BudgetExceeded(
                code, Capability(CapabilityState.UNKNOWN, code, _SCOPE)
            ) from exc
        except (OSError, ValueError, TypeError, NativeCapabilityError) as exc:
            self.close()
            raise _refuse("ipc_request_failed") from exc

    def request(
        self, payload: Mapping[str, object], *, timeout_s: float
    ) -> Mapping[str, object]:
        return self._exchange("rpc", payload, timeout_s)

    def close(self) -> None:
        self.conn.close()


def connect_authenticated(
    socket_path: Path, *, lease: ServiceLease, timeout_s: float
) -> AuthenticatedChannel:
    _native()
    check_socket_path(socket_path)
    deadline = _deadline(timeout_s)
    fd = validate_lease(socket_path.parent, lease)
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        credentials = _credentials(fd, socket_path.name, lease)
        names = (socket_path.name, socket_path.name + ".auth", "manager.lock")
        expected = (credentials["device"], credentials["inode"])
        _endpoint(fd, socket_path.name, expected)
        key = bytes.fromhex(credentials["key"])
        if len(key) != 32:
            raise _refuse()
        _remaining(conn, deadline)
        conn.connect(str(socket_path))
        if _peer(conn) != (lease.uid, credentials["pid"]):
            raise _refuse("ipc_wrong_peer")
        _endpoint(fd, socket_path.name, expected)
        identities = tuple(_identity(fd, name) for name in names)
        client_nonce = secrets.token_hex(32)
        _send(
            conn,
            {"version": 1, "generation": lease.generation, "nonce": client_nonce},
            deadline,
        )
        hello = _receive(conn, deadline, limit=4096)
        transcript: list[object] = [
            1,
            lease.generation,
            lease.label,
            client_nonce,
            _nonce(hello.get("nonce")),
        ]
        _verify(key, "server", transcript, hello.get("proof"))
        _send(conn, {"proof": _proof(key, "client", transcript)}, deadline)
        channel = _Channel(conn, key, transcript)
        # Authentication is completed by an explicit generation-specific ping.
        pong = channel._exchange("ping", {}, max(0.000001, deadline - time.monotonic()))
        if pong != {"generation": lease.generation, "ready": True}:
            raise _refuse("ipc_readiness_failed")
        if identities != tuple(
            _identity(fd, name) for name in names
        ) or credentials != _credentials(fd, socket_path.name, lease):
            raise _refuse("ipc_generation_fenced")
        channel.recovery = _remember_endpoint(
            socket_path, lease, credentials, identities
        )
        return channel
    except (TimeoutError, BudgetExceeded) as exc:
        conn.close()
        code = "ipc_connect_timeout"
        raise BudgetExceeded(
            code, Capability(CapabilityState.UNKNOWN, code, _SCOPE)
        ) from exc
    except (OSError, ValueError, KeyError, TypeError, NativeCapabilityError) as exc:
        conn.close()
        raise _refuse("ipc_connect_refused") from exc
    finally:
        os.close(fd)


def capture_recovery_authority(channel: AuthenticatedChannel) -> EndpointRecovery:
    """Retain live-handshake evidence for explicit post-crash recovery."""
    if not isinstance(channel, _Channel) or channel.recovery is None:
        raise _refuse("ipc_recovery_not_authenticated")
    return channel.recovery


def _serve_connection(
    conn: socket.socket,
    lease: ServiceLease,
    key: bytes,
    handler: Callable[[Mapping[str, object]], Mapping[str, object]],
    validate: Callable[[], None],
    stop: Event,
) -> None:
    deadline = _deadline(2)
    if _peer(conn)[0] != lease.uid:
        raise _refuse("ipc_wrong_peer")
    hello = _receive(conn, deadline, limit=4096)
    if (
        type(hello.get("version")) is not int
        or hello.get("version") != 1
        or hello.get("generation") != lease.generation
    ):
        raise _refuse("ipc_generation_mismatch")
    transcript: list[object] = [
        1,
        lease.generation,
        lease.label,
        _nonce(hello.get("nonce")),
        secrets.token_hex(32),
    ]
    _send(
        conn,
        {"nonce": transcript[-1], "proof": _proof(key, "server", transcript)},
        deadline,
    )
    _verify(
        key, "client", transcript, _receive(conn, deadline, limit=4096).get("proof")
    )
    sequence = 0
    while not stop.is_set():
        # Idle authenticated channels have no expiry. Partial frames get 2 s;
        # polling lets shutdown drain idle workers without dropping active replies.
        if not select.select([conn], [], [], 0.1)[0]:
            continue
        message = _receive(conn, _deadline(2))
        kind, payload = message.get("kind"), message.get("payload")
        value = [transcript, sequence, kind, payload]
        if type(message.get("sequence")) is not int or message["sequence"] != sequence:
            raise _refuse("ipc_replay_refused")
        _verify(key, "request", value, message.get("proof"))
        validate()
        if stop.is_set():
            return
        if kind == "ping" and payload == {}:
            response: Mapping[str, object] = {
                "generation": lease.generation,
                "ready": True,
            }
        elif kind == "rpc" and isinstance(payload, dict):
            response = handler(payload)
        else:
            raise _refuse()
        try:
            _send(
                conn,
                {
                    "payload": dict(response),
                    "proof": _proof(key, "response", [value, dict(response)]),
                },
                _deadline(2),  # response I/O budget starts AFTER handler execution
            )
        except Exception:
            _LOG.warning("ipc_response_undelivered")
            raise
        sequence += 1


def serve_authenticated(
    socket_path: Path,
    *,
    lease: ServiceLease,
    handler: Callable[[Mapping[str, object]], Mapping[str, object]],
    stop: Event,
) -> None:
    _native()
    check_socket_path(socket_path)
    fd = validate_lease(socket_path.parent, lease)
    lock = -1
    owned: dict[str, tuple[int, int]] = {}
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        lock = _lock_root(fd)
        # Refuse any pre-existing socket, file, symlink or authentication record.
        for name in (socket_path.name, socket_path.name + ".auth"):
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise _refuse("ipc_stale_endpoint_refused")
        listener.bind(str(socket_path))
        owned[socket_path.name] = _identity(fd, socket_path.name)
        os.chmod(socket_path.name, 0o600, dir_fd=fd, follow_symlinks=False)
        key = secrets.token_bytes(32)
        info = owned[socket_path.name]
        credentials = {
            "key": key.hex(),
            "pid": os.getpid(),
            "uid": lease.uid,
            "generation": lease.generation,
            "label": lease.label,
            "device": info[0],
            "inode": info[1],
        }
        name = socket_path.name + ".auth"
        key_fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        try:
            key_info = os.fstat(key_fd)
            owned[name] = (key_info.st_dev, key_info.st_ino)
            with os.fdopen(key_fd, "wb", closefd=False) as stream:
                stream.write(_encode(credentials))
                stream.flush()
                os.fsync(key_fd)
        finally:
            os.close(key_fd)
        listener.listen(8)
        listener.settimeout(0.1)
        lock_info = os.fstat(lock)

        def validate() -> None:
            current = validate_lease(socket_path.parent, lease)
            os.close(current)
            _endpoint(fd, socket_path.name, owned[socket_path.name])
            if _identity(fd, name) != owned[name] or _identity(fd, "manager.lock") != (
                lock_info.st_dev,
                lock_info.st_ino,
            ):
                raise _refuse("ipc_generation_fenced")

        _serve_clients(listener, lease, key, handler, validate, stop)
    except OSError as exc:
        raise _refuse("ipc_endpoint_unavailable") from exc
    finally:
        listener.close()
        clean = True
        try:
            for name, identity in owned.items():
                clean = unlink_owned(fd, name, identity) and clean
        except OSError as exc:
            raise _refuse("ipc_cleanup_failed") from exc
        finally:
            if lock >= 0:
                os.close(lock)  # Persistent lock inode is never unlinked.
            os.close(fd)
        if not clean:
            raise _refuse("ipc_cleanup_identity_changed")


def _serve_clients(
    listener: socket.socket,
    lease: ServiceLease,
    key: bytes,
    handler: Callable[[Mapping[str, object]], Mapping[str, object]],
    validate: Callable[[], None],
    stop: Event,
) -> None:
    """At most 16 channels; per-channel serial RPC, concurrent handlers.

    Callers supply a thread-safe handler. No queued excess sockets, idle expiry,
    automatic request retry or cross-connection deduplication. Client timeout
    means outcome UNKNOWN, never cancellation. Drain handlers before unlock.
    """
    draining = Event()

    def serve(conn: socket.socket) -> None:
        with conn:
            try:
                _serve_connection(conn, lease, key, handler, validate, draining)
            except Exception:  # noqa: BLE001 - per-client fault containment boundary
                # Contain ordinary handler/parser faults, without disclosing data.
                _LOG.debug("ipc_connection_dropped")

    with ThreadPoolExecutor(max_workers=_MAX_CLIENTS) as pool:
        pending: set[Future[None]] = set()
        try:
            while not stop.is_set():
                validate()
                for future in tuple(pending):
                    if future.done():
                        pending.remove(future)
                        future.result()  # BaseException still propagates to owner
                try:
                    conn, _ = listener.accept()
                except TimeoutError:
                    continue
                if len(pending) >= _MAX_CLIENTS:
                    conn.close()
                    continue
                pending.add(pool.submit(serve, conn))
        finally:
            draining.set()
            for future in pending:
                future.result()  # join handlers before releasing generation/lock

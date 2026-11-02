"""Opt-in Linux SCM_RIGHTS start endpoint for the *existing* Python job owner.

This module is **not** loaded by the production manager entry point. It must
be explicitly instantiated with a v2 socket, its own pinned allowed roots,
and a JobManager instance; the old v1 JSON/line socket is unmodified.

Only the start operation uses v2. Status/stop and durable job/process ownership
remain in the original Python owner. No path-only v1 downgrade is permitted.
"""

from __future__ import annotations

import array
import json
import logging
import os
import socket
import socketserver
import stat
import struct
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

from binnacle.features.files import fd_walk

if TYPE_CHECKING:
    from binnacle.features.commands.job_manager import JobManager

log = logging.getLogger("binnacle.job_manager_v2")
_VERSION = 2
_MAX_REQUEST = 1024 * 1024
_FIRST_READ = 64 * 1024
_MAX_FDS = 4
_TIMEOUT = 5.0


class V2Denied(ValueError):
    """A rejected v2 start request must never launch a job."""


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise V2Denied("duplicate JSON field")
        result[key] = value
    return result


def _request_from_wire(payload: bytes) -> dict[str, Any]:
    try:
        request = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2Denied("invalid UTF-8 JSON request") from exc
    if not isinstance(request, dict):
        raise V2Denied("request must be a JSON object")
    required = {
        "version",
        "op",
        "workdir",
        "workdir_fd",
        "command",
        "stdin",
        "wait_seconds",
        "call_id",
    }
    if set(request) != required or type(request["version"]) is not int:
        raise V2Denied("unsupported v2 request fields")
    if request["version"] != _VERSION or request["op"] != "start":
        raise V2Denied("unsupported v2 manager operation")
    if request["workdir_fd"] is not True:
        raise V2Denied("workdir FD required")
    command = request["command"]
    stdin = request["stdin"]
    call = request["call_id"]
    if not isinstance(command, str) or not (0 < len(command.encode("utf-8")) <= 65536):
        raise V2Denied("invalid command")
    if not isinstance(stdin, (str, type(None))) or (
        stdin is not None and len(stdin.encode("utf-8")) > 512 * 1024
    ):
        raise V2Denied("invalid stdin")
    if (
        not isinstance(call, str)
        or not (0 < len(call) <= 128)
        or any(ord(ch) < 32 for ch in call)
    ):
        raise V2Denied("invalid call ID")
    wait = request["wait_seconds"]
    if type(wait) not in (int, float) or not (0.0 <= wait <= 50.0):
        raise V2Denied("invalid wait window")
    return request


def _receive(conn: socket.socket) -> tuple[dict[str, Any], int]:
    """Read one JSON line plus exactly one FD; always close rejected FDs."""
    received: list[int] = []
    try:
        raw, ancillary, flags, _ = conn.recvmsg(
            _FIRST_READ,
            socket.CMSG_SPACE(array.array("i", [0] * _MAX_FDS).itemsize * _MAX_FDS),
            getattr(socket, "MSG_CMSG_CLOEXEC", 0),
        )
        for level, kind, blob in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise V2Denied("unexpected ancillary data")
            ints = array.array("i")
            if len(blob) % ints.itemsize:
                raise V2Denied("invalid ancillary FD framing")
            ints.frombytes(blob)
            received.extend(ints)
        if flags & (socket.MSG_CTRUNC | getattr(socket, "MSG_TRUNC", 0)):
            raise V2Denied("truncated ancillary data or request")
        if len(received) != 1:
            raise V2Denied("exactly one directory FD required")
        if not raw:
            raise V2Denied("empty v2 request")
        content = bytearray(raw)
        while b"\n" not in content:
            if len(content) >= _MAX_REQUEST:
                raise V2Denied("v2 request exceeds size limit")
            chunk = conn.recv(min(_FIRST_READ, _MAX_REQUEST + 1 - len(content)))
            if not chunk:
                raise V2Denied("unterminated v2 request")
            content.extend(chunk)
        line, extra = content.split(b"\n", 1)
        if extra or len(line) > _MAX_REQUEST:
            raise V2Denied("unexpected trailing data or oversized v2 request")
        request = _request_from_wire(bytes(line))
        return request, received.pop()
    finally:
        for fd in received:
            os.close(fd)


class _Root:
    def __init__(self, logical: Path, fd: int):
        self.path = logical
        self.fd = fd
        self.identity = os.fstat(fd)


class _V2Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: V2FDServer = self.server  # type: ignore[assignment]
        conn: socket.socket = self.request  # type: ignore[assignment]
        conn.settimeout(_TIMEOUT)
        reply: dict[str, Any] = {"version": _VERSION, "ok": False}
        directory_fd = -1
        try:
            server.authorize_peer(conn)
            request, directory_fd = _receive(conn)
            server.authorize_workdir(request["workdir"], directory_fd)
            response = server.manager._start(request, pinned_workdir_fd=directory_fd)
            if response.get("ok") is not True:
                raise V2Denied("job owner rejected start")
            if not isinstance(response.get("job_id"), str) or not isinstance(
                response.get("state"), str
            ):
                raise V2Denied("job owner response invalid")
            reply.update(response)
            reply["workdir_fd_accepted"] = True
            reply["ok"] = True
        except (V2Denied, OSError, ValueError, KeyError, TypeError) as exc:
            # Do not echo command, stdin, workdir or credentials in the reply.
            log.warning(
                "event=job_manager_v2_refused error_class=%s", type(exc).__name__
            )
            reply["error"] = "v2 start refused"
        except Exception:
            log.exception("event=job_manager_v2_start_error")
            reply["error"] = "internal job-manager error"
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
        try:
            conn.sendall(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # The owner may already have launched a durable job. The client
            # must NOT automatically retry after this ambiguous outcome.
            log.info("event=job_manager_v2_client_disconnected")


class V2FDServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Explicitly created v2 socket, never activated by v1 `main()`."""

    daemon_threads = True
    block_on_close = True

    def __init__(
        self,
        socket_path: Path,
        manager: JobManager,
        allowed_roots: tuple[Path, ...],
        *,
        peer_uid: int | None = None,
    ) -> None:
        if not allowed_roots:
            raise ValueError("v2 manager requires explicit authorized roots")
        if (
            not socket_path.is_absolute()
            or socket_path.exists()
            or socket_path.is_symlink()
        ):
            raise ValueError("v2 socket must be a new absolute pathname")
        parent = socket_path.parent
        info = parent.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("v2 socket parent must be private and owner-controlled")
        if parent.is_symlink():
            raise ValueError("v2 socket parent may not be a symlink")
        self.manager = manager
        self.peer_uid = os.geteuid() if peer_uid is None else peer_uid
        self._resources = ExitStack()
        self._roots: list[_Root] = []
        try:
            for path in allowed_roots:
                logical = path.resolve(strict=True)
                if not logical.is_absolute():
                    raise ValueError("v2 authorized root must be absolute")
                fd = self._resources.enter_context(fd_walk.open_root(logical))
                self._roots.append(_Root(logical, fd))
            super().__init__(str(socket_path), _V2Handler)
            os.chmod(socket_path, 0o600)
            self._socket_path = socket_path
            self._socket_identity = os.stat(socket_path)
        except BaseException:
            self._resources.close()
            raise

    def authorize_peer(self, conn: socket.socket) -> None:
        if not hasattr(socket, "SO_PEERCRED"):
            raise V2Denied("Linux peer credential verification unavailable")
        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _, uid, _ = struct.unpack("3i", creds)
        if uid != self.peer_uid:
            raise V2Denied("untrusted peer")

    def authorize_workdir(self, raw_path: Any, received_fd: int) -> None:
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            raise V2Denied("invalid logical workdir")
        if "\0" in raw_path or os.path.normpath(raw_path) != raw_path:
            raise V2Denied("noncanonical workdir")
        target = os.fstat(received_fd)
        if not stat.S_ISDIR(target.st_mode):
            raise V2Denied("received FD is not a directory")
        wanted = Path(raw_path)
        for root in self._roots:
            try:
                parts = wanted.relative_to(root.path).parts
            except ValueError:
                continue
            # A renamed root may still have a valid directory FD. Do not let
            # it become a new grant: verify its current kernel location.
            if os.readlink(f"/proc/self/fd/{root.fd}") != str(root.path):
                raise V2Denied("allowed root was moved")
            with fd_walk.directory_at(root.fd, parts) as verified:
                check = os.fstat(verified)
                if (target.st_dev, target.st_ino) != (check.st_dev, check.st_ino):
                    raise V2Denied("workdir FD does not match authorized path")
                if os.readlink(f"/proc/self/fd/{received_fd}") != raw_path:
                    raise V2Denied("workdir was moved during validation")
                return
        raise V2Denied("workdir outside independently authorized roots")

    def server_close(self) -> None:
        super().server_close()
        try:
            existing = self._socket_path.lstat()
            if (existing.st_dev, existing.st_ino) == (
                self._socket_identity.st_dev,
                self._socket_identity.st_ino,
            ):
                self._socket_path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._resources.close()

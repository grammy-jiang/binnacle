"""Edge refusals of the opt-in Manager v2 SCM_RIGHTS start endpoint.

Every socket, root and job store lives under tmp_path. Each refusal goes
through the real v2 request path and must leave the job store untouched.
"""

from __future__ import annotations

import array
import errno
import json
import logging
import os
import socket
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest

from binnacle.features.commands import job_manager_v2 as v2
from binnacle.features.commands import job_manager_v2_receipts as receipts
from binnacle.features.commands import jobs
from tests.integration.test_job_manager_v2 import (
    _pinned_fd,
    _record_ids,
    _request,
    _send,
)

# Reuse the strictly isolated real Manager fixture (running_owner).
pytest_plugins = ["tests.integration.test_job_manager_v2"]

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY

_REFUSED = {"version": 2, "ok": False, "error": "v2 start refused"}


def _raw(
    path: Path, chunks: list[bytes], fds: tuple[int, ...] = (), *, shut: bool = False
) -> dict[str, Any] | None:
    """Send raw bytes (first chunk carries the FDs); return the reply or None."""
    ancillary = (
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(6)
        conn.connect(str(path))
        if chunks:
            sent = conn.sendmsg([chunks[0]], ancillary)
            if sent < len(chunks[0]):  # never send b"" after a fast refusal
                conn.sendall(chunks[0][sent:])
            for chunk in chunks[1:]:
                conn.sendall(chunk)
        if shut:
            conn.shutdown(socket.SHUT_WR)
        data = bytearray()
        while chunk := conn.recv(4096):
            data.extend(chunk)
    return json.loads(data) if data else None


def _wire(request: dict[str, Any]) -> bytes:
    return json.dumps(request).encode() + b"\n"


_WIRE_REFUSALS: list[tuple[str, Callable[[Path], bytes], str]] = [
    ("utf8", lambda _r: b"\xff\xfe\n", "invalid UTF-8 JSON request"),
    ("array", lambda _r: b"[]\n", "request must be a JSON object"),
    (
        "version_type",
        lambda r: _wire(_request(r, version="2")),
        "unsupported v2 request version",
    ),
    (
        "maintenance_extra",
        lambda _r: _wire({"version": 2, "op": "pause_starts", "nonce": "n", "x": 1}),
        "invalid v2 maintenance operation",
    ),
    (
        "maintenance_nonce",
        lambda _r: _wire({"version": 2, "op": "resume_starts", "nonce": 7}),
        "invalid maintenance nonce",
    ),
    ("op", lambda r: _wire(_request(r, op="status")), "unsupported v2 manager op"),
    ("fd_flag", lambda r: _wire(_request(r, workdir_fd=1)), "workdir FD required"),
    ("command", lambda r: _wire(_request(r, command="")), "invalid command"),
    ("stdin", lambda r: _wire(_request(r, stdin=5)), "invalid stdin"),
    ("call_id", lambda r: _wire(_request(r, call_id="a\nb")), "invalid call ID"),
    ("wait_bool", lambda r: _wire(_request(r, wait_seconds=True)), "invalid wait"),
    ("wait_high", lambda r: _wire(_request(r, wait_seconds=51)), "invalid wait"),
]


@pytest.mark.parametrize(
    ("build", "message"),
    [case[1:] for case in _WIRE_REFUSALS],
    ids=[case[0] for case in _WIRE_REFUSALS],
)
def test_request_validation_refusals_never_launch(
    running_owner, caplog, build: Callable[[Path], bytes], message: str
):
    """Each malformed request is refused with the generic, non-echoing reply."""
    _, root, _, run, store = running_owner
    wire = build(root)
    with pytest.raises(v2.V2Denied, match=message):
        v2._request_from_wire(wire.rstrip(b"\n"))
    caplog.set_level(logging.WARNING, logger="binnacle.job_manager_v2")
    fd = _pinned_fd(root)
    try:
        assert _raw(run / "start-v2.sock", [wire], (fd,)) == _REFUSED
    finally:
        os.close(fd)
    assert "error_class=V2Denied" in caplog.text
    assert not _record_ids(store)


def test_framing_refusals_never_launch(running_owner):
    """Oversized, unterminated and over-FD requests are refused."""
    _, root, _, run, store = running_owner
    sock = run / "start-v2.sock"
    fd = _pinned_fd(root)
    try:
        oversized = [b"x" * v2._FIRST_READ] * (v2._MAX_REQUEST // v2._FIRST_READ)
        assert _raw(sock, oversized, (fd,)) == _REFUSED
        assert _raw(sock, [b'{"version":2'], (fd,), shut=True) == _REFUSED
        # Five FDs overflow the four-FD control buffer: MSG_CTRUNC.
        assert _raw(sock, [_wire(_request(root))], (fd,) * 5) == _REFUSED
    finally:
        os.close(fd)
    assert not _record_ids(store)


def test_closed_probe_gets_no_reply_and_no_job(running_owner):
    """A peer that closes without data is an identity probe, not a refusal."""
    _, _, _, run, store = running_owner
    assert _raw(run / "start-v2.sock", [], shut=True) is None
    assert not _record_ids(store)


def test_workdir_validation_refusals_through_socket(running_owner, tmp_path):
    """Relative, noncanonical and outside workdirs are refused."""
    _, root, outside, run, store = running_owner
    fd = _pinned_fd(root)
    out_fd = _pinned_fd(outside)
    try:
        for workdir, descriptor in [
            ("relative/dir", fd),
            (f"{root}/./", fd),
            (str(outside.resolve()), out_fd),
        ]:
            request = {**_request(root), "workdir": workdir}
            assert _send(run / "start-v2.sock", request, (descriptor,)) == _REFUSED
    finally:
        os.close(fd)
        os.close(out_fd)
    assert not _record_ids(store)


class _FakeReceive:
    """A connection double for kernel framings a real peer cannot produce."""

    def __init__(self, raw: bytes, ancillary: list[tuple[int, int, bytes]]):
        self.reply = (raw, ancillary, 0, None)

    def recvmsg(self, *_args: Any) -> tuple[bytes, list, int, None]:
        return self.reply


def test_receive_refuses_unexpected_or_misframed_ancillary_data():
    """Non-SCM_RIGHTS data, partial FD ints and FD-only messages are refused."""
    rights = (socket.SOL_SOCKET, socket.SCM_RIGHTS)
    cases = [
        (b"{}\n", [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS, b"")], "unexpected"),
        (b"{}\n", [(*rights, b"\x00\x00\x00")], "invalid ancillary FD framing"),
    ]
    for raw, ancillary, message in cases:
        with pytest.raises(v2.V2Denied, match=message):
            v2._receive(_FakeReceive(raw, ancillary))
    held = os.open(os.devnull, os.O_RDONLY)
    blob = array.array("i", [held]).tobytes()
    with pytest.raises(v2.V2Denied, match="empty v2 request") as caught:
        v2._receive(_FakeReceive(b"", [(*rights, blob)]))
    assert not isinstance(caught.value, v2.V2ProbeClosed)
    with pytest.raises(OSError) as closed:
        os.fstat(held)  # _receive always closes a rejected FD
    assert closed.value.errno == errno.EBADF


class _FakeOwner:
    """A StartOwner double whose _start outcome each test chooses."""

    def __init__(self) -> None:
        self._v2_start_admission_guard: Callable[[], None] | None = None
        self.outcome: Callable[[], dict[str, Any]] = lambda: {"ok": False}

    def _start(self, request: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return self.outcome()


@pytest.fixture()
def fake_server(tmp_path: Path, monkeypatch) -> Iterator[SimpleNamespace]:
    root = (tmp_path / "allowed").resolve()
    root.mkdir()
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    store = tmp_path / "store"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    owner = _FakeOwner()
    server = v2.V2FDServer(run / "v2.sock", owner, (root,))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(server=server, owner=owner, root=root, run=run)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
        assert not store.exists()


def _start_via(env: SimpleNamespace) -> dict[str, Any]:
    fd = _pinned_fd(env.root)
    try:
        return _send(env.run / "v2.sock", _request(env.root), (fd,))
    finally:
        os.close(fd)


def _raise(exc: BaseException) -> Callable[..., Any]:
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return fail


def test_owner_reply_without_string_job_id_is_refused(fake_server):
    fake_server.owner.outcome = lambda: {"ok": True, "job_id": 7, "state": "exited"}
    assert _start_via(fake_server) == _REFUSED


def test_owner_internal_error_is_reported_without_details(fake_server):
    fake_server.owner.outcome = _raise(RuntimeError("secret command text"))
    reply = _start_via(fake_server)
    assert reply == {"version": 2, "ok": False, "error": "internal job-manager error"}


@pytest.mark.parametrize(
    ("lookup_error", "expected"),
    [
        (receipts.ReceiptNotReady("pending"), "v2_start_outcome_unknown"),
        (receipts.ReceiptFailure("conflict"), "v2 start refused"),
    ],
)
def test_already_reserved_lookup_failures_never_retry(
    fake_server, monkeypatch, lookup_error: Exception, expected: str
):
    """A reserved call ID is only looked up; lookup failures stay refusals."""
    fake_server.owner.outcome = _raise(receipts.ReceiptAlreadyReserved("dup"))
    monkeypatch.setattr(receipts, "lookup", _raise(lookup_error))
    assert _start_via(fake_server) == {"version": 2, "ok": False, "error": expected}


def test_authorize_peer_requires_linux_peer_credentials(fake_server, monkeypatch):
    monkeypatch.delattr(socket, "SO_PEERCRED")
    with pytest.raises(v2.V2Denied, match="peer credential verification"):
        fake_server.server.authorize_peer(None)


def test_authorize_workdir_refusal_messages(fake_server, tmp_path, monkeypatch):
    """Each workdir check names its own reason to the owner log path."""
    root, check = fake_server.root, fake_server.server.authorize_workdir
    fd = _pinned_fd(root)
    try:
        cases = [
            (42, "invalid logical workdir"),
            ("relative", "invalid logical workdir"),
            (f"{root}/../allowed", "noncanonical workdir"),
            (str(tmp_path), "outside independently authorized roots"),
        ]
        for raw, message in cases:
            with pytest.raises(v2.V2Denied, match=message):
                check(raw, fd)
        real_readlink = os.readlink
        target = f"/proc/self/fd/{fd}"
        monkeypatch.setattr(
            os,
            "readlink",
            lambda p: "/moved" if p == target else real_readlink(p),
        )
        with pytest.raises(v2.V2Denied, match="moved during validation"):
            check(str(root), fd)
        monkeypatch.undo()
        moved = root.with_name("renamed")
        root.rename(moved)
        try:
            with pytest.raises(v2.V2Denied, match="allowed root was moved"):
                check(str(root), fd)
        finally:
            moved.rename(root)
    finally:
        os.close(fd)


@pytest.fixture()
def private_run(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "root"
    root.mkdir()
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    owner = SimpleNamespace(_v2_start_admission_guard=None)
    return SimpleNamespace(root=root, run=run, owner=owner, path=run / "v2.sock")


def _stale_socket(path: Path) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
        stale.bind(str(path))  # closed without unlink: an inert pathname


def test_constructor_refuses_unsafe_socket_paths(private_run, tmp_path):
    env = private_run
    with pytest.raises(ValueError, match="absolute non-symlink"):
        v2.V2FDServer(Path("relative.sock"), env.owner, (env.root,))
    link = tmp_path / "link"
    link.symlink_to(env.run)
    with pytest.raises(ValueError, match="parent may not be a symlink"):
        v2.V2FDServer(link / "v2.sock", env.owner, (env.root,))
    env.path.write_text("not a socket")
    with pytest.raises(ValueError, match="occupied by an unsafe object"):
        v2.V2FDServer(env.path, env.owner, (env.root,))
    env.path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as active:
        active.bind(str(env.path))
        active.listen(1)
        with pytest.raises(ValueError, match="already has an active listener"):
            v2.V2FDServer(env.path, env.owner, (env.root,))
    assert env.path.exists()  # an active endpoint is never unlinked


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses socket permissions")
def test_constructor_refuses_unprobeable_stale_socket(private_run):
    env = private_run
    _stale_socket(env.path)
    env.path.chmod(0)  # connect() fails with EACCES, not ECONNREFUSED
    with pytest.raises(ValueError, match="cannot be safely recovered"):
        v2.V2FDServer(env.path, env.owner, (env.root,))
    assert env.path.exists()


def test_constructor_recovers_stale_socket_and_close_removes_it(private_run):
    env = private_run
    _stale_socket(env.path)
    server = v2.V2FDServer(env.path, env.owner, (env.root,))
    assert env.owner._v2_start_admission_guard is not None
    assert env.path.stat().st_mode & 0o777 == 0o600
    server.server_close()
    assert not env.path.exists()


def test_constructor_refuses_socket_replaced_during_stale_check(
    private_run, monkeypatch
):
    env = private_run
    _stale_socket(env.path)
    real_socket = socket.socket

    class SwappingProbe:
        """Replaces the pathname between lstat and unlink, then refuses."""

        def __init__(self, *_args: Any) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def settimeout(self, _value: float) -> None:
            return None

        def connect(self, address: str) -> None:
            # Bind first, then rename over: the new inode cannot reuse the old.
            with real_socket(socket.AF_UNIX, socket.SOCK_STREAM) as other:
                other.bind(address + ".new")
            os.replace(address + ".new", address)
            raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    monkeypatch.setattr(socket, "socket", SwappingProbe)
    with pytest.raises(ValueError, match="changed during stale-socket check"):
        v2.V2FDServer(env.path, env.owner, (env.root,))
    monkeypatch.undo()
    assert env.path.exists()  # the replacement is never unlinked


def test_constructor_failure_releases_roots_and_binds_nothing(private_run, tmp_path):
    env = private_run
    with pytest.raises(FileNotFoundError):
        v2.V2FDServer(env.path, env.owner, (env.root, tmp_path / "missing"))
    assert not env.path.exists()
    assert env.owner._v2_start_admission_guard is None


def test_server_close_keeps_replaced_or_missing_socket_paths(private_run):
    env = private_run
    server = v2.V2FDServer(env.path, env.owner, (env.root,))
    env.path.unlink()
    env.path.write_text("someone else's file")
    server.server_close()
    assert env.path.read_text() == "someone else's file"
    env.path.unlink()
    server = v2.V2FDServer(env.path, env.owner, (env.root,))
    env.path.unlink()
    server.server_close()  # a missing pathname is not an error
    assert not env.path.exists()


def test_bind_failure_surfaces_the_bind_error_and_releases_roots(private_run):
    """server_close runs before the socket is recorded; the OSError must win."""
    env = private_run
    deep = env.run / ("d" * 110)
    deep.mkdir(mode=0o700)
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(OSError) as caught:
        v2.V2FDServer(deep / "v2.sock", env.owner, (env.root,))
    assert not isinstance(caught.value, AttributeError)
    assert len(os.listdir("/proc/self/fd")) == before  # root FDs released

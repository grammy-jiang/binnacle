"""Full A3 HMAC/peer/generation Unix socket integration on isolated Linux temp.

The repository's A3 transport is Darwin-native. For this test ONLY, map the
peer-credential syscall to Linux SO_PEERCRED without changing transport
handshake, MAC verification, framing, sequencing or endpoint publication.
No production sockets, Mac services or raw archives are accessed.
"""

from __future__ import annotations

import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from binnacle.platform.darwin import (
    generation_runtime,
    ipc_transport,
)
from binnacle.platform.darwin import (
    log_maintenance_recovery_rpc as rpc,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceTransactionJournal,
)
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    advance_to,
    begin,
)


@pytest.fixture
def isolated_a3(monkeypatch: pytest.MonkeyPatch):
    """A3 runs unchanged except for its Darwin-only peer syscall gate."""
    if not hasattr(socket, "SO_PEERCRED"):
        pytest.skip("Linux SO_PEERCRED needed for portability-only proof")

    def linux_peer(conn: socket.socket) -> tuple[int, int]:
        credentials = conn.getsockopt(
            socket.SOL_SOCKET, vars(socket)["SO_PEERCRED"], struct.calcsize("3i")
        )
        pid, uid, _gid = struct.unpack("3i", credentials)
        return uid, pid

    def linux_publish(fd: int, source: str, target: str) -> None:
        # Private Linux *test fixture only*: replace Darwin RENAME_EXCL with
        # an isolated-tree publication. Never used by installed native code.
        try:
            os.stat(target, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("fixture destination already exists")
        os.rename(source, target, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)

    with monkeypatch.context() as m:
        m.setattr(ipc_transport, "_native", lambda: None)
        m.setattr(ipc_transport, "_peer", linux_peer)
        m.setattr(ipc_transport, "_publish_entry", linux_publish)
        yield


@pytest.fixture
def roots(isolated_a3):
    # Short absolute path fits Darwin's 103-byte sun_path limit as well.
    with tempfile.TemporaryDirectory(prefix="bi30-rpc-", dir="/tmp") as temp:
        base = Path(temp)
        assert base.stat().st_uid == os.getuid()
        assert stat.S_IMODE(base.stat().st_mode) == 0o700
        tx = base / ("txn-" + NONCE)
        tx.mkdir(mode=0o700)
        tx.chmod(0o700)
        ipc = base / "log-maintenance-observer-ipc"
        ipc.mkdir(mode=0o700)
        ipc.chmod(0o700)
        path = ipc / "observe.sock"
        assert len(os.fsencode(path)) < 104
        yield tx, path


def _launch_a3(socket_path: Path, transaction_root: Path):
    lease = generation_runtime.open_service_lease(
        root=socket_path.parent, label=rpc._LABEL, generation="h" * 32
    )
    stop = threading.Event()
    failures: list[BaseException] = []

    def serve():
        try:
            rpc.serve_readonly_recovery_over_a3(
                socket_path, lease=lease, transaction_root=transaction_root, stop=stop
            )
        except Exception as exc:  # noqa: BLE001 - test-thread failure collection
            failures.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    timeout = time.monotonic() + 5.0
    while time.monotonic() < timeout:
        if failures:
            break
        if (
            socket_path.is_socket()
            and socket_path.with_name("observe.sock.auth").is_file()
        ):
            break
        time.sleep(0.025)
    assert not failures, repr(
        [(type(e).__name__, str(e), repr(e.__cause__)) for e in failures]
    )
    assert socket_path.is_socket(), "A3 failed to publish isolated fixture endpoint"
    assert socket_path.with_name("observe.sock.auth").is_file()
    return lease, stop, thread, failures


def _stop(stop: threading.Event, thread: threading.Thread, failures: list):
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive(), "isolated fixture A3 server did not drain"
    assert not failures, repr(failures)


def test_real_hmac_socket_round_trip_after_controller_exit(roots) -> None:
    root, path = roots
    with MaintenanceTransactionJournal(root) as controller:
        begin(controller)
        report = advance_to(controller, "guardian_armed")
    original_bytes = (root / "transaction.json").read_bytes()
    lease, stop, thread, failures = _launch_a3(path, root)
    try:
        discovery = generation_runtime.discover_service_lease(
            root=path.parent, label=rpc._LABEL, name="observe.sock"
        )
        assert discovery == lease
        result = rpc.observe_recovery_over_a3(
            path, lease=discovery, transaction_nonce=NONCE, timeout_s=3
        )
        assert result.transaction_nonce == report.nonce
        assert result.phase == "guardian_armed"
        assert result.status == "possible_outage_manual_review"
        assert result.manual_review_required
        assert not result.production_authorized
        assert not result.autonomous_restart_allowed
        assert "observation_not_authenticated" in result.risks
        assert (root / "transaction.json").read_bytes() == original_bytes
    finally:
        _stop(stop, thread, failures)
    assert not path.exists()
    assert not path.with_name("observe.sock.auth").exists()


def test_real_hmac_socket_reports_busy_controller_as_unknown(roots) -> None:
    root, path = roots
    with MaintenanceTransactionJournal(root) as controller:
        begin(controller)
        _lease, stop, thread, failures = _launch_a3(path, root)
        try:
            discovery = generation_runtime.discover_service_lease(
                root=path.parent, label=rpc._LABEL, name="observe.sock"
            )
            with pytest.raises(rpc.RecoveryRPCRefused, match="unavailable"):
                rpc.observe_recovery_over_a3(
                    path, lease=discovery, transaction_nonce=NONCE, timeout_s=3
                )
            assert controller.inspect() is not None
        finally:
            _stop(stop, thread, failures)


def test_real_hmac_socket_refuses_corrupted_journal(roots) -> None:
    root, path = roots
    with MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    raw = b"not an authentic journal record"
    (root / "transaction.json").write_bytes(raw)
    (root / "transaction.json").chmod(0o600)
    _, stop, thread, failures = _launch_a3(path, root)
    try:
        discovery = generation_runtime.discover_service_lease(
            root=path.parent, label=rpc._LABEL, name="observe.sock"
        )
        with pytest.raises(rpc.RecoveryRPCRefused, match="unavailable"):
            rpc.observe_recovery_over_a3(
                path, lease=discovery, transaction_nonce=NONCE, timeout_s=3
            )
    finally:
        _stop(stop, thread, failures)
    assert (root / "transaction.json").read_bytes() == raw


def test_genuine_a3_peer_challenge_in_independent_fixture_process(roots) -> None:
    tx_root, socket_path = roots
    with MaintenanceTransactionJournal(tx_root) as tx:
        begin(tx)
        expected = advance_to(tx, "guardian_armed")
    original = (tx_root / "transaction.json").read_bytes()
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.issue30_readonly_observer_a3_fixture",
            str(socket_path),
            str(tx_root),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if (
                socket_path.is_socket()
                and socket_path.with_name("observe.sock.auth").is_file()
            ):
                break
            if child.poll() is not None:
                break
            time.sleep(0.025)
        assert child.poll() is None, "isolated sidecar exited before handshake"
        assert socket_path.is_socket()
        lease = generation_runtime.discover_service_lease(
            root=socket_path.parent, label=rpc._LABEL, name="observe.sock"
        )
        before = (tx_root / "transaction.json").stat().st_mtime_ns
        response = rpc.observe_recovery_over_a3(
            socket_path,
            lease=lease,
            transaction_nonce=NONCE,
            timeout_s=3,
        )
        assert response.transaction_nonce == expected.nonce
        assert response.phase == "guardian_armed"
        assert response.status == "possible_outage_manual_review"
        assert response.manual_review_required
        assert not response.production_authorized
        assert not response.autonomous_restart_allowed
        assert (tx_root / "transaction.json").read_bytes() == original
        assert (tx_root / "transaction.json").stat().st_mtime_ns == before
    finally:
        if child.poll() is None:
            child.terminate()  # ONLY the child spawned by this exact test
        _out, err = child.communicate(timeout=7)
    assert child.returncode == 0, err.decode(errors="replace")[-1500:]
    assert not socket_path.exists()
    assert not socket_path.with_name("observe.sock.auth").exists()


def test_unauthed_socket_client_cannot_invoke_rpc_or_mutate_journal(roots) -> None:
    tx_root, socket_path = roots
    with MaintenanceTransactionJournal(tx_root) as tx:
        begin(tx)
        advance_to(tx, "guardian_armed")
    original = (tx_root / "transaction.json").read_bytes()
    _lease, stop, thread, failures = _launch_a3(socket_path, tx_root)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as attacker:
            attacker.settimeout(2)
            attacker.connect(str(socket_path))
            # A valid bounded frame, but not a valid A3 hello, peer proof,
            # client/server HMAC transcript or authorized RPC sequence.
            attacker.sendall(b"\x00\x00\x00\x02{}")
            try:
                reply = attacker.recv(128)
            except (ConnectionResetError, BrokenPipeError):
                reply = b""
            assert reply == b""
        lease = generation_runtime.discover_service_lease(
            root=socket_path.parent, label=rpc._LABEL, name="observe.sock"
        )
        valid = rpc.observe_recovery_over_a3(
            socket_path,
            lease=lease,
            transaction_nonce=NONCE,
        )
        assert valid.phase == "guardian_armed"
        assert not valid.production_authorized
        assert (tx_root / "transaction.json").read_bytes() == original
    finally:
        _stop(stop, thread, failures)

"""Native composition qualification fixtures, without launchd or host mutations."""

import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from binnacle.platform import composition
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError


@pytest.fixture
def native_channel_qualification(monkeypatch):
    """Exercise real authenticated capacity, concurrency, retry and fresh epochs."""
    backlogs, failures, channels = [], [], []
    original_socket = socket.socket

    class ObservedSocket(original_socket):
        def listen(self, backlog=0):
            backlogs.append(backlog)
            return super().listen(backlog)

    monkeypatch.setattr(socket, "socket", ObservedSocket)
    with tempfile.TemporaryDirectory(
        prefix="b0cap-", dir=Path("/tmp").resolve()
    ) as directory:
        root = Path(directory)
        lease = composition.create_service_lease(
            root=root, label="com.binnacle.r3test.probe"
        )
        successor = composition.create_service_lease(root=root, label=lease.label)
        stop, overlap = threading.Event(), threading.Event()
        lock = threading.Lock()
        active, peak, calls, effects = 0, 0, 0, set()

        def handler(payload):
            nonlocal active, peak, calls
            with lock:
                active += 1
                calls += 1
                peak = max(peak, active)
                if active == 2:
                    overlap.set()
            try:
                assert overlap.wait(2), "composition serialized independent channels"
                # The handler owns idempotency under a lock, not the transport.
                with lock:
                    effects.add(payload["operation_id"])
                    return {"effects": len(effects)}
            finally:
                with lock:
                    active -= 1

        def serve():
            try:
                composition.serve_native_channel(
                    socket_path=root / "jobs.sock",
                    lease=lease,
                    handler=handler,
                    stop=stop,
                )
            except Exception as exc:  # noqa: BLE001 - propagate worker failures to teardown
                failures.append(exc)

        server = threading.Thread(target=serve)
        server.start()

        def connect(timeout=1):
            return composition.connect_native_channel(
                socket_path=root / "jobs.sock", lease=lease, timeout_s=timeout
            )

        try:
            channels.extend(connect() for _ in range(16))
            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = [
                    pool.submit(
                        ch.request, {"operation_id": "same-mutation"}, timeout_s=3
                    )
                    for ch in channels[:2]
                ]
                replies = [future.result(timeout=4) for future in requests]
            started = time.monotonic()
            with pytest.raises(NativeCapabilityError) as refused:
                connect(0.15)
            refusal_time = time.monotonic() - started
            # A readiness retry succeeds after one of the 16 slots is released.
            releaser = threading.Timer(0.1, channels[-1].close)
            releaser.start()
            try:
                replacement = connect()
                channels.append(replacement)
            finally:
                releaser.join(2)
            return {
                "backlogs": backlogs,
                "peak": peak,
                "calls": calls,
                "effects": len(effects),
                "replies": replies,
                "capacity_error": refused.value.code,
                "refusal_time": refusal_time,
                "unique_generations": lease.generation != successor.generation,
                "generation_bits": len(lease.generation) * 4,
            }
        finally:
            for channel in channels:
                channel.close()
            stop.set()
            server.join(5)
            assert not server.is_alive(), "bounded handlers failed to drain"
            assert not failures
            assert not (root / "jobs.sock").exists()
            assert not (root / "jobs.sock.auth").exists()

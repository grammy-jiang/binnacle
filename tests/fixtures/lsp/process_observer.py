"""POSIX test-only process observer. No PID from a log is ever signaled.

The parent is an unreaped Popen child; descendants receive private pipe EOF.
This observes only cooperative synthetic descendants, not arbitrary providers.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.fixtures.lsp.lsp_peer import FIXTURE, LspPeer


class ProcessObserver(LspPeer):
    def __init__(
        self,
        directory: Path,
        fault: str = "none",
        *,
        command=None,
        cwd: Path | None = None,
    ):
        self.process = None
        self.selector = None
        self.control = None
        self.buffer = bytearray()
        self.pending_length = None
        self.max_buffered = 0
        self.stderr_size = 0
        self.stderr_sample = bytearray()
        self.escalated = False
        self.cleanup_verified = False
        self.escaped = False
        self.reaps_via_rpc = command is None
        self.expects_child = fault in ("child", "escaped-child")
        read_fd = None
        try:
            fd, name = tempfile.mkstemp(prefix="trace-", suffix=".jsonl", dir=directory)
            os.close(fd)
            self.trace = Path(name)
            read_fd, self.control = os.pipe()
            argv = command or [str(FIXTURE), "--fault", fault]
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    *argv,
                    "--trace",
                    name,
                    "--control-fd",
                    str(read_fd),
                ],
                cwd=cwd,
                pass_fds=(read_fd,),
                start_new_session=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.selector = selectors.DefaultSelector()
            for pipe in (self.process.stdout, self.process.stderr):
                self.selector.register(pipe, selectors.EVENT_READ)
            os.set_blocking(self.process.stderr.fileno(), False)
        except BaseException:
            # If our synthetic provider already spawned a cooperative child,
            # release its control pipe and allow the owning parent to reap it
            # before tearing down the parent. Killing the parent immediately
            # can leave a zombie and produce false cleanup evidence.
            if self.process is not None and self.expects_child:
                try:
                    if self.control is not None:
                        os.close(self.control)
                        self.control = None
                    self.wait_event("child-ready", timeout=2)
                    self.wait_event("child-exit", timeout=2)
                    if self.reaps_via_rpc and self.process.poll() is None:
                        from tests.fixtures.lsp.lsp_transport import frame

                        assert self.process.stdin is not None
                        self.process.stdin.write(
                            frame(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 901,
                                    "method": "fixture/reap",
                                }
                            )
                        )
                        self.process.stdin.flush()
                    self.wait_event("child-reaped", timeout=2)
                except (OSError, TimeoutError, BrokenPipeError):
                    # A failed cooperative handshake cannot certify cleanup.
                    # The final resource rollback still reaps our owned parent.
                    pass
            self.release_resources()
            raise
        finally:
            if read_fd is not None:
                os.close(read_fd)

    def events(self) -> list[dict]:
        # Ignore only the incomplete final line during a concurrent append.
        data = self.trace.read_bytes()
        return [
            json.loads(line)
            for line in data.splitlines(keepends=True)
            if line.endswith(b"\n")
        ]

    def wait_event(self, event: str, timeout: float = 3) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for entry in self.events():
                if entry["event"] == event:
                    return entry
            time.sleep(0.005)
        raise TimeoutError(f"fixture event deadline: {event}")

    def read_chunk(self, timeout: float) -> bytes | None:
        """Drain stderr without retaining unbounded data; None means no stdout yet."""
        ready = self.selector.select(max(0, timeout))
        stdout_chunk = None
        for key, _ in ready:
            chunk = os.read(key.fileobj.fileno(), 1024)
            if key.fileobj is self.process.stdout:
                stdout_chunk = chunk
                continue
            # Drain a bounded burst, including bytes queued behind stdout readiness.
            for index in range(257):
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    break
                self.stderr_size += len(chunk)
                self.stderr_sample.extend(
                    chunk[: max(0, 4096 - len(self.stderr_sample))]
                )
                if index == 256:
                    break
                try:
                    chunk = os.read(key.fileobj.fileno(), 1024)
                except BlockingIOError:
                    break
        return stdout_chunk

    def close_children(self) -> None:
        if self.control is not None:
            os.close(self.control)
            self.control = None
        if self.expects_child:
            self.wait_event("child-ready")
        children = [e for e in self.events() if e["event"] == "child-ready"]
        self.escaped = any(e["pgid"] != self.process.pid for e in children)
        if children:
            self.wait_event("child-exit")
            if self.process.poll() is None and self.reaps_via_rpc:
                self.request("fixture/reap", 900)
            self.wait_event("child-reaped")
            # Exit intent is NOT proof of disappearance. Signal 0 only observes.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if all(not self.pid_exists(e["pid"]) for e in children):
                    return
                time.sleep(0.005)
            raise TimeoutError("descendant cleanup unverified")

    @staticmethod
    def pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def __exit__(self, *exc: object) -> None:
        try:
            self.close_children()
        finally:
            try:
                if self.process.poll() is None:
                    self.process.send_signal(signal.SIGTERM)
                    try:
                        self.process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        self.escalated = True
                        self.process.kill()
                self.process.wait(timeout=3)
            finally:
                self.selector.close()
                for pipe in (
                    self.process.stdin,
                    self.process.stdout,
                    self.process.stderr,
                ):
                    pipe.close()
        self.cleanup_verified = True

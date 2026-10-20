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
    def __init__(self, directory: Path, fault: str = "none", *, command=None):
        fd, name = tempfile.mkstemp(prefix="trace-", suffix=".jsonl", dir=directory)
        os.close(fd)
        self.trace = Path(name)
        read_fd, self.control = os.pipe()
        self.selector = selectors.DefaultSelector()
        self.buffer = bytearray()
        self.max_buffered = 0
        self.stderr_size = 0
        self.stderr_sample = bytearray()
        self.escalated = False
        self.cleanup_verified = False
        self.escaped = False
        self.expects_child = fault in ("child", "escaped-child")
        argv = command or [str(FIXTURE), "--fault", fault]
        try:
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
                pass_fds=(read_fd,),
                start_new_session=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except BaseException:
            os.close(self.control)
            self.selector.close()
            raise
        finally:
            os.close(read_fd)
        for pipe in (self.process.stdout, self.process.stderr):
            self.selector.register(pipe, selectors.EVENT_READ)

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
        for key, _ in ready:
            chunk = os.read(key.fileobj.fileno(), 1024)
            if key.fileobj is self.process.stdout:
                return chunk
            if not chunk:
                self.selector.unregister(key.fileobj)
            self.stderr_size += len(chunk)
            self.stderr_sample.extend(chunk[: max(0, 4096 - len(self.stderr_sample))])
        return None

    def receive(self, timeout: float = 3) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            if b"\r\n\r\n" in self.buffer:
                header, _, body = self.buffer.partition(b"\r\n\r\n")
                length = int(header.split(b":", 1)[1])
                if length > 8192:
                    raise ValueError("fixture body too large")
                if len(body) >= length:
                    self.buffer = body[length:]
                    return json.loads(body[:length])
            if time.monotonic() >= deadline:
                raise TimeoutError("fixture response deadline")
            chunk = self.read_chunk(deadline - time.monotonic())
            if chunk == b"":
                raise EOFError("fixture stdout EOF")
            if chunk:
                self.buffer.extend(chunk)
                self.max_buffered = max(self.max_buffered, len(self.buffer))
                if len(self.buffer) > 9216:
                    raise ValueError("fixture buffer limit")

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
            if self.process.poll() is None:
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

"""P1.5 synthetic process faults only; never imported by production code."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

MODES = (
    "none",
    "hang-initialize",
    "delay-initialize",
    "crash-initialize",
    "eof-initialize",
    "crash-request",
    "eof-request",
    "stderr-flood",
    "non-exit",
    "child",
    "escaped-child",
)


def record(path: str | None, event: str, **metadata: int | bool | str) -> None:
    """Only call with fixed labels and numeric metadata, never request payloads."""
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **metadata}) + "\n")


class Faults:
    def __init__(self, mode: str, trace: str | None, control_fd: int | None):
        self.mode, self.trace = mode, trace
        self.child: subprocess.Popen | None = None
        if mode == "non-exit":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if mode in ("child", "escaped-child"):
            if control_fd is None or trace is None:
                raise ValueError("child fault requires private control pipe and trace")
            self.child = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__)), str(control_fd), trace],
                pass_fds=(control_fd,),
                start_new_session=mode == "escaped-child",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.close(control_fd)
        record(trace, "ready", pid=os.getpid(), pgid=os.getpgrp())

    def accept(self, request: dict) -> bool:
        method = request.get("method")
        if method == "$/cancelRequest":
            record(self.trace, "cancel-observed")
            return False
        # No method, URI, request params, environment, or diagnostic text is logged.
        phase = "initialize" if method == "initialize" else "request"
        if method == "fixture/reap" and self.child is not None:
            self.child.wait(timeout=3)
            record(self.trace, "child-reaped", pid=self.child.pid)
        if self.mode == "non-exit" and method in ("shutdown", "exit"):
            record(self.trace, "ignored-shutdown")
            return True
        if self.mode == f"crash-{phase}":
            record(self.trace, "crash", phase=phase)
            os._exit(23)
        if self.mode == f"eof-{phase}":
            record(self.trace, "stdout-closed", phase=phase)
            os.close(sys.stdout.fileno())
            while True:
                time.sleep(60)
        if method == "initialize":
            if self.mode == "hang-initialize":
                record(self.trace, "withheld")
                return True
            if self.mode == "delay-initialize":
                record(self.trace, "delay-start")
                time.sleep(0.3)
                record(self.trace, "delay-end")
            if self.mode == "stderr-flood":
                sys.stderr.buffer.write(b"x" * (256 * 1024))
                sys.stderr.buffer.flush()
                record(self.trace, "stderr-written", size=256 * 1024)
        return False


if __name__ == "__main__":
    fd, trace = int(sys.argv[1]), sys.argv[2]
    record(trace, "child-ready", pid=os.getpid(), pgid=os.getpgrp())
    # The harness alone owns the writer. EOF works across sessions and on failure.
    # A finite watchdog bounds lifetime even if a broken harness retains the pipe.
    import select

    if select.select([fd], [], [], 15)[0]:
        os.read(fd, 1)
    os.close(fd)
    record(trace, "child-exit", pid=os.getpid())

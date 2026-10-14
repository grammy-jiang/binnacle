"""Tiny isolated producer for Issue #30 full transaction tests. NEVER installed."""

from __future__ import annotations

import os
import re
import select
import stat
import sys
import time
from pathlib import Path

_ROOT = re.compile(r"^issue30-fixture-e2e-[0-9a-f]{32}$")
_ARCHIVE = "mcp.stderr.log.0"
_ACTIVE = "mcp.stderr.log"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[1] not in ("raw", "active", "guardian-active"):
        return 64
    root, mode = Path(args[0]), args[1]
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        return 64
    if (
        not root.is_absolute()
        or _ROOT.fullmatch(root.name) is None
        or root.resolve() != root
    ):
        return 64
    logs = root / "private-logs"
    try:
        dirs = (root.lstat(), logs.lstat())
        if any(
            not stat.S_ISDIR(s.st_mode)
            or s.st_uid != os.getuid()
            or stat.S_IMODE(s.st_mode) != 0o700
            for s in dirs
        ):
            return 64
        path = logs / (_ARCHIVE if mode == "raw" else _ACTIVE)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                return 64
            os.write(fd, ("e2e-fixture-generation " + mode + "\n").encode())
            os.fsync(fd)
            print(f"READY {os.getpid()} {mode}", flush=True)
            if mode == "guardian-active":
                # No pipeline/controlling-process lifetime dependency. A test
                # creates a private stop flag or this worker expires at 20s.
                stop = root / "guardian-worker.stop"
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not stop.exists():
                    time.sleep(0.05)
            else:
                ready, _, _ = select.select([sys.stdin], [], [], 18)
                if ready and sys.stdin.readline().strip() != "STOP":
                    return 75
                if not ready:
                    return 75
        finally:
            os.close(fd)
        return 0
    except (OSError, ValueError, PermissionError):
        return 74


if __name__ == "__main__":
    sys.exit(main())

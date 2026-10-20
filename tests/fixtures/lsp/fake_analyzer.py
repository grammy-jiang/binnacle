"""P1.6 standalone synthetic CLI analyzer. Not a production analyzer runner.

Every writable path must be an explicit child of the supplied private sandbox.
No project configuration, tools, language servers, or network are consulted.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from process_faults import Faults, record

MODES = (
    "clean",
    "findings",
    "nonzero-findings",
    "malformed",
    "oversize",
    "timeout",
    "crash",
    "partial",
    "truncated",
    "empty",
    "signal",
    "workspace-write",
    "ignored-cache",
    "external-cache",
    "child",
    "write-crash",
    "write-malformed",
    "write-partial",
    "write-timeout",
    "valid-json-crash",
    "stderr",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=MODES, required=True)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--control-fd", type=int, required=True)
    args = parser.parse_args()
    sandbox = args.sandbox.resolve(strict=True)
    if not (sandbox / ".fixture-sandbox").is_file():
        raise ValueError("explicit synthetic sandbox marker required")
    workspace = sandbox / "workspace"
    cache = sandbox / "external-cache"
    # Refuse redirected sandbox roots before any intentional writes.
    for directory in (workspace, cache):
        if directory.is_symlink() or directory.resolve().parent != sandbox:
            raise ValueError("sandbox directory escape")
    mode = args.scenario
    record(args.trace, "analyzer-ready", pid=os.getpid())
    if mode.startswith("write-") or mode == "workspace-write":
        write_sentinel(workspace / "sentinel.txt")
    if mode == "ignored-cache":
        directory = workspace / ".ignored-cache"
        if directory.is_symlink():
            raise ValueError("cache symlink escape")
        directory.mkdir(exist_ok=True)
        write_sentinel(directory / "sentinel.txt")
    if mode == "external-cache":
        write_sentinel(cache / "sentinel.txt")
    if mode in ("timeout", "write-timeout"):
        record(args.trace, "timeout-entered")
        time.sleep(15)
        return 24
    if mode in ("crash", "write-crash"):
        os._exit(23)
    if mode == "signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if mode in ("malformed", "write-malformed"):
        print("{not-json")
        return 0
    if mode == "oversize":
        print("x" * (256 * 1024))
        return 0
    if mode == "empty":
        return 0
    if mode == "truncated":
        print('{"complete": true, "diagnostics": [')
        return 0
    findings = mode in ("findings", "nonzero-findings")
    result = {
        "complete": mode not in ("partial", "write-partial"),
        "analyzed": ["fixture.py"],
        "diagnostics": [
            {
                "path": "fixture.py",
                "severity": "error",
                "code": "FIX001",
                "message": "Synthetic finding → 文\nsecond line",
                "range": {
                    "start": {"line": 0, "character": 1},
                    "end": {"line": 0, "character": 2},
                },
            }
        ]
        if findings
        else [],
    }
    child = None
    if mode == "child":
        child = Faults("child", args.trace, args.control_fd).child
    if mode == "stderr":
        sys.stderr.write("synthetic analyzer stderr\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if child is not None:
        child.wait(timeout=16)
        record(args.trace, "child-reaped", pid=child.pid)
    if mode == "valid-json-crash":
        os._exit(23)
    return 1 if mode == "nonzero-findings" else 0


def write_sentinel(path: Path) -> None:
    # Exclusive creation refuses existing files and symlinks, even dangling links.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("synthetic side effect\n")


if __name__ == "__main__":
    raise SystemExit(main())

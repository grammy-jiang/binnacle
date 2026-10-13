"""Real launchd manager restart — separate from the J5 MCP integration process."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.platform.darwin.test_durable_jobs_e2e import (
    REPO,
    Stack,
    client,
    group_gone,
    meta_of,
    ping,
    track,
    until,
)
from tests.platform.darwin.test_durable_jobs_e2e import (
    stack as stack,  # noqa: PLC0414 - required shared test fixture
)

NATIVE = pytest.mark.skipif(
    sys.platform != "darwin" or not hasattr(os, "waitid"),
    reason="Darwin kqueue/A3 IPC; SD-97 requires waitid",
)


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    argv = ["/bin/launchctl", *args]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def label_pid(target: str) -> int | None:
    found = re.search(
        r"^\s+pid = (\d+)$", launchctl("print", target).stdout, re.MULTILINE
    )
    return int(found[1]) if found else None


def render_test_plist(base: Path, label: str, config: Path) -> Path:
    assert label.startswith("com.binnacle.r4test.j5."), "never a production label"
    env = {"HOME": str(base), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src")}
    env["BINNACLE_CONFIG_FILE"] = str(config)
    module = "binnacle.platform.darwin.job_manager_service"  # the production entry
    plist = {
        "Label": label,
        "ProgramArguments": [sys.executable, "-m", module],
        "EnvironmentVariables": env,
        "LimitLoadToSessionType": "Background",
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardErrorPath": str(base / "launchd.err.log"),
    }
    path = base / f"{label}.plist"
    path.write_bytes(plistlib.dumps(plist))
    return path


@NATIVE
def test_launchd_kickstart_restart_leaves_no_orphans_and_marks_owner_restart(
    stack: Stack,
) -> None:
    base, sock = stack.root.parent, stack.sock
    config = base / "config.toml"
    config.write_text(f'[jobs]\nsocket_path = "{sock}"\ndir = "{stack.jobs}"\n')
    label = f"com.binnacle.r4test.j5.jobs.{uuid.uuid4().hex[:8]}"
    plist = render_test_plist(base, label, config)
    domain, target = f"user/{os.getuid()}", f"user/{os.getuid()}/{label}"
    try:
        assert launchctl("bootstrap", domain, str(plist)).returncode == 0
        assert until(lambda: ping(sock) is not None, 60), "manager not ready"
        first = label_pid(target)  # recorded to prove a new incarnation
        job = client().start(
            sock, command="(sleep 120 &); sleep 120", wait_seconds=0.2,
            workdir=stack.work, stdin=None, call_id="e2e-launchd",
        )  # fmt: skip
        pgid = track(stack, job["job_id"])
        result = launchctl("kickstart", "-k", target)  # SIGTERM -> owned groups reaped
        assert result.returncode == 0, result.stderr
        assert until(lambda: group_gone(pgid), 30), "group member survived restart"
        assert until(lambda: ping(sock) is not None, 60), "no restart"
        assert label_pid(target) not in (None, first)
        meta = meta_of(stack.jobs, job["job_id"])
        assert meta["termination_reason"] == "owner_restart"
        assert (ping(sock) or {})["running_jobs"] == 0  # the new incarnation owns none
    finally:
        launchctl("bootout", target)
        assert until(lambda: launchctl("print", target).returncode != 0, 30)
        plist.unlink(missing_ok=True)
    assert launchctl("print", target).returncode != 0  # label absent after teardown

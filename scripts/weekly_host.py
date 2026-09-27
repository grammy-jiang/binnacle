"""What the weekly quality run touches on the host (scripts/weekly_quality.py).

Everything goes through ``Host`` so the tests inject fakes: short commands,
long-running processes, the production journal, the clock, the load, the
host's free memory and a scope's resident memory. ``default_host`` is the
real host. ``job_env`` builds the environment every job runs with.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PRODUCTION_UNIT = "binnacle-mcp.service"
STATE_DIR = Path.home() / ".local" / "state" / "binnacle" / "quality-weekly"
REMOTE_URL = "https://github.com/grammy-jiang/binnacle.git"
TOOL_CALL = "event=tool_call"


class Proc(Protocol):
    """The part of subprocess.Popen the job runner uses."""

    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass
class Host:
    """Everything the weekly run touches, injectable for tests."""

    run: Callable[[Sequence[str], float], tuple[int, str]]
    spawn: Callable[[Sequence[str], Path, Path, Mapping[str, str]], Proc]
    journal: Callable[[float, float | None], list[str]]
    now: Callable[[], float]
    sleep: Callable[[float], None]
    load1: Callable[[], float]
    mem_available_kb: Callable[[], int]
    scope_rss_kb: Callable[[str], int | None]


def run_command(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:g} s"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def spawn(argv: Sequence[str], cwd: Path, log: Path, env: Mapping[str, str]) -> Proc:
    """Start a long-running command with its output appended to ``log``."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        return subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=dict(env),
            start_new_session=True,
        )


def read_journal(since: float, until: float | None = None) -> list[str]:
    """The production server's journal lines in a time window."""
    argv = ["journalctl", "--user", "-u", PRODUCTION_UNIT, "--since", f"@{int(since)}"]
    if until is not None:
        argv += ["--until", f"@{int(until) + 1}"]
    rc, out = run_command([*argv, "--no-pager", "-o", "cat"], 120)
    return out.splitlines() if rc == 0 else []


def mem_available_kb(meminfo: Path = Path("/proc/meminfo")) -> int:
    for line in meminfo.read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    return 0


def _rss_kb(pid: str) -> int:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except OSError:  # the process ended between the listing and the read
        return 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def scope_rss_kb(unit: str) -> int | None:
    """The resident memory of every process in a user scope, or None when
    the scope is gone. The user manager here has no memory controller, so
    this sum is what enforces the scope's memory cap."""
    rc, out = run_command(
        [
            "systemctl",
            "--user",
            "show",
            f"{unit}.scope",
            "-p",
            "ControlGroup",
            "--value",
        ],
        30,
    )
    group = out.strip()
    if rc != 0 or not group:
        return None
    try:
        pids = Path(f"/sys/fs/cgroup{group}/cgroup.procs").read_text().split()
    except OSError:
        return None
    return sum(_rss_kb(pid) for pid in pids)


def default_host() -> Host:
    import time

    return Host(
        run=run_command,
        spawn=spawn,
        journal=read_journal,
        now=time.time,
        sleep=time.sleep,
        load1=lambda: os.getloadavg()[0],
        mem_available_kb=mem_available_kb,
        scope_rss_kb=scope_rss_kb,
    )


def user_bus_env(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` plus the user bus variables cron does not set; without
    them ``systemd-run --user`` cannot reach the user manager."""
    env = dict(environ)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = runtime
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    return env


def job_env(environ: Mapping[str, str], state_dir: Path) -> dict[str, str]:
    """The environment of every job.

    The jobs see the settings' defaults, as CI does: BINNACLE_CONFIG_FILE
    points at an empty file, so the host's ~/.config/binnacle/config.toml
    does not reach the suite. BINNACLE_MANAGED_DEPLOYMENT is dropped, so
    run_command jobs in the tests are owned by the test process and never
    by the production job manager. ~/.local/bin is on PATH for uv.
    """
    env = user_bus_env(environ)
    env.pop("BINNACLE_MANAGED_DEPLOYMENT", None)
    empty = state_dir / "empty-config.toml"
    empty.parent.mkdir(parents=True, exist_ok=True)
    if not empty.exists():
        empty.write_text("", encoding="utf-8")
    env["BINNACLE_CONFIG_FILE"] = str(empty)
    local_bin = str(Path.home() / ".local" / "bin")
    path = env.get("PATH") or "/usr/bin:/bin"
    if local_bin not in path.split(":"):
        env["PATH"] = f"{local_bin}:{path}"
    return env


def uv_binary() -> str:
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

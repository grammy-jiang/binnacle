"""Linux process mechanics and compatibility helpers for durable jobs."""

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO, Literal

from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    JobSignalLease,
    ProcessHandle,
)
from binnacle.platform.linux import job_identity

_CLK_TCK = os.sysconf("SC_CLK_TCK")


def _proc_stat_fields(pid: int) -> list[str] | None:
    """Fields of /proc/<pid>/stat after the '(comm)' token, or None."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat[stat.rindex(")") + 2 :].split()
    except (OSError, ValueError):
        return None


def _proc_starttime(pid: int) -> int | None:
    """Kernel start time (clock ticks since boot): the pid's identity."""
    fields = _proc_stat_fields(pid)
    try:
        return int(fields[19]) if fields else None
    except (IndexError, ValueError):
        return None


def _pid_alive(pid: int, starttime: int | None = None) -> bool:
    """Is this pid alive AND still the process we launched?

    Pids are reused. After a reload a job's pid can belong to an unrelated
    process, which would read as "running" forever and, worse, let stop_job
    signal that stranger. When the record carries the launch-time
    `starttime`, require it to match; records without one (pre-2026-09-06)
    fall back to existence.
    """
    current = _proc_starttime(pid)
    if current is None:
        return False
    return starttime is None or current == starttime


def _descendants(pid: int) -> set[int]:
    """All live descendants of pid, via the /proc ppid chain.

    Catches a child that called setsid() (own session, so outside the job's
    process group) while its parent is still alive. A double-forked daemon
    that reparented to init is not reachable this way and is a documented
    limit.
    """
    children: dict[int, list[int]] = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        fields = _proc_stat_fields(int(entry.name))
        if not fields:
            continue
        try:
            children.setdefault(int(fields[1]), []).append(int(entry.name))
        except (IndexError, ValueError):
            continue
    out: set[int] = set()
    stack = [pid]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


def _uptime_s() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def job_processes(pgid: int, max_cmd_chars: int = 200) -> list[dict]:
    """Live processes in the job's process group, from /proc (no ps needed).

    ChatGPT polled its jobs' children with ``ps -p PID`` 150+ times in the
    first week (docs/usage-analysis-2026-09-03.md); surfacing the group
    here makes that a field instead of a shell round trip.
    """
    out: list[dict] = []
    uptime = _uptime_s()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            stat = Path(entry.path, "stat").read_text()
            # "pid (comm) state ppid pgrp session ..." -- comm may hold spaces.
            rest = stat[stat.rindex(")") + 2 :].split()
            if int(rest[2]) != pgid:
                continue
            cmdline = Path(entry.path, "cmdline").read_bytes()
        except (OSError, ValueError, IndexError):
            continue  # raced with exit
        cmd = cmdline.replace(b"\0", b" ").decode(errors="replace").strip()
        start_s = int(rest[19]) / _CLK_TCK
        out.append(
            {
                "pid": int(entry.name),
                "state": rest[0],
                "etime_s": round(max(uptime - start_s, 0.0), 1),
                "cpu_s": round((int(rest[11]) + int(rest[12])) / _CLK_TCK, 2),
                "cmd": cmd[:max_cmd_chars],
            }
        )
    out.sort(key=lambda p: p["pid"])
    return out


def signal_group(pgid: int, sig: int) -> None:
    os.killpg(pgid, sig)


class LinuxProcessBackend:
    """Process mechanics only; callers retain files, policy, and wait ownership."""

    def launch(
        self,
        argv: Sequence[str],
        *,
        workdir: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        output: BinaryIO,
    ) -> ProcessHandle:
        return subprocess.Popen(
            argv,
            cwd=str(workdir),
            env=env,
            stdin=stdin,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def starttime(self, pid: int) -> int | None:
        return _proc_starttime(pid)

    def alive(self, pid: int, starttime: int | None = None) -> bool:
        return _pid_alive(pid, starttime)

    def processes(self, pgid: int, max_cmd_chars: int = 200) -> list[dict]:
        return job_processes(pgid, max_cmd_chars)

    def descendants(self, pid: int) -> set[int]:
        return _descendants(pid)

    def signal_job(
        self, pgid: int, strays: set[int], intent: Literal["terminate", "kill"]
    ) -> None:
        sig = {"terminate": signal.SIGTERM, "kill": signal.SIGKILL}[intent]
        signal_group(pgid, sig)
        for pid in strays:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    def identity_from_record(
        self, metadata: Mapping[str, object]
    ) -> JobProcessIdentity | None:
        return job_identity.identity_from_record(metadata)

    def open_job_signals(self, identity: JobProcessIdentity) -> JobSignalLease:
        return job_identity.open_job_signals(identity, boot_id=self.boot_id)

    def inspect_job(
        self, identity: JobProcessIdentity, max_cmd_chars: int = 200
    ) -> list[dict]:
        record = identity.native
        if not isinstance(record, job_identity.LinuxJobRecord):
            return []
        try:
            job_identity.verify_boot(record, boot_id=self.boot_id)
        except job_identity.UnverifiedJobProcess:
            return []
        if not self.alive(record.leader, record.starttime):
            return []
        return job_processes(record.group, max_cmd_chars)

    def boot_id(self) -> str:
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return "unknown"

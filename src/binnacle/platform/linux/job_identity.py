"""Verified pidfd signal leases for Linux job-owned processes.

A pidfd pins the kernel process identity and avoids signaling an unrelated
process after PID reuse. Every target is opened and rechecked BEFORE any
SIGTERM/SIGKILL; handles remain pinned through the escalation window.

Limitations: newly forked processes after snapshot are not acquired; old
metadata without a starttime cannot safely create a signal lease; escaped
children already reparented before the scan cannot be proven descendants.
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    JobSignalDeliveryError,
    UnverifiedJobProcess,
)


@dataclass(frozen=True, slots=True)
class LinuxJobRecord:
    leader: int
    group: int
    started_at: float
    starttime: int
    boot_id: str | None


@dataclass(frozen=True, slots=True)
class _Proc:
    pid: int
    ppid: int
    pgid: int
    starttime: int
    state: str


def identity_from_record(metadata: Mapping[str, object]) -> JobProcessIdentity | None:
    """Persisted fields stay unchanged; the native identity remains opaque to Core."""
    leader = metadata.get("pid")
    group = metadata.get("pgid", leader)
    started = metadata.get("started_at")
    birth = metadata.get("starttime")
    boot = metadata.get("boot_id")
    if (
        type(leader) is not int
        or type(group) is not int
        or leader <= 1
        or group != leader
        or type(birth) is not int
        or birth <= 0
        or not isinstance(started, (int, float))
        or isinstance(started, bool)
        or started <= 0
    ):
        return None
    if boot is not None and not isinstance(boot, str):
        return None
    return JobProcessIdentity(
        LinuxJobRecord(leader, group, float(started), birth, boot)
    )


def _proc(pid: int) -> _Proc | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rindex(")") + 2 :].split()
        return _Proc(pid, int(fields[1]), int(fields[2]), int(fields[19]), fields[0])
    except (OSError, ValueError, IndexError):
        return None


def _scan() -> dict[int, _Proc]:
    snapshot = {}
    try:
        with os.scandir("/proc") as entries:
            for entry in entries:
                if entry.name.isdigit():
                    pid = int(entry.name)
                    info = _proc(pid)
                    if info is not None:
                        snapshot[pid] = info
    except OSError as exc:
        raise UnverifiedJobProcess(
            f"cannot inspect Linux process table: {exc}"
        ) from exc
    return snapshot


class LinuxJobSignalLease:
    """Owns verified pidfds and has no dependency on job policy or storage."""

    def __init__(self, targets: list[tuple[int, int]]) -> None:
        self._targets = targets

    def signal(self, intent: Literal["terminate", "kill"]) -> None:
        sig = {"terminate": signal.SIGTERM, "kill": signal.SIGKILL}[intent]
        failed = 0
        for _, fd in self._targets:
            try:
                signal.pidfd_send_signal(fd, sig)
            except ProcessLookupError:
                # A pinned process exited; do not redirect to its reused PID.
                continue
            except OSError:
                # Never let one setuid or otherwise unsignalable descendant
                # prevent delivery to other verified members, especially the
                # original job leader which is deliberately signaled last.
                failed += 1
        if failed:
            raise JobSignalDeliveryError(
                f"{failed} verified process target(s) could not receive "
                f"{intent}; other owned targets were still signaled"
            )

    def close(self) -> None:
        targets, self._targets = self._targets, []
        for _, fd in targets:
            os.close(fd)


def verify_boot(record: LinuxJobRecord, boot_id: Callable[[], str]) -> None:
    current = boot_id()
    if record.boot_id and record.boot_id not in {"unknown", "-"}:
        if current != record.boot_id:
            raise UnverifiedJobProcess("stored job belongs to another host boot")
        return
    # v1 embedded jobs have no boot id; an old record must not reuse a PID
    # with a coincidentally matching start tick on a new kernel boot.
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError) as exc:
        raise UnverifiedJobProcess("cannot validate Linux boot epoch") from exc
    if record.started_at < time.time() - uptime - 2:
        raise UnverifiedJobProcess("job predates current Linux boot")


def open_job_signals(
    identity: JobProcessIdentity, *, boot_id: Callable[[], str]
) -> LinuxJobSignalLease:
    """Acquire an all-or-nothing validated target set; never call killpg."""
    record = identity.native
    if not isinstance(record, LinuxJobRecord):
        raise UnverifiedJobProcess("unrecognized native process identity")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise UnverifiedJobProcess("pidfd support is required for safe signaling")
    verify_boot(record, boot_id)

    acquired: list[tuple[int, int]] = []
    try:
        leader_fd = os.pidfd_open(record.leader)
        acquired.append((record.leader, leader_fd))
        leader = _proc(record.leader)
        if (
            leader is None
            or leader.state in {"Z", "X"}
            or leader.starttime != record.starttime
            or leader.pgid != record.group
        ):
            raise UnverifiedJobProcess("job leader identity no longer matches")

        snapshot = _scan()
        children: dict[int, set[int]] = {}
        for pid, info in snapshot.items():
            children.setdefault(info.ppid, set()).add(pid)
        owned = {record.leader}
        depths = {record.leader: 0}
        pending = [record.leader]
        while pending:
            parent = pending.pop()
            for pid in children.get(parent, ()):
                if pid not in owned:
                    owned.add(pid)
                    depths[pid] = depths[parent] + 1
                    pending.append(pid)

        group = {
            pid
            for pid, info in snapshot.items()
            if info.pgid == record.group and info.starttime >= record.starttime
        }
        all_targets = (owned | group) - {record.leader}
        if len(all_targets) > 4095:
            raise UnverifiedJobProcess("too many signal targets to verify")
        for pid in sorted(all_targets, key=lambda i: (-depths.get(i, 1), i)):
            original = snapshot[pid]
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue  # exited during scan; no signal
            acquired.append((pid, fd))
            current = _proc(pid)
            if current is None or current.starttime != original.starttime:
                raise UnverifiedJobProcess("process identity changed during scan")
            if current.state in {"Z", "X"}:
                continue
            if pid in group:
                if current.pgid != record.group:
                    raise UnverifiedJobProcess("process left the verified group")
            elif current.ppid != original.ppid or original.ppid not in owned:
                raise UnverifiedJobProcess("escaped descendant ancestry changed")
        # Reverse insertion order: descendants first, original leader last.
        pinned = acquired[1:] + acquired[:1]
        acquired = []
        return LinuxJobSignalLease(pinned)
    except BaseException:
        for _, fd in acquired:
            os.close(fd)
        raise

"""Dormant, fail-closed Darwin Manager job-start maintenance fence reader.

No controller, CLI, RPC mutation or production config enables this reader.
When explicitly injected, the Manager checks it inside the existing job
creation transaction (after taking manager lock, before any prune/spawn).
A verified pause blocks new jobs; malformed/foreign/expired state ALSO blocks.

Only a separately authenticated out-of-band J7 maintenance controller can
eventually publish the transaction file. This reader never grants a lease,
stops an existing job, or authorizes service/log lifecycle actions.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class _ManagerSnapshot(Protocol):
    owner_instance_id: str

    def _transaction(
        self, wait_s: float | None = None
    ) -> AbstractContextManager[None]: ...

    def job_counts(self) -> tuple[int, int]: ...


_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_BYTES_MAX = 512


@dataclass(frozen=True)
class MaintenanceObservation:
    state: str  # "absent" | "paused" | "unknown"
    nonce: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {"absent", "paused", "unknown"}:
            raise ValueError("unknown manager maintenance state")
        if self.state != "paused" and self.nonce is not None:
            raise ValueError("unverified manager nonce cannot be accepted")


class ManagerStartFence:
    """Check one private controller-owned directory; no writes ever."""

    def __init__(self, root: Path, *, owner_instance_id: str, pid: int) -> None:
        self.root = root
        self.owner_instance_id = owner_instance_id
        self.pid = pid

    def inspect(self) -> MaintenanceObservation:
        dfd = -1
        fd = -1
        try:
            if (
                not self.root.is_absolute()
                or not isinstance(self.owner_instance_id, str)
                or _TOKEN.fullmatch(self.owner_instance_id) is None
                or type(self.pid) is not int
                or self.pid <= 0
                or self.pid != os.getpid()
            ):
                return MaintenanceObservation("unknown")
            dfd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            dir_info, dir_named = os.fstat(dfd), self.root.lstat()
            if (
                not stat.S_ISDIR(dir_info.st_mode)
                or dir_info.st_uid != os.getuid()
                or dir_info.st_mode & 0o077
                or (dir_info.st_dev, dir_info.st_ino)
                != (
                    dir_named.st_dev,
                    dir_named.st_ino,
                )
            ):
                return MaintenanceObservation("unknown")
            try:
                fd = os.open("request.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
            except FileNotFoundError:
                return MaintenanceObservation("absent")
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or not 0 < opened.st_size <= _BYTES_MAX
            ):
                return MaintenanceObservation("unknown")
            body = os.read(fd, _BYTES_MAX + 1)
            named = os.stat("request.json", dir_fd=dfd, follow_symlinks=False)
            if (
                len(body) != opened.st_size
                or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or named.st_mtime_ns != opened.st_mtime_ns
                or named.st_ctime_ns != opened.st_ctime_ns
            ):
                return MaintenanceObservation("unknown")

            def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
                out: dict[str, Any] = {}
                for key, value in items:
                    if key in out:
                        raise ValueError("duplicate manager maintenance key")
                    out[key] = value
                return out

            record = json.loads(body, object_pairs_hook=unique)
            if not isinstance(record, dict):
                return MaintenanceObservation("unknown")
            nonce, until = record.get("nonce"), record.get("until")
            now = time.time()
            if (
                set(record)
                != {"version", "nonce", "owner_instance_id", "pid", "until", "scope"}
                or type(record.get("version")) is not int
                or record["version"] != 1
                or not isinstance(nonce, str)
                or _TOKEN.fullmatch(nonce) is None
                or record.get("scope") != "jobs"
                or record.get("owner_instance_id") != self.owner_instance_id
                or type(record.get("pid")) is not int
                or record.get("pid") != self.pid
                or not isinstance(until, (float, int))
                or isinstance(until, bool)
                or not now - 5 <= until <= now + 180
            ):
                return MaintenanceObservation("unknown")
            return MaintenanceObservation("paused", nonce)
        except (OSError, UnicodeError, ValueError, TypeError):
            return MaintenanceObservation("unknown")
        finally:
            if fd >= 0:
                os.close(fd)
            if dfd >= 0:
                os.close(dfd)

    def synchronized_ping(
        self, manager: _ManagerSnapshot, reply: dict[str, Any]
    ) -> dict[str, Any]:
        """Add private authenticated ping fields under the SAME start lock.

        A reader may report a paused nonce only after all earlier job-start
        transactions exit. The returned counts are observed under that lock
        rather than from the stale initial ping snapshot. A future controller
        must still own J7, Watchdog and MCP barriers and recheck uncertainty.
        This helper is never installed in the production Manager by default.
        """
        with manager._transaction():
            state = self.inspect()
            if (
                manager.owner_instance_id != self.owner_instance_id
                or self.pid != os.getpid()
            ):
                state = MaintenanceObservation("unknown")
            running, unknown = manager.job_counts()
            report = dict(reply)
            report["running_jobs"], report["unknown_jobs"] = running, unknown
            report["maintenance_admission"] = {
                "state": state.state,
                "nonce": state.nonce,
            }
            return report

    def refusal(self) -> dict[str, Any] | None:
        """Not present -> legacy behavior; otherwise NO new start is allowed."""
        state = self.inspect()
        if state.state == "absent":
            return None
        if state.state == "paused":
            return {
                "ok": False,
                "code": "maintenance_paused",
                "error": "job manager maintenance: new starts temporarily refused",
                "retryable": True,
            }
        return {
            "ok": False,
            "code": "maintenance_state_unknown",
            "error": "job manager maintenance state unknown; new starts refused",
            "retryable": False,
        }

"""Fixture-only Issue #30 admission choreography, NEVER a production controller.

Exercises actual OS J7 flocks and the default-off watchdog/MCP/Jobs gate
interfaces together on an explicitly test-owned directory. No service stop,
launchctl, live Unix RPC, raw log, compression or privileged operation exists.

Even a successful rehearsal returns production_authorized=False. The real
controller additionally requires independent verified launchd writer quiescence
and crash-durable out-of-band recovery, which this module cannot confer.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from binnacle.companions.darwin_log_j7_interlocks import J7Interlocks
from binnacle.companions.service_watchdog_maintenance import (
    confirmed_ack,
    release_pause,
    request_pause,
)
from binnacle.companions.service_watchdog_safety import active_jobs
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.darwin.job_manager_maintenance_fence import ManagerStartFence
from binnacle.platform.darwin.job_manager_service import PROTOCOL_VERSION

_NONCE = re.compile(r"^[0-9a-f]{32}$")
_STOP_POINT = "quiescence_proved_in_fixture_only"


class RehearsalRefused(RuntimeError):
    """A missing, changed or undecidable fixture proof forbids the next step."""


class FixtureJobsManager(Protocol):
    owner_instance_id: str
    jobs_dir: Path
    maintenance_fence: Callable[[], dict[str, Any] | None] | None
    maintenance_probe: Callable[[dict[str, Any]], dict[str, Any]] | None

    def _transaction(
        self, wait_s: float | None = None
    ) -> AbstractContextManager[None]: ...

    def job_counts(self) -> tuple[int, int]: ...

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FixtureRehearsalResult:
    """A test result; even successful fixture barriers grant NO real authority."""

    nonce: str
    manager_owner: str
    manager_pid: int
    mcp_generation: str
    state: str
    watchdog_acknowledged: bool
    mcp_drained: bool
    manager_start_paused: bool
    running_jobs: int
    unknown_jobs: int
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized or self.state != _STOP_POINT:
            raise ValueError("fixture observation is not production authorization")


def _safe_fixture(root: Path, manager: FixtureJobsManager) -> None:
    try:
        s = root.lstat()
        if (
            not root.is_absolute()
            or not root.name.startswith("issue30-fixture-")
            or not stat.S_ISDIR(s.st_mode)
            or s.st_uid != os.getuid()
            or s.st_mode & 0o077
            or root.resolve() != root
            or manager.jobs_dir != root / "jobs"
        ):
            raise RehearsalRefused("fixture isolation proof failed")
        for name in ("j7-state", "watchdog", "manager-pause", "jobs"):
            item = root / name
            ds = item.lstat()
            if (
                not stat.S_ISDIR(ds.st_mode)
                or ds.st_uid != os.getuid()
                or ds.st_mode & 0o077
            ):
                raise RehearsalRefused("fixture child not private")
    except OSError as exc:
        raise RehearsalRefused("fixture directory unavailable") from exc


def _request_jobs(manager: FixtureJobsManager, root: Path, nonce: str) -> None:
    """Publish in the same jobs/.lock creation transaction; no remote RPC."""
    name = root / "manager-pause" / "request.json"
    temp = name.with_name("." + uuid.uuid4().hex + ".tmp")
    fd = -1
    owned_inode: tuple[int, int] | None = None
    try:
        with manager._transaction():
            if name.exists() or name.is_symlink():
                raise RehearsalRefused("other fixture Jobs transaction owns pause")
            fd = os.open(
                temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            opened = os.fstat(fd)
            owned_inode = (opened.st_dev, opened.st_ino)
            payload = json.dumps(
                {
                    "version": 1,
                    "nonce": nonce,
                    "owner_instance_id": manager.owner_instance_id,
                    "pid": os.getpid(),
                    "scope": "jobs",
                    "until": time.time() + 90,
                },
                sort_keys=True,
            ).encode()
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise RehearsalRefused("fixture short write")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            # Atomic create-only publication, never replace a foreign owner.
            os.link(temp, name, follow_symlinks=False)
            os.unlink(temp)
            parentfd = os.open(root / "manager-pause", os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parentfd)
            finally:
                os.close(parentfd)
    except OSError as exc:
        raise RehearsalRefused("fixture manager request not published") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        # A failed exclusive open has no ownership. A failed write on our
        # opened FD can be cleaned only if its path still names that inode.
        named: os.stat_result | None
        try:
            named = temp.lstat()
        except FileNotFoundError:
            named = None
        if named is not None:
            if owned_inode is None or (named.st_dev, named.st_ino) != owned_inode:
                raise RehearsalRefused("fixture temporary publication not settled")
            os.unlink(temp)


def _release_jobs(manager: FixtureJobsManager, root: Path, nonce: str) -> None:
    """Release only our exact private request after no writer was stopped."""
    path = root / "manager-pause" / "request.json"
    with manager._transaction():
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RehearsalRefused("fixture Jobs release cannot open") from exc
        try:
            info = os.fstat(fd)
            named = path.lstat()
            if (
                (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                raise RehearsalRefused("fixture Jobs release request replaced")
            record = json.loads(os.read(fd, 513))
            if (
                record.get("nonce") != nonce
                or record.get("owner_instance_id") != manager.owner_instance_id
                or record.get("pid") != os.getpid()
            ):
                raise RehearsalRefused("fixture Jobs release owner mismatch")
            os.unlink(path)
        finally:
            os.close(fd)


def rehearse_fixture_quiescence(
    root: Path,
    *,
    manager: FixtureJobsManager,
    mcp: ToolAdmissionDrain,
    nonce: str,
    watchdog_ack: Callable[[], object],
    watchdog_pid: int,
    timeout_s: float = 0.1,
) -> FixtureRehearsalResult:
    """Perform a safe sequence with NO production writer lifecycle actions."""
    _safe_fixture(root, manager)
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise RehearsalRefused("invalid fixture transaction nonce")
    if type(watchdog_pid) is not int or watchdog_pid <= 0:
        raise RehearsalRefused("invalid fixture watchdog incarnation")
    watchdog_root = root / "watchdog"
    with J7Interlocks(root / "j7-state") as j7:
        fence = ManagerStartFence(
            root / "manager-pause",
            owner_instance_id=manager.owner_instance_id,
            pid=os.getpid(),
        )
        manager.maintenance_fence = fence.refusal
        manager.maintenance_probe = lambda reply: fence.synchronized_ping(
            manager, reply
        )
        wd_armed = False
        jobs_armed = False
        try:
            request_pause(watchdog_root, nonce=nonce, until=time.time() + 90)
            wd_armed = True
            watchdog_ack()
            if not confirmed_ack(watchdog_root, nonce=nonce, watchdog_pid=watchdog_pid):
                raise RehearsalRefused("fixture Watchdog ACK unavailable")
            j7.verify()
            mcp.fence(nonce=nonce, generation=mcp.generation)
            drained = mcp.wait_drained(nonce=nonce, timeout=timeout_s)
            if not drained.drained:
                raise RehearsalRefused("fixture MCP call still in flight")
            _request_jobs(manager, root, nonce)
            jobs_armed = True
            ping = manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
            stamp = ping.get("maintenance_admission")
            if (
                ping.get("ok") is not True
                or ping.get("owner_instance_id") != manager.owner_instance_id
                or ping.get("pid") != os.getpid()
                or stamp != {"state": "paused", "nonce": nonce}
                or ping.get("running_jobs") != 0
                or ping.get("unknown_jobs") != 0
            ):
                raise RehearsalRefused("fixture Manager admission not quiet")
            if active_jobs(manager.jobs_dir) != 0:
                raise RehearsalRefused("fixture durable Jobs history not quiet")
            j7.verify()
            return FixtureRehearsalResult(
                nonce,
                manager.owner_instance_id,
                os.getpid(),
                mcp.generation,
                _STOP_POINT,
                True,
                True,
                True,
                0,
                0,
            )
        finally:
            # No real writer was stopped by this rehearsal. Release only
            # fixture requests; MCP generation intentionally stays fenced.
            if jobs_armed:
                _release_jobs(manager, root, nonce)
            if wd_armed:
                release_pause(watchdog_root, nonce=nonce)

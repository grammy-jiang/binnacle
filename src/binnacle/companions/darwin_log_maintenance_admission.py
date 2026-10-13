"""Read-only, fail-closed Darwin log maintenance admission audit.

This is not a maintenance lease. It NEVER grants writer quiescence, restarts a
service, installs sudo rules, reconfigures launchd or prunes an archive.

Production code must separately acquire and continuously hold the existing
J7 mac-deploy-gate.lock and jobs-service.lock and a guardian-backed RPC
admission/drain barrier, then recheck the exact owner generation. This module
only identifies reasons the maintenance operator must refuse before that.
"""

from __future__ import annotations

import os
import platform
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from binnacle.companions.service_watchdog_safety import active_jobs

_OWNER = re.compile(r"^[0-9a-f]{32}$")
_REVISION = re.compile(r"^[0-9a-f]{12,40}$")
_REASON_NO_LEASE = "maintenance_barrier_not_held"


@dataclass(frozen=True)
class ManagerGeneration:
    """Authenticated manager facts bound to its durable directory and PID."""

    owner_instance_id: str
    pid: int
    revision: str
    jobs_dir: str
    running_jobs: int
    unknown_jobs: int


@dataclass(frozen=True)
class AdmissionAudit:
    """Advisory-only result: even empty job counts cannot authorize IO."""

    manager: ManagerGeneration | None
    record_active: int | None
    reasons: tuple[str, ...]
    approved: bool = False

    def __post_init__(self) -> None:
        if self.approved or _REASON_NO_LEASE not in self.reasons:
            raise ValueError("read-only admission must never grant authority")


def _count(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _pid(value: object) -> int | None:
    number = _count(value)
    return number if number is not None and number > 0 else None


def _decode_ping(reply: Mapping[str, Any], root: str) -> ManagerGeneration | None:
    """Never trust incomplete/suspicious manager counts or stale directory."""
    if reply.get("ok") is not True:
        return None
    owner, revision, jobs_dir = (
        reply.get("owner_instance_id"),
        reply.get("revision"),
        reply.get("jobs_dir"),
    )
    pid = _pid(reply.get("pid"))
    running, unknown = (
        _count(reply.get("running_jobs")),
        _count(reply.get("unknown_jobs")),
    )
    if (
        not isinstance(owner, str)
        or _OWNER.fullmatch(owner) is None
        or not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or not isinstance(jobs_dir, str)
        or jobs_dir != root
        or pid is None
        or running is None
        or unknown is None
    ):
        return None
    return ManagerGeneration(owner, pid, revision, jobs_dir, running, unknown)


def _root_identity(root: Path) -> tuple[int, int] | None:
    """Require one private, owned directory without following its leaf symlink."""
    dfd = -1
    try:
        dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stat0 = os.fstat(dfd)
        leaf = root.lstat()
        if (
            not stat.S_ISDIR(stat0.st_mode)
            or stat0.st_uid != os.getuid()
            or stat0.st_mode & 0o077
            or (leaf.st_dev, leaf.st_ino) != (stat0.st_dev, stat0.st_ino)
        ):
            return None
        return stat0.st_dev, stat0.st_ino
    except OSError:
        return None
    finally:
        if dfd >= 0:
            os.close(dfd)


def audit_jobs(
    root: Path,
    *,
    ping: Callable[[], Mapping[str, Any]],
    service_pid: Callable[[], int | None],
    record_counter: Callable[[Path], int | None] = active_jobs,
) -> AdmissionAudit:
    """Verify stable authenticated manager+launchd+records without side effects.

    This does not close MCP admission; a new RPC/job can arrive immediately
    after either ping. Accordingly approved can NEVER become True.
    """
    reasons: list[str] = []
    identity = _root_identity(root)
    expected = str(root)
    if identity is None or not root.is_absolute() or expected != os.path.realpath(root):
        reasons.append("jobs_directory_untrusted")
    first: ManagerGeneration | None = None
    last: ManagerGeneration | None = None
    try:
        raw = ping()
        if isinstance(raw, Mapping):
            first = _decode_ping(raw, expected)
    except Exception:  # noqa: BLE001 - unavailable authenticated RPC is unknown
        first = None
    if first is None:
        reasons.append("manager_ping_unverifiable")
    seen_pid: int | None = None
    try:
        seen_pid = _pid(service_pid())
    except Exception:  # noqa: BLE001 - unknown process identity
        seen_pid = None
    if seen_pid is None:
        reasons.append("launchd_jobs_pid_unverifiable")
    observed: int | None = None
    if identity is not None:
        try:
            observed = record_counter(root)
        except Exception:  # noqa: BLE001 - unknown history blocks admission
            observed = None
        if _count(observed) is None:
            observed = None
            reasons.append("durable_jobs_unverifiable")
        if _root_identity(root) != identity:
            reasons.append("jobs_directory_changed")
    try:
        raw2 = ping()
        if isinstance(raw2, Mapping):
            last = _decode_ping(raw2, expected)
    except Exception:  # noqa: BLE001 - never guess a missing second ping
        last = None
    if last is None:
        reasons.append("manager_reping_unverifiable")
    if first is not None and last is not None:
        if first != last:
            reasons.append("manager_generation_or_counts_changed")
        if seen_pid is not None and (first.pid != seen_pid or last.pid != seen_pid):
            reasons.append("manager_launchd_pid_mismatch")
        if first.running_jobs:
            reasons.append("running_jobs")
        if first.unknown_jobs:
            reasons.append("unknown_jobs")
        if observed is not None and observed != (
            first.running_jobs + first.unknown_jobs
        ):
            reasons.append("durable_manager_counts_disagree")
    if observed is not None and observed > 0:
        reasons.append("durable_jobs_active")
    reasons.append(_REASON_NO_LEASE)
    # Stable, enumerable ordering simplifies operator reports and audit tests.
    return AdmissionAudit(first, observed, tuple(dict.fromkeys(reasons)))


def inspect_local_jobs(root: Path) -> AdmissionAudit:
    """Darwin-only host adapter; verified RPC and launchctl are read-only.

    Intended for an operator's Python REPL or offline report, never for
    running inside a production finalization or deletion transaction.
    """
    if platform.system() != "Darwin":
        return AdmissionAudit(None, None, ("host_not_darwin", _REASON_NO_LEASE))

    def authenticated_ping() -> Mapping[str, Any]:
        from binnacle.config import get_settings
        from binnacle.platform.composition import (
            create_job_client,
            create_runtime_paths,
        )

        sock = get_settings().jobs.socket_path or create_runtime_paths().jobs_socket
        return create_job_client().ping(sock)

    def launchd_pid() -> int | None:
        from binnacle.companions.darwin_log_writer_hold import _running_pid

        return _running_pid("system/com.binnacle.jobs")

    return audit_jobs(root, ping=authenticated_ping, service_pid=launchd_pid)

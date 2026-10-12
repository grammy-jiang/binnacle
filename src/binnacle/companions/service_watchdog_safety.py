"""Fail-closed last-moment safety gate for the application-only watchdog.

The stable Binnacle Job Manager owns durable jobs. Observing its store is
read-only: never signal, prune, lock, restart, or reinterpret a possibly
in-flight record as completed. An inaccessible store is never "idle".
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

_JOB_ID = re.compile(r"^[0-9a-f]{12}$")
_MAX_JOBS = 250
_MAX_META = 16384


def _completed(meta: dict[str, Any]) -> bool:
    """Require durable terminal evidence, not an absent/live PID guess."""
    if meta.get("authority") == "UNKNOWN":
        return False
    ended = meta.get("ended_at")
    if not isinstance(ended, (float, int)) or isinstance(ended, bool):
        return False
    code, signal = meta.get("exit_code"), meta.get("signal")
    return (
        isinstance(code, int)
        and not isinstance(code, bool)
        or isinstance(signal, int)
        and not isinstance(signal, bool)
        or meta.get("termination_reason") in {"owner_restart", "host_reboot"}
    )


def active_jobs(root: Path) -> int | None:
    """Return active/unknown count; None means safe classification was impossible.

    Directory descriptors and O_NOFOLLOW defend against a symlink swap. A
    concurrent durable write is treated as unknown, never as an idle host.
    """
    dfd = -1
    try:
        dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.fstat(dfd)
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid():
            return None
        names = os.listdir(dfd)
        ids = [name for name in names if _JOB_ID.fullmatch(name)]
        if len(ids) > _MAX_JOBS:
            return None
        active = 0
        for name in ids:
            jfd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd
            )
            try:
                jst = os.fstat(jfd)
                if not stat.S_ISDIR(jst.st_mode) or jst.st_uid != os.getuid():
                    return None
                mfd = os.open("meta.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=jfd)
                try:
                    st = os.fstat(mfd)
                    if (
                        not stat.S_ISREG(st.st_mode)
                        or st.st_uid != os.getuid()
                        or not 0 < st.st_size <= _MAX_META
                    ):
                        return None
                    with os.fdopen(mfd, "rb") as stream:
                        mfd = -1
                        data = stream.read(_MAX_META + 1)
                finally:
                    if mfd >= 0:
                        os.close(mfd)
            finally:
                os.close(jfd)
            if len(data) > _MAX_META:
                return None
            meta = json.loads(data)
            if not isinstance(meta, dict) or not all(
                key in meta for key in ("command", "workdir", "pid", "started_at")
            ):
                return None
            if not _completed(meta):
                active += 1
        return active
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    finally:
        if dfd >= 0:
            os.close(dfd)


def current_job_activity(root: Path, *, host: str = "linux") -> int | None:
    """Darwin manager ping is authoritative; Linux uses its durable job store.

    The Linux manager's version-1 ping has no job counts. A Darwin ping does,
    so it avoids treating superseded-manager metadata as an active process.
    Neither path mutates jobs, and a failed ping is UNKNOWN, not idle.
    """
    if host != "darwin":
        return active_jobs(root)
    try:
        from binnacle.config import get_settings
        from binnacle.platform.composition import (
            create_job_client,
            create_runtime_paths,
        )

        socket = get_settings().jobs.socket_path or create_runtime_paths().jobs_socket
        reply = create_job_client().ping(socket)
        if reply.get("ok") is not True:
            return None
        counts = (reply.get("running_jobs"), reply.get("unknown_jobs"))
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts
        ):
            return None
        return sum(counts)
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
        # A crashed/missing manager is not evidence that it has no jobs.
        return None


def recovery_allowed(
    *,
    root: Path,
    fresh_running: bool | None,
    fresh_responsive: bool | None,
    host: str = "linux",
) -> tuple[bool, str]:
    """One final observation plus host-authoritative job idle proof."""
    if fresh_running is not True:
        return False, "service_not_confirmed_running"
    if fresh_responsive is not False:
        return False, "endpoint_not_confirmed_unresponsive"
    count = current_job_activity(root, host=host)
    if count is None:
        return False, "jobs_state_unknown"
    if count:
        return False, "jobs_active"
    return True, "verified"

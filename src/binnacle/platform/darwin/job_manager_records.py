"""Durable job-record primitives of the Darwin job manager.

The jobs-dir flocks, the ``meta.json`` reader and the exit-record merge. Split
from ``job_manager_service`` (MS1); behavior unchanged.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from binnacle.platform.contracts.process_contracts import OwnedJobExit

META_REQUIRED = ("command", "workdir", "pid", "started_at")


@contextmanager
def _flock(path: Path, operation: int, busy: str = "") -> Iterator[int]:
    """CLOEXEC so spawned jobs never inherit (and pin) a manager lock (yields it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, operation)
        except BlockingIOError as exc:
            raise RuntimeError(busy) from exc
        yield fd
    finally:
        os.close(fd)


def _exit_meta(meta: dict[str, Any], exited: OwnedJobExit) -> dict[str, Any]:
    if exited.termination_reason == "owner_restart":
        # job_owner._record_interruption: the owner stop ended it; no exit status.
        meta.update(exit_code=None, signal=None)
        reason = "owner_restart"
    elif exited.signal is not None:
        meta.update(signal=exited.signal, exit_code=None)
        reason = "signal"
    else:
        meta["exit_code"] = exited.exit_code
        reason = "normal_exit"
    meta["ended_at"] = time.time()
    stopped = meta.get("stop_requested")
    meta["termination_reason"] = "stop_requested" if stopped else reason
    return meta


def jobs_dir_writer(jobs_dir: Path) -> Any:
    """Lifetime singleton: one manager writer per jobs dir, any runtime root."""
    busy = f"job manager already owns {jobs_dir}"
    return _flock(jobs_dir / ".manager.lock", fcntl.LOCK_EX | fcntl.LOCK_NB, busy)


def read_meta(root: Path, job_id: str) -> dict[str, Any] | None:
    """``job_store.read_meta``: a complete record, or None when unusable."""
    try:
        meta = json.loads((root / job_id / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or any(k not in meta for k in META_REQUIRED):
        return None
    return meta


def list_job_ids(root: Path) -> list[str]:
    try:
        return [path.name for path in root.iterdir() if path.is_dir()]
    except OSError:
        return []

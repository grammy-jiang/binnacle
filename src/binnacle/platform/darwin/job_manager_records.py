"""Durable job-record primitives of the Darwin job manager.

The jobs-dir flocks, the ``meta.json`` reader and the exit-record merge. Split
from ``job_manager_service`` (MS1); behavior unchanged. RL1 adds the bounded
``.lock`` acquire of the reaper's record path (``_flock_bounded``).
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
LOCK_POLL_S = 0.005  # RL1: the bounded acquire re-tries LOCK_NB this often


def _lock_fd(path: Path) -> int:
    """CLOEXEC so spawned jobs never inherit (and pin) a manager lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    return os.open(path, flags, 0o600)


@contextmanager
def _flock(path: Path, operation: int, busy: str = "") -> Iterator[int]:
    """``fcntl.flock`` on a ``_lock_fd`` for the block (yields the fd)."""
    fd = _lock_fd(path)
    try:
        try:
            fcntl.flock(fd, operation)
        except BlockingIOError as exc:
            raise RuntimeError(busy) from exc
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _flock_bounded(path: Path, wait_s: float) -> Iterator[int]:
    """RL1: LOCK_EX within ``wait_s``, else BlockingIOError (an OSError)."""
    deadline = time.monotonic() + wait_s
    fd = _lock_fd(path)
    attempts = 0
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                # F5: bounded backoff reduces repeated 5ms lock barging.
                # Monotonic deadline still bounds EVERY waiter, even under load.
                attempts += 1
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(
                        min(remaining, LOCK_POLL_S * min(2 ** (attempts // 3), 8))
                    )
        yield fd
    finally:
        os.close(fd)


def queued_exit_metrics(
    queued_since: dict[str, float], now: float
) -> dict[str, int | float | None]:
    """Advisory ping telemetry, never interpreted as process authority."""
    oldest = min(queued_since.values(), default=None)
    return {
        "unrecorded_exits": len(queued_since),
        "oldest_unrecorded_age_s": (
            max(0.0, now - oldest) if oldest is not None else None
        ),
    }


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

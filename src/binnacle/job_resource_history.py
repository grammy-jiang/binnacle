"""Compact long-term resource summaries for completed durable jobs."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from binnacle import job_cgroup

log = logging.getLogger("binnacle.jobs")

SCHEMA_VERSION = 1
RETENTION_DAYS = 365
_last_prune_day: str | None = None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d")


def _prune(root: Path, today: str, *, retention_days: int) -> None:
    global _last_prune_day
    if _last_prune_day == today:
        return
    _last_prune_day = today
    cutoff = time.time() - retention_days * 86400
    try:
        paths = list(root.glob("????-??-??.jsonl"))
    except OSError:
        return
    for path in paths:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def append(
    root: Path,
    job_id: str,
    meta: dict,
    resources: dict[str, object],
    *,
    retention_days: int = RETENTION_DAYS,
) -> Path:
    """Append one privacy-minimal completed-job resource row.

    The full command is intentionally omitted. ``workdir`` plus the existing
    non-reversible command hash provide useful attribution without duplicating
    command contents into a year-long history.
    """
    ended = float(meta.get("ended_at") or time.time())
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    today = _day(ended)
    _prune(root, today, retention_days=retention_days)
    row = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": time.time(),
        "job_id": job_id,
        "workdir": meta.get("workdir"),
        "command_hash": meta.get("command_hash"),
        "owner_instance_id": meta.get("owner_instance_id"),
        "started_at": meta.get("started_at"),
        "ended_at": ended,
        "termination_reason": meta.get("termination_reason"),
        "exit_code": meta.get("exit_code"),
        "signal": meta.get("signal"),
        "cgroup_cleanup_pending": bool(meta.get("cgroup_cleanup_pending")),
        "resources": resources,
    }
    path = root / f"{today}.jsonl"
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    return path


def append_best_effort(
    root: Path, job_id: str, meta: dict, resources: dict[str, object]
) -> str | None:
    """Append a summary without ever making job completion fail."""
    try:
        return str(append(root, job_id, meta, resources))
    except OSError as exc:
        log.warning(
            "event=job_resource_history_error job_id=%s error_class=%s",
            job_id,
            type(exc).__name__,
        )
        return None


def merge_final_meta(current: dict, final_meta: dict) -> dict:
    """Merge only resource-finalizer fields into one durable job record."""
    keys = (
        "resource_usage",
        "resource_history_path",
        "resource_finalized_at",
        "cgroup_cleanup_pending",
    )
    for key in keys:
        if key in final_meta:
            current[key] = final_meta[key]
        else:
            current.pop(key, None)
    return current


def finalize_async(
    job_id: str,
    cgroup: str,
    exit_meta: dict,
    *,
    history_root: Path,
    on_finalized: Callable[[dict], None],
) -> None:
    """Finalize counters after a detached descendant empties its cgroup."""

    def _watch() -> None:
        if not job_cgroup.wait_empty(cgroup):
            log.warning(
                "event=job_cgroup_finalizer_unavailable job_id=%s cgroup=%s",
                job_id,
                cgroup,
            )
            return
        resources = job_cgroup.snapshot(cgroup)
        cleaned = job_cgroup.cleanup(cgroup)
        final_meta = dict(exit_meta)
        final_meta.pop("cgroup_cleanup_pending", None)
        final_meta["resource_finalized_at"] = time.time()
        if resources:
            final_meta["resource_usage"] = resources
            history = append_best_effort(history_root, job_id, final_meta, resources)
            if history is not None:
                final_meta["resource_history_path"] = history
        if not cleaned:
            final_meta["cgroup_cleanup_pending"] = True
        on_finalized(final_meta)
        log.info(
            "event=job_cgroup_finalized job_id=%s cleaned=%s cgroup=%s",
            job_id,
            str(cleaned).lower(),
            cgroup,
        )

    threading.Thread(target=_watch, name=f"job-cgroup-{job_id}", daemon=True).start()

"""Compact long-term resource summaries for completed durable jobs."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

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

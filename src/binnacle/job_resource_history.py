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

SCHEMA_VERSION = 2
RETENTION_DAYS = 365
_last_prune_day: str | None = None

# memory.stat mixes current byte gauges with cumulative event counters.  Keep
# them separate in long-term history so a final anon/file value cannot be
# mistaken for a job's historical peak while useful fault/reclaim counters
# remain explicitly cumulative.
CUMULATIVE_MEMORY_STAT_KEYS = frozenset(
    {
        "workingset_refault_anon",
        "workingset_refault_file",
        "workingset_activate_anon",
        "workingset_activate_file",
        "workingset_restore_anon",
        "workingset_restore_file",
        "workingset_nodereclaim",
        "pgdemote_kswapd",
        "pgdemote_direct",
        "pgdemote_khugepaged",
        "pgdemote_proactive",
        "pgscan",
        "pgsteal",
        "pswpin",
        "pswpout",
        "pgscan_kswapd",
        "pgscan_direct",
        "pgscan_khugepaged",
        "pgscan_proactive",
        "pgsteal_kswapd",
        "pgsteal_direct",
        "pgsteal_khugepaged",
        "pgsteal_proactive",
        "pgfault",
        "pgmajfault",
        "pgrefill",
        "pgactivate",
        "pgdeactivate",
        "pglazyfree",
        "pglazyfreed",
        "swpin_zero",
        "swpout_zero",
        "zswpin",
        "zswpout",
        "zswpwb",
    }
)

_FINAL_RESOURCE_RENAMES = {
    "memory_current": "memory_current_final",
    "memory_swap_current": "memory_swap_current_final",
    "pids_current": "pids_current_final",
    "processes": "processes_final",
}


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


def _call_id(value: object) -> str | None:
    return value if isinstance(value, str) and value and value != "-" else None


def history_resources(resources: dict[str, object]) -> dict[str, object]:
    """Convert live/raw cgroup counters to unambiguous history semantics."""
    out = dict(resources)
    for old, new in _FINAL_RESOURCE_RENAMES.items():
        if old in out:
            out[new] = out.pop(old)

    memory_stat = out.pop("memory_stat", None)
    if isinstance(memory_stat, dict):
        final: dict[str, int] = {}
        cumulative: dict[str, int] = {}
        for key, value in memory_stat.items():
            if not isinstance(value, int):
                continue
            target = cumulative if key in CUMULATIVE_MEMORY_STAT_KEYS else final
            target[key] = value
        if final:
            out["memory_stat_final"] = final
        if cumulative:
            out["memory_counters"] = cumulative
    return out


def upgrade_row(row: dict, *, call_id: str | None = None) -> dict:
    """Upgrade one v1 history row to the current schema, idempotently."""
    upgraded = dict(row)
    upgraded["schema_version"] = SCHEMA_VERSION
    existing = _call_id(upgraded.get("call_id"))
    upgraded["call_id"] = existing or _call_id(call_id)
    resources = upgraded.get("resources")
    if isinstance(resources, dict):
        upgraded["resources"] = history_resources(resources)
    return upgraded


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
    non-reversible command hash and call ID provide useful attribution without
    duplicating command contents into a year-long history.
    """
    ended = float(meta.get("ended_at") or time.time())
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    today = _day(ended)
    _prune(root, today, retention_days=retention_days)
    row = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": time.time(),
        "job_id": job_id,
        "call_id": _call_id(meta.get("call_id")),
        "workdir": meta.get("workdir"),
        "command_hash": meta.get("command_hash"),
        "owner_instance_id": meta.get("owner_instance_id"),
        "started_at": meta.get("started_at"),
        "ended_at": ended,
        "termination_reason": meta.get("termination_reason"),
        "exit_code": meta.get("exit_code"),
        "signal": meta.get("signal"),
        "cgroup_cleanup_pending": bool(meta.get("cgroup_cleanup_pending")),
        "resources": history_resources(resources),
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

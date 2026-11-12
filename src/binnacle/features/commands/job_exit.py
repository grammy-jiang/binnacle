"""Record a job's exit in its meta.json (split out of ``jobs.py``).

``jobs.record_exit`` passes its current ``JOBS_DIR`` and resource accounting,
so callers and tests keep using the ``jobs`` entry points.
"""

import logging
import time
from pathlib import Path

from binnacle.features.commands import job_resource_history, job_store
from binnacle.platform.contracts.resource_contracts import ResourceAccounting

logger = logging.getLogger("binnacle.jobs")


def termination_reason(meta: dict, rc: int | None) -> str:
    if meta.get("stop_requested"):
        return "stop_requested"
    if rc is not None and rc < 0:
        return "signal"
    return "normal_exit"


def save_final_resource_meta(jobs_dir: Path, job_id: str, final_meta: dict) -> None:
    """Merge late cgroup counters into a job's meta.json, if it still exists."""
    with job_store.STORE_LOCK:
        current = job_store.read_meta(jobs_dir, job_id)
        if current is None:
            return
        job_resource_history.merge_final_meta(current, final_meta)
        try:
            job_store.write_meta(jobs_dir, job_id, current)
        except OSError:
            pass


def record_exit(
    jobs_dir: Path, job_id: str, rc: int | None, accounting: ResourceAccounting
) -> None:
    """Write an already-exited process's status (``rc``) to meta.json.

    The exit is read from the in-memory Popen object (``proc.returncode``),
    which is the authoritative record while the server lives; meta.json is
    the durable copy for later, stateless job_status/stop_job calls (which
    may run after a ``uvicorn --reload``). Whoever observed the exit calls
    this: the run_command request thread for a command that finished within
    its wait window, or the background reaper for one that outlived it.
    Call only after the process has exited (``proc.returncode`` is set).
    """
    with job_store.STORE_LOCK:
        meta = job_store.read_meta(jobs_dir, job_id) or {}
        if rc is not None and rc < 0:
            meta["signal"] = -rc
            meta["exit_code"] = None
        else:
            meta["exit_code"] = rc
        meta["ended_at"] = time.time()
        meta["termination_reason"] = termination_reason(meta, rc)
        cgroup = meta.get("cgroup")
        resources = accounting.snapshot(cgroup if isinstance(cgroup, str) else None)
        if resources:
            meta["resource_usage"] = resources
        cleanup_pending = False
        if isinstance(cgroup, str) and not accounting.cleanup(cgroup):
            cleanup_pending = True
            meta["cgroup_cleanup_pending"] = True
        elif resources:
            history = job_resource_history.append_best_effort(
                jobs_dir.parent / "resource-jobs", job_id, meta, resources
            )
            if history is not None:
                meta["resource_history_path"] = history
        try:
            job_store.write_meta(jobs_dir, job_id, meta)
        except OSError:
            # The job dir vanished (pruned or removed externally); there is
            # nowhere to record the exit, and crashing helps nobody.
            logger.warning(
                "event=job_exit_unrecorded job_id=%s exit_code=%s signal=%s "
                "call=%s owner=%s owner_instance=%s command_hash=%s",
                job_id,
                meta.get("exit_code"),
                meta.get("signal"),
                meta.get("call_id", "-"),
                meta.get("owner", "embedded"),
                str(meta.get("owner_instance_id") or "-")[:12],
                meta.get("command_hash", "-"),
            )
            return
    if cleanup_pending and isinstance(cgroup, str):
        job_resource_history.finalize_async(
            job_id,
            cgroup,
            dict(meta),
            accounting=accounting,
            history_root=jobs_dir.parent / "resource-jobs",
            on_finalized=lambda final: save_final_resource_meta(
                jobs_dir, job_id, final
            ),
        )
    try:
        log_bytes = (job_store.job_dir(jobs_dir, job_id) / "out.log").stat().st_size
    except OSError:
        log_bytes = 0
    started = meta.get("started_at")
    logger.info(
        "event=job_exit job_id=%s exit_code=%s signal=%s reason=%s runtime_s=%s "
        "log_bytes=%d call=%s owner=%s owner_instance=%s command_hash=%s",
        job_id,
        meta.get("exit_code"),
        meta.get("signal"),
        meta.get("termination_reason"),
        round(meta["ended_at"] - started, 3)
        if isinstance(started, (int, float))
        else "-",
        log_bytes,
        meta.get("call_id", "-"),
        meta.get("owner", "embedded"),
        str(meta.get("owner_instance_id") or "-")[:12],
        meta.get("command_hash", "-"),
    )

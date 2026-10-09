"""Ownership routing and manager recovery for durable command jobs.

This module delegates to the Commands-owned durable job engine,
binnacle.features.commands.jobs. It selects the embedded owner or
the stable manager service without owning storage internals.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from binnacle.mcp.callctx import current_call

logger = logging.getLogger("binnacle.jobs")


def start_and_wait(
    command: str, workdir: Path, stdin: str | None, wait_seconds: float
) -> str:
    from binnacle.features.commands import job_client, jobs

    if jobs.OWNER_MODE == "manager":
        response = job_client.start(
            jobs.MANAGER_SOCKET,
            command=command,
            workdir=workdir,
            stdin=stdin,
            wait_seconds=wait_seconds,
            call_id=current_call.get(),
        )
        return str(response["job_id"])

    job_id, proc = jobs.start_job(command, workdir, stdin)
    try:
        proc.wait(timeout=wait_seconds)
        jobs.record_exit(job_id, proc)
    except subprocess.TimeoutExpired:
        jobs.reap_in_background(job_id, proc)
    return job_id


def mark_stop_requested(job_id: str) -> None:
    from binnacle.features.commands import job_store, jobs

    with job_store.STORE_LOCK:
        meta = job_store.read_meta(jobs.JOBS_DIR, job_id)
        if meta is None or "exit_code" in meta or "signal" in meta:
            return
        meta["stop_requested"] = True
        meta["stop_call_id"] = current_call.get()
        job_store.write_meta(jobs.JOBS_DIR, job_id, meta)
    logger.info(
        "event=job_stop_requested job_id=%s call=%s origin_call=%s "
        "owner_instance=%s command_hash=%s",
        job_id,
        current_call.get(),
        meta.get("call_id", "-"),
        str(meta.get("owner_instance_id") or "-")[:12],
        meta.get("command_hash", "-"),
    )


def _record_interruption(
    job_id: str, meta: dict, reason: str, current_owner: str
) -> None:
    from binnacle.features.commands import job_store, jobs

    meta["exit_code"] = None
    meta["signal"] = None
    meta["ended_at"] = time.time()
    meta["termination_reason"] = reason
    job_store.write_meta(jobs.JOBS_DIR, job_id, meta)
    logger.warning(
        "event=job_interrupted job_id=%s reason=%s call=%s previous_owner=%s "
        "current_owner=%s command_hash=%s",
        job_id,
        reason,
        meta.get("call_id", "-"),
        str(meta.get("owner_instance_id") or "-")[:12],
        current_owner[:12],
        meta.get("command_hash", "-"),
    )


def recover_previous_owner(current_owner: str, current_boot: str) -> int:
    """Finalize unfinished v2 records left by an earlier manager/host boot."""
    from binnacle.features.commands import job_store, jobs

    recovered = 0
    for job_id in job_store.list_job_ids(jobs.JOBS_DIR):
        meta = job_store.read_meta(jobs.JOBS_DIR, job_id)
        if meta is None or meta.get("schema_version") != 2:
            continue
        if "exit_code" in meta or "signal" in meta:
            continue
        previous_owner = meta.get("owner_instance_id")
        previous_boot = meta.get("boot_id")
        if previous_owner == current_owner:
            continue
        if meta.get("stop_requested"):
            reason = "stop_requested"
        else:
            reason = "host_reboot" if previous_boot != current_boot else "owner_restart"
        _record_interruption(job_id, meta, reason, current_owner)
        recovered += 1
    return recovered


def stop_job(job_id: str) -> dict | None:
    """Stop a running manager-owned job; terminal jobs are locally idempotent."""
    from binnacle.features.commands import job_client, job_store, jobs

    state = jobs.job_state(job_id)
    if state is None:
        return None
    meta = job_store.read_meta(jobs.JOBS_DIR, job_id)
    if state["state"] == "unknown" and meta is not None and meta.get("stop_requested"):
        # Another concurrent stop may have killed the process just before its
        # reaper persisted the terminal state. Wait for that durable record
        # instead of exposing the transient post-death ``unknown`` window.
        return jobs.await_exit(job_id, jobs.STOP_SIGKILL_GRACE_S)
    if state["state"] != "running":
        return state
    if (
        meta is not None
        and meta.get("schema_version") == 2
        and meta.get("owner_instance_id")
    ):
        job_client.stop(jobs.MANAGER_SOCKET, job_id, call_id=current_call.get())
        return jobs.job_state(job_id)
    mark_stop_requested(job_id)
    return jobs.stop_job_embedded(job_id)

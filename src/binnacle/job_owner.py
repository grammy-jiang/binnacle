"""Ownership routing and manager recovery for durable command jobs.

This module is deliberately thin around :mod:`binnacle.jobs`: the latter keeps the
legacy process/store primitives while this layer decides whether MCP calls use the
embedded rollback owner or the stable manager service.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from binnacle.callctx import current_call

logger = logging.getLogger("binnacle.jobs")


def start_and_wait(
    command: str, workdir: Path, stdin: str | None, wait_seconds: float
) -> str:
    from binnacle import job_client, jobs

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
    from binnacle import jobs

    with jobs._STORE_LOCK:
        meta = jobs._read_meta(job_id)
        if meta is None or "exit_code" in meta or "signal" in meta:
            return
        meta["stop_requested"] = True
        jobs._write_meta(job_id, meta)


def _record_interruption(job_id: str, meta: dict, reason: str) -> None:
    from binnacle import jobs

    meta["exit_code"] = None
    meta["signal"] = None
    meta["ended_at"] = time.time()
    meta["termination_reason"] = reason
    jobs._write_meta(job_id, meta)
    logger.warning("event=job_interrupted job_id=%s reason=%s", job_id, reason)


def recover_previous_owner(current_owner: str, current_boot: str) -> int:
    """Finalize unfinished v2 records left by an earlier manager/host boot."""
    from binnacle import job_store, jobs

    recovered = 0
    for job_id in job_store.list_job_ids(jobs.JOBS_DIR):
        meta = jobs._read_meta(job_id)
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
        _record_interruption(job_id, meta, reason)
        recovered += 1
    return recovered


def stop_job(job_id: str) -> dict | None:
    """Stop a running manager-owned job; terminal jobs are locally idempotent."""
    from binnacle import job_client, jobs

    state = jobs.job_state(job_id)
    if state is None or state["state"] != "running":
        return state
    meta = jobs._read_meta(job_id)
    if (
        meta is not None
        and meta.get("schema_version") == 2
        and meta.get("owner_instance_id")
    ):
        job_client.stop(jobs.MANAGER_SOCKET, job_id)
        return jobs.job_state(job_id)
    return jobs.stop_job_embedded(job_id)

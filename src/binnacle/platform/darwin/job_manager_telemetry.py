"""Comparable, single-event Darwin durable-job lifecycle telemetry.

Formatting lives outside the job manager so persistence/ownership logic
remains separate from observability; no job or process mutation occurs here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def configure_job_manager_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def log_job_start(logger: logging.Logger, job_id: str, meta: Mapping[str, Any]) -> None:
    """Log durable start facts, never stdin or full command content."""
    logger.info(
        "event=job_start job_id=%s pid=%s workdir=%s call=%s "
        "owner=manager owner_instance=%s command_hash=%s command_chars=%s",
        job_id,
        meta["pid"],
        meta["workdir"],
        meta.get("call_id", "-"),
        str(meta.get("owner_instance_id") or "-")[:12],
        meta.get("command_hash", "-"),
        len(meta["command"]),
    )


def log_job_exit(
    logger: logging.Logger, job_id: str, meta: Mapping[str, Any], job_dir: Path
) -> None:
    """Emit one already-durable terminal state with Linux-compatible fields."""
    try:
        log_bytes = (job_dir / "out.log").stat().st_size
    except OSError:
        log_bytes = 0
    started = meta.get("started_at")
    ended = meta["ended_at"]
    duration = round(ended - started, 3) if isinstance(started, (int, float)) else "-"
    logger.info(
        "event=job_exit job_id=%s exit_code=%s signal=%s reason=%s "
        "runtime_s=%s log_bytes=%d call=%s owner=manager "
        "owner_instance=%s command_hash=%s",
        job_id,
        meta.get("exit_code"),
        meta.get("signal"),
        meta["termination_reason"],
        duration,
        log_bytes,
        meta.get("call_id", "-"),
        str(meta.get("owner_instance_id") or "-")[:12],
        meta.get("command_hash", "-"),
    )

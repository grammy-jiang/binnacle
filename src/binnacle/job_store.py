"""Filesystem-backed durable storage for command jobs.

This module deliberately owns no process lifecycle. Callers provide the active
store root so deployment/tests can repoint it without hidden global state.
"""

import json
import os
import uuid
from pathlib import Path

META_REQUIRED = ("command", "workdir", "pid", "started_at")


class JobGone(Exception):
    """The durable job or its output disappeared before a range read opened."""


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def job_dir(root: Path, job_id: str) -> Path:
    return root / job_id


def read_meta(root: Path, job_id: str) -> dict | None:
    """Return a complete job metadata record, or ``None`` when unusable."""
    try:
        meta = json.loads((job_dir(root, job_id) / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or any(k not in meta for k in META_REQUIRED):
        return None
    return meta


def write_meta(root: Path, job_id: str, meta: dict) -> None:
    """Atomically replace one job's metadata with a complete JSON record."""
    directory = job_dir(root, job_id)
    target = directory / "meta.json"
    temp = directory / f".meta.{uuid.uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(meta))
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def remove_job_dir(path: Path) -> bool:
    """Best-effort removal; concurrent disappearance is not an error."""
    try:
        for item in path.iterdir():
            item.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        return False
    return True


def read_log(root: Path, job_id: str) -> bytes:
    try:
        return (job_dir(root, job_id) / "out.log").read_bytes()
    except OSError:
        return b""


def read_log_range(
    root: Path, job_id: str, start: int, max_bytes: int
) -> tuple[bytes, int]:
    """Read a bounded byte range from one open snapshot of a job log."""
    if start < 0:
        raise ValueError("start must be >= 0")
    if max_bytes < 0:
        raise ValueError("max_bytes must be >= 0")

    directory = job_dir(root, job_id)
    if not (directory / "meta.json").is_file():
        raise JobGone(job_id)

    try:
        with open(directory / "out.log", "rb") as log:
            size_at_open = os.fstat(log.fileno()).st_size
            log.seek(start)
            return log.read(max_bytes), size_at_open
    except (FileNotFoundError, NotADirectoryError):
        raise JobGone(job_id) from None


def list_job_ids(root: Path) -> list[str]:
    try:
        return [path.name for path in root.iterdir() if path.is_dir()]
    except OSError:
        return []

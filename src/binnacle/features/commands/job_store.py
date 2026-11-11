"""Filesystem-backed durable storage for command jobs.

This module deliberately owns no process lifecycle. Callers provide the active
store root so deployment/tests can repoint it without hidden global state.
"""

import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

STORE_LOCK = threading.RLock()  # Process-local; not an interprocess transaction.

META_REQUIRED = ("command", "workdir", "pid", "started_at")

# The only shape new_job_id produces. A job_id is also a path component under
# the spool root, so anything else (``..``, ``/``, absolute paths) is refused
# before a path is built.
JOB_ID_PATTERN = re.compile(r"[0-9a-f]{12}")
INVALID_JOB_ID = "job_id must be 12 lowercase hex"


class JobGone(Exception):
    """The durable job or its output disappeared before a range read opened."""


class InvalidJobId(ValueError):
    """A job_id that ``new_job_id`` cannot produce; it never names a job."""

    def __init__(self) -> None:
        super().__init__(INVALID_JOB_ID)


def is_valid_job_id(value: object) -> bool:
    return isinstance(value, str) and JOB_ID_PATTERN.fullmatch(value) is not None


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def job_dir(root: Path, job_id: str) -> Path:
    """Return the spool directory of one job; refuse ids that could escape it."""
    if not is_valid_job_id(job_id):
        raise InvalidJobId
    return root / job_id


def read_meta(root: Path, job_id: str) -> dict | None:
    """Return a complete job metadata record, or ``None`` when unusable."""
    try:
        meta = json.loads((job_dir(root, job_id) / "meta.json").read_text())
    except (OSError, json.JSONDecodeError, InvalidJobId):
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


def mark_signal_delivery_partial(root: Path, job_id: str) -> bool:
    """Persist native stop failure without altering schema version or exit status.

    The same storage lock protects the reaper's final status update, so a
    subsequent record_exit cannot silently overwrite this failure marker.
    """
    with STORE_LOCK:
        meta = read_meta(root, job_id)
        if meta is None:
            return False
        meta["stop_signal_partial"] = True
        write_meta(root, job_id, meta)
        return True


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
    except (OSError, InvalidJobId):
        return b""


def read_log_range(
    root: Path, job_id: str, start: int, max_bytes: int
) -> tuple[bytes, int]:
    """Read a bounded byte range from one open snapshot of a job log."""
    if start < 0:
        raise ValueError("start must be >= 0")
    if max_bytes < 0:
        raise ValueError("max_bytes must be >= 0")

    if not is_valid_job_id(job_id):
        raise JobGone(job_id)
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


def prune(
    jobs_dir: Path,
    keep: int,
    is_running: Callable[[str], bool],
    remove: Callable[[Path], bool],
) -> tuple[int, int]:
    """Remove job directories beyond the ``keep`` newest; return (removed, running).

    The caller passes ``keep`` already reduced by the slots it reserves:
    ``start_job`` reserves one, so KEEP_NEWEST=50 makes the new directory the
    50th base entry rather than a permanent 51st. Never delete a live job: its
    process would keep running while job_status loses it and the reaper
    crashes on exit. Unreadable or malformed meta, exited, and unknown jobs
    stay deletable so garbage cannot become immortal.
    """
    try:
        dirs = sorted(
            (d for d in jobs_dir.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0, 0
    removed = skipped_running = 0
    for stale in dirs[keep:]:
        if is_running(stale.name):
            skipped_running += 1
        elif remove(stale):
            removed += 1
    return removed, skipped_running

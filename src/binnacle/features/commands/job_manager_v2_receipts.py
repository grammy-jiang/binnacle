"""Small persistent, fail-closed v2 call-ID reservation for the Python owner.

One `O_EXCL` reservation is durably synced *before* any child can launch.
Retries never run a second command. If an owner crashes between reservation
and durable job metadata, outcome remains UNKNOWN until inspected; this is
at-most-once scheduling, not exactly-once execution or a retry promise.

No change to the existing v1 manager wire protocol, spool or job retention.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from binnacle.features.commands import jobs

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_NOFOLLOW | os.O_CLOEXEC
_MAX_RECORD_BYTES = 2048


class ReceiptFailure(ValueError):
    """Missing, unsafe, corrupt or conflicting receipt must refuse a launch."""


class ReceiptNotReady(ReceiptFailure):
    """An existing reservation is incomplete; its command may already run."""


def payload_digest(request: dict[str, Any]) -> str:
    # Include all start behavior parameters except the unique call key itself.
    canonical = {k: v for k, v in request.items() if k != "call_id"}
    data = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def receipt_key(call_id: str) -> str:
    return hashlib.sha256(call_id.encode("utf-8")).hexdigest()


def _encode(record: dict[str, Any]) -> bytes:
    wire = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    if len(wire) > _MAX_RECORD_BYTES:
        raise ReceiptFailure("v2 receipt too large")
    return wire


@contextmanager
def _receipts_dir() -> Iterator[int]:
    # Sibling of the ordinary jobs store: the existing `_prune` enumerates
    # children of jobs.JOBS_DIR and must never delete these dedup records.
    root = jobs.JOBS_DIR.parent / "v2-start-receipts"
    root.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(root, _DIR_FLAGS)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or os.readlink(f"/proc/self/fd/{fd}") != str(root)
        ):
            raise ReceiptFailure("v2 receipt directory not private or changed")
        yield fd
    finally:
        os.close(fd)


def _read(dirfd: int, name: str) -> dict[str, Any] | None:
    try:
        filefd = os.open(name, os.O_RDONLY | _FILE_FLAGS | os.O_NONBLOCK, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(filefd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > _MAX_RECORD_BYTES
        ):
            raise ReceiptFailure("v2 receipt record unsafe")
        raw = os.read(filefd, _MAX_RECORD_BYTES + 1)
    finally:
        os.close(filefd)
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReceiptNotReady("v2 receipt reservation incomplete or corrupt") from exc
    if not isinstance(record, dict) or record.get("version") != 2:
        raise ReceiptFailure("v2 receipt record invalid")
    if record.get("state") not in ("pending", "accepted"):
        raise ReceiptFailure("v2 receipt state unknown")
    return record


def _write_atomic(
    dirfd: int, name: str, record: dict[str, Any], *, create: bool
) -> None:
    data = _encode(record)
    temp = name if create else f".v2-{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_FLAGS
    fd = os.open(temp, flags, 0o600, dir_fd=dirfd)
    try:
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError("v2 receipt zero-byte write")
                view = view[n:]
            os.fsync(fd)
            if not create:
                os.replace(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
            os.fsync(dirfd)
        except BaseException:
            if not create:
                os.unlink(temp, dir_fd=dirfd)
            # If a freshly created reservation failed to sync, retain it.
            # It could still be visible to another caller; never free the key.
            raise
    finally:
        os.close(fd)


def reserve(request: dict[str, Any]) -> tuple[bool, str]:
    """Return (new, fingerprint); duplicate or conflict never creates a job."""
    name = receipt_key(request["call_id"])
    fingerprint = payload_digest(request)
    expected = {"version": 2, "state": "pending", "fingerprint": fingerprint}
    with _receipts_dir() as dirfd:
        try:
            _write_atomic(dirfd, name, expected, create=True)
            return True, fingerprint
        except FileExistsError:
            record = _read(dirfd, name)
            if record is None or record.get("fingerprint") != fingerprint:
                raise ReceiptFailure(
                    "v2 call_id reused for different request"
                ) from None
            return False, fingerprint


def lookup(request: dict[str, Any]) -> dict[str, Any]:
    """A duplicate start may query its previous outcome but cannot resubmit."""
    name = receipt_key(request["call_id"])
    fingerprint = payload_digest(request)
    with _receipts_dir() as dirfd:
        record = _read(dirfd, name)
    if record is None or record.get("fingerprint") != fingerprint:
        raise ReceiptFailure("v2 receipt missing or payload changed")
    job_id = record.get("job_id")
    if record["state"] == "accepted":
        if not isinstance(job_id, str) or len(job_id) != 12:
            raise ReceiptFailure("accepted receipt lacks a job ID")
        state = jobs.job_state(job_id)
        return {
            "version": 2,
            "ok": True,
            "workdir_fd_accepted": True,
            "job_id": job_id,
            "state": state["state"] if state is not None else "unknown",
            "replayed": True,
        }
    # Crash after successful launch but before receipt ack: the actual job
    # metadata may already be durable and includes the v2 request fingerprint.
    # Check its identity rather than launching a second job.
    candidates = []
    try:
        entries = list(jobs.JOBS_DIR.iterdir())
    except FileNotFoundError:
        entries = []
    for directory in entries:
        if not directory.is_dir() or directory.is_symlink():
            continue
        meta = jobs._read_meta(directory.name)
        if (
            meta
            and meta.get("v2_request_fingerprint") == fingerprint
            and meta.get("call_id") == request["call_id"]
        ):
            candidates.append(directory.name)
    if len(candidates) == 1:
        job_id = candidates[0]
        record["state"] = "accepted"
        record["job_id"] = job_id
        with _receipts_dir() as dirfd:
            current = _read(dirfd, name)
            if current is None or current.get("fingerprint") != fingerprint:
                raise ReceiptFailure("v2 receipt changed during reconciliation")
            if current.get("state") != "accepted":
                _write_atomic(dirfd, name, record, create=False)
        state = jobs.job_state(job_id)
        return {
            "version": 2,
            "ok": True,
            "workdir_fd_accepted": True,
            "job_id": job_id,
            "state": state["state"] if state else "unknown",
            "replayed": True,
        }
    # No record, multiple matches, incomplete/corrupt job metadata or
    # potentially already-started child => no safe way to resubmit.
    return {"version": 2, "ok": False, "error": "v2_start_outcome_unknown"}


def accepted(request: dict[str, Any], job_id: str) -> None:
    name = receipt_key(request["call_id"])
    fingerprint = payload_digest(request)
    with _receipts_dir() as dirfd:
        current = _read(dirfd, name)
        if current is None or current.get("fingerprint") != fingerprint:
            raise ReceiptFailure("v2 start reservation disappeared")
        if current["state"] == "accepted" and current.get("job_id") == job_id:
            return  # An identical retry already reconciled durable job metadata.
        if current["state"] != "pending":
            raise ReceiptFailure("v2 receipt state changed during start")
        _write_atomic(
            dirfd,
            name,
            {
                "version": 2,
                "state": "accepted",
                "fingerprint": fingerprint,
                "job_id": job_id,
            },
            create=False,
        )

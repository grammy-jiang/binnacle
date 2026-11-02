"""Small, opt-in, Manager-owned v2 start-admission fence for safe job drain.

The v2 owner may pause all v1+v2 command launches using the existing
`jobs._STORE_LOCK`, which covers reserve -> Popen -> durable metadata.
A durable private marker keeps starts fenced after Manager restart. A paused
Manager still serves job status and stop; this is not a new process owner.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from binnacle.features.commands import job_manager_v2_receipts as receipts
from binnacle.features.commands import jobs

_MARKER = "starts-paused"
_NONCE = re.compile(r"^[a-fA-F0-9-]{16,128}$")
_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class DrainRefused(ValueError):
    """Pause or resume was not durably verified. Fail closed."""


def _nonce_hash(nonce: str) -> str:
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise DrainRefused("invalid maintenance nonce")
    return hashlib.sha256(nonce.encode("ascii")).hexdigest()


def _read(dirfd: int) -> str | None:
    try:
        opened = os.open(_MARKER, _FLAGS, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(opened)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
            or info.st_size > 256
        ):
            raise DrainRefused("maintenance fence file unsafe")
        raw = os.read(opened, 257)
    finally:
        os.close(opened)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DrainRefused("maintenance marker corrupt") from exc
    if (
        not isinstance(body, dict)
        or set(body) != {"version", "nonce_hash"}
        or body["version"] != 2
        or not isinstance(body["nonce_hash"], str)
        or len(body["nonce_hash"]) != 64
    ):
        raise DrainRefused("maintenance marker invalid")
    return body["nonce_hash"]


def require_starts_allowed() -> None:
    """Call under jobs._STORE_LOCK immediately before job reservation/spawn."""
    with receipts._receipts_dir() as dirfd:
        if _read(dirfd) is not None:
            raise DrainRefused("job_manager_starts_paused")


def pause(nonce: str) -> dict[str, object]:
    """Serialize against every running start, fsync a fence, then inventory.

    No new v1 or v2 job may begin after this call returns. Running and unknown
    jobs explicitly block a stop; a completed job has durable exit metadata.
    """
    wanted = _nonce_hash(nonce)
    with jobs._STORE_LOCK, receipts._receipts_dir() as dirfd:
        try:
            fd = os.open(
                _MARKER,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=dirfd,
            )
        except FileExistsError:
            if _read(dirfd) != wanted:
                raise DrainRefused(
                    "pause already active for a different nonce"
                ) from None
        else:
            try:
                payload = json.dumps(
                    {"version": 2, "nonce_hash": wanted}, separators=(",", ":")
                ).encode()
                if os.write(fd, payload) != len(payload):
                    raise DrainRefused("partial maintenance marker write")
                os.fsync(fd)
                os.fsync(dirfd)
            finally:
                os.close(fd)
        active = []
        for item in jobs.list_jobs():
            if item["state"] in ("running", "unknown"):
                active.append({"job_id": item["job_id"], "state": item["state"]})
                continue
            # A completed shell can leave a descendant in the *same* per-job
            # cgroup; KillMode=control-group would kill it on owner restart.
            # The deployed Linux backend places each job in a leaf cgroup.
            cgroup = item.get("cgroup")
            if (
                isinstance(cgroup, str)
                and cgroup.startswith("/")
                and ".." not in cgroup.split("/")
            ):
                path = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
                if path.exists():
                    try:
                        pending = (path / "cgroup.procs").read_text().strip()
                    except OSError:
                        active.append(
                            {"job_id": item["job_id"], "state": "cgroup_unverified"}
                        )
                    else:
                        if pending:
                            active.append(
                                {
                                    "job_id": item["job_id"],
                                    "state": "descendants_running",
                                }
                            )
        # A PENDING at-most-once receipt with no job metadata can mean that
        # child launch already occurred and metadata/ack were interrupted.
        # Do not call such a state safe to restart the owner.
        pending_receipts = 0
        for name in os.listdir(dirfd):
            if re.fullmatch(r"[0-9a-f]{64}", name):
                record = receipts._read(dirfd, name)
                if record is None or record.get("state") == "pending":
                    pending_receipts += 1
        return {
            "version": 2,
            "ok": True,
            "starts_paused": True,
            "active_jobs": active,
            "pending_receipts": pending_receipts,
            "safe_to_stop": not active and pending_receipts == 0,
        }


def resume(nonce: str) -> dict[str, object]:
    """Explicitly remove the durable fence after completing the rollout."""
    wanted = _nonce_hash(nonce)
    with jobs._STORE_LOCK, receipts._receipts_dir() as dirfd:
        if _read(dirfd) != wanted:
            raise DrainRefused("cannot resume unknown maintenance nonce")
        os.unlink(_MARKER, dir_fd=dirfd)
        os.fsync(dirfd)
        return {"version": 2, "ok": True, "starts_paused": False}

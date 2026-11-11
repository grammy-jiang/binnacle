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
from contextlib import suppress
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


def _owner_cgroup_safety() -> tuple[bool, list[dict[str, str]]]:
    """Verify no unknown processes remain in the *delegated owner service*.

    Job records can be pruned or a leader can exit while descendants live.
    Therefore `jobs.list_jobs()` alone is not a sufficient stop condition.
    This reads the *actual* systemd/cgroup-v2 owner boundary, including
    unknown per-job cgroups, without creating new resource-accounting code.
    """
    owner_cgroup = getattr(jobs._RESOURCE_ACCOUNTING, "owner_cgroup", None)
    current, manager_subgroup = owner_cgroup() if owner_cgroup else (None, "")
    if not current or Path(current).name != manager_subgroup:
        # The test runner may be invoked *as a child job* of the production
        # independent Manager, inheriting INVOCATION_ID from systemd. That
        # is NOT the owner's delegated subgroup and cannot verify it.
        if current and re.fullmatch(r"job-[0-9a-f]{12}", Path(current).name):
            return False, []
        if os.environ.get("INVOCATION_ID") or os.environ.get("NOTIFY_SOCKET"):
            return False, [{"job_id": "-", "state": "owner_cgroup_unverified"}]
        # A standalone Python pytest fixture has no delegated systemd owner
        # cgroup; it can validate logical admission separately.
        return False, []
    unit_root = Path("/sys/fs/cgroup") / current.lstrip("/")
    owner_subgroup = unit_root
    unit_root = unit_root.parent
    try:
        owner_pids = set((owner_subgroup / "cgroup.procs").read_text().split())
        if owner_pids != {str(os.getpid())}:
            return False, [
                {"job_id": "-", "state": "owner_subgroup_has_other_processes"}
            ]
        if (unit_root / "cgroup.procs").read_text().strip():
            return False, [{"job_id": "-", "state": "service_root_has_processes"}]
        blocked: list[dict[str, str]] = []
        for group in unit_root.iterdir():
            # The cgroup2 root contains kernel-owned cgroup.* and memory.*
            # control FILES as well as child directories. Only nested
            # directories represent actual process-containing subgroups.
            if not group.is_dir():
                continue
            if group.name == manager_subgroup:
                continue
            if not re.fullmatch(r"job-[0-9a-f]{12}", group.name):
                blocked.append({"job_id": "-", "state": "unexpected_owner_cgroup"})
                continue
            lines = (group / "cgroup.events").read_text().splitlines()
            events = dict(line.split(maxsplit=1) for line in lines if " " in line)
            if events.get("populated") != "0":
                blocked.append(
                    {"job_id": group.name[4:], "state": "job_cgroup_populated"}
                )
        return True, blocked
    except (OSError, ValueError):
        return False, [{"job_id": "-", "state": "owner_cgroup_scan_failed"}]


def _publish_marker(dirfd: int, wanted: str) -> None:
    """Write the fence to a private file, then link it into place.

    A short write leaves no marker (the pause fails and may be retried); a
    half-written marker could never be resumed. link() keeps O_EXCL's rule:
    FileExistsError when a marker is already there.
    """
    staged = f".{_MARKER}.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    # One owner per spool and the store lock is held: any staged file is a
    # leftover of a crashed pause.
    for name in os.listdir(dirfd):
        if name.startswith(f".{_MARKER}."):
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=dirfd)
    fd = os.open(staged, flags, 0o600, dir_fd=dirfd)
    try:
        payload = json.dumps(
            {"version": 2, "nonce_hash": wanted}, separators=(",", ":")
        ).encode()
        if os.write(fd, payload) != len(payload):
            raise DrainRefused("partial maintenance marker write")
        os.fsync(fd)
        os.link(staged, _MARKER, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.unlink(staged, dir_fd=dirfd)  # the marker must have one link
        os.fsync(dirfd)
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(staged, dir_fd=dirfd)


def pause(nonce: str) -> dict[str, object]:
    """Serialize against every running start, fsync a fence, then inventory.

    No new v1 or v2 job may begin after this call returns. Running and unknown
    jobs explicitly block a stop; a completed job has durable exit metadata.
    """
    wanted = _nonce_hash(nonce)
    with jobs._STORE_LOCK, receipts._receipts_dir() as dirfd:
        try:
            _publish_marker(dirfd, wanted)
        except FileExistsError:
            if _read(dirfd) != wanted:
                raise DrainRefused(
                    "pause already active for a different nonce"
                ) from None
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
        # A PENDING at-most-once receipt might be after a completed Popen,
        # while a v2 reply is still being finalized. If a *single* durable
        # metadata record already links the exact fingerprint and receipt
        # key, this is a known job tracked above. Otherwise its launch
        # outcome remains ambiguous and we MUST NOT stop the owner.
        pending_receipts = 0
        for name in os.listdir(dirfd):
            if not re.fullmatch(r"[0-9a-f]{64}", name):
                continue
            record = receipts._read(dirfd, name)
            if record is None or record.get("state") != "pending":
                continue
            fingerprint = record.get("fingerprint")
            matches = 0
            for item in jobs.list_jobs():
                meta = jobs._read_meta(item["job_id"])
                if (
                    meta is not None
                    and meta.get("v2_receipt_key") == name
                    and meta.get("v2_request_fingerprint") == fingerprint
                ):
                    matches += 1
            if matches != 1:
                pending_receipts += 1
        cgroup_verified, unmatched_groups = _owner_cgroup_safety()
        active.extend(unmatched_groups)
        return {
            "version": 2,
            "ok": True,
            "starts_paused": True,
            "active_jobs": active,
            "owner_cgroup_verified": cgroup_verified,
            "pending_receipts": pending_receipts,
            # Only a verified kernel delegated owner cgroup proves there are
            # no untracked process groups. A plain pytest/Popen owner is
            # allowed to pause starts but must NEVER claim restart safety.
            "safe_to_stop": cgroup_verified and not active and pending_receipts == 0,
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

"""Production-plist and raw-inode *read-only* identity attestation for Issue #30.

The authenticated independent controller will need this proof before and
after ANY launchd service action. The probe never calls launchctl/bootout,
opens a service socket, signals a PID, creates files or unlinks raw logs.
A passed identity check is NOT authority to stop a Binnacle producer.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import pwd
import re
import stat
from dataclasses import dataclass
from pathlib import Path

_PLIST_DIR = Path("/Library/LaunchDaemons")
_PORTS = {
    "com.binnacle.mcp": ("mcp.stderr.log", "mcp.stdout.log"),
    "com.binnacle.jobs": ("com.binnacle.jobs.err.log", "com.binnacle.jobs.out.log"),
    "com.binnacle.tunnel": ("tunnel.stderr.log", "tunnel.stdout.log"),
    "com.binnacle.service-watchdog": (
        "service-watchdog.stderr.log",
        "service-watchdog.stdout.log",
    ),
    "com.binnacle.resource-monitor": (
        "resource-monitor.stderr.log",
        "resource-monitor.stdout.log",
    ),
}
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_RAW = re.compile(r"^([A-Za-z0-9.-]+\.log)\.(0|[1-9][0-9]{0,2})$")
_MAX_PLIST = 32 * 1024


class InstalledIdentityRefused(RuntimeError):
    """Production identity is unknown: preserve files and service uptime."""


@dataclass(frozen=True)
class InstalledWriterIdentity:
    """No lifecycle authorization follows from a successful read-only audit."""

    label: str
    launchd_target: str
    plist_path: Path
    plist_digest: str
    plist_device: int
    plist_inode: int
    raw_path: Path
    raw_device: int
    raw_inode: int
    raw_size: int
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized:
            raise ValueError("plist/source identity does not authorize bootout")


def _names(label: str, raw: str) -> tuple[str, str]:
    known = _PORTS.get(label)
    match = _RAW.fullmatch(raw)
    if known is None or match is None or match.group(1) not in known:
        raise InstalledIdentityRefused("unknown installed writer or raw generation")
    return known


def _verify_plist(
    data: bytes,
    *,
    label: str,
    stderr_name: str,
    stdout_name: str,
    private_logs: Path,
    username: str,
) -> None:
    if not data or len(data) > _MAX_PLIST:
        raise InstalledIdentityRefused("installed plist not bounded")
    try:
        value = plistlib.loads(data)
    except (ValueError, TypeError, plistlib.InvalidFileException) as exc:
        raise InstalledIdentityRefused("installed plist parsing refused") from exc
    if not isinstance(value, dict):
        raise InstalledIdentityRefused("installed service plist not an object")
    keep = value.get("KeepAlive")
    # Installed Jobs and resource monitor use SuccessfulExit=false; the
    # other three approved LaunchDaemons use KeepAlive=true.
    expected_keep: bool | dict[str, bool] = (
        {"SuccessfulExit": False}
        if label in ("com.binnacle.jobs", "com.binnacle.resource-monitor")
        else True
    )
    args = value.get("ProgramArguments")
    if (
        value.get("Label") != label
        or value.get("RunAtLoad") is not True
        or type(keep) is not type(expected_keep)
        or keep != expected_keep
        or value.get("UserName") != username
        or value.get("GroupName") != "staff"
        or value.get("StandardErrorPath") != str(private_logs / stderr_name)
        or value.get("StandardOutPath") != str(private_logs / stdout_name)
        or not isinstance(args, list)
        or not args
        or not all(isinstance(arg, str) and "\x00" not in arg for arg in args)
        or not Path(args[0]).is_absolute()
    ):
        raise InstalledIdentityRefused("installed plist launchd plan differs")
    if any(k in value for k in ("MachServices", "Sockets", "QueueDirectories")):
        raise InstalledIdentityRefused("installed plist has unexpected activation")
    # argv/environment variations must match an independently pinned digest
    # supplied by an authorized preflight caller, never learned from this file.


def _owned(info: os.stat_result, *, uid: int, mode: int, root: bool) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == (0 if root else uid)
        and info.st_gid == (0 if root else info.st_gid)
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == mode
    )


def _pinned_file(
    path: Path, *, root: bool, owner_uid: int
) -> tuple[bytes, os.stat_result]:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        initial = os.fstat(fd)
        mode = 0o644 if root else 0o600
        if not _owned(initial, uid=owner_uid, mode=mode, root=root):
            raise InstalledIdentityRefused("file owner/mode/inode not approved")
        if root and initial.st_gid != 0:
            raise InstalledIdentityRefused("root plist group not wheel")
        if initial.st_size <= 0 or (root and initial.st_size > _MAX_PLIST):
            raise InstalledIdentityRefused("file size unknown or too large")
        # Do not inspect private raw log contents: only the trusted plist
        # needs bounded bytes for its independently supplied SHA-256 proof.
        value = os.read(fd, _MAX_PLIST + 1) if root else b""
        if root and len(value) != initial.st_size:
            raise InstalledIdentityRefused("plist content truncated")
        now = os.fstat(fd)
        by_path = os.stat(path, follow_symlinks=False)
        if (
            (initial.st_dev, initial.st_ino) != (now.st_dev, now.st_ino)
            or (initial.st_dev, initial.st_ino) != (by_path.st_dev, by_path.st_ino)
            or (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns)
            != (now.st_size, now.st_mtime_ns, now.st_ctime_ns)
            or not _owned(by_path, uid=owner_uid, mode=mode, root=root)
        ):
            raise InstalledIdentityRefused("installed inode changed during inspection")
        return value, initial
    except OSError as exc:
        raise InstalledIdentityRefused(
            "installed service identity unavailable"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def inspect_installed_writer(
    *,
    label: str,
    raw_name: str,
    approved_plist_sha256: str,
    home: Path | None = None,
) -> InstalledWriterIdentity:
    """Validate existing installed label/plist/source; no production mutation.

    The digest MUST be independently approved by an authorized controller;
    deriving it from the same plist would defeat tamper detection.
    """
    stderr_name, stdout_name = _names(label, raw_name)
    if (
        not isinstance(approved_plist_sha256, str)
        or _HEX64.fullmatch(approved_plist_sha256) is None
    ):
        raise InstalledIdentityRefused("approved plist fingerprint absent")
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        raise InstalledIdentityRefused("inspection must run unprivileged")
    user = pwd.getpwuid(os.getuid())
    selected = Path(user.pw_dir) if home is None else home
    if not selected.is_absolute() or selected.resolve() != selected:
        raise InstalledIdentityRefused("configured home must be canonical")
    if selected != Path(user.pw_dir):
        raise InstalledIdentityRefused("home differs from authenticated user")
    logs = selected / "Library" / "Logs" / "binnacle"
    try:
        directory = logs.lstat()
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.getuid()
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise InstalledIdentityRefused("installed private logs untrusted")
    except OSError as exc:
        raise InstalledIdentityRefused("installed private logs unavailable") from exc
    plist = _PLIST_DIR / f"{label}.plist"
    content, pinfo = _pinned_file(plist, root=True, owner_uid=os.getuid())
    digest = hashlib.sha256(content).hexdigest()
    if digest != approved_plist_sha256:
        raise InstalledIdentityRefused("installed service digest differs")
    _verify_plist(
        content,
        label=label,
        stderr_name=stderr_name,
        stdout_name=stdout_name,
        private_logs=logs,
        username=user.pw_name,
    )
    raw = logs / raw_name
    _bytes, rinfo = _pinned_file(raw, root=False, owner_uid=os.getuid())
    return InstalledWriterIdentity(
        label,
        f"system/{label}",
        plist,
        digest,
        pinfo.st_dev,
        pinfo.st_ino,
        raw,
        rinfo.st_dev,
        rinfo.st_ino,
        rinfo.st_size,
    )

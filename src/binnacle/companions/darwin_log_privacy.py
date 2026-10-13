"""Repair privacy on existing Binnacle launchd logs without reopening services.

launchd can create stdout/stderr paths before the configured Umask takes
effect. Tightening a regular file's mode via its already-open descriptor is
non-disruptive, even while the original process is still writing to it.
Never follow symlinks, change owner or touch unrelated directories.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

# Large Mac SSD: bound worst-case raw data while reserving ample free space.
# We do NOT compress an archive which may still be receiving launchd writes.
# 12 observed streams * (1 active + 2 archives) * 50 GiB = 1,800 GiB,
# below the 2.4 TiB free at deployment. Archive growth can exceed this if
# launchd keeps a rotated inode open: monitor both active and raw archives.
ROTATION_SIZE_KIB = 50 * 1024 * 1024  # 50 GiB per live log
ROTATION_WARNING_BYTES = 40 * 1024**3
MIN_DISK_FREE_BYTES = 100 * 1024**3
ARCHIVE_COUNT = 2
# Keep GN: G = glob, N = do not signal. In particular OMIT J and Z, which
# compress open inodes and destroy writes after rotation.
ROTATION_FLAGS = "GN"
_RAW_LOG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*\.log(?:\.[0-9]+)?$")


def render_newsyslog_rule(
    home: Path,
    *,
    user: str,
    group: str = "staff",
    size_kib: int = ROTATION_SIZE_KIB,
    archives: int = ARCHIVE_COUNT,
) -> str:
    """Pure policy renderer; never install or rotate an active log file.

    GN performs a *rename-only* rotation: no J/Z compression or signals.
    A launchd process holding the original descriptor keeps writing into the
    renamed .log.0 inode; content is retained rather than compressed early.
    An offline, writer-coordinated maintenance pass may later compress it.

    """
    if (
        not home.is_absolute()
        or any(c.isspace() for c in str(home))
        or not user
        or not group
        or not all(c.isalnum() or c in "_-" for c in user + group)
        or not 1 <= archives <= 50
        or not 1024 <= size_kib <= 100 * 1024**2
    ):
        raise ValueError("unsafe Darwin log retention policy")
    root = home / "Library/Logs/binnacle"
    return f"{root}/*.log {user}:{group} 600 {archives} {size_kib} * {ROTATION_FLAGS}"


def harden_private_logs(root: Path, *, max_files: int = 64) -> tuple[str, ...]:
    """Make safe, user-owned *.log files 0600; reject ambiguity as a unit."""
    dfd = -1
    try:
        dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.fstat(dfd)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.getuid()
            or directory.st_mode & 0o077
        ):
            raise RuntimeError("unsafe Binnacle log directory")
        names = sorted(name for name in os.listdir(dfd) if _RAW_LOG.fullmatch(name))
        if len(names) > max_files or max_files <= 0:
            raise RuntimeError("too many Binnacle log files")
        # Validate every target first to avoid partially accepting a planted
        # symlink or hardlink. Files may still change concurrently, so validate
        # the descriptor again before fchmod.
        descriptors: list[tuple[str, int]] = []
        try:
            for name in names:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
                descriptors.append((name, fd))
                st = os.fstat(fd)
                if (
                    not stat.S_ISREG(st.st_mode)
                    or st.st_uid != os.getuid()
                    or st.st_nlink != 1
                ):
                    raise RuntimeError("unsafe Binnacle log file")
            changed = []
            for name, fd in descriptors:
                mode = stat.S_IMODE(os.fstat(fd).st_mode)
                if mode != 0o600:
                    os.fchmod(fd, 0o600)
                    changed.append(name)
            return tuple(changed)
        finally:
            for _, fd in descriptors:
                os.close(fd)
    except OSError as exc:
        raise RuntimeError("Binnacle log privacy verification unavailable") from exc
    finally:
        if dfd >= 0:
            os.close(dfd)


def logs_nearing_rotation(
    root: Path, *, warn_bytes: int = ROTATION_WARNING_BYTES
) -> tuple[tuple[str, int], ...]:
    """Report growing live and rotated-but-still-open raw logs, read only."""
    if warn_bytes <= 0:
        raise ValueError("invalid rotation warning threshold")
    dfd = -1
    try:
        dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.fstat(dfd)
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid():
            raise RuntimeError("unsafe Binnacle log directory")
        out = []
        for name in sorted(os.listdir(dfd)):
            if not _RAW_LOG.fullmatch(name):
                continue
            info = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError("unsafe Binnacle log file")
            if info.st_size >= warn_bytes:
                out.append((name, info.st_size))
        return tuple(out)
    except OSError as exc:
        raise RuntimeError("Binnacle log rotation size check unavailable") from exc
    finally:
        if dfd >= 0:
            os.close(dfd)

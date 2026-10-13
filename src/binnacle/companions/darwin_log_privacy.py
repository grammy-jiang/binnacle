"""Repair privacy on existing Binnacle launchd logs without reopening services.

launchd can create stdout/stderr paths before the configured Umask takes
effect. Tightening a regular file's mode via its already-open descriptor is
non-disruptive, even while the original process is still writing to it.
Never follow symlinks, change owner or touch unrelated directories.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


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
        names = sorted(name for name in os.listdir(dfd) if name.endswith(".log"))
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
    root: Path, *, warn_bytes: int = 768 * 1024 * 1024
) -> tuple[tuple[str, int], ...]:
    """Report files near the installed newsyslog size limit; never rotate them."""
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
            if not name.endswith(".log"):
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

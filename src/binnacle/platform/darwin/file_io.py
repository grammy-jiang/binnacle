"""Descriptor-only I/O helpers shared by Darwin file traversal and access.

None of these helpers resolves an absolute path or changes grant ownership.
"""

from __future__ import annotations

import errno
import os
import stat

from binnacle.platform.contracts.special_file_contracts import SPECIAL_OPEN_ERRNOS


def failed_open_special(parent: int, name: str, exc: OSError) -> bool:
    """Check a refused open by the already-held parent, without following links."""
    if exc.errno not in SPECIAL_OPEN_ERRNOS:
        return False
    try:
        actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_IFMT(actual.st_mode) in (
        stat.S_IFSOCK,
        stat.S_IFIFO,
        stat.S_IFCHR,
        stat.S_IFBLK,
    )


def open_directory_child(parent: int, name: str, flags: int) -> int:
    """Clarify refused child type using only the held parent's no-follow stat.

    Darwin may report either ELOOP or ENOTDIR for a no-follow directory open.
    Metadata can change during diagnosis; a failed/ambiguous stat must never
    trigger a retry, alter authority, or weaken the original refusal.
    """
    try:
        return os.open(name, flags, dir_fd=parent)
    except OSError as exc:
        if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
            raise
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError:
            info = None
        if info is not None:
            if stat.S_ISLNK(info.st_mode):
                diagnosed = errno.ELOOP
            elif not stat.S_ISDIR(info.st_mode):
                diagnosed = errno.ENOTDIR
            else:
                diagnosed = exc.errno
            if diagnosed != exc.errno:
                raise OSError(diagnosed, os.strerror(diagnosed)) from exc
        raise


def read_at_most(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum
    while remaining:
        chunk = os.read(fd, min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

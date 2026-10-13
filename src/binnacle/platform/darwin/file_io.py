"""Descriptor-only I/O helpers shared by Darwin file traversal and access.

None of these helpers resolves an absolute path or changes grant ownership.
"""

from __future__ import annotations

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

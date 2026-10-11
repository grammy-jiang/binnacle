"""Exclusive publication of a generation's endpoint files (R-M1a2-S1 split).

Moved verbatim from ``generation_runtime``, which re-exports both names. The
credential file is created O_EXCL, and an entry is published with Darwin
RENAME_EXCL, so neither ever overwrites an existing entry. The threat boundary
is the cooperative user account, as in ``generation_runtime``.
"""

from __future__ import annotations

import ctypes
import json
import os
from typing import Any


def _write_credentials(
    fd: int, name: str, credentials: dict[str, Any], owned: dict[str, tuple[int, int]]
) -> None:
    key_fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
    )
    try:
        info = os.fstat(key_fd)
        owned[name] = (info.st_dev, info.st_ino)
        with os.fdopen(key_fd, "wb", closefd=False) as stream:
            stream.write(json.dumps(credentials).encode())
            stream.flush()
            os.fsync(key_fd)
    finally:
        os.close(key_fd)


def _publish_entry(fd: int, source: str, target: str) -> None:
    """Darwin RENAME_EXCL publishes an inode without overwriting any entry."""
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = libc.renameatx_np
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(fd, os.fsencode(source), fd, os.fsencode(target), 0x4) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    os.fsync(fd)

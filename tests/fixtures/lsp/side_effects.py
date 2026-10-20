"""Test-only full-tree manifest; deliberately never consults Git ignore rules.

Symlink text is recorded without following links. Audit external targets using
additional explicit roots; this is an observation harness, not confinement.
Snapshot errors propagate: an unreadable tree cannot be declared unchanged.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    kind: str
    mode: int
    size: int
    digest: str | None = None
    target: str | None = None


def manifest(root: Path) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}

    def visit(path: Path) -> None:
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        digest = target = None
        if stat.S_ISLNK(info.st_mode):
            kind, target = "symlink", os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            kind = "file"
            hasher = hashlib.sha256()
            # Do not follow a symlink substituted between lstat and open.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino, before.st_mode) != (
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                ):
                    raise ValueError("file changed during snapshot")
                while chunk := stream.read(65536):
                    hasher.update(chunk)
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise ValueError("file changed during snapshot")
            digest = hasher.hexdigest()
        elif stat.S_ISDIR(info.st_mode):
            kind = "directory"
        else:
            kind = "special"
        entries[path.relative_to(root).as_posix()] = Entry(
            kind, mode, info.st_size, digest, target
        )
        if kind == "directory":
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return entries


def differences(before: dict[str, Entry], after: dict[str, Entry]) -> dict:
    return {
        name: (before.get(name), after.get(name))
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    }

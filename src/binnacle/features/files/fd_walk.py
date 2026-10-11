"""Descriptor walk for the Linux Files tools (r6 W2 X3a, SD-74).

Linux twin of platform/darwin/file_traversal.py ``directory_at`` and
platform/darwin/file_access.py ``absolute_in_root``/``link_target_info``.
A root is opened from '/' one component at a time; every directory below it
is opened with O_NOFOLLOW|O_DIRECTORY relative to its parent descriptor, and
every metadata or link read is relative to an opened directory. A same-uid
swap of an in-root component for a symlink between a check and its use
therefore cannot redirect the walk outside the root. This is not continuous
containment: a directory renamed after it was opened keeps its identity.
"""

import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

MAX_LINK_HOPS = 40  # Darwin platform/darwin/file_access.py MAX_LINK_HOPS.
DIRECTORY_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY
)


def absolute_in_root(text: str, root: str) -> list[str] | None:
    """Lexical gate for absolute link text (r6 X2; Darwin file_access.py twin).

    The components of text below root, or None: any '..' component, or text
    outside root. Only '' and '.' components are dropped; the filesystem is
    never consulted, so text that steps out and back is no existence oracle.
    A trailing '/' or '/.' keeps one '' marker, so the walk requires a
    directory there, as it does for relative text (RX2-F2).
    """
    raw = text.split("/")
    parts = [part for part in raw if part not in ("", ".")]
    base = [part for part in root.split("/") if part]
    if ".." in parts or parts[: len(base)] != base:
        return None
    below = parts[len(base) :]
    return [*below, ""] if raw[-1] in ("", ".") else below


@contextmanager
def directory_at(base_fd: int, parts: Sequence[str]) -> Iterator[int]:
    """Open each component no-follow before releasing its parent descriptor."""
    fd = os.open(".", DIRECTORY_FLAGS, dir_fd=base_fd)
    try:
        for part in parts:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def open_root(root: Path) -> Iterator[int]:
    """Open a canonical root from '/'; a symlink component fails (ENOTDIR)."""
    top = os.open("/", DIRECTORY_FLAGS)
    try:
        with directory_at(top, root.parts[1:]) as fd:
            yield fd
    finally:
        os.close(top)


def link_target_info(
    root_fd: int, directory: Sequence[str], name: str, root_path: str
) -> os.stat_result | None:
    """ONE no-follow read of a link's target, only if it resolves in the root.

    ``directory`` holds the link's components below root_fd, the root being
    listed. Absolute text is walked from root_fd only when absolute_in_root
    accepts it for root_path. '..' above the root (also into an outer root
    when roots nest), an absolute intermediate link, more than MAX_LINK_HOPS
    links, a non-directory intermediate, a dangling link, a loop and any read
    failure yield None. The result is the lstat of the last component, or the
    fstat of the directory a trailing '', '.' or '..' ends on; it is never a
    symlink, and no path string below '/' is followed.
    """
    stack = list(directory)
    try:
        with directory_at(root_fd, stack) as start:
            text = os.readlink(name, dir_fd=start)
        pending = text.split("/")
        if pending[0] == "":
            below = absolute_in_root(text, root_path)
            if below is None:
                return None  # '..', another root or an alias: omitted.
            stack, pending = [], below
        hops = 1
        info: os.stat_result | None = None
        while pending:
            part = pending.pop(0)
            if part in ("", "."):
                info = None
                continue
            if part == "..":
                if not stack:
                    return None
                stack.pop()
                info = None
                continue
            with directory_at(root_fd, stack) as parent:
                info = os.lstat(part, dir_fd=parent)
                if stat.S_ISLNK(info.st_mode):
                    hops += 1
                    target = os.readlink(part, dir_fd=parent)
                    if hops > MAX_LINK_HOPS or target.startswith("/"):
                        return None
                    pending[:0] = target.split("/")
                    info = None
                    continue
            if pending:
                if not stat.S_ISDIR(info.st_mode):
                    return None
                stack.append(part)
        if info is None:
            with directory_at(root_fd, stack) as final:
                info = os.fstat(final)
    except OSError:
        return None
    return info

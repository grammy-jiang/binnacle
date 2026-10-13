"""Linux FD-relative write/edit operations (SEC-FU-14).

Path resolution retains the public in-root symlink and display semantics, but
authorization of the destination uses a no-follow walk from an opened root.
No pathname is independently re-opened for writing; the destination is
replaced relative to the *held* parent descriptor. The best-effort /proc
identity check also refuses a parent observed to have moved while held.

This is a tool-scope guard for a trusted same-UID service, not a transactional
sandbox against an adversary who controls renames throughout the commit.
"""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.platform.contracts.file_access_contracts import WriteReceipt
from binnacle.platform.contracts.special_file_contracts import (
    PATH_IS_DIRECTORY_CODE,
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    path_is_directory_text,
)

_TARGET_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _TARGET_FLAGS
_CHUNK = 1 << 20


def _require_linux() -> None:
    if sys.platform != "linux":
        raise RuntimeError("fd_write is Linux-only")


def _regular(info: os.stat_result, path: Path, tool: str) -> None:
    if stat.S_ISDIR(info.st_mode):
        raise CodedToolError(PATH_IS_DIRECTORY_CODE, path_is_directory_text(path, tool))
    if not stat.S_ISREG(info.st_mode):
        raise CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_nlink,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verify_parent(fd: int, path: Path, tool: str) -> None:
    # An openat() parent survives a rename. Refuse observed moves (including
    # a deleted parent); this is NOT a lock against a later same-UID rename.
    if os.readlink(f"/proc/self/fd/{fd}") != str(path):
        raise fd_walk.path_changed(path, tool)


@contextmanager
def _parent(
    path: Path, roots: Sequence[Path], *, create: bool, tool: str
) -> Iterator[tuple[int, str]]:
    _require_linux()
    holders = [root for root in roots if path.is_relative_to(root)]
    if not holders:
        raise fd_walk._outside(str(path), roots)
    top = max(holders, key=lambda root: len(root.parts))
    parts = path.relative_to(top).parts
    if not parts:
        raise CodedToolError(PATH_IS_DIRECTORY_CODE, path_is_directory_text(path, tool))
    try:
        with fd_walk.open_root(top) as root_fd:
            fd = os.dup(root_fd)
            try:
                for name in parts[:-1]:
                    try:
                        child = os.open(name, fd_walk.TRAVERSE_FLAGS, dir_fd=fd)
                    except FileNotFoundError:
                        if not create:
                            raise
                        # Create relative to the *already held* parent. If an
                        # adversary supplies a link instead, open() fails closed.
                        try:
                            os.mkdir(name, dir_fd=fd)
                        except FileExistsError:
                            pass  # A simultaneous creator must still pass no-follow.
                        child = os.open(name, fd_walk.TRAVERSE_FLAGS, dir_fd=fd)
                    except NotADirectoryError as exc:
                        # Existing regular ancestor: preserve the former
                        # Path.mkdir(exist_ok=True) EEXIST message (R4 parity).
                        # A link that races into this position is a different
                        # condition and must still fail closed.
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if create and stat.S_ISREG(info.st_mode):
                            raise FileExistsError(
                                errno.EEXIST, os.strerror(errno.EEXIST), str(path)
                            ) from exc
                        raise
                    os.close(fd)
                    fd = child
                _verify_parent(fd, path.parent, tool)
                yield fd, parts[-1]
            finally:
                os.close(fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.ENOENT):
            raise fd_walk.path_changed(path, tool) from exc
        raise


def _open_target(
    parent: int, name: str, path: Path, tool: str, *, edit: bool
) -> int | None:
    flags = (os.O_RDWR if edit else os.O_WRONLY) | _TARGET_FLAGS
    try:
        return os.open(name, flags, dir_fd=parent)
    except FileNotFoundError:
        if edit:
            raise CodedToolError(
                "edit_conflict", f"File changed since you read it: {path}."
            ) from None
        return None
    except OSError as exc:
        # Inspect the *same descriptor-relative name* on a failed open, never
        # follow its symlink, and do not accidentally open a FIFO or a device.
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError:
            current = None
        if current is not None:
            if stat.S_ISLNK(current.st_mode):
                raise fd_walk.path_changed(path, tool) from exc
            _regular(current, path, tool)
        raise


def _destination(
    parent: int, name: str, path: Path, tool: str, *, digest: str | None
) -> os.stat_result | None:
    fd = _open_target(parent, name, path, tool, edit=digest is not None)
    if fd is None:
        return None
    try:
        info = os.fstat(fd)
        _regular(info, path, tool)
        if digest is not None:
            h = hashlib.sha256()
            while chunk := os.read(fd, _CHUNK):
                h.update(chunk)
            if h.hexdigest() != digest or _identity(os.fstat(fd)) != _identity(info):
                raise CodedToolError(
                    "edit_conflict", f"File changed since you read it: {path}."
                )
        return info
    finally:
        os.close(fd)


def read_for_edit(path: Path, roots: Sequence[Path]) -> tuple[bytes, tuple[int, int]]:
    """Read a regular file through a pinned parent; verify stability/identity."""
    _require_linux()
    with _parent(path, roots, create=False, tool="edit_file") as (parent, name):
        try:
            fd = os.open(name, fd_walk.READ_FLAGS, dir_fd=parent)
        except OSError as exc:
            if fd_walk._failed_open_special(parent, name, exc):
                raise CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT) from exc
            if exc.errno in (errno.ELOOP, errno.ENOENT, errno.ENOTDIR):
                raise fd_walk.path_changed(path, "edit_file") from exc
            raise
        try:
            initial = os.fstat(fd)
            _regular(initial, path, "edit_file")
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if _identity(current) != _identity(initial):
                raise fd_walk.path_changed(path, "edit_file")
            chunks = []
            while chunk := os.read(fd, _CHUNK):
                chunks.append(chunk)
            original = b"".join(chunks)
            if (
                _identity(os.fstat(fd)) != _identity(initial)
                or len(original) != initial.st_size
            ):
                raise fd_walk.path_changed(path, "edit_file")
            _verify_parent(parent, path.parent, "edit_file")
            return original, (initial.st_dev, initial.st_ino)
        finally:
            os.close(fd)


def write_bytes(
    path: Path,
    roots: Sequence[Path],
    data: bytes,
    *,
    create_parents: bool,
    expected_sha256: str | None = None,
    expected_identity: tuple[int, int] | None = None,
) -> WriteReceipt:
    """Commit with no-follow FD-relative atomic replace; refuse observed races."""
    _require_linux()
    tool = "edit_file" if expected_sha256 is not None else "write_file"
    with _parent(path, roots, create=create_parents, tool=tool) as (parent, name):
        before = _destination(parent, name, path, tool, digest=expected_sha256)
        if expected_identity is not None and (
            before is None or (before.st_dev, before.st_ino) != expected_identity
        ):
            raise CodedToolError(
                "edit_conflict", f"File changed since you read it: {path}."
            )
        temporary = ".binnacle-write-" + secrets.token_hex(16)
        tempfd = os.open(
            temporary,
            _CREATE_FLAGS,
            (stat.S_IMODE(before.st_mode) if before is not None else 0o666),
            dir_fd=parent,
        )
        published = False
        try:
            rest = memoryview(data)
            while rest:
                count = os.write(tempfd, rest)
                if count <= 0:
                    raise OSError(errno.EIO, "short write")
                rest = rest[count:]
            current = _destination(parent, name, path, tool, digest=expected_sha256)
            if (before is None) != (current is None) or (
                before is not None
                and current is not None
                and _identity(before) != _identity(current)
            ):
                raise CodedToolError(
                    "edit_conflict"
                    if expected_sha256 is not None
                    else "write_conflict",
                    f"File changed while writing: {path}.",
                )
            if current is not None:
                os.fchmod(tempfd, stat.S_IMODE(current.st_mode))
            # Verify the held parent has not visibly been renamed or detached.
            # Descriptor-relative replacement also never follows a final link.
            _verify_parent(parent, path.parent, tool)
            # Flush the final mode and payload only after all refusal checks.
            os.fsync(tempfd)
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            published = True
            return WriteReceipt(
                len(data),
                current.st_size if current is not None else None,
                "overwritten" if current is not None else "created",
            )
        finally:
            os.close(tempfd)
            if not published:
                os.unlink(temporary, dir_fd=parent)

"""Descriptor-based, offline file access for P3.6 trust inputs.

Every path component is opened relative to its parent descriptor with
``O_NOFOLLOW``; symlinks, hardlinks, foreign owners and writable parents are
refused before bytes are read. This is local filesystem hygiene only: it cannot
defend against root, a kernel compromise or the process owner itself.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_PATH = 4096
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_UNSAFE_FILE_BITS = stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID
_UNSAFE_FILE_BITS |= stat.S_ISVTX


class PathRefused(ValueError):
    """Fixed non-sensitive denial identifier; never carries path data."""


@dataclass(frozen=True)
class PathPolicy:
    """Who may own the target and which locations are never acceptable."""

    owner_uids: frozenset[int]
    check_ancestors: bool = True
    allow_sticky_ancestors: bool = False
    forbidden_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecureFile:
    """Bytes plus the identity of the exact inode that supplied them."""

    data: bytes
    uid: int
    mode: int
    dev: int
    ino: int


def _split(path: str | Path) -> list[str]:
    text = os.fspath(path)
    if not isinstance(text, str) or not text.startswith("/") or "\x00" in text:
        raise PathRefused("path_not_absolute")
    if len(text) > MAX_PATH:
        raise PathRefused("path_too_long")
    parts = text.split("/")[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise PathRefused("path_not_canonical")
    return parts


def _forbidden_ids(policy: PathPolicy) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for root in policy.forbidden_roots:
        try:
            info = os.stat(root)
        except OSError:
            continue
        found.add((info.st_dev, info.st_ino))
    return found


def _check_dir(info: os.stat_result, policy: PathPolicy) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise PathRefused("path_component_not_directory")
    if not policy.check_ancestors:
        return
    if info.st_uid != 0 and info.st_uid not in policy.owner_uids:
        raise PathRefused("path_ancestor_owner_untrusted")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        shared_ok = (
            policy.allow_sticky_ancestors
            and info.st_uid == 0
            and info.st_mode & stat.S_ISVTX
        )
        if not shared_ok:
            raise PathRefused("path_ancestor_writable")


def _step(name: str, parent: int) -> int:
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent)
    except OSError as exc:
        try:
            link = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError:
            link = None
        if link is not None and stat.S_ISLNK(link.st_mode):
            raise PathRefused("path_symlink_refused") from exc
        if exc.errno == errno.ELOOP:
            raise PathRefused("path_symlink_refused") from exc
        raise PathRefused("path_unreadable") from exc


def _walk(parts: list[str], policy: PathPolicy) -> tuple[int, set[tuple[int, int]]]:
    """Return an open descriptor for the final directory; caller must close it."""
    try:
        fd = os.open("/", _DIR_FLAGS)
    except OSError as exc:
        raise PathRefused("path_unreadable") from exc
    forbidden = _forbidden_ids(policy)
    chain: set[tuple[int, int]] = set()
    try:
        for name in [None, *parts]:
            if name is not None:
                nxt = _step(name, fd)
                os.close(fd)
                fd = nxt
            info = os.fstat(fd)
            _check_dir(info, policy)
            chain.add((info.st_dev, info.st_ino))
        if chain & forbidden:
            raise PathRefused("path_inside_untrusted_root")
    except BaseException:
        os.close(fd)
        raise
    return fd, chain


def open_directory(path: str | Path, policy: PathPolicy) -> int:
    """Open a symlink-free directory chain and return its final descriptor."""
    fd, _ = _walk(_split(path), policy)
    return fd


def read_file(path: str | Path, policy: PathPolicy, max_bytes: int) -> SecureFile:
    """Read one regular, single-link, non-writable file from a vetted chain."""
    parts = _split(path)
    dir_fd, chain = _walk(parts[:-1], policy)
    fd = -1
    try:
        try:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=dir_fd)
        except OSError as exc:
            raise PathRefused("path_symlink_or_unreadable") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PathRefused("file_not_regular")
        if info.st_nlink != 1:
            raise PathRefused("file_hardlink_refused")
        if info.st_uid not in policy.owner_uids:
            raise PathRefused("file_owner_untrusted")
        if info.st_mode & _UNSAFE_FILE_BITS:
            raise PathRefused("file_mode_unsafe")
        if (info.st_dev, info.st_ino) in _forbidden_ids(policy) | chain:
            raise PathRefused("path_inside_untrusted_root")
        if not 0 < info.st_size <= max_bytes:
            raise PathRefused("file_size_invalid")
        data = b""
        while len(data) <= max_bytes:
            block = os.read(fd, max_bytes + 1 - len(data))
            if not block:
                break
            data += block
        after = os.fstat(fd)
        current = os.stat(parts[-1], dir_fd=dir_fd, follow_symlinks=False)
        stable = (
            len(data) == info.st_size
            and (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns)
            == (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns)
            and (current.st_ino, current.st_dev) == (info.st_ino, info.st_dev)
        )
        if not stable:
            raise PathRefused("file_changed_during_read")
        return SecureFile(data, info.st_uid, info.st_mode, info.st_dev, info.st_ino)
    except OSError as exc:
        raise PathRefused("file_unreadable") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(dir_fd)

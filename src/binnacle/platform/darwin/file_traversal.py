"""Descriptor traversal for the opened-object Files subset.

No path below a grant is reopened by absolute name. Captured directories retain
identity across rename; this is not continuous pathname containment or a hostile
same-UID sandbox. Recursive ignore support is deliberately root-local: positive
excludes in .ignore/.rgignore only. Git/global/ancestor policies are unsupported.
"""

from __future__ import annotations

import errno
import fnmatch
import math
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import PurePosixPath

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    BudgetExceeded,
    Capability,
    CapabilityState,
    CapabilityUnavailable,
    PermissionDenied,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import (
    FileEntry,
    FileListing,
    ListRequest,
)

MAX_BYTES = 64 * 1024 * 1024
MAX_VISITED = 100_000
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def capability(code: str, *, unavailable: bool = False) -> Capability:
    return Capability(
        CapabilityState.UNAVAILABLE if unavailable else CapabilityState.LIMITED,
        code,
        "opened-object files; root-local ignore subset; no full macOS parity",
    )


def unsafe(code: str) -> UnsafePath:
    return UnsafePath(code, capability(code))


def unavailable(code: str) -> CapabilityUnavailable:
    return CapabilityUnavailable(code, capability(code, unavailable=True))


@contextmanager
def native_errors() -> Iterator[None]:
    """EPERM cannot diagnose TCC: preserve denial without claiming its cause."""
    try:
        yield
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            code = "permission_denied_tcc_possible"
            raise PermissionDenied(code, capability(code)) from None
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise unsafe("symlink_or_wrong_path_type") from None
        if exc.errno == errno.ENOENT:
            raise unsafe("path_not_found") from None
        code = "file_io_failed"
        raise AuthorityUnknown(code, capability(code)) from None


def validate_relative_path(relative_path: str) -> tuple[str, ...]:
    if relative_path in ("", "."):
        return ()
    parts = relative_path.split("/")
    if "\0" in relative_path or any(p in ("", ".", "..") for p in parts):
        raise unsafe("invalid_relative_path")
    if len(parts) > 128:
        raise unsafe("path_depth_exceeded")
    return tuple(parts)


def require_positive(value: int, maximum: int) -> None:
    if not 0 < value <= maximum:
        raise BudgetExceeded("invalid_file_budget", capability("invalid_file_budget"))


def deadline_after(timeout: float) -> float:
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise BudgetExceeded("invalid_timeout", capability("invalid_timeout"))
    return time.monotonic() + timeout


@contextmanager
def directory_at(
    root_fd: int, parts: tuple[str, ...], *, create: bool = False, max_new: int = 32
) -> Iterator[int]:
    """Transfer traversal to each opened directory before releasing its parent."""
    fd = os.dup(root_fd)
    created = 0
    try:
        for part in parts:
            try:
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                if created >= max_new:
                    raise BudgetExceeded(
                        "parent_budget", capability("parent_budget")
                    ) from None
                try:
                    os.mkdir(part, mode=0o777, dir_fd=fd)
                    created += 1
                except FileExistsError:
                    pass  # A racer won; no-follow open still establishes authority.
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def regular_fd(parent: int, name: str, flags: int = READ_FLAGS) -> int:
    fd = os.open(name, flags, dir_fd=parent)
    try:
        mode = os.fstat(fd).st_mode
        if stat.S_ISDIR(mode):
            raise unsafe("path_is_directory")
        if not stat.S_ISREG(mode):
            raise unsafe("special_file_unsupported")
    except BaseException:
        os.close(fd)
        raise
    return fd


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


def _full_match(path: str, pattern: str) -> bool:
    """POSIX segment globbing without importing the tool/configuration layer."""
    names, patterns = PurePosixPath(path).parts, PurePosixPath(pattern).parts
    if len(pattern) > 4096 or len(patterns) > 128:
        raise unavailable("glob_budget_exceeded")

    @cache
    def matches(index: int, offset: int) -> bool:
        if index == len(patterns):
            return offset == len(names)
        part = patterns[index]
        if part == "**":
            if index == len(patterns) - 1:
                # A preceding literal separator needs a remaining component.
                return offset < len(names) or index == 0
            return any(matches(index + 1, end) for end in range(offset, len(names) + 1))
        return (
            offset < len(names)
            and fnmatch.fnmatchcase(names[offset], part)
            and matches(index + 1, offset + 1)
        )

    return matches(0, 0)


def glob_matches(path: str, pattern: str) -> bool:
    return _full_match(path, pattern if "/" in pattern else f"**/{pattern}")


def _local_excludes(fd: int, prefix: str) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for name in (".git", ".gitignore"):
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise unavailable("darwin_git_ignore_policy_unavailable")
    for name in (".ignore", ".rgignore"):
        try:
            policy_fd = regular_fd(fd, name)
        except FileNotFoundError:
            continue
        try:
            data = read_at_most(policy_fd, 65537)
        finally:
            os.close(policy_fd)
        if len(data) > 65536:
            raise unavailable("darwin_ignore_policy_too_large")
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeError:
            raise unavailable("darwin_ignore_policy_encoding") from None
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if line != line.strip() or any(c in line for c in "!\\[]{}"):
                raise unavailable("darwin_ignore_policy_unavailable")
            rules.append((prefix, line))
    return rules


@contextmanager
def listing_directory(
    root_fd: int, parts: tuple[str, ...], recursive: bool
) -> Iterator[int]:
    if recursive:
        for depth in range(len(parts)):
            with directory_at(root_fd, parts[:depth]) as ancestor:
                if _local_excludes(ancestor, ""):
                    raise unavailable("darwin_ancestor_ignore_policy_unavailable")
    with directory_at(root_fd, parts) as directory:
        yield directory


def _excluded(path: str, is_dir: bool, rules: list[tuple[str, str]]) -> bool:
    for prefix, pattern in rules:
        relative = path[len(prefix) :]
        if pattern.endswith("/") and not is_dir:
            continue
        pattern = pattern.rstrip("/")
        if pattern.startswith("/"):
            matched = _full_match(relative, pattern[1:])
        else:
            matched = glob_matches(relative, pattern)
        if matched:
            return True
    return False


class Listing:
    """One bounded walk; scandir receives only opened directory descriptors."""

    def __init__(self, request: ListRequest) -> None:
        require_positive(request.max_entries, MAX_VISITED)
        require_positive(request.max_visited, MAX_VISITED)
        if request.glob is not None and len(request.glob) > 4096:
            raise unavailable("glob_budget_exceeded")
        self.request = request
        self.deadline = deadline_after(request.timeout_s)
        self.visited = 0
        self.truncated = False
        self.entries: list[FileEntry] = []

    def exhausted(self) -> bool:
        if (
            self.visited >= self.request.max_visited
            or time.monotonic() >= self.deadline
        ):
            self.truncated = True
        return self.truncated

    def walk(
        self,
        fd: int,
        prefix: str = "",
        rules: list[tuple[str, str]] | None = None,
        *,
        depth: int = 0,
    ) -> None:
        if depth >= 128:
            raise BudgetExceeded("traversal_depth", capability("traversal_depth"))
        recursive = self.request.glob is not None
        rules = (rules or []) + (_local_excludes(fd, prefix) if recursive else [])
        if len(rules) > 1000:
            raise unavailable("darwin_ignore_rule_budget")
        with os.scandir(fd) as children:
            for child in children:
                if self.exhausted():
                    break
                self.visited += 1
                name = child.name
                if name == ".git" or (
                    not self.request.include_hidden and name.startswith(".")
                ):
                    continue
                path = prefix + name
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                is_dir = stat.S_ISDIR(info.st_mode)
                if recursive and _excluded(path, is_dir, rules):
                    continue
                child_fd = os.open(name, READ_FLAGS, dir_fd=fd)
                try:
                    info = os.fstat(child_fd)
                    if stat.S_ISDIR(info.st_mode):
                        if recursive:
                            self.walk(child_fd, path + "/", rules, depth=depth + 1)
                        else:
                            self.add(path, "directory", info)
                    elif stat.S_ISREG(info.st_mode):
                        if not recursive or glob_matches(path, self.request.glob or ""):
                            self.add(path, "file", info)
                    else:
                        raise unsafe("special_file_unsupported")
                finally:
                    os.close(child_fd)

    def add(self, path: str, kind: str, info: os.stat_result) -> None:
        # Retain at most the visit budget, then sort before applying result cap.
        self.entries.append(
            FileEntry(
                path,
                "directory" if kind == "directory" else "file",
                info.st_size if kind == "file" else None,
                info.st_mtime_ns,
            )
        )

    def result(self, base: tuple[str, ...]) -> FileListing:
        if self.request.glob is None:
            self.entries.sort(
                key=lambda e: (e.kind != "directory", e.relative_path.lower())
            )
        else:
            self.entries.sort(key=lambda e: (-(e.modified_ns or 0), e.relative_path))
        prefix = "/".join(base) + "/" if base else ""
        selected = [
            FileEntry(prefix + e.relative_path, e.kind, e.size_bytes, e.modified_ns)
            for e in self.entries[: self.request.max_entries]
        ]
        return FileListing(
            selected, self.truncated or len(self.entries) > self.request.max_entries
        )

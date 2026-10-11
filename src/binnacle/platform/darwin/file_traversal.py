"""Descriptor traversal for the opened-object Files subset.

No path below a grant is reopened by absolute name. Captured directories retain
identity across rename; this is not continuous pathname containment or a hostile
same-UID sandbox. Recursive ignore rules come only from inside the grant;
.gitignore/.ignore/.rgignore apply whether or not the grant is a git
repository (as rg --no-require-git). Global and above-grant policies are
never read. Git metadata is never opened. ACLs/xattrs are not preserved on write.
"""

from __future__ import annotations

import errno
import fnmatch
import math
import os
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathspec import GitIgnoreSpec

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
MAX_WALK_DEPTH = 48
DIRECTORY_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY
)
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY


def capability(code: str, *, unavailable: bool = False) -> Capability:
    return Capability(
        CapabilityState.UNAVAILABLE if unavailable else CapabilityState.LIMITED,
        code,
        "opened-object files; ignore files above grant and global policies excluded; "
        "no full macOS parity",
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
    fd = os.open(".", DIRECTORY_FLAGS, dir_fd=root_fd)
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
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
        raise unsafe("path_is_directory")
    if not stat.S_ISREG(info.st_mode):
        raise unsafe("special_file_unsupported")
    return checked_open(parent, name, flags, info)


def checked_open(parent: int, name: str, flags: int, info: os.stat_result) -> int:
    """Bind a no-follow open to the exact entry used for policy decisions."""
    fd = os.open(name, flags, dir_fd=parent)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode)) != (
            info.st_dev,
            info.st_ino,
            stat.S_IFMT(info.st_mode),
        ):
            raise unsafe("entry_changed")
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


# Ordered by precedence first, directory depth second (rgignore > ignore > git).
IgnoreRules = list[tuple[int, str, "GitIgnoreSpec"]]


def _local_rules(
    fd: int, prefix: str, rules: IgnoreRules, in_git: bool
) -> tuple[IgnoreRules, bool]:
    # Lazy import: Linux runtime has no pathspec dependency. Darwin construction
    # is separately gated; importing this module remains portable.
    from pathspec import GitIgnoreSpec

    try:
        marker = os.stat(".git", dir_fd=fd, follow_symlinks=False)
        in_git = in_git or stat.S_ISDIR(marker.st_mode) or stat.S_ISREG(marker.st_mode)
    except FileNotFoundError:
        pass
    local = list(rules)
    for priority, name in enumerate((".gitignore", ".ignore", ".rgignore")):
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue  # Never follow a policy symlink or open a special file.
        policy_fd = checked_open(fd, name, READ_FLAGS, info)
        try:
            data = read_at_most(policy_fd, 65537)
        finally:
            os.close(policy_fd)
        if len(data) > 65536:
            raise unavailable("darwin_ignore_policy_too_large")
        try:
            policy = GitIgnoreSpec.from_lines(data.decode("utf-8").splitlines())
        except (UnicodeError, ValueError):
            raise unavailable("darwin_ignore_policy_invalid") from None
        local.append((priority, prefix, policy))
    if sum(len(spec.patterns) for _, _, spec in local) > 1000:
        raise unavailable("darwin_ignore_rule_budget")
    return sorted(local, key=lambda rule: rule[0]), in_git


@contextmanager
def listing_directory(
    root_fd: int, parts: tuple[str, ...], listing: Listing
) -> Iterator[int]:
    # Discover requested-path ancestors through the same descriptor chain. No
    # policy outside the grant is consulted, even when rg would discover it.
    fd = os.open(".", DIRECTORY_FLAGS, dir_fd=root_fd)
    try:
        for depth, part in enumerate(parts):
            if listing.request.glob is not None:
                prefix = "/".join(parts[:depth]) + "/" if depth else ""
                listing.rules, listing.in_git = _local_rules(
                    fd, prefix, listing.rules, listing.in_git
                )
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        listing.base = "/".join(parts) + "/" if parts else ""
        yield fd
    finally:
        os.close(fd)


def _ignore_decision(path: str, is_dir: bool, rules: IgnoreRules) -> bool | None:
    from pathspec import GitIgnoreSpec

    excluded = None
    for _, prefix, policy in rules:
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix) :] + ("/" if is_dir else "")
        decision = policy.check_file(relative)
        if decision.index is not None:
            match = policy.patterns[decision.index].match_file(relative)
            if (
                match
                and any(match.match.groupdict().values())
                and match.match.end() < len(relative)
            ):
                # GitIgnoreSpec also matches descendants of directory patterns.
                # The walker already decided those ancestors (or the caller
                # explicitly named one). rg applies only the current entry here.
                # Keep library patterns/precedence, dropping inherited directory
                # matches identified by their regex directory-marker groups.
                direct = []
                for pattern in policy.patterns:
                    hit = pattern.match_file(relative)
                    if hit and not (
                        any(hit.match.groupdict().values())
                        and hit.match.end() < len(relative)
                    ):
                        direct.append(pattern)
                decision = GitIgnoreSpec(direct).check_file(relative)
        if decision.include is not None:
            excluded = decision.include
    return excluded


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
        self.base = ""
        self.rules: IgnoreRules = []
        self.in_git = False
        # Installed by the adapter, which holds the root descriptor.
        self.resolve_link: Callable[[str], os.stat_result | None] = lambda _: None

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
        rules: IgnoreRules | None = None,
        *,
        depth: int = 0,
        in_git: bool | None = None,
    ) -> None:
        if depth >= MAX_WALK_DEPTH:
            raise BudgetExceeded("traversal_depth", capability("traversal_depth"))
        recursive = self.request.glob is not None
        rules = self.rules if rules is None else rules
        in_git = self.in_git if in_git is None else in_git
        if recursive:
            rules, in_git = _local_rules(fd, self.base + prefix, rules, in_git)
        with os.scandir(fd) as children:
            for child in children:
                if self.exhausted():
                    break
                self.visited += 1
                name = child.name
                if name == ".git":
                    continue
                path = prefix + name
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError as exc:
                    if exc.errno not in (errno.ENOENT, errno.EACCES, errno.EPERM):
                        raise
                    continue  # No metadata can be safely claimed for this entry.
                is_dir = stat.S_ISDIR(info.st_mode)
                if (
                    recursive
                    and not is_dir
                    and not glob_matches(path, self.request.glob or "")
                ):
                    continue
                decision = (
                    _ignore_decision(self.base + path, is_dir, rules)
                    if recursive
                    else None
                )
                if decision is True or (
                    not self.request.include_hidden
                    and name.startswith(".")
                    and decision is not False
                ):
                    continue
                if stat.S_ISLNK(info.st_mode):
                    # Recursive (glob) listings omit symlinks. A one-level listing
                    # reports an in-root target by its kind; others are omitted.
                    target = None if recursive else self.resolve_link(name)
                    self.add(path, "other", info, target)
                    continue
                kind: Literal["file", "directory", "other"] = (
                    "directory"
                    if is_dir
                    else "file"
                    if stat.S_ISREG(info.st_mode)
                    else "other"
                )
                if kind == "other":
                    self.add(path, kind, info)
                    continue  # Never open symlinks, sockets, devices or FIFOs.
                try:
                    child_fd = checked_open(
                        fd, name, DIRECTORY_FLAGS if is_dir else READ_FLAGS, info
                    )
                except UnsafePath:
                    continue  # Entry swapped since fstatat; no authority for it.
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        self.add(path, kind, info)
                        continue
                    if exc.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
                        continue
                    raise
                try:
                    if is_dir:
                        if recursive:
                            self.walk(
                                child_fd,
                                path + "/",
                                rules,
                                depth=depth + 1,
                                in_git=in_git,
                            )
                        else:
                            self.add(path, kind, info)
                    else:
                        self.add(path, kind, info)
                except PermissionError:
                    self.add(path, kind, info)
                finally:
                    os.close(child_fd)

    def add(
        self,
        path: str,
        kind: Literal["file", "directory", "other"],
        info: os.stat_result,
        target: os.stat_result | None = None,
    ) -> None:
        if self.request.glob is not None and (
            kind != "file" or not glob_matches(path, self.request.glob)
        ):
            return
        # Retain at most the visit budget, then sort before applying result cap.
        resolved: Literal["file", "directory"] | None = None
        if target is not None:
            resolved = "directory" if stat.S_ISDIR(target.st_mode) else "file"
            info = target
        self.entries.append(
            FileEntry(
                path,
                kind,
                info.st_size if "file" in (kind, resolved) else None,
                info.st_mtime_ns,
                resolved,
            )
        )

    def result(self, base: tuple[str, ...]) -> FileListing:
        if self.request.glob is None:
            self.entries.sort(
                key=lambda e: (
                    (e.target_kind or e.kind) != "directory",
                    e.relative_path.lower(),
                )
            )
        else:
            self.entries.sort(key=lambda e: (-(e.modified_ns or 0), e.relative_path))
        prefix = "/".join(base) + "/" if base else ""
        selected = [
            FileEntry(
                prefix + e.relative_path,
                e.kind,
                e.size_bytes,
                e.modified_ns,
                e.target_kind,
            )
            for e in self.entries[: self.request.max_entries]
        ]
        return FileListing(
            selected, self.truncated or len(self.entries) > self.request.max_entries
        )

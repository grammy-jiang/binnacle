"""Opened-root Darwin Files adapter, awaiting independent review and B0 wiring.

Atomic replacement preserves permission bits (0777 only), but changes inode and does not preserve
ownership, xattrs or ACLs. Hardlinks keep old content. Digest checking observes
conflicts; it is not hostile-writer CAS. Failed writes may leave created parents.
No power-loss durability, continuous containment or full parity is claimed.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from binnacle.platform.contracts.capability_contracts import UnsafePath
from binnacle.platform.contracts.file_access_contracts import (
    FileListing,
    FileMetadata,
    ListRequest,
    OpenedFile,
    RootGrant,
    WriteReceipt,
)
from binnacle.platform.darwin.file_traversal import (
    DIRECTORY_FLAGS,
    MAX_BYTES,
    READ_FLAGS,
    Listing,
    directory_at,
    listing_directory,
    native_errors,
    read_at_most,
    regular_fd,
    require_positive,
    unsafe,
    validate_relative_path,
)

MAX_LINK_HOPS = 40


def absolute_in_root(text: str, root: str) -> list[str] | None:
    """Lexical gate for absolute link text (r6 X2; Linux list_files.py twin).

    The components of text below root, or None: any ``..`` component, or text
    outside root. Only empty and ``.`` components are dropped; the filesystem
    is never consulted, so text that steps out and back is no existence oracle.
    A trailing ``/`` or ``/.`` keeps one empty marker, so the walk requires a
    directory there, as it does for relative text (RX2-F2).
    """
    raw = text.split("/")
    parts = [part for part in raw if part not in ("", ".")]
    base = [part for part in root.split("/") if part]
    if ".." in parts or parts[: len(base)] != base:
        return None
    below = parts[len(base) :]
    return [*below, ""] if raw[-1] in ("", ".") else below


def link_target_info(
    root_fd: int,
    directory: tuple[str, ...],
    name: str,
    root_path: str | None,
    aliases: Sequence[str] = (),
) -> os.stat_result | None:
    """Stat a symlink's target only if it resolves inside the opened root.

    Every component is examined with no-follow descriptor calls starting at the
    root descriptor. Absolute link text is walked from the root descriptor only
    when ``absolute_in_root`` accepts it for ``root_path``, the granted root,
    or for one of ``aliases`` (configured alias strings of that root whose
    identity was re-checked for this call; LP, SD-74);
    absolute intermediate links, ``..`` above the root, dangling links, loops
    and non-file/non-directory targets yield None; the root is never widened
    and no path string is followed.
    """
    stack = list(directory)
    try:
        with directory_at(root_fd, directory) as start:
            text = os.readlink(name, dir_fd=start)
        pending = text.split("/")
        if pending[0] == "":
            below = None
            for prefix in () if root_path is None else (root_path, *aliases):
                below = absolute_in_root(text, prefix)
                if below is not None:
                    break
            if below is None:
                return None  # '..', another root or an unknown root path.
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
            with directory_at(root_fd, tuple(stack)) as parent:
                info = os.stat(part, dir_fd=parent, follow_symlinks=False)
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
            with directory_at(root_fd, tuple(stack)) as final:
                info = os.fstat(final)
        if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
            return info
    except (OSError, UnsafePath):
        return None
    return None


class _RootGrant:
    def __init__(
        self, fd: int, generation: str, path: str, aliases: tuple[str, ...] = ()
    ) -> None:
        self.fd = fd
        self._generation = generation
        self.path = path  # The granted canonical root, for absolute link text.
        self.aliases = aliases  # Configured alias strings, realpath == path.
        self.lock = RLock()

    def live_aliases(self, root_fd: int) -> tuple[str, ...]:
        """The aliases that still name this root: one stat each, per call.

        An alias retargeted after the grant no longer matches the opened
        root's (st_dev, st_ino), so its prefix is ignored for this call.
        """
        if not self.aliases:
            return ()
        opened = os.fstat(root_fd)
        live = []
        for alias in self.aliases:
            try:
                info = os.stat(alias)
            except OSError:
                continue
            if (info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino):
                live.append(alias)
        return tuple(live)

    @property
    def generation(self) -> str:
        return self._generation

    def close(self) -> None:
        with self.lock:
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1


class _OpenedFile:
    def __init__(self, fd: int, display_path: str) -> None:
        self.fd = fd
        self._display_path = display_path
        self.lock = RLock()

    @property
    def display_path(self) -> str:
        return self._display_path

    def _check(self) -> None:
        if self.fd < 0:
            raise unsafe("opened_file_closed")

    def metadata(self) -> FileMetadata:
        with self.lock, native_errors():
            self._check()
            info = os.fstat(self.fd)
            return FileMetadata(
                info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns
            )

    def read(self, max_bytes: int) -> bytes:
        require_positive(max_bytes, MAX_BYTES + 1)
        with self.lock, native_errors():
            self._check()
            return read_at_most(self.fd, max_bytes)

    def close(self) -> None:
        with self.lock:
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1


def _destination(parent: int, name: str, expected: str | None) -> os.stat_result | None:
    # Checking actual write access matters: rename alone would bypass a read-only
    # destination's permissions. No O_TRUNC; this descriptor cannot mutate bytes.
    flags = (os.O_RDWR if expected is not None else os.O_WRONLY) | (
        os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
    )
    try:
        fd = regular_fd(parent, name, flags)
    except FileNotFoundError:
        if expected is not None:
            raise unsafe("edit_conflict") from None
        return None
    try:
        info = os.fstat(fd)
        if expected is not None:
            require_positive(max(1, info.st_size), MAX_BYTES)
            data = read_at_most(fd, MAX_BYTES + 1)
            if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
                raise unsafe("edit_conflict")
        return info
    finally:
        os.close(fd)


def _replace(parent: int, name: str, data: bytes, expected: str | None) -> WriteReceipt:
    previous = _destination(parent, name, expected)
    temporary = ".binnacle-write-" + secrets.token_hex(16)
    fd = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC
        | os.O_NOCTTY,
        (previous.st_mode & 0o0777) if previous is not None else 0o666,
        dir_fd=parent,
    )
    replaced = False
    try:
        remaining = memoryview(data)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise unsafe("short_write")
            remaining = remaining[count:]
        # Revalidate immediately before replace. This detects observed conflicts,
        # not a CAS against concurrent hostile writers between this and rename.
        current = _destination(parent, name, expected)
        if previous is None:
            if current is not None:
                raise unsafe("write_conflict")
        elif current is None or (
            current.st_dev,
            current.st_ino,
            current.st_mtime_ns,
            current.st_size,
        ) != (previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_size):
            raise unsafe("write_conflict")
        if current is not None:
            os.fchmod(fd, current.st_mode & 0o0777)
        os.fsync(fd)
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        replaced = True
        return WriteReceipt(
            len(data),
            current.st_size if current else None,
            "overwritten" if current else "created",
        )
    finally:
        os.close(fd)
        if not replaced:
            os.unlink(temporary, dir_fd=parent)


class DarwinFileAccess:
    def __init__(self) -> None:
        self._lock = RLock()
        self._closed = False
        self._grants: set[_RootGrant] = set()
        self._files: set[_OpenedFile] = set()

    def _check(self) -> None:
        if self._closed:
            raise unsafe("file_access_closed")

    def grant(
        self, root: Path, *, generation: str, aliases: Sequence[Path] = ()
    ) -> RootGrant:
        if not root.is_absolute() or not generation:
            raise unsafe("invalid_root_grant")
        parts = validate_relative_path(str(root)[1:])
        # Only configured alias strings, never inferred: absolute, no '..',
        # and realpath equal to the canonical root now (LP, SD-74).
        accepted = tuple(
            str(alias)
            for alias in aliases
            if alias.is_absolute()
            and ".." not in alias.parts
            and alias != root
            and os.path.realpath(alias) == str(root)
        )
        with self._lock, native_errors():
            self._check()
            # Composition supplies canonical roots; even root capture refuses
            # symlink ancestors instead of resolving aliases at access time.
            fd = os.open("/", DIRECTORY_FLAGS)
            try:
                with directory_at(fd, parts) as directory:
                    grant = _RootGrant(
                        os.dup(directory), generation, str(root), accepted
                    )
            finally:
                os.close(fd)
            self._grants.add(grant)
            return grant

    @contextmanager
    def _root(self, grant: RootGrant) -> Iterator[int]:
        # Capture per-call ownership; slow traversal never holds the registry lock.
        # Already admitted calls retain their duplicate if the grant is closed.
        with native_errors():
            with self._lock:
                self._check()
                if not isinstance(grant, _RootGrant) or grant not in self._grants:
                    raise unsafe("foreign_root_grant")
                with grant.lock:
                    if grant.fd < 0:
                        raise unsafe("root_grant_closed")
                    fd = os.dup(grant.fd)
            try:
                yield fd
            finally:
                os.close(fd)

    def open_read(self, grant: RootGrant, relative_path: str) -> OpenedFile:
        parts = validate_relative_path(relative_path)
        if not parts:
            raise unsafe("path_is_directory")
        with self._root(grant) as root, directory_at(root, parts[:-1]) as parent:
            fd = regular_fd(parent, parts[-1], READ_FLAGS)
            opened = _OpenedFile(fd, "/".join(parts))
            with self._lock:
                if self._closed:
                    opened.close()
                    self._check()
                self._files = {file for file in self._files if file.fd >= 0}
                self._files.add(opened)
                return opened

    def list_entries(self, grant: RootGrant, request: ListRequest) -> FileListing:
        parts = validate_relative_path(request.relative_path)
        listing = Listing(request)
        with (
            self._root(grant) as root,
            listing_directory(root, parts, listing) as directory,
        ):
            top: str | None = None
            aliases: tuple[str, ...] = ()
            if isinstance(grant, _RootGrant):
                top, aliases = grant.path, grant.live_aliases(root)
            listing.resolve_link = lambda name: link_target_info(
                root, parts, name, top, aliases
            )
            listing.walk(directory)
        return listing.result(parts)

    def nearby_hint(
        self, grant: RootGrant, relative_path: str, *, max_entries: int
    ) -> Sequence[str]:
        # relative_path denotes the failed target, not a license to probe upward.
        parts = validate_relative_path(relative_path)
        parent = "/".join(parts[:-1])
        listing = self.list_entries(
            grant, ListRequest(parent, None, False, max_entries, 1000, 1.0)
        )
        return [entry.relative_path for entry in listing.entries]

    def write_bytes(
        self,
        grant: RootGrant,
        relative_path: str,
        data: bytes,
        *,
        create_parents: bool = False,
        max_new_parents: int = 32,
        expected_sha256: str | None = None,
    ) -> WriteReceipt:
        parts = validate_relative_path(relative_path)
        if not parts:
            raise unsafe("path_is_directory")
        require_positive(max(1, len(data)), MAX_BYTES)
        if not 0 <= max_new_parents <= 128:
            raise unsafe("invalid_parent_budget")
        with (
            self._root(grant) as root,
            directory_at(
                root, parts[:-1], create=create_parents, max_new=max_new_parents
            ) as parent,
        ):
            return _replace(parent, parts[-1], data, expected_sha256)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for opened in self._files:
                opened.close()
            for grant in self._grants:
                grant.close()
            self._files.clear()
            self._grants.clear()

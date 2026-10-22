"""P2.5: descriptor-relative workspace authority and disk snapshots (POSIX).

Only an explicit host allowlist grants read authority. Untrusted paths do not
resolve through symlinks; Git markers identify roots, never grant new roots.
This is data-access protection, *not* provider filesystem/OS confinement.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_SOURCE_BYTES = 2 * 1024 * 1024
_PROJECT_MARKERS = ("pyrightconfig.json", "pyproject.toml")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class WorkspaceAccessError(ValueError):
    """Invalid or unauthorized workspace operation (no path disclosure)."""


class WorkspaceStaleError(WorkspaceAccessError):
    """File content or identity changed during a request."""


def _components(path: str, *, absolute: bool) -> tuple[str, ...]:
    if not isinstance(path, str) or "\x00" in path or "\\" in path:
        raise WorkspaceAccessError("invalid_workspace_path")
    if path.startswith("/") != absolute or "//" in path:
        raise WorkspaceAccessError("invalid_workspace_path")
    parts = path.split("/")
    if absolute:
        parts = parts[1:]
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise WorkspaceAccessError("invalid_workspace_path")
    return tuple(parts)


def _open_directory(root: Path, directories: tuple[str, ...] = ()) -> int:
    """Walk from an operator-authorized root, never follow a child symlink."""
    try:
        handle = os.open(root, _DIR_FLAGS)
        for part in directories:
            try:
                next_handle = os.open(part, _DIR_FLAGS, dir_fd=handle)
            finally:
                os.close(handle)
            handle = next_handle
        return handle
    except (OSError, ValueError) as exc:
        raise WorkspaceAccessError("workspace_directory_unavailable") from exc


def _marker(directory: int, name: str, *, git: bool = False) -> bool:
    try:
        record = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise WorkspaceAccessError("workspace_marker_unavailable") from exc
    if stat.S_ISLNK(record.st_mode):
        raise WorkspaceAccessError("workspace_marker_symlink")
    return stat.S_ISREG(record.st_mode) or (git and stat.S_ISDIR(record.st_mode))


@dataclass(frozen=True)
class DiskSnapshot:
    relative_path: str
    uri: str
    contents: str
    sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


class AuthorizedWorkspace:
    """One selected Git/marker/parent workspace, bound to an allowed root.

    Root discovery does not execute Git nor read project configuration. The
    explicit fallback is only for standalone sources authorized by the host.
    """

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        requested_file: str | Path,
        *,
        allow_parent_fallback: bool = False,
        max_file_bytes: int = MAX_SOURCE_BYTES,
        allowed_suffixes: tuple[str, ...] = (".py", ".pyi"),
    ) -> None:
        if (
            type(max_file_bytes) is not int
            or not 0 < max_file_bytes <= MAX_SOURCE_BYTES
        ):
            raise ValueError("invalid_workspace_file_ceiling")
        if (
            not isinstance(allowed_suffixes, tuple)
            or not allowed_suffixes
            or any(
                not isinstance(ext, str)
                or not ext.startswith(".")
                or not ext[1:].isalnum()
                for ext in allowed_suffixes
            )
        ):
            raise ValueError("invalid_source_file_extensions")
        self.allowed_suffixes = frozenset(allowed_suffixes)
        self.max_file_bytes = max_file_bytes
        target_parts = _components(str(requested_file), absolute=True)
        selected: tuple[Path, tuple[str, ...]] | None = None
        longest_prefix = -1
        for allowed in allowed_roots:
            # Only host-declared root aliases may be canonicalized (e.g.
            # macOS /tmp -> /private/tmp). Never resolve symlinks in the
            # untrusted suffix: every directory/file beneath root is checked
            # with no-follow directory descriptors.
            configured = Path(allowed).expanduser()
            try:
                root = configured.resolve(strict=True)
            except OSError as exc:
                raise WorkspaceAccessError(
                    "configured_workspace_root_unavailable"
                ) from exc
            if not root.is_dir():
                raise WorkspaceAccessError("configured_workspace_root_not_directory")
            for authorized_prefix in (configured, root):
                parts = _components(str(authorized_prefix), absolute=True)
                if target_parts[: len(parts)] != parts or len(target_parts) <= len(
                    parts
                ):
                    continue
                if len(parts) > longest_prefix:
                    selected = root, target_parts[len(parts) :]
                    longest_prefix = len(parts)
        if selected is None:
            raise WorkspaceAccessError("source_outside_allowed_roots")
        authority_root, subpath = selected
        # Prove every parent can be traversed using O_NOFOLLOW. For nested Git
        # worktrees, a `.git` file is just as authoritative as a directory.
        parent_handle = _open_directory(authority_root, subpath[:-1])
        os.close(parent_handle)
        found_git: tuple[str, ...] | None = None
        found_marker: tuple[str, ...] | None = None
        for count in range(len(subpath) - 1, -1, -1):
            prefix = subpath[:count]
            directory = _open_directory(authority_root, prefix)
            try:
                if _marker(directory, ".git", git=True):
                    found_git = prefix
                    break
                if found_marker is None and any(
                    _marker(directory, item) for item in _PROJECT_MARKERS
                ):
                    found_marker = prefix
            finally:
                os.close(directory)
        relative_root = found_git if found_git is not None else found_marker
        if relative_root is None:
            if not allow_parent_fallback:
                raise WorkspaceAccessError("workspace_root_marker_required")
            relative_root = subpath[:-1]
        self.workspace_root = authority_root.joinpath(*relative_root)
        self.source_file = "/".join(subpath[len(relative_root) :])
        self._authority_root = authority_root
        self._workspace_parts = relative_root
        root_handle = _open_directory(authority_root, relative_root)
        try:
            root_stat = os.fstat(root_handle)
            self._root_identity = root_stat.st_dev, root_stat.st_ino
        finally:
            os.close(root_handle)
        self.snapshot(self.source_file)  # reject missing/nonregular/unsafe targets now

    def _workspace_fd(self) -> int:
        handle = _open_directory(self._authority_root, self._workspace_parts)
        actual = os.fstat(handle)
        if (actual.st_dev, actual.st_ino) != self._root_identity:
            os.close(handle)
            raise WorkspaceStaleError("workspace_root_replaced")
        return handle

    def snapshot(self, relative_file: str) -> DiskSnapshot:
        parts = _components(relative_file, absolute=False)
        if Path(parts[-1]).suffix not in self.allowed_suffixes:
            raise WorkspaceAccessError("unsupported_source_extension")
        handle = self._workspace_fd()
        try:
            for directory in parts[:-1]:
                try:
                    child = os.open(directory, _DIR_FLAGS, dir_fd=handle)
                except OSError as exc:
                    raise WorkspaceAccessError("source_directory_unauthorized") from exc
                os.close(handle)
                handle = child
            try:
                file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=handle)
            except OSError as exc:
                raise WorkspaceAccessError("source_not_authorized") from exc
            try:
                before = os.fstat(file_fd)
                if not stat.S_ISREG(before.st_mode):
                    raise WorkspaceAccessError("source_not_regular_file")
                if before.st_size > self.max_file_bytes:
                    raise WorkspaceAccessError("source_too_large")
                chunks = []
                remaining = self.max_file_bytes + 1
                try:
                    while remaining:
                        block = os.read(file_fd, min(64 * 1024, remaining))
                        if not block:
                            break
                        chunks.append(block)
                        remaining -= len(block)
                except OSError as exc:
                    raise WorkspaceAccessError("source_read_unavailable") from exc
                raw = b"".join(chunks)
                after = os.fstat(file_fd)

                def identity(st):
                    return (
                        st.st_dev,
                        st.st_ino,
                        st.st_size,
                        st.st_mtime_ns,
                        st.st_ctime_ns,
                    )

                if identity(before) != identity(after):
                    raise WorkspaceStaleError("source_modified_during_read")
                if len(raw) > self.max_file_bytes:
                    raise WorkspaceAccessError("source_too_large")
                # Prevent rename/unlink/replacement between fd open and result.
                try:
                    current = os.stat(parts[-1], dir_fd=handle, follow_symlinks=False)
                except OSError as exc:
                    raise WorkspaceStaleError("source_replaced_during_read") from exc
                if not stat.S_ISREG(current.st_mode) or identity(current) != identity(
                    after
                ):
                    raise WorkspaceStaleError("source_replaced_during_read")
                # Re-walk the path from the anchored workspace root. An old
                # parent dirfd alone could reference a directory moved out of
                # the workspace while its file descriptor remains valid.
                confirmed = self._workspace_fd()
                try:
                    for directory in parts[:-1]:
                        try:
                            child = os.open(directory, _DIR_FLAGS, dir_fd=confirmed)
                        except OSError as exc:
                            raise WorkspaceStaleError("source_parent_replaced") from exc
                        os.close(confirmed)
                        confirmed = child
                    actual_parent = os.fstat(confirmed)
                    saved_parent = os.fstat(handle)
                    if (actual_parent.st_dev, actual_parent.st_ino) != (
                        saved_parent.st_dev,
                        saved_parent.st_ino,
                    ):
                        raise WorkspaceStaleError("source_parent_replaced")
                    latest = os.stat(parts[-1], dir_fd=confirmed, follow_symlinks=False)
                    if not stat.S_ISREG(latest.st_mode) or identity(latest) != identity(
                        after
                    ):
                        raise WorkspaceStaleError("source_replaced_during_read")
                except FileNotFoundError as exc:
                    raise WorkspaceStaleError("source_parent_replaced") from exc
                finally:
                    os.close(confirmed)
                if b"\x00" in raw:
                    raise WorkspaceAccessError("binary_source_unsupported")
                try:
                    contents = raw.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise WorkspaceAccessError("source_not_utf8") from exc
                name = "/".join(parts)
                return DiskSnapshot(
                    name,
                    self.workspace_root.joinpath(*parts).as_uri(),
                    contents,
                    hashlib.sha256(raw).hexdigest(),
                    len(raw),
                    after.st_dev,
                    after.st_ino,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
            finally:
                os.close(file_fd)
        finally:
            os.close(handle)

    def assert_fresh(self, snapshot: DiskSnapshot) -> None:
        try:
            current = self.snapshot(snapshot.relative_path)
        except WorkspaceAccessError as exc:
            raise WorkspaceStaleError("source_no_longer_authorized") from exc
        if current.sha256 != snapshot.sha256 or (
            current.device,
            current.inode,
            current.mtime_ns,
            current.ctime_ns,
        ) != (snapshot.device, snapshot.inode, snapshot.mtime_ns, snapshot.ctime_ns):
            raise WorkspaceStaleError("source_changed_during_request")

    def snapshot_uri(self, uri: str) -> DiskSnapshot:
        if not isinstance(uri, str):
            raise WorkspaceAccessError("invalid_result_uri")
        try:
            parsed = urlsplit(uri)
            if (
                parsed.scheme != "file"
                or parsed.netloc not in ("", "localhost")
                or parsed.query
                or parsed.fragment
            ):
                raise WorkspaceAccessError("invalid_result_uri")
            path = unquote(parsed.path, encoding="utf-8", errors="strict")
            candidate = _components(path, absolute=True)
        except (ValueError, UnicodeDecodeError) as exc:
            raise WorkspaceAccessError("invalid_result_uri") from exc
        root_parts = _components(str(self.workspace_root), absolute=True)
        if candidate[: len(root_parts)] != root_parts or len(candidate) <= len(
            root_parts
        ):
            raise WorkspaceAccessError("result_outside_workspace")
        return self.snapshot("/".join(candidate[len(root_parts) :]))

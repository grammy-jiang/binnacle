"""Descriptor-relative, mount-aware Linux workspace filesystem boundary."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from binnacle.domain.workspace import (
    MAX_MUTATION_BYTES,
    MAX_PATH_DEPTH,
    MountIdentity,
    WorkspaceMutationKind,
    WorkspaceObjectIdentity,
    WorkspaceObjectKind,
    WorkspaceRootIdentity,
    canonical_sha256,
    normalize_workspace_path,
    object_version,
    require_content_path_allowed,
    validate_identifier,
    validate_sha256,
)
from binnacle.ports import workspace as workspace_ports
from binnacle.ports.workspace import (
    WorkspaceCreateIntent,
    WorkspaceEffectReceipt,
    WorkspaceEntry,
    WorkspaceInspectRequest,
    WorkspaceListing,
    WorkspaceListRequest,
    WorkspaceReadRequest,
    WorkspaceReadResult,
    WorkspaceWriteIntent,
)

_PRIMITIVE_PROFILE_VERSION = "linux-fdinfo-mount-v1"
_MAX_FDINFO_BYTES = 16 * 1024
_MAX_MOUNTINFO_BYTES = 4 * 1024 * 1024
_DEFAULT_MAX_READ_BYTES = 1024 * 1024
_DEFAULT_MAX_LIST_ENTRIES = 4096
_DEFAULT_MAX_PREFLIGHT_ENTRIES = 100_000
_CLOSED_CREATE_MODES = frozenset({0o644, 0o755})
_CLOSED_REPLACE_MODES = frozenset({0o600, 0o640, 0o644, 0o700, 0o750, 0o755})
_RENAME_NOREPLACE = 1


class WorkspaceFilesystemError(RuntimeError):
    """Workspace containment, identity, or durability could not be proven."""


class WorkspaceEffectNotStarted(
    WorkspaceFilesystemError,
    workspace_ports.WorkspaceEffectNotStarted,
):
    """A verified pre-effect predicate prevented a workspace effect."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class WorkspaceEffectUncertain(
    WorkspaceFilesystemError,
    workspace_ports.WorkspaceEffectUncertain,
):
    """A workspace syscall may have occurred but its durable result is unprovable."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class WorkspaceCapabilityUnavailable(WorkspaceFilesystemError):
    """A deliberately unimplemented Phase 6 filesystem capability was requested."""


class LinuxWorkspace:
    """Own one pinned registered root and its fail-closed Linux filesystem primitives.

    The optional ``proc_root`` argument is a local-test seam. Production composition must
    use the fixed default and must never derive it from a request or ordinary configuration.
    """

    def __init__(
        self,
        *,
        root: Path,
        workspace_id: str,
        profile_sha256: str,
        protected_roots: Sequence[str] = (),
        maximum_mutation_bytes: int = MAX_MUTATION_BYTES,
        maximum_read_bytes: int = _DEFAULT_MAX_READ_BYTES,
        maximum_list_entries: int = _DEFAULT_MAX_LIST_ENTRIES,
        maximum_preflight_entries: int = _DEFAULT_MAX_PREFLIGHT_ENTRIES,
        proc_root: Path = Path("/proc"),
    ) -> None:
        if not root.is_absolute() or root == Path(root.anchor) or ".." in root.parts:
            raise ValueError("workspace root must be a canonical non-root absolute path")
        self._workspace_id = validate_identifier(workspace_id, name="workspace_id")
        self._profile_sha256 = validate_sha256(profile_sha256, name="profile_sha256")
        if not 1 <= maximum_mutation_bytes <= MAX_MUTATION_BYTES:
            raise ValueError("workspace mutation limit is outside the frozen bound")
        if not 1 <= maximum_read_bytes <= _DEFAULT_MAX_READ_BYTES:
            raise ValueError("workspace read limit is outside the frozen bound")
        if not 1 <= maximum_list_entries <= _DEFAULT_MAX_LIST_ENTRIES:
            raise ValueError("workspace listing limit is outside the frozen bound")
        if maximum_preflight_entries < maximum_list_entries:
            raise ValueError("workspace mount preflight limit is too small")
        if not all(
            hasattr(os, name) for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_PATH")
        ):
            raise WorkspaceCapabilityUnavailable("linux_descriptor_primitives_unavailable")
        self._root = root
        self._protected_roots = tuple(normalize_workspace_path(value) for value in protected_roots)
        self._maximum_mutation_bytes = maximum_mutation_bytes
        self._maximum_read_bytes = maximum_read_bytes
        self._maximum_list_entries = maximum_list_entries
        self._maximum_preflight_entries = maximum_preflight_entries
        self._proc_root = proc_root
        self._root_fd: int | None = None
        self._root_identity: WorkspaceRootIdentity | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def initialize(self) -> WorkspaceRootIdentity:
        async with self._lifecycle_lock:
            return await asyncio.to_thread(self._initialize)

    async def close(self) -> None:
        async with self._lifecycle_lock:
            await asyncio.to_thread(self._close)

    async def root_identity(self) -> WorkspaceRootIdentity:
        return await asyncio.to_thread(self._current_root_identity)

    async def verify_scope_no_submounts(self, relative_path: str) -> None:
        normalized = self._normalize_scope(relative_path)
        await asyncio.to_thread(self._verify_scope_no_submounts, normalized)

    async def inspect(self, request: WorkspaceInspectRequest) -> WorkspaceEntry:
        return await asyncio.to_thread(self._inspect, request)

    async def list(self, request: WorkspaceListRequest) -> WorkspaceListing:
        return await asyncio.to_thread(self._list, request)

    async def read(self, request: WorkspaceReadRequest) -> WorkspaceReadResult:
        return await asyncio.to_thread(self._read, request)

    async def create(self, intent: WorkspaceCreateIntent) -> WorkspaceEffectReceipt:
        return await asyncio.to_thread(self._create, intent)

    async def write(self, intent: WorkspaceWriteIntent) -> WorkspaceEffectReceipt:
        return await asyncio.to_thread(self._write, intent)

    async def search(self, request: object) -> NoReturn:
        del request
        raise WorkspaceCapabilityUnavailable("workspace_search_unavailable")

    async def move(self, intent: object) -> NoReturn:
        del intent
        raise WorkspaceCapabilityUnavailable("workspace_move_unavailable")

    async def delete(self, intent: object) -> NoReturn:
        del intent
        raise WorkspaceCapabilityUnavailable("workspace_delete_unavailable")

    def staging_reference(
        self,
        *,
        operation_id: str,
        mutation_kind: WorkspaceMutationKind,
        relative_path: str,
    ) -> str:
        """Return the exact deterministic staging name durable admission can retain."""

        validate_identifier(operation_id, name="operation_id")
        normalized = require_content_path_allowed(
            relative_path,
            additional_roots=self._protected_roots,
        )
        correlation = canonical_sha256(
            {
                "kind": mutation_kind.value,
                "operation_id": operation_id,
                "relative_path": normalized,
                "workspace_id": self._workspace_id,
            }
        )[:40]
        return f".binnacle-{mutation_kind.value}-v1-{correlation}"

    def _initialize(self) -> WorkspaceRootIdentity:
        self._close()
        descriptor: int | None = None
        try:
            descriptor, info, mount = self._open_configured_root()
            mode = stat.S_IMODE(info.st_mode)
            if info.st_uid != os.geteuid() or mode & 0o022:
                raise WorkspaceFilesystemError(
                    "workspace root ownership or write permissions are unsafe"
                )
            identity_digest = canonical_sha256(
                {
                    "device": info.st_dev,
                    "filesystem_type": mount.filesystem_type,
                    "gid": info.st_gid,
                    "inode": info.st_ino,
                    "mode": mode,
                    "mount_identity_sha256": mount.digest_sha256,
                    "profile_sha256": self._profile_sha256,
                    "uid": info.st_uid,
                    "workspace_id": self._workspace_id,
                }
            )
            identity = WorkspaceRootIdentity(
                workspace_id=self._workspace_id,
                profile_sha256=self._profile_sha256,
                identity_sha256=identity_digest,
                mount=mount,
                device=info.st_dev,
                inode=info.st_ino,
                owner_uid=info.st_uid,
                owner_gid=info.st_gid,
                mode=mode,
            )
            self._root_fd = descriptor
            self._root_identity = identity
            descriptor = None
            self._verify_scope_no_submounts("")
            return identity
        except Exception:
            self._close()
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _close(self) -> None:
        descriptor = self._root_fd
        self._root_fd = None
        self._root_identity = None
        if descriptor is not None:
            os.close(descriptor)

    def _current_root_identity(self) -> WorkspaceRootIdentity:
        expected = self._require_initialized()
        descriptor = self._open_root_checked()
        os.close(descriptor)
        return expected

    def _require_initialized(self) -> WorkspaceRootIdentity:
        if self._root_fd is None or self._root_identity is None:
            raise WorkspaceFilesystemError("workspace root is not initialized")
        return self._root_identity

    def _open_configured_root(self) -> tuple[int, os.stat_result, MountIdentity]:
        try:
            path_before = os.stat(self._root, follow_symlinks=False)
            descriptor = os.open(
                self._root,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as exc:
            raise WorkspaceFilesystemError("workspace root cannot be opened safely") from exc
        try:
            info = os.fstat(descriptor)
            path_after = os.stat(self._root, follow_symlinks=False)
            if (
                stat.S_ISLNK(path_before.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or self._stat_key(path_before) != self._stat_key(info)
                or self._stat_key(path_after) != self._stat_key(info)
            ):
                raise WorkspaceFilesystemError("workspace root path does not name the opened root")
            return descriptor, info, self._mount_identity_for_fd(descriptor)
        except Exception:
            os.close(descriptor)
            raise

    def _open_root_checked(self) -> int:
        expected = self._require_initialized()
        pinned_fd = self._root_fd
        if pinned_fd is None:
            raise WorkspaceFilesystemError("workspace root is not initialized")
        pinned = os.fstat(pinned_fd)
        self._verify_fd_mount(pinned_fd, expected.mount)
        if self._stat_key(pinned) != self._root_stat_key(expected):
            raise WorkspaceFilesystemError("pinned workspace root identity changed")
        descriptor, info, mount = self._open_configured_root()
        try:
            if self._stat_key(info) != self._root_stat_key(expected) or mount != expected.mount:
                raise WorkspaceFilesystemError("configured workspace root or mount changed")
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    def _assert_request_bindings(
        self,
        *,
        expected_root_identity_sha256: str,
        expected_mount_identity_sha256: str,
    ) -> WorkspaceRootIdentity:
        expected = self._require_initialized()
        if (
            expected_root_identity_sha256 != expected.identity_sha256
            or expected_mount_identity_sha256 != expected.mount.digest_sha256
        ):
            raise WorkspaceFilesystemError("workspace request identity binding is stale")
        return expected

    def _normalize_scope(self, relative_path: str) -> str:
        if relative_path == "":
            return ""
        return normalize_workspace_path(relative_path)

    def _allowed_path(self, relative_path: str) -> str:
        return require_content_path_allowed(
            relative_path,
            additional_roots=self._protected_roots,
        )

    def _verify_scope_no_submounts(self, relative_path: str) -> None:
        root = self._open_root_checked()
        try:
            if relative_path:
                candidate = self._open_path(root, relative_path, content=False)
            else:
                candidate = os.dup(root)
            try:
                info = os.fstat(candidate)
                self._verify_fd_mount(candidate, self._require_initialized().mount)
                if stat.S_ISDIR(info.st_mode):
                    self._walk_no_submounts(candidate, depth=0, seen={"count": 0})
            finally:
                os.close(candidate)
        finally:
            os.close(root)

    def _walk_no_submounts(
        self,
        directory_fd: int,
        *,
        depth: int,
        seen: dict[str, int],
    ) -> None:
        if depth > MAX_PATH_DEPTH:
            raise WorkspaceFilesystemError("workspace mount preflight depth exceeded")
        for name in self._bounded_directory_names(
            directory_fd,
            maximum=self._maximum_preflight_entries - seen["count"],
            require_complete=True,
        ):
            seen["count"] += 1
            if seen["count"] > self._maximum_preflight_entries:
                raise WorkspaceFilesystemError("workspace mount preflight entry bound exceeded")
            child = self._open_entry_metadata(directory_fd, name)
            try:
                info = os.fstat(child)
                self._verify_fd_mount(child, self._require_initialized().mount)
                if stat.S_ISDIR(info.st_mode):
                    nested = os.open(
                        name,
                        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                    try:
                        self._verify_fd_mount(nested, self._require_initialized().mount)
                        self._walk_no_submounts(nested, depth=depth + 1, seen=seen)
                    finally:
                        os.close(nested)
            finally:
                os.close(child)

    def _inspect(self, request: WorkspaceInspectRequest) -> WorkspaceEntry:
        relative_path = self._normalize_scope(request.relative_path)
        if relative_path:
            self._allowed_path(relative_path)
        self._assert_request_bindings(
            expected_root_identity_sha256=request.expected_root_identity_sha256,
            expected_mount_identity_sha256=request.expected_mount_identity_sha256,
        )
        root = self._open_root_checked()
        try:
            descriptor = (
                self._open_path(root, relative_path, content=False)
                if relative_path
                else os.dup(root)
            )
            try:
                digest: str | None = None
                info = os.fstat(descriptor)
                if stat.S_ISREG(info.st_mode):
                    self._require_single_link(info)
                    if request.include_content_digest and (
                        request.maximum_hash_bytes > 0
                        and info.st_size
                        <= min(
                            request.maximum_hash_bytes,
                            self._maximum_mutation_bytes,
                        )
                    ):
                        os.close(descriptor)
                        descriptor = self._open_path(root, relative_path, content=True)
                        info, digest = self._stable_regular_digest(
                            descriptor,
                            maximum_bytes=request.maximum_hash_bytes,
                        )
                return self._entry(relative_path, descriptor, info=info, content_sha256=digest)
            finally:
                os.close(descriptor)
        finally:
            os.close(root)

    def _list(self, request: WorkspaceListRequest) -> WorkspaceListing:
        relative_path = self._normalize_scope(request.relative_path)
        if relative_path:
            self._allowed_path(relative_path)
        self._assert_request_bindings(
            expected_root_identity_sha256=request.expected_root_identity_sha256,
            expected_mount_identity_sha256=request.expected_mount_identity_sha256,
        )
        if not 1 <= request.maximum_entries <= self._maximum_list_entries:
            raise WorkspaceFilesystemError("workspace listing bound is invalid")
        root = self._open_root_checked()
        try:
            directory = self._open_directory(root, relative_path) if relative_path else os.dup(root)
            try:
                names, truncated = self._listing_names(directory, request.maximum_entries)
                entries: list[WorkspaceEntry] = []
                for name in names:
                    child_path = f"{relative_path}/{name}" if relative_path else name
                    try:
                        self._allowed_path(child_path)
                    except ValueError:
                        truncated = True
                        continue
                    descriptor = self._open_entry_metadata(directory, name)
                    try:
                        info = os.fstat(descriptor)
                        self._verify_fd_mount(descriptor, self._require_initialized().mount)
                        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                            truncated = True
                            continue
                        entries.append(self._entry(child_path, descriptor, info=info))
                    finally:
                        os.close(descriptor)
                return WorkspaceListing(
                    relative_path=relative_path,
                    entries=tuple(entries),
                    truncated=truncated,
                )
            finally:
                os.close(directory)
        finally:
            os.close(root)

    def _read(self, request: WorkspaceReadRequest) -> WorkspaceReadResult:
        relative_path = self._allowed_path(request.relative_path)
        expected = self._assert_request_bindings(
            expected_root_identity_sha256=request.expected_root_identity_sha256,
            expected_mount_identity_sha256=request.expected_mount_identity_sha256,
        )
        permit = request.permit
        request_sha256 = canonical_sha256(
            {
                "maximum_bytes": request.maximum_bytes,
                "offset": request.offset,
                "relative_path": relative_path,
                "session_id": permit.session_id,
                "workspace_id": self._workspace_id,
            }
        )
        if (
            permit.workspace_id != self._workspace_id
            or permit.workspace_profile_sha256 != self._profile_sha256
            or permit.root_identity_sha256 != expected.identity_sha256
            or permit.mount_identity_sha256 != expected.mount.digest_sha256
            or permit.request_sha256 != request_sha256
        ):
            raise WorkspaceFilesystemError("content-read permit is not bound to this workspace")
        if request.offset < 0 or not 1 <= request.maximum_bytes <= self._maximum_read_bytes:
            raise WorkspaceFilesystemError("workspace read range is invalid")
        root = self._open_root_checked()
        try:
            descriptor = self._open_path(root, relative_path, content=True)
            try:
                before = self._require_content_file(os.fstat(descriptor))
                if request.offset > before.st_size:
                    raise WorkspaceFilesystemError("workspace read offset exceeds file size")
                content_digest: str | None = None
                if before.st_size <= self._maximum_mutation_bytes:
                    stable, full = self._stable_regular_bytes(
                        descriptor,
                        maximum_bytes=self._maximum_mutation_bytes,
                    )
                    before = stable
                    content_digest = hashlib.sha256(full).hexdigest()
                    content = full[request.offset : request.offset + request.maximum_bytes]
                else:
                    content = os.pread(descriptor, request.maximum_bytes, request.offset)
                    after = self._require_content_file(os.fstat(descriptor))
                    if self._mutable_stat_key(before) != self._mutable_stat_key(after):
                        raise WorkspaceFilesystemError("workspace file changed during read")
                identity = self._object_identity(
                    relative_path,
                    before,
                    content_sha256=content_digest,
                )
                next_offset_value = request.offset + len(content)
                complete = next_offset_value >= before.st_size
                return WorkspaceReadResult(
                    relative_path=relative_path,
                    content=content,
                    offset=request.offset,
                    next_offset=None if complete else next_offset_value,
                    complete=complete,
                    object_identity=identity,
                    object_version=object_version(identity),
                    content_sha256=content_digest,
                )
            finally:
                os.close(descriptor)
        finally:
            os.close(root)

    def _create(self, intent: WorkspaceCreateIntent) -> WorkspaceEffectReceipt:
        try:
            relative_path = self._allowed_path(intent.relative_path)
            self._assert_request_bindings(
                expected_root_identity_sha256=intent.expected_root_identity_sha256,
                expected_mount_identity_sha256=intent.expected_mount_identity_sha256,
            )
            validate_identifier(intent.operation_id, name="operation_id")
            if intent.mode not in _CLOSED_CREATE_MODES:
                raise WorkspaceEffectNotStarted("workspace_create_mode_unsupported")
            if intent.kind is WorkspaceObjectKind.DIRECTORY:
                if intent.content or intent.mode != 0o755:
                    raise WorkspaceEffectNotStarted("workspace_create_directory_shape_invalid")
            elif intent.kind is not WorkspaceObjectKind.REGULAR_FILE:
                raise WorkspaceEffectNotStarted("workspace_create_kind_unsupported")
            elif len(intent.content) > self._maximum_mutation_bytes:
                raise WorkspaceEffectNotStarted("workspace_create_content_too_large")
        except (WorkspaceEffectNotStarted, WorkspaceEffectUncertain):
            raise
        except Exception as exc:
            raise WorkspaceEffectNotStarted("workspace_create_precondition_failed") from exc
        if intent.kind is WorkspaceObjectKind.DIRECTORY:
            return self._create_directory(intent, relative_path)
        return self._create_file(intent, relative_path)

    def _create_directory(
        self,
        intent: WorkspaceCreateIntent,
        relative_path: str,
    ) -> WorkspaceEffectReceipt:
        root: int | None = None
        published = False
        try:
            root = self._open_root_checked()
            parent, name = self._open_parent(root, relative_path)
            try:
                self._require_absent(parent, name)
                self._assert_root_path_current()
                try:
                    os.mkdir(name, intent.mode, dir_fd=parent)
                except FileExistsError as exc:
                    raise WorkspaceEffectNotStarted("workspace_create_target_exists") from exc
                published = True
                os.fsync(parent)
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent,
                )
                try:
                    self._verify_fd_mount(descriptor, self._require_initialized().mount)
                    info = os.fstat(descriptor)
                    if stat.S_IMODE(info.st_mode) != intent.mode:
                        raise WorkspaceFilesystemError("created workspace directory mode changed")
                    entry = self._entry(relative_path, descriptor, info=info)
                finally:
                    os.close(descriptor)
                self._assert_root_path_current()
                return self._effect_receipt(
                    intent.operation_id,
                    WorkspaceMutationKind.CREATE,
                    entry,
                    staging_reference=None,
                    durability_step="parent_fsync",
                )
            finally:
                os.close(parent)
        except WorkspaceEffectNotStarted:
            raise
        except Exception as exc:
            if published:
                raise WorkspaceEffectUncertain(
                    "workspace_create_directory_result_uncertain"
                ) from exc
            raise WorkspaceEffectNotStarted("workspace_create_directory_not_started") from exc
        finally:
            if root is not None:
                os.close(root)

    def _create_file(
        self,
        intent: WorkspaceCreateIntent,
        relative_path: str,
    ) -> WorkspaceEffectReceipt:
        staging = self.staging_reference(
            operation_id=intent.operation_id,
            mutation_kind=WorkspaceMutationKind.CREATE,
            relative_path=relative_path,
        )
        root: int | None = None
        published = False
        try:
            root = self._open_root_checked()
            parent, name = self._open_parent(root, relative_path)
            try:
                self._require_absent(parent, name)
                staging_fd = self._create_staging(parent, staging, intent.content, intent.mode)
                os.close(staging_fd)
                self._assert_root_path_current()
                try:
                    self._rename_noreplace(parent, staging, parent, name)
                except FileExistsError as exc:
                    raise WorkspaceEffectNotStarted("workspace_create_target_exists") from exc
                published = True
                os.fsync(parent)
                entry = self._verify_final_regular(
                    parent,
                    name,
                    relative_path,
                    expected_content_sha256=hashlib.sha256(intent.content).hexdigest(),
                    expected_mode=intent.mode,
                )
                self._assert_root_path_current()
                return self._effect_receipt(
                    intent.operation_id,
                    WorkspaceMutationKind.CREATE,
                    entry,
                    staging_reference=staging,
                    durability_step="file_fsync_rename_noreplace_parent_fsync",
                )
            finally:
                os.close(parent)
        except WorkspaceEffectNotStarted:
            raise
        except Exception as exc:
            if published:
                raise WorkspaceEffectUncertain("workspace_create_file_result_uncertain") from exc
            raise WorkspaceEffectNotStarted("workspace_create_file_not_started") from exc
        finally:
            if root is not None:
                os.close(root)

    def _write(self, intent: WorkspaceWriteIntent) -> WorkspaceEffectReceipt:
        root: int | None = None
        published = False
        try:
            relative_path = self._allowed_path(intent.relative_path)
            self._assert_request_bindings(
                expected_root_identity_sha256=intent.expected_root_identity_sha256,
                expected_mount_identity_sha256=intent.expected_mount_identity_sha256,
            )
            validate_identifier(intent.operation_id, name="operation_id")
            validate_sha256(intent.expected_object_version, name="expected_object_version")
            validate_sha256(intent.expected_content_sha256, name="expected_content_sha256")
            if len(intent.content) > self._maximum_mutation_bytes:
                raise WorkspaceEffectNotStarted("workspace_write_content_too_large")
            staging = self.staging_reference(
                operation_id=intent.operation_id,
                mutation_kind=WorkspaceMutationKind.WRITE,
                relative_path=relative_path,
            )
            root = self._open_root_checked()
            parent, name = self._open_parent(root, relative_path)
            try:
                current = self._open_regular_at(parent, name)
                try:
                    current_info, current_digest = self._stable_regular_digest(
                        current,
                        maximum_bytes=self._maximum_mutation_bytes,
                    )
                    self._require_replaceable_metadata(current, current_info)
                    current_identity = self._object_identity(
                        relative_path,
                        current_info,
                        content_sha256=current_digest,
                    )
                    if (
                        current_digest != intent.expected_content_sha256
                        or object_version(current_identity) != intent.expected_object_version
                    ):
                        raise WorkspaceEffectNotStarted("workspace_write_expected_state_changed")
                    replacement_mode = stat.S_IMODE(current_info.st_mode)
                finally:
                    os.close(current)
                staging_fd = self._create_staging(
                    parent,
                    staging,
                    intent.content,
                    replacement_mode,
                )
                os.close(staging_fd)
                # Re-open and reproduce the exact expected version immediately before rename.
                current = self._open_regular_at(parent, name)
                try:
                    final_info, final_digest = self._stable_regular_digest(
                        current,
                        maximum_bytes=self._maximum_mutation_bytes,
                    )
                    self._require_replaceable_metadata(current, final_info)
                    final_identity = self._object_identity(
                        relative_path,
                        final_info,
                        content_sha256=final_digest,
                    )
                    if (
                        final_digest != intent.expected_content_sha256
                        or object_version(final_identity) != intent.expected_object_version
                    ):
                        raise WorkspaceEffectNotStarted("workspace_write_expected_state_changed")
                finally:
                    os.close(current)
                self._assert_root_path_current()
                os.rename(staging, name, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                os.fsync(parent)
                entry = self._verify_final_regular(
                    parent,
                    name,
                    relative_path,
                    expected_content_sha256=hashlib.sha256(intent.content).hexdigest(),
                    expected_mode=replacement_mode,
                )
                self._assert_root_path_current()
                return self._effect_receipt(
                    intent.operation_id,
                    WorkspaceMutationKind.WRITE,
                    entry,
                    staging_reference=staging,
                    durability_step="file_fsync_atomic_replace_parent_fsync",
                )
            finally:
                os.close(parent)
        except WorkspaceEffectNotStarted:
            raise
        except FileNotFoundError as exc:
            if published:
                raise WorkspaceEffectUncertain("workspace_write_result_uncertain") from exc
            raise WorkspaceEffectNotStarted("workspace_write_target_missing") from exc
        except Exception as exc:
            if published:
                raise WorkspaceEffectUncertain("workspace_write_result_uncertain") from exc
            raise WorkspaceEffectNotStarted("workspace_write_not_started") from exc
        finally:
            if root is not None:
                os.close(root)

    def _create_staging(self, parent: int, name: str, content: bytes, mode: int) -> int:
        try:
            descriptor = os.open(
                name,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
        except FileExistsError as exc:
            raise WorkspaceEffectNotStarted("workspace_staging_collision") from exc
        try:
            self._verify_fd_mount(descriptor, self._require_initialized().mount)
            self._write_all(descriptor, content)
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
            stable, digest = self._stable_regular_digest(
                descriptor,
                maximum_bytes=self._maximum_mutation_bytes,
            )
            if (
                digest != hashlib.sha256(content).hexdigest()
                or stable.st_size != len(content)
                or stat.S_IMODE(stable.st_mode) != mode
            ):
                raise WorkspaceFilesystemError("workspace staging verification failed")
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _verify_final_regular(
        self,
        parent: int,
        name: str,
        relative_path: str,
        *,
        expected_content_sha256: str,
        expected_mode: int,
    ) -> WorkspaceEntry:
        descriptor = self._open_regular_at(parent, name)
        try:
            info, digest = self._stable_regular_digest(
                descriptor,
                maximum_bytes=self._maximum_mutation_bytes,
            )
            if digest != expected_content_sha256 or stat.S_IMODE(info.st_mode) != expected_mode:
                raise WorkspaceFilesystemError("workspace mutation result verification failed")
            return self._entry(relative_path, descriptor, info=info, content_sha256=digest)
        finally:
            os.close(descriptor)

    def _effect_receipt(
        self,
        operation_id: str,
        mutation_kind: WorkspaceMutationKind,
        entry: WorkspaceEntry,
        *,
        staging_reference: str | None,
        durability_step: str,
    ) -> WorkspaceEffectReceipt:
        reference = (
            f"workspace-effect:v1:{mutation_kind.value}:{operation_id}:"
            f"{canonical_sha256(entry.relative_path)}:{entry.object_version}"
        )
        reference_sha256 = hashlib.sha256(
            b"binnacle.workspace-effect-reference.v1\0" + reference.encode("ascii")
        ).hexdigest()
        return WorkspaceEffectReceipt(
            operation_id=operation_id,
            mutation_kind=mutation_kind,
            relative_path=entry.relative_path,
            object_identity=entry.object_identity,
            object_version=entry.object_version,
            content_sha256=entry.object_identity.content_sha256,
            staging_reference=staging_reference,
            primitive_profile_version=_PRIMITIVE_PROFILE_VERSION,
            durability_step=durability_step,
            reference=reference,
            reference_sha256=reference_sha256,
        )

    def _open_path(self, root: int, relative_path: str, *, content: bool) -> int:
        parent, name = self._open_parent(root, relative_path)
        try:
            if content:
                descriptor = self._open_regular_at(parent, name)
            else:
                descriptor = self._open_entry_metadata(parent, name)
            self._verify_fd_mount(descriptor, self._require_initialized().mount)
            return descriptor
        finally:
            os.close(parent)

    def _open_parent(self, root: int, relative_path: str) -> tuple[int, str]:
        components = relative_path.split("/")
        if len(components) == 1:
            return os.dup(root), components[0]
        return self._open_directory(root, "/".join(components[:-1])), components[-1]

    def _open_directory(self, root: int, relative_path: str) -> int:
        current = os.dup(root)
        try:
            for component in relative_path.split("/") if relative_path else ():
                try:
                    child = os.open(
                        component,
                        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                except OSError as exc:
                    raise WorkspaceFilesystemError(
                        "workspace directory component cannot be opened without following"
                    ) from exc
                try:
                    self._verify_fd_mount(child, self._require_initialized().mount)
                except Exception:
                    os.close(child)
                    raise
                os.close(current)
                current = child
            return current
        except Exception:
            os.close(current)
            raise

    def _open_entry_metadata(self, parent: int, name: str) -> int:
        try:
            return os.open(name, os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
        except OSError as exc:
            raise WorkspaceFilesystemError(
                "workspace entry cannot be opened without following"
            ) from exc

    def _open_regular_at(self, parent: int, name: str) -> int:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent,
            )
        except OSError as exc:
            raise WorkspaceFilesystemError(
                "workspace content target cannot be opened safely"
            ) from exc
        try:
            self._verify_fd_mount(descriptor, self._require_initialized().mount)
            self._require_content_file(os.fstat(descriptor))
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _entry(
        self,
        relative_path: str,
        descriptor: int,
        *,
        info: os.stat_result | None = None,
        content_sha256: str | None = None,
    ) -> WorkspaceEntry:
        self._verify_fd_mount(descriptor, self._require_initialized().mount)
        identity = self._object_identity(
            relative_path,
            info or os.fstat(descriptor),
            content_sha256=content_sha256,
        )
        return WorkspaceEntry(
            relative_path=relative_path,
            kind=identity.kind,
            object_identity=identity,
            object_version=object_version(identity),
        )

    def _object_identity(
        self,
        relative_path: str,
        info: os.stat_result,
        *,
        content_sha256: str | None = None,
    ) -> WorkspaceObjectIdentity:
        kind = self._object_kind(info.st_mode)
        expected = self._require_initialized()
        return WorkspaceObjectIdentity(
            workspace_id=self._workspace_id,
            profile_sha256=self._profile_sha256,
            root_identity_sha256=expected.identity_sha256,
            mount_identity_sha256=expected.mount.digest_sha256,
            relative_path=relative_path,
            kind=kind,
            device=info.st_dev,
            inode=info.st_ino,
            mode=info.st_mode,
            size=info.st_size,
            modified_ns=info.st_mtime_ns,
            link_count=info.st_nlink,
            content_sha256=content_sha256,
        )

    @staticmethod
    def _object_kind(mode: int) -> WorkspaceObjectKind:
        if stat.S_ISREG(mode):
            return WorkspaceObjectKind.REGULAR_FILE
        if stat.S_ISDIR(mode):
            return WorkspaceObjectKind.DIRECTORY
        if stat.S_ISLNK(mode):
            return WorkspaceObjectKind.SYMLINK
        return WorkspaceObjectKind.OTHER

    def _stable_regular_digest(
        self,
        descriptor: int,
        *,
        maximum_bytes: int,
    ) -> tuple[os.stat_result, str]:
        info, content = self._stable_regular_bytes(descriptor, maximum_bytes=maximum_bytes)
        return info, hashlib.sha256(content).hexdigest()

    def _stable_regular_bytes(
        self,
        descriptor: int,
        *,
        maximum_bytes: int,
    ) -> tuple[os.stat_result, bytes]:
        before = self._require_content_file(os.fstat(descriptor))
        if before.st_size > maximum_bytes:
            raise WorkspaceFilesystemError("workspace file exceeds the content-hash bound")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(descriptor, min(65_536, before.st_size - offset), offset)
            if not chunk:
                raise WorkspaceFilesystemError("workspace file ended during bounded read")
            chunks.append(chunk)
            offset += len(chunk)
        after = self._require_content_file(os.fstat(descriptor))
        if self._mutable_stat_key(before) != self._mutable_stat_key(after):
            raise WorkspaceFilesystemError("workspace file changed during bounded read")
        return after, b"".join(chunks)

    @staticmethod
    def _require_single_link(info: os.stat_result) -> None:
        if info.st_nlink != 1:
            raise WorkspaceFilesystemError("workspace regular file is multiply linked")

    def _require_content_file(self, info: os.stat_result) -> os.stat_result:
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceFilesystemError("workspace content target is not a regular file")
        self._require_single_link(info)
        if stat.S_IMODE(info.st_mode) & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
            raise WorkspaceFilesystemError("workspace content target has a special mode")
        return info

    def _require_replaceable_metadata(self, descriptor: int, info: os.stat_result) -> None:
        mode = stat.S_IMODE(info.st_mode)
        if (
            info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or mode not in _CLOSED_REPLACE_MODES
        ):
            raise WorkspaceEffectNotStarted("workspace_write_metadata_unsupported")
        try:
            attributes = os.listxattr(descriptor)
        except OSError as exc:
            raise WorkspaceEffectNotStarted("workspace_write_xattr_check_unavailable") from exc
        if attributes:
            raise WorkspaceEffectNotStarted("workspace_write_xattrs_unsupported")

    def _require_absent(self, parent: int, name: str) -> None:
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise WorkspaceEffectNotStarted("workspace_create_target_exists")

    def _assert_root_path_current(self) -> None:
        descriptor = self._open_root_checked()
        os.close(descriptor)

    def _verify_fd_mount(self, descriptor: int, expected: MountIdentity) -> None:
        observed = self._mount_identity_for_fd(descriptor)
        if observed != expected:
            raise WorkspaceFilesystemError("workspace descriptor crossed its registered mount")

    def _mount_identity_for_fd(self, descriptor: int) -> MountIdentity:
        info = os.fstat(descriptor)
        mount_id = self._mount_id_for_fd(descriptor)
        filesystem_type, mount_device = self._mountinfo_facts(mount_id)
        if mount_device != info.st_dev:
            raise WorkspaceFilesystemError("workspace mount and descriptor device disagree")
        digest = canonical_sha256(
            {
                "device": info.st_dev,
                "filesystem_type": filesystem_type,
                "mount_id": mount_id,
            }
        )
        return MountIdentity(
            mount_id=mount_id,
            device=info.st_dev,
            filesystem_type=filesystem_type,
            digest_sha256=digest,
        )

    def _mount_id_for_fd(self, descriptor: int) -> int:
        content = self._read_proc_file(
            self._proc_root / "self" / "fdinfo" / str(descriptor),
            maximum_bytes=_MAX_FDINFO_BYTES,
        )
        values: list[int] = []
        for line in content.splitlines():
            key, separator, value = line.partition(b":")
            if key == b"mnt_id" and separator:
                try:
                    values.append(int(value.strip(), 10))
                except ValueError as exc:
                    raise WorkspaceFilesystemError("workspace fd mount ID is malformed") from exc
        if len(values) != 1 or values[0] < 1:
            raise WorkspaceFilesystemError("workspace fd mount ID is unavailable")
        return values[0]

    def _mountinfo_facts(self, mount_id: int) -> tuple[str, int]:
        content = self._read_proc_file(
            self._proc_root / "self" / "mountinfo",
            maximum_bytes=_MAX_MOUNTINFO_BYTES,
        )
        matches: list[tuple[str, int]] = []
        for line in content.splitlines():
            prefix, separator, suffix = line.partition(b" - ")
            fields = prefix.split()
            suffix_fields = suffix.split()
            if not separator or len(fields) < 3 or len(suffix_fields) < 1:
                raise WorkspaceFilesystemError("Linux mountinfo contains a malformed record")
            try:
                candidate_id = int(fields[0], 10)
            except ValueError as exc:
                raise WorkspaceFilesystemError("Linux mountinfo mount ID is malformed") from exc
            if candidate_id != mount_id:
                continue
            device_text = fields[2].decode("ascii", errors="strict")
            major_text, colon, minor_text = device_text.partition(":")
            try:
                device = os.makedev(int(major_text, 10), int(minor_text, 10))
                filesystem_type = suffix_fields[0].decode("ascii", errors="strict")
            except (UnicodeDecodeError, ValueError) as exc:
                raise WorkspaceFilesystemError("Linux mountinfo facts are malformed") from exc
            if (
                not colon
                or not filesystem_type
                or len(filesystem_type) > 64
                or any(not 0x21 <= ord(character) <= 0x7E for character in filesystem_type)
            ):
                raise WorkspaceFilesystemError("Linux mountinfo facts are unsafe")
            matches.append((filesystem_type, device))
        if len(matches) != 1:
            raise WorkspaceFilesystemError("workspace mount ID is not unique in mountinfo")
        return matches[0]

    @staticmethod
    def _read_proc_file(path: Path, *, maximum_bytes: int) -> bytes:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except OSError as exc:
            raise WorkspaceFilesystemError(
                "Linux descriptor mount evidence is unavailable"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceFilesystemError("Linux descriptor mount evidence is unsafe")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum_bytes:
                    raise WorkspaceFilesystemError("Linux descriptor mount evidence is unbounded")
        finally:
            os.close(descriptor)

    def _bounded_directory_names(
        self,
        directory_fd: int,
        *,
        maximum: int,
        require_complete: bool,
    ) -> tuple[str, ...]:
        if maximum < 1:
            raise WorkspaceFilesystemError("workspace directory enumeration bound exhausted")
        names: list[str] = []
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                names.append(entry.name)
                if len(names) > maximum:
                    if require_complete:
                        raise WorkspaceFilesystemError(
                            "workspace directory enumeration exceeded its bound"
                        )
                    break
        return tuple(sorted(names))

    def _listing_names(self, directory_fd: int, maximum: int) -> tuple[tuple[str, ...], bool]:
        names = self._bounded_directory_names(
            directory_fd,
            maximum=maximum,
            require_complete=False,
        )
        return names[:maximum], len(names) > maximum

    @staticmethod
    def _rename_noreplace(
        source_directory: int,
        source_name: str,
        target_directory: int,
        target_name: str,
    ) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:
            raise WorkspaceEffectNotStarted("workspace_rename_noreplace_unavailable") from exc
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            source_directory,
            os.fsencode(source_name),
            target_directory,
            os.fsencode(target_name),
            _RENAME_NOREPLACE,
        )
        if result != 0:
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise FileExistsError(error, os.strerror(error), target_name)
            raise OSError(error, os.strerror(error), source_name)

    @staticmethod
    def _write_all(descriptor: int, content: bytes) -> None:
        view = memoryview(content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short workspace staging write")
            written += count

    @staticmethod
    def _stat_key(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        )

    @staticmethod
    def _root_stat_key(identity: WorkspaceRootIdentity) -> tuple[int, int, int, int, int]:
        return (
            identity.device,
            identity.inode,
            identity.owner_uid,
            identity.owner_gid,
            identity.mode,
        )

    @staticmethod
    def _mutable_stat_key(info: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_nlink,
        )


__all__ = [
    "LinuxWorkspace",
    "WorkspaceCapabilityUnavailable",
    "WorkspaceEffectNotStarted",
    "WorkspaceEffectUncertain",
    "WorkspaceFilesystemError",
]

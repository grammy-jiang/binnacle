"""Framework-independent Phase 6 workspace values and transformations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Final

MAX_PATH_BYTES: Final = 4_096
MAX_PATH_DEPTH: Final = 64
MAX_MUTATION_BYTES: Final = 4 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_PROTECTED_ROOTS: Final = frozenset({".git"})
_RESERVED_PREFIXES: Final = (".binnacle-",)


class WorkspaceError(ValueError):
    """A workspace value lies outside the frozen Phase 6 boundary."""


class WorkspaceObjectKind(StrEnum):
    REGULAR_FILE = "regular_file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class WorkspaceMutationKind(StrEnum):
    CREATE = "create"
    WRITE = "write"
    PATCH = "patch"
    MOVE = "move"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class MountIdentity:
    mount_id: int
    device: int
    filesystem_type: str
    digest_sha256: str

    def __post_init__(self) -> None:
        if self.mount_id < 1 or self.device < 0 or not self.filesystem_type:
            raise WorkspaceError("workspace mount identity is invalid")
        validate_sha256(self.digest_sha256, name="mount_identity_sha256")


@dataclass(frozen=True, slots=True)
class WorkspaceRootIdentity:
    workspace_id: str
    profile_sha256: str
    identity_sha256: str
    mount: MountIdentity
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int

    def __post_init__(self) -> None:
        validate_identifier(self.workspace_id, name="workspace_id")
        validate_sha256(self.profile_sha256, name="profile_sha256")
        validate_sha256(self.identity_sha256, name="root_identity_sha256")
        if min(self.device, self.inode, self.owner_uid, self.owner_gid, self.mode) < 0:
            raise WorkspaceError("workspace root identity has negative facts")


@dataclass(frozen=True, slots=True)
class WorkspaceObjectIdentity:
    workspace_id: str
    profile_sha256: str
    root_identity_sha256: str
    mount_identity_sha256: str
    relative_path: str
    kind: WorkspaceObjectKind
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    link_count: int
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.workspace_id, name="workspace_id")
        validate_sha256(self.profile_sha256, name="profile_sha256")
        validate_sha256(self.root_identity_sha256, name="root_identity_sha256")
        validate_sha256(self.mount_identity_sha256, name="mount_identity_sha256")
        normalize_workspace_path(
            self.relative_path,
            allow_root=(self.kind is WorkspaceObjectKind.DIRECTORY),
        )
        if not self.relative_path and self.kind is not WorkspaceObjectKind.DIRECTORY:
            raise WorkspaceError("only the registered root directory may use an empty path")
        if min(self.device, self.inode, self.mode, self.size, self.modified_ns) < 0:
            raise WorkspaceError("workspace object identity has negative facts")
        if self.link_count < 1:
            raise WorkspaceError("workspace object link count is invalid")
        if self.content_sha256 is not None:
            validate_sha256(self.content_sha256, name="content_sha256")


@dataclass(frozen=True, slots=True)
class ContentReadPermit:
    permit_id: str
    session_id: str
    session_state_version: int
    workspace_id: str
    workspace_profile_sha256: str
    root_identity_sha256: str
    mount_identity_sha256: str
    request_sha256: str
    content_guard_epoch: int

    def __post_init__(self) -> None:
        for name, value in (
            ("permit_id", self.permit_id),
            ("session_id", self.session_id),
            ("workspace_id", self.workspace_id),
        ):
            validate_identifier(value, name=name)
        for name, value in (
            ("workspace_profile_sha256", self.workspace_profile_sha256),
            ("root_identity_sha256", self.root_identity_sha256),
            ("mount_identity_sha256", self.mount_identity_sha256),
            ("request_sha256", self.request_sha256),
        ):
            validate_sha256(value, name=name)
        if self.session_state_version < 1 or self.content_guard_epoch < 1:
            raise WorkspaceError("content permit version/epoch is invalid")


@dataclass(frozen=True, slots=True)
class SearchFileSnapshot:
    relative_path: str
    handle_id: str
    object_version: str
    object_identity_sha256: str
    mount_identity_sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        normalize_workspace_path(self.relative_path)
        validate_identifier(self.handle_id, name="handle_id")
        for name, value in (
            ("object_version", self.object_version),
            ("object_identity_sha256", self.object_identity_sha256),
            ("mount_identity_sha256", self.mount_identity_sha256),
        ):
            validate_sha256(value, name=name)
        if self.byte_count < 0:
            raise WorkspaceError("search snapshot byte count is invalid")


@dataclass(frozen=True, slots=True)
class WorkspaceFence:
    workspace_id: str
    fence_version: int
    active_operation_id: str | None
    active_contract: str | None

    def __post_init__(self) -> None:
        validate_identifier(self.workspace_id, name="workspace_id")
        if self.fence_version < 1:
            raise WorkspaceError("workspace fence version is invalid")
        active = self.active_operation_id is not None
        if active != (self.active_contract is not None):
            raise WorkspaceError("workspace fence owner shape is invalid")
        if self.active_operation_id is not None:
            validate_identifier(self.active_operation_id, name="active_operation_id")
            validate_identifier(self.active_contract or "", name="active_contract")


@dataclass(frozen=True, slots=True)
class ExactTextReplacement:
    old: str
    new: str

    def __post_init__(self) -> None:
        if not self.old:
            raise WorkspaceError("patch match cannot be empty")


def normalize_workspace_path(
    raw_path: str,
    *,
    allow_root: bool = False,
    maximum_bytes: int = MAX_PATH_BYTES,
    maximum_depth: int = MAX_PATH_DEPTH,
) -> str:
    """Return one canonical relative POSIX path; containment remains descriptor-owned."""

    if not isinstance(raw_path, str):
        raise WorkspaceError("workspace path must be text")
    if unicodedata.normalize("NFC", raw_path) != raw_path:
        raise WorkspaceError("workspace path must already be NFC-normalized")
    if raw_path == "" and allow_root:
        return ""
    if not raw_path or raw_path.startswith(("/", "\\")) or "\\" in raw_path:
        raise WorkspaceError("workspace path must be relative POSIX form")
    if any(character in raw_path for character in ("\0", "\r", "\n")):
        raise WorkspaceError("workspace path contains a forbidden character")
    components = raw_path.split("/")
    if len(components) > maximum_depth or any(part in {"", ".", ".."} for part in components):
        raise WorkspaceError("workspace path depth/components are invalid")
    if any(part.startswith(_RESERVED_PREFIXES) for part in components):
        raise WorkspaceError("workspace path uses a reserved name")
    try:
        encoded = raw_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WorkspaceError("workspace path is not valid UTF-8") from exc
    if len(encoded) > maximum_bytes or any(len(part.encode("utf-8")) > 255 for part in components):
        raise WorkspaceError("workspace path exceeds the reviewed limit")
    # PurePosixPath catches platform-independent absolute/drive-like surprises while the
    # explicit component checks above retain the exact input spelling.
    if PurePosixPath(raw_path).is_absolute():
        raise WorkspaceError("workspace path cannot be absolute")
    return raw_path


def is_protected_workspace_path(
    relative_path: str,
    *,
    additional_roots: Sequence[str] = (),
) -> bool:
    normalized = normalize_workspace_path(relative_path)
    protected = set(_PROTECTED_ROOTS)
    protected.update(normalize_workspace_path(item) for item in additional_roots)
    return any(normalized == root or normalized.startswith(f"{root}/") for root in protected)


def require_content_path_allowed(
    relative_path: str,
    *,
    additional_roots: Sequence[str] = (),
) -> str:
    normalized = normalize_workspace_path(relative_path)
    if is_protected_workspace_path(normalized, additional_roots=additional_roots):
        raise WorkspaceError("workspace path is protected")
    return normalized


def workspace_path_sha256(relative_path: str, *, allow_root: bool = False) -> str:
    """Bind one canonical logical path without treating the digest as authority."""

    normalized = normalize_workspace_path(relative_path, allow_root=allow_root)
    return hashlib.sha256(b"binnacle.workspace-path.v1\0" + normalized.encode("utf-8")).hexdigest()


def object_version(identity: WorkspaceObjectIdentity) -> str:
    """Return an opaque content/state token that includes mount and alias facts."""

    return canonical_sha256(
        {
            "content_sha256": identity.content_sha256,
            "device": identity.device,
            "inode": identity.inode,
            "kind": identity.kind.value,
            "link_count": identity.link_count,
            "mode": identity.mode,
            "modified_ns": identity.modified_ns,
            "mount_identity_sha256": identity.mount_identity_sha256,
            "profile_sha256": identity.profile_sha256,
            "relative_path": identity.relative_path,
            "root_identity_sha256": identity.root_identity_sha256,
            "size": identity.size,
            "workspace_id": identity.workspace_id,
        }
    )


def apply_exact_text_patch(
    base: bytes,
    replacements: Sequence[ExactTextReplacement],
    *,
    maximum_bytes: int = MAX_MUTATION_BYTES,
) -> bytes:
    """Apply ordered unique non-overlapping matches against the original UTF-8 base."""

    if not replacements:
        raise WorkspaceError("patch requires at least one replacement")
    try:
        text = base.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("patch base is not valid UTF-8") from exc
    spans: list[tuple[int, int, str]] = []
    for replacement in replacements:
        first = text.find(replacement.old)
        if first < 0 or text.find(replacement.old, first + 1) >= 0:
            raise WorkspaceError("patch match must occur exactly once in the original base")
        spans.append((first, first + len(replacement.old), replacement.new))
    spans.sort(key=lambda item: item[0])
    if any(left[1] > right[0] for left, right in pairwise(spans)):
        raise WorkspaceError("patch match spans overlap")
    cursor = 0
    pieces: list[str] = []
    for start, end, new in spans:
        pieces.extend((text[cursor:start], new))
        cursor = end
    pieces.append(text[cursor:])
    result = "".join(pieces).encode("utf-8", errors="strict")
    if len(result) > maximum_bytes:
        raise WorkspaceError("patched content exceeds the reviewed mutation limit")
    return result


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def validate_sha256(value: str, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WorkspaceError(f"{name} is not lowercase SHA-256")
    return value


def validate_identifier(value: str, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise WorkspaceError(f"{name} is not a bounded identifier")
    return value


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(child) for child in value]
    return value


__all__ = [
    "MAX_MUTATION_BYTES",
    "MAX_PATH_BYTES",
    "MAX_PATH_DEPTH",
    "ContentReadPermit",
    "ExactTextReplacement",
    "MountIdentity",
    "SearchFileSnapshot",
    "WorkspaceError",
    "WorkspaceFence",
    "WorkspaceMutationKind",
    "WorkspaceObjectIdentity",
    "WorkspaceObjectKind",
    "WorkspaceRootIdentity",
    "apply_exact_text_patch",
    "canonical_sha256",
    "is_protected_workspace_path",
    "normalize_workspace_path",
    "object_version",
    "require_content_path_allowed",
    "validate_identifier",
    "validate_sha256",
    "workspace_path_sha256",
]

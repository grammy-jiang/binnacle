"""Ports and immutable boundary values for the Phase 6 workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.workspace import (
    ContentReadPermit,
    WorkspaceFence,
    WorkspaceMutationKind,
    WorkspaceObjectIdentity,
    WorkspaceObjectKind,
    WorkspaceRootIdentity,
)


class WorkspaceEffectNotStarted(RuntimeError):
    """The adapter proved that no workspace effect syscall crossed its boundary."""


class WorkspaceEffectUncertain(RuntimeError):
    """The adapter cannot prove the outcome after an effect may have started."""


@dataclass(frozen=True, slots=True)
class RegisteredWorkspaceSnapshot:
    workspace_id: str
    profile_sha256: str
    root_identity_sha256: str
    mount_identity_sha256: str
    root_device: int
    root_inode: int
    mount_id: int
    mount_device: int
    filesystem_type: str
    owner_uid: int
    owner_gid: int
    mode: int
    primitive_profile_version: str
    registration_version: int
    registered_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceOperationRecord:
    operation_id: str
    session_id: str
    workspace_id: str
    mutation_kind: WorkspaceMutationKind
    object_kind: WorkspaceObjectKind
    source_path_sha256: str | None
    target_path_sha256: str | None
    expected_object_sha256: str | None
    expected_content_sha256: str | None
    expected_link_count: int | None
    expected_mount_identity_sha256: str
    proposed_content_sha256: str | None
    proposed_byte_count: int | None
    state_binding_sha256: str
    staging_reference: str | None
    staging_reference_sha256: str | None
    primitive_profile_version: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceAuthorisationRequest:
    """Exact post-policy facts committed with the mutation fence and operation."""

    operation: OperationSnapshot
    decision: PolicyDecision
    record: WorkspaceOperationRecord
    expected_fence_version: int
    required_scope_digest: str | None
    normalized_target_digest: str
    authorised_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceInspectRequest:
    relative_path: str
    expected_root_identity_sha256: str
    expected_mount_identity_sha256: str
    include_content_digest: bool = False
    maximum_hash_bytes: int = 0


@dataclass(frozen=True, slots=True)
class WorkspaceListRequest:
    relative_path: str
    expected_root_identity_sha256: str
    expected_mount_identity_sha256: str
    maximum_entries: int


@dataclass(frozen=True, slots=True)
class WorkspaceReadRequest:
    relative_path: str
    expected_root_identity_sha256: str
    expected_mount_identity_sha256: str
    permit: ContentReadPermit
    offset: int
    maximum_bytes: int


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    relative_path: str
    kind: WorkspaceObjectKind
    object_identity: WorkspaceObjectIdentity
    object_version: str


@dataclass(frozen=True, slots=True)
class WorkspaceListing:
    relative_path: str
    entries: tuple[WorkspaceEntry, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class WorkspaceReadResult:
    relative_path: str
    content: bytes
    offset: int
    next_offset: int | None
    complete: bool
    object_identity: WorkspaceObjectIdentity
    object_version: str
    content_sha256: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceCreateIntent:
    operation_id: str
    relative_path: str
    kind: WorkspaceObjectKind
    content: bytes
    mode: int
    expected_root_identity_sha256: str
    expected_mount_identity_sha256: str


@dataclass(frozen=True, slots=True)
class WorkspaceWriteIntent:
    operation_id: str
    relative_path: str
    content: bytes
    expected_object_version: str
    expected_content_sha256: str
    expected_root_identity_sha256: str
    expected_mount_identity_sha256: str


@dataclass(frozen=True, slots=True)
class WorkspaceEffectReceipt:
    operation_id: str
    mutation_kind: WorkspaceMutationKind
    relative_path: str
    object_identity: WorkspaceObjectIdentity
    object_version: str
    content_sha256: str | None
    staging_reference: str | None
    primitive_profile_version: str
    durability_step: str
    reference: str
    reference_sha256: str


class WorkspaceRepository(Protocol):
    async def register_workspace(
        self,
        registration: RegisteredWorkspaceSnapshot,
    ) -> RegisteredWorkspaceSnapshot: ...

    async def get_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot | None: ...

    async def require_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot: ...

    async def get_fence(self, workspace_id: str) -> WorkspaceFence: ...

    async def acquire_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        contract: str,
        acquired_at: datetime,
    ) -> WorkspaceFence: ...

    async def release_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        released_at: datetime,
    ) -> WorkspaceFence: ...

    async def authorise_mutation(
        self,
        request: WorkspaceAuthorisationRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence]: ...

    async def get_operation(self, operation_id: str) -> WorkspaceOperationRecord | None: ...

    async def list_operations(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[WorkspaceOperationRecord, ...]: ...

    async def verify_integrity(self) -> None: ...


class WorkspaceFilesystem(Protocol):
    async def initialize(self) -> WorkspaceRootIdentity: ...

    async def root_identity(self) -> WorkspaceRootIdentity: ...

    async def verify_scope_no_submounts(self, relative_path: str) -> None: ...

    async def inspect(self, request: WorkspaceInspectRequest) -> WorkspaceEntry: ...

    async def list(self, request: WorkspaceListRequest) -> WorkspaceListing: ...

    async def read(self, request: WorkspaceReadRequest) -> WorkspaceReadResult: ...

    async def create(self, intent: WorkspaceCreateIntent) -> WorkspaceEffectReceipt: ...

    async def write(self, intent: WorkspaceWriteIntent) -> WorkspaceEffectReceipt: ...


__all__ = [
    "RegisteredWorkspaceSnapshot",
    "WorkspaceAuthorisationRequest",
    "WorkspaceCreateIntent",
    "WorkspaceEffectNotStarted",
    "WorkspaceEffectReceipt",
    "WorkspaceEffectUncertain",
    "WorkspaceEntry",
    "WorkspaceFilesystem",
    "WorkspaceInspectRequest",
    "WorkspaceListRequest",
    "WorkspaceListing",
    "WorkspaceOperationRecord",
    "WorkspaceReadRequest",
    "WorkspaceReadResult",
    "WorkspaceRepository",
    "WorkspaceWriteIntent",
]

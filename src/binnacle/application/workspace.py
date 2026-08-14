"""Default-disabled Phase 6 workspace read service and effect adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from binnacle.application.development_session import DevelopmentSessionAuthorityGate
from binnacle.application.operations import CoordinatedOperationRequest, OperationAuthorityError
from binnacle.application.workspace_coordination import (
    WorkspaceAccessGate,
    WorkspaceCoordinationError,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    Terminality,
)
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.workspace import (
    WorkspaceMutationKind,
    WorkspaceObjectKind,
    canonical_sha256,
    normalize_workspace_path,
    validate_identifier,
    validate_sha256,
    workspace_path_sha256,
)
from binnacle.ports.boundary import BoundaryCheckResult, OperationBoundaryCheck
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectRequest,
    EffectStartReceipt,
)
from binnacle.ports.workspace import (
    WorkspaceAuthorisationRequest,
    WorkspaceCreateIntent,
    WorkspaceEffectNotStarted,
    WorkspaceEffectUncertain,
    WorkspaceEntry,
    WorkspaceFilesystem,
    WorkspaceInspectRequest,
    WorkspaceListing,
    WorkspaceListRequest,
    WorkspaceOperationRecord,
    WorkspaceReadRequest,
    WorkspaceReadResult,
    WorkspaceRepository,
    WorkspaceWriteIntent,
)


class WorkspaceCapabilityUnavailable(OperationAuthorityError):
    """The requested Phase 6 capability is not promoted by the active profile."""


@dataclass(frozen=True, slots=True)
class WorkspaceReadPolicy:
    maximum_hash_bytes: int
    maximum_list_entries: int
    maximum_read_bytes: int


class WorkspaceReadService:
    """Coordinate session-bound metadata/content reads without exposing MCP handlers."""

    def __init__(
        self,
        *,
        workspace_id: str,
        filesystem: WorkspaceFilesystem,
        access_gate: WorkspaceAccessGate,
        session_gate: DevelopmentSessionAuthorityGate,
        policy: WorkspaceReadPolicy,
    ) -> None:
        self._workspace_id = validate_identifier(workspace_id, name="workspace_id")
        self._filesystem = filesystem
        self._access_gate = access_gate
        self._session_gate = session_gate
        self._policy = policy
        if (
            min(
                policy.maximum_hash_bytes,
                policy.maximum_list_entries,
                policy.maximum_read_bytes,
            )
            < 1
        ):
            raise ValueError("workspace read policy limits must be positive")

    async def inspect(
        self,
        *,
        session_id: str,
        relative_path: str,
        include_content_digest: bool = False,
    ) -> WorkspaceEntry:
        if include_content_digest:
            # A digest of source bytes is content-bearing.  The initial metadata
            # surface deliberately cannot obtain it without the CONTENT_READ ->
            # request-bound permit sequence used by ``read``.
            raise WorkspaceCapabilityUnavailable(
                "content-bearing workspace inspection is not promoted"
            )
        root = await self._filesystem.root_identity()
        async with self._session_gate.hold_member_start(
            session_id=session_id,
            workspace_id=self._workspace_id,
        ):
            return await self._filesystem.inspect(
                WorkspaceInspectRequest(
                    relative_path=normalize_workspace_path(relative_path, allow_root=True),
                    expected_root_identity_sha256=root.identity_sha256,
                    expected_mount_identity_sha256=root.mount.digest_sha256,
                    include_content_digest=include_content_digest,
                    maximum_hash_bytes=self._policy.maximum_hash_bytes,
                )
            )

    async def list(
        self,
        *,
        session_id: str,
        relative_path: str,
    ) -> WorkspaceListing:
        root = await self._filesystem.root_identity()
        async with self._session_gate.hold_member_start(
            session_id=session_id,
            workspace_id=self._workspace_id,
        ):
            return await self._filesystem.list(
                WorkspaceListRequest(
                    relative_path=normalize_workspace_path(relative_path, allow_root=True),
                    expected_root_identity_sha256=root.identity_sha256,
                    expected_mount_identity_sha256=root.mount.digest_sha256,
                    maximum_entries=self._policy.maximum_list_entries,
                )
            )

    async def read(
        self,
        *,
        session_id: str,
        relative_path: str,
        offset: int = 0,
        maximum_bytes: int | None = None,
    ) -> WorkspaceReadResult:
        bounded_bytes = self._policy.maximum_read_bytes if maximum_bytes is None else maximum_bytes
        if not 1 <= bounded_bytes <= self._policy.maximum_read_bytes or offset < 0:
            raise ValueError("workspace read range is outside the configured bound")
        normalized = normalize_workspace_path(relative_path)
        guard = await self._access_gate.acquire_content_read()
        try:
            request_sha256 = canonical_sha256(
                {
                    "maximum_bytes": bounded_bytes,
                    "offset": offset,
                    "relative_path": normalized,
                    "session_id": session_id,
                    "workspace_id": self._workspace_id,
                }
            )
            permit = await self._session_gate.admit_content_read(
                session_id=session_id,
                workspace_id=self._workspace_id,
                request_sha256=request_sha256,
                content_guard=guard,
            )
            root = await self._filesystem.root_identity()
            return await self._filesystem.read(
                WorkspaceReadRequest(
                    relative_path=normalized,
                    expected_root_identity_sha256=root.identity_sha256,
                    expected_mount_identity_sha256=root.mount.digest_sha256,
                    permit=permit,
                    offset=offset,
                    maximum_bytes=bounded_bytes,
                )
            )
        finally:
            await self._access_gate.release_content_read(guard)

    async def search(self) -> None:
        raise WorkspaceCapabilityUnavailable("workspace search is not promoted")


WorkspaceOperationRecordReader = Callable[
    [OperationSnapshot, CoordinatedOperationRequest],
    Awaitable[WorkspaceOperationRecord],
]
WorkspaceReleaseVerifier = Callable[
    [OperationSnapshot, WorkspaceOperationRecord],
    Awaitable[bool],
]


class WorkspaceChangePostPolicyAuthority:
    """Hold process-local CHANGE until the durable fence is released or retained."""

    def __init__(
        self,
        *,
        workspace_id: str,
        access_gate: WorkspaceAccessGate,
        repository: WorkspaceRepository,
    ) -> None:
        self._workspace_id = validate_identifier(workspace_id, name="workspace_id")
        self._access_gate = access_gate
        self._repository = repository

    @asynccontextmanager
    async def hold(
        self,
        *,
        operation: OperationSnapshot,
        decision: PolicyDecision,
        request: CoordinatedOperationRequest,
    ) -> AsyncIterator[None]:
        del decision, request
        try:
            guard = await self._access_gate.acquire_change(operation.operation_id)
        except WorkspaceCoordinationError as exc:
            raise WorkspaceCapabilityUnavailable("workspace_change_recovery_closed") from exc
        try:
            yield
        finally:
            try:
                fence = await self._repository.get_fence(self._workspace_id)
            except BaseException:
                await asyncio.shield(self._access_gate.retain_uncertain_change(guard))
                raise
            if fence.active_operation_id == operation.operation_id:
                # Any incomplete/uncertain closure keeps the durable owner and closes
                # both read and change admission for recovery.
                await asyncio.shield(self._access_gate.retain_uncertain_change(guard))
            elif fence.active_operation_id is None:
                await asyncio.shield(self._access_gate.release_change(guard))
            else:
                await asyncio.shield(self._access_gate.retain_uncertain_change(guard))
                raise WorkspaceCapabilityUnavailable(
                    "workspace fence changed to a foreign owner while CHANGE was held"
                )


class WorkspaceMutationAuthoriser:
    """Atomically bind an allowed operation to exact session facts and the fence."""

    def __init__(
        self,
        *,
        repository: WorkspaceRepository,
        record_reader: WorkspaceOperationRecordReader,
    ) -> None:
        self._repository = repository
        self._record_reader = record_reader

    async def authorise(
        self,
        *,
        operation: OperationSnapshot,
        decision: PolicyDecision,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        record = await self._record_reader(operation, request)
        if record.operation_id != operation.operation_id:
            raise WorkspaceCapabilityUnavailable(
                "workspace operation record does not match the admitted operation"
            )
        fence = await self._repository.get_fence(record.workspace_id)
        authorised, owned_fence = await self._repository.authorise_mutation(
            WorkspaceAuthorisationRequest(
                operation=operation,
                decision=decision,
                record=record,
                expected_fence_version=fence.fence_version,
                required_scope_digest=request.required_scope_digest,
                normalized_target_digest=request.normalized_target_digest,
                authorised_at=decision.decided_at,
            )
        )
        if owned_fence.active_operation_id != operation.operation_id:
            raise WorkspaceCapabilityUnavailable(
                "workspace authorisation did not retain its exact fence"
            )
        return authorised


class WorkspaceMutationDispatchAuthority:
    """Acquire the exact session gate after the per-operation dispatch handoff."""

    def __init__(
        self,
        *,
        repository: WorkspaceRepository,
        session_gate: DevelopmentSessionAuthorityGate,
    ) -> None:
        self._repository = repository
        self._session_gate = session_gate

    @asynccontextmanager
    async def hold(
        self,
        *,
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> AsyncIterator[None]:
        del request
        record = await self._repository.get_operation(operation.operation_id)
        if record is None:
            raise WorkspaceCapabilityUnavailable("workspace operation authority is missing")
        fence = await self._repository.get_fence(record.workspace_id)
        if fence.active_operation_id != operation.operation_id:
            raise WorkspaceCapabilityUnavailable("workspace mutation fence is not exact-self")
        async with self._session_gate.hold_member_start(
            session_id=record.session_id,
            workspace_id=record.workspace_id,
        ):
            current = await self._repository.get_fence(record.workspace_id)
            if current != fence:
                raise WorkspaceCapabilityUnavailable(
                    "workspace mutation fence changed before consequential start"
                )
            yield


class WorkspaceMutationClosure:
    """Release durable CHANGE only after exact terminal/audit/domain proof."""

    def __init__(
        self,
        *,
        repository: WorkspaceRepository,
        release_verifier: WorkspaceReleaseVerifier,
    ) -> None:
        self._repository = repository
        self._release_verifier = release_verifier

    async def close(
        self,
        *,
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        del request
        return await self.close_retained(operation)

    async def close_retained(self, operation: OperationSnapshot) -> OperationSnapshot:
        """Close one retained mutation from its durable operation/fence projection."""

        record = await self._repository.get_operation(operation.operation_id)
        if record is None:
            raise WorkspaceCapabilityUnavailable("workspace operation closure is missing")
        fence = await self._repository.get_fence(record.workspace_id)
        if fence.active_operation_id != operation.operation_id:
            raise WorkspaceCapabilityUnavailable("workspace closure fence is not exact-self")
        releasable = (
            operation.terminality is Terminality.TERMINAL
            and operation.effect_knowledge
            in {EffectKnowledge.KNOWN_NO_EFFECT, EffectKnowledge.KNOWN_EFFECT}
            and await self._release_verifier(operation, record)
        )
        if not releasable:
            return operation
        released = await self._repository.release_fence(
            workspace_id=record.workspace_id,
            expected_version=fence.fence_version,
            operation_id=operation.operation_id,
            released_at=datetime.now(UTC),
        )
        if released.active_operation_id is not None:
            raise WorkspaceCapabilityUnavailable("workspace fence release was not durable")
        return operation


class WorkspaceMutationBoundaryVerifier:
    """Re-prove durable self-ownership and the registered mount immediately pre-start."""

    def __init__(
        self,
        *,
        repository: WorkspaceRepository,
        filesystem: WorkspaceFilesystem,
    ) -> None:
        self._repository = repository
        self._filesystem = filesystem

    async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult:
        readiness = await self._filesystem.mutation_readiness()
        if not readiness.available:
            reason = readiness.reason_code
            if reason is None:
                raise WorkspaceCapabilityUnavailable(
                    "workspace mutation readiness contract violated"
                )
            return BoundaryCheckResult(False, reason)
        record = await self._repository.get_operation(request.operation_id)
        if record is None:
            return BoundaryCheckResult(False, "workspace_operation_missing")
        registration = await self._repository.require_registration(record.workspace_id)
        fence = await self._repository.get_fence(record.workspace_id)
        root = await self._filesystem.root_identity()
        predicates = request.predicates
        if (
            fence.active_operation_id != request.operation_id
            or fence.active_contract is None
            or registration.workspace_id != record.workspace_id
            or registration.profile_sha256 != root.profile_sha256
            or registration.root_identity_sha256 != root.identity_sha256
            or registration.mount_identity_sha256 != root.mount.digest_sha256
            or registration.root_device != root.device
            or registration.root_inode != root.inode
            or registration.mount_id != root.mount.mount_id
            or registration.mount_device != root.mount.device
            or registration.filesystem_type != root.mount.filesystem_type
            or registration.owner_uid != root.owner_uid
            or registration.owner_gid != root.owner_gid
            or registration.mode != root.mode
            or record.expected_mount_identity_sha256 != root.mount.digest_sha256
            or predicates.get("workspace_id") != record.workspace_id
            or predicates.get("session_id") != record.session_id
            or predicates.get("root_identity_sha256") != root.identity_sha256
            or predicates.get("mount_identity_sha256") != root.mount.digest_sha256
            or predicates.get("state_binding_sha256") != record.state_binding_sha256
            or predicates.get("expected_object_sha256") != record.expected_object_sha256
            or predicates.get("expected_content_sha256") != record.expected_content_sha256
            or predicates.get("expected_link_count") != record.expected_link_count
            or predicates.get("proposed_content_sha256") != record.proposed_content_sha256
            or predicates.get("proposed_byte_count") != record.proposed_byte_count
            or predicates.get("primitive_profile_version") != record.primitive_profile_version
            or predicates.get("staging_reference_sha256") != record.staging_reference_sha256
        ):
            return BoundaryCheckResult(False, "workspace_boundary_identity_mismatch")
        relative_path = predicates.get("relative_path")
        if not isinstance(relative_path, str):
            return BoundaryCheckResult(False, "workspace_boundary_path_missing")
        normalized = normalize_workspace_path(relative_path)
        expected_path = (
            record.target_path_sha256
            if record.mutation_kind is WorkspaceMutationKind.CREATE
            else record.source_path_sha256
        )
        if workspace_path_sha256(normalized) != expected_path:
            return BoundaryCheckResult(False, "workspace_boundary_path_mismatch")
        scope = normalized
        if record.mutation_kind is WorkspaceMutationKind.CREATE:
            scope = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
        await self._filesystem.verify_scope_no_submounts(scope)
        return BoundaryCheckResult(True, "workspace_boundary_verified")


class WorkspaceMutationEffectBoundary:
    """Dispatch only protected create/write intents selected by the application."""

    def __init__(self, filesystem: WorkspaceFilesystem) -> None:
        self._filesystem = filesystem

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        try:
            if request.effect_type == "workspace_create":
                receipt = await self._filesystem.create(_create_intent(request))
            elif request.effect_type == "workspace_write":
                receipt = await self._filesystem.write(_write_intent(request))
            else:
                return EffectStartReceipt(
                    crossing=BoundaryCrossing.DEFINITELY_NOT_CROSSED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    terminal_state=OperationState.FAILED,
                    reason_code="workspace_effect_type_unavailable",
                )
        except WorkspaceEffectNotStarted:
            return EffectStartReceipt(
                crossing=BoundaryCrossing.DEFINITELY_NOT_CROSSED,
                effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                terminal_state=OperationState.FAILED,
                reason_code="workspace_effect_not_started",
            )
        except WorkspaceEffectUncertain:
            return EffectStartReceipt(
                crossing=BoundaryCrossing.UNCERTAIN,
                effect_knowledge=EffectKnowledge.UNCERTAIN,
                terminal_state=OperationState.UNCERTAIN,
                reason_code="workspace_effect_uncertain",
            )
        return EffectStartReceipt(
            crossing=BoundaryCrossing.CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference=receipt.reference,
            reference_digest=receipt.reference_sha256,
            terminal_state=OperationState.SUCCEEDED,
            reason_code="workspace_effect_verified",
        )


def _create_intent(request: EffectRequest) -> WorkspaceCreateIntent:
    arguments = request.protected_arguments
    kind_value = _text(arguments, "kind")
    try:
        kind = WorkspaceObjectKind(kind_value)
    except ValueError as exc:
        raise WorkspaceEffectNotStarted("workspace create kind is invalid") from exc
    if kind not in {WorkspaceObjectKind.REGULAR_FILE, WorkspaceObjectKind.DIRECTORY}:
        raise WorkspaceEffectNotStarted("workspace create kind is unavailable")
    return WorkspaceCreateIntent(
        operation_id=request.operation_id,
        relative_path=_text(arguments, "relative_path"),
        kind=kind,
        content=_bytes(arguments, "content"),
        mode=_integer(arguments, "mode"),
        expected_root_identity_sha256=_digest(arguments, "root_identity_sha256"),
        expected_mount_identity_sha256=_digest(arguments, "mount_identity_sha256"),
    )


def _write_intent(request: EffectRequest) -> WorkspaceWriteIntent:
    arguments = request.protected_arguments
    return WorkspaceWriteIntent(
        operation_id=request.operation_id,
        relative_path=_text(arguments, "relative_path"),
        content=_bytes(arguments, "content"),
        expected_object_version=_digest(arguments, "expected_object_version"),
        expected_content_sha256=_digest(arguments, "expected_content_sha256"),
        expected_root_identity_sha256=_digest(arguments, "root_identity_sha256"),
        expected_mount_identity_sha256=_digest(arguments, "mount_identity_sha256"),
    )


def _text(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise WorkspaceEffectNotStarted(f"workspace effect {key} is not text")
    return value


def _bytes(arguments: Mapping[str, object], key: str) -> bytes:
    value = arguments.get(key)
    if not isinstance(value, bytes):
        raise WorkspaceEffectNotStarted(f"workspace effect {key} is not bytes")
    return value


def _integer(arguments: Mapping[str, object], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkspaceEffectNotStarted(f"workspace effect {key} is not an integer")
    return value


def _digest(arguments: Mapping[str, object], key: str) -> str:
    value = _text(arguments, key)
    try:
        return validate_sha256(value, name=key)
    except ValueError as exc:
        raise WorkspaceEffectNotStarted(f"workspace effect {key} is invalid") from exc


__all__ = [
    "WorkspaceCapabilityUnavailable",
    "WorkspaceChangePostPolicyAuthority",
    "WorkspaceMutationAuthoriser",
    "WorkspaceMutationBoundaryVerifier",
    "WorkspaceMutationClosure",
    "WorkspaceMutationDispatchAuthority",
    "WorkspaceMutationEffectBoundary",
    "WorkspaceReadPolicy",
    "WorkspaceReadService",
]

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from tests.phase4_support import intent, owner

from binnacle.application.development_session import (
    DevelopmentSessionAuthorityError,
    DevelopmentSessionAuthorityGate,
)
from binnacle.application.operations import CoordinatedOperationRequest
from binnacle.application.workspace import (
    WorkspaceCapabilityUnavailable,
    WorkspaceChangePostPolicyAuthority,
    WorkspaceMutationAuthoriser,
    WorkspaceMutationBoundaryVerifier,
    WorkspaceMutationClosure,
    WorkspaceMutationDispatchAuthority,
    WorkspaceMutationEffectBoundary,
    WorkspaceReadPolicy,
    WorkspaceReadService,
)
from binnacle.application.workspace_coordination import WorkspaceAccessGate
from binnacle.domain.development_session import (
    DevelopmentSessionSnapshot,
    SessionAuthorityFacts,
    activate_session,
    complete_activation,
    new_pending_session,
)
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
    new_received_operation,
    transition,
)
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.domain.workspace import (
    MountIdentity,
    WorkspaceFence,
    WorkspaceMutationKind,
    WorkspaceObjectIdentity,
    WorkspaceObjectKind,
    WorkspaceRootIdentity,
    canonical_sha256,
    object_version,
    workspace_path_sha256,
)
from binnacle.ports.boundary import OperationBoundaryCheck
from binnacle.ports.effect import BoundaryCrossing, EffectRequest
from binnacle.ports.operation_store import CreateOrFindRequest
from binnacle.ports.workspace import (
    RegisteredWorkspaceSnapshot,
    WorkspaceAuthorisationRequest,
    WorkspaceCreateIntent,
    WorkspaceEffectReceipt,
    WorkspaceEntry,
    WorkspaceInspectRequest,
    WorkspaceListing,
    WorkspaceListRequest,
    WorkspaceOperationRecord,
    WorkspaceReadRequest,
    WorkspaceReadResult,
    WorkspaceRepository,
    WorkspaceWriteIntent,
)

NOW = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
DIGEST = "a" * 64


class FixtureFilesystem:
    def __init__(self) -> None:
        mount = MountIdentity(7, 1, "ext4", DIGEST)
        self.root = WorkspaceRootIdentity(
            "workspace",
            DIGEST,
            DIGEST,
            mount,
            1,
            2,
            1000,
            1000,
            0o40750,
        )
        self.identity = WorkspaceObjectIdentity(
            "workspace",
            DIGEST,
            DIGEST,
            DIGEST,
            "src/file.py",
            WorkspaceObjectKind.REGULAR_FILE,
            1,
            3,
            0o100644,
            7,
            10,
            1,
            canonical_sha256(b"content".hex()),
        )
        self.read_count = 0
        self.create_count = 0
        self.verified_scopes: list[str] = []

    async def initialize(self) -> WorkspaceRootIdentity:
        return self.root

    async def root_identity(self) -> WorkspaceRootIdentity:
        return self.root

    async def verify_scope_no_submounts(self, relative_path: str) -> None:
        self.verified_scopes.append(relative_path)

    async def inspect(self, request: WorkspaceInspectRequest) -> WorkspaceEntry:
        del request
        return WorkspaceEntry(
            self.identity.relative_path,
            self.identity.kind,
            self.identity,
            object_version(self.identity),
        )

    async def list(self, request: WorkspaceListRequest) -> WorkspaceListing:
        del request
        entry = await self.inspect(WorkspaceInspectRequest("src/file.py", DIGEST, DIGEST))
        return WorkspaceListing("src", (entry,), False)

    async def read(self, request: WorkspaceReadRequest) -> WorkspaceReadResult:
        self.read_count += 1
        assert request.permit.workspace_id == "workspace"
        return WorkspaceReadResult(
            request.relative_path,
            b"content",
            request.offset,
            None,
            True,
            self.identity,
            object_version(self.identity),
            self.identity.content_sha256,
        )

    async def create(self, intent: WorkspaceCreateIntent) -> WorkspaceEffectReceipt:
        self.create_count += 1
        return self._receipt(intent.operation_id, WorkspaceMutationKind.CREATE)

    async def write(self, intent: WorkspaceWriteIntent) -> WorkspaceEffectReceipt:
        return self._receipt(intent.operation_id, WorkspaceMutationKind.WRITE)

    def _receipt(
        self, operation_id: str, mutation: WorkspaceMutationKind
    ) -> WorkspaceEffectReceipt:
        reference = f"workspace:{operation_id}"
        return WorkspaceEffectReceipt(
            operation_id,
            mutation,
            self.identity.relative_path,
            self.identity,
            object_version(self.identity),
            self.identity.content_sha256,
            None,
            "linux-v1",
            "parent_fsync",
            reference,
            canonical_sha256(reference),
        )


class FixtureWorkspaceRepository:
    def __init__(
        self,
        *,
        root: WorkspaceRootIdentity,
        operation: OperationSnapshot,
        record: WorkspaceOperationRecord,
    ) -> None:
        self.operation = operation
        self.record = record
        self.fence = WorkspaceFence(record.workspace_id, 1, None, None)
        self.registration = RegisteredWorkspaceSnapshot(
            workspace_id=record.workspace_id,
            profile_sha256=root.profile_sha256,
            root_identity_sha256=root.identity_sha256,
            mount_identity_sha256=root.mount.digest_sha256,
            root_device=root.device,
            root_inode=root.inode,
            mount_id=root.mount.mount_id,
            mount_device=root.mount.device,
            filesystem_type=root.mount.filesystem_type,
            owner_uid=root.owner_uid,
            owner_gid=root.owner_gid,
            mode=root.mode,
            primitive_profile_version=record.primitive_profile_version,
            registration_version=1,
            registered_at=NOW,
            updated_at=NOW,
        )
        self.authorisation: WorkspaceAuthorisationRequest | None = None

    async def get_fence(self, workspace_id: str) -> WorkspaceFence:
        assert workspace_id == self.record.workspace_id
        return self.fence

    async def get_operation(self, operation_id: str) -> WorkspaceOperationRecord | None:
        return self.record if operation_id == self.record.operation_id else None

    async def require_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot:
        assert workspace_id == self.registration.workspace_id
        return self.registration

    async def authorise_mutation(
        self, request: WorkspaceAuthorisationRequest
    ) -> tuple[OperationSnapshot, WorkspaceFence]:
        assert request.expected_fence_version == self.fence.fence_version
        self.authorisation = request
        self.operation = transition(
            request.operation,
            TransitionRequest(
                request.operation.state_version,
                OperationState.AUTHORISED,
                EffectKnowledge.NONE,
                "policy_allowed",
                occurred_at=request.authorised_at,
            ),
        )
        self.fence = WorkspaceFence(
            self.record.workspace_id,
            self.fence.fence_version + 1,
            self.operation.operation_id,
            self.operation.intent.operation_contract,
        )
        return self.operation, self.fence

    async def release_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        released_at: datetime,
    ) -> WorkspaceFence:
        del released_at
        assert workspace_id == self.fence.workspace_id
        assert expected_version == self.fence.fence_version
        assert operation_id == self.fence.active_operation_id
        self.fence = WorkspaceFence(workspace_id, expected_version + 1, None, None)
        return self.fence


def _received_operation() -> OperationSnapshot:
    return new_received_operation(owner=owner(), intent=intent(), now=NOW)


def _workspace_record(operation: OperationSnapshot) -> WorkspaceOperationRecord:
    staging = f".binnacle-staging/{operation.operation_id}.tmp"
    return WorkspaceOperationRecord(
        operation_id=operation.operation_id,
        session_id="dev_session",
        workspace_id="workspace",
        mutation_kind=WorkspaceMutationKind.CREATE,
        object_kind=WorkspaceObjectKind.REGULAR_FILE,
        source_path_sha256=None,
        target_path_sha256=workspace_path_sha256("src/file.py"),
        expected_object_sha256=None,
        expected_content_sha256=None,
        expected_link_count=None,
        expected_mount_identity_sha256=DIGEST,
        proposed_content_sha256=canonical_sha256(b"content".hex()),
        proposed_byte_count=7,
        state_binding_sha256="b" * 64,
        staging_reference=staging,
        staging_reference_sha256=canonical_sha256(staging),
        primitive_profile_version="linux-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _decision(operation: OperationSnapshot) -> PolicyDecision:
    return PolicyDecision(
        "decision_workspace",
        operation.operation_id,
        "bootstrap-policy",
        "1.0.0",
        PolicyDecisionValue.ALLOW,
        ("policy_allowed",),
        "c" * 64,
        "d" * 64,
        NOW,
    )


def _coordinated_request(operation: OperationSnapshot) -> CoordinatedOperationRequest:
    return CoordinatedOperationRequest(
        admission=CreateOrFindRequest(
            key=validate_and_digest_key("1" * 64, IdempotencyKeyMode.CALLER_KEY),
            owner=operation.owner,
            intent=operation.intent,
            tool_name="internal.workspace_create",
            contract_version="1.0.0",
        ),
        required_scope_digest="e" * 64,
        normalized_target_digest="f" * 64,
        boundary_predicates={
            "workspace_id": "workspace",
            "session_id": "dev_session",
            "root_identity_sha256": DIGEST,
            "mount_identity_sha256": DIGEST,
            "state_binding_sha256": "b" * 64,
            "expected_object_sha256": None,
            "expected_content_sha256": None,
            "expected_link_count": None,
            "proposed_content_sha256": canonical_sha256(b"content".hex()),
            "proposed_byte_count": 7,
            "primitive_profile_version": "linux-v1",
            "staging_reference_sha256": canonical_sha256(
                f".binnacle-staging/{operation.operation_id}.tmp"
            ),
            "relative_path": "src/file.py",
        },
        effect_type="workspace_create",
        protected_effect_arguments={},
    )


def _session() -> DevelopmentSessionSnapshot:
    pending = new_pending_session(
        session_id="dev_session",
        begin_operation_id="op_begin",
        controller_id="controller",
        controller_epoch=1,
        device_id="device",
        device_epoch=1,
        workspace_id="workspace",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        objective_sha256=DIGEST,
        expires_at=NOW + timedelta(hours=1),
        trusted_time_generation=1,
        activation_boot_id_digest=DIGEST,
        monotonic_deadline_ns=10_000,
        now=NOW,
    )
    return complete_activation(
        activate_session(
            pending,
            expected_state_version=1,
            effect_reference="activation_ref",
            effect_reference_sha256=DIGEST,
            now=NOW + timedelta(seconds=1),
        ),
        expected_state_version=2,
    )


def _facts(*, ready: bool = True) -> SessionAuthorityFacts:
    return SessionAuthorityFacts(
        "controller",
        1,
        "device",
        1,
        "workspace",
        DIGEST,
        DIGEST,
        DIGEST,
        "policy-v1",
        DIGEST,
        NOW + timedelta(minutes=1),
        True,
        1,
        DIGEST,
        1_000,
        ready,
    )


async def _service(
    filesystem: FixtureFilesystem,
    *,
    ready: bool = True,
) -> tuple[WorkspaceReadService, WorkspaceAccessGate]:
    snapshot = _session()

    async def read_session(session_id: str) -> DevelopmentSessionSnapshot | None:
        return snapshot if session_id == snapshot.session_id else None

    async def read_facts(_snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return _facts(ready=ready)

    access = WorkspaceAccessGate("workspace")
    await access.open_after_recovery(
        fence=_free_fence(),
        search_children_quiesced=True,
        root_mount_verified=True,
    )
    service = WorkspaceReadService(
        workspace_id="workspace",
        filesystem=filesystem,
        access_gate=access,
        session_gate=DevelopmentSessionAuthorityGate(
            session_reader=read_session,
            facts_reader=read_facts,
        ),
        policy=WorkspaceReadPolicy(4 * 1024 * 1024, 100, 1024),
    )
    return service, access


def _free_fence() -> WorkspaceFence:
    return WorkspaceFence("workspace", 1, None, None)


@pytest.mark.anyio
async def test_read_holds_content_guard_and_returns_only_after_session_permit() -> None:
    filesystem = FixtureFilesystem()
    service, access = await _service(filesystem)
    result = await service.read(session_id="dev_session", relative_path="src/file.py")
    assert result.content == b"content"
    assert filesystem.read_count == 1
    assert access.content_reader_count == 0


@pytest.mark.anyio
async def test_unhealthy_session_returns_zero_source_bytes() -> None:
    filesystem = FixtureFilesystem()
    service, access = await _service(filesystem, ready=False)
    with pytest.raises(DevelopmentSessionAuthorityError, match="kernel_unavailable"):
        await service.read(session_id="dev_session", relative_path="src/file.py")
    assert filesystem.read_count == 0
    assert access.content_reader_count == 0


@pytest.mark.anyio
async def test_metadata_inspect_cannot_hash_content_without_content_permit() -> None:
    filesystem = FixtureFilesystem()
    service, access = await _service(filesystem)

    with pytest.raises(
        WorkspaceCapabilityUnavailable,
        match="content-bearing workspace inspection is not promoted",
    ):
        await service.inspect(
            session_id="dev_session",
            relative_path="src/file.py",
            include_content_digest=True,
        )

    assert filesystem.read_count == 0
    assert access.content_reader_count == 0


@pytest.mark.anyio
async def test_metadata_surfaces_and_read_bounds_remain_closed() -> None:
    filesystem = FixtureFilesystem()
    service, _access = await _service(filesystem)

    inspected = await service.inspect(session_id="dev_session", relative_path="src/file.py")
    assert inspected.relative_path == "src/file.py"
    listing = await service.list(session_id="dev_session", relative_path="src")
    assert tuple(entry.relative_path for entry in listing.entries) == ("src/file.py",)

    for offset, maximum in ((-1, 1), (0, 0), (0, 1025)):
        with pytest.raises(ValueError, match="outside the configured bound"):
            await service.read(
                session_id="dev_session",
                relative_path="src/file.py",
                offset=offset,
                maximum_bytes=maximum,
            )
    with pytest.raises(WorkspaceCapabilityUnavailable, match="search is not promoted"):
        await service.search()

    with pytest.raises(ValueError, match="limits must be positive"):
        WorkspaceReadService(
            workspace_id="workspace",
            filesystem=filesystem,
            access_gate=WorkspaceAccessGate("workspace"),
            session_gate=DevelopmentSessionAuthorityGate(
                session_reader=lambda _session_id: _session_coroutine(),
                facts_reader=lambda _snapshot: _facts_coroutine(),
            ),
            policy=WorkspaceReadPolicy(1, 0, 1),
        )


async def _session_coroutine() -> DevelopmentSessionSnapshot:
    return _session()


async def _facts_coroutine() -> SessionAuthorityFacts:
    return _facts()


@pytest.mark.anyio
async def test_mutation_authority_holds_change_through_atomic_fence_and_closure() -> None:
    filesystem = FixtureFilesystem()
    received = _received_operation()
    record = _workspace_record(received)
    repository = FixtureWorkspaceRepository(
        root=filesystem.root,
        operation=received,
        record=record,
    )
    repository_port = cast(WorkspaceRepository, repository)
    access = WorkspaceAccessGate("workspace")
    await access.open_after_recovery(
        fence=repository.fence,
        search_children_quiesced=True,
        root_mount_verified=True,
    )
    authority = WorkspaceChangePostPolicyAuthority(
        workspace_id="workspace",
        access_gate=access,
        repository=repository_port,
    )

    async def read_record(
        operation: OperationSnapshot,
        request: CoordinatedOperationRequest,
    ) -> WorkspaceOperationRecord:
        del request
        assert operation.operation_id == record.operation_id
        return record

    authoriser = WorkspaceMutationAuthoriser(
        repository=repository_port,
        record_reader=read_record,
    )
    decision = _decision(received)
    request = _coordinated_request(received)
    async with authority.hold(operation=received, decision=decision, request=request):
        authorised = await authoriser.authorise(
            operation=received,
            decision=decision,
            request=request,
        )
        assert access.change_operation_id == received.operation_id
        assert repository.fence.active_operation_id == received.operation_id
        assert repository.authorisation is not None
        assert repository.authorisation.authorised_at == decision.decided_at
        running = transition(
            authorised,
            TransitionRequest(
                authorised.state_version,
                OperationState.RUNNING,
                EffectKnowledge.NONE,
                "dispatch_attempt_recorded",
                occurred_at=NOW,
            ),
        )
        succeeded = transition(
            running,
            TransitionRequest(
                running.state_version,
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "workspace_effect_verified",
                effect_reference="workspace:effect",
                effect_reference_digest="9" * 64,
                occurred_at=NOW,
            ),
        )

        async def release_verified(
            operation: OperationSnapshot,
            retained_record: WorkspaceOperationRecord,
        ) -> bool:
            return operation is succeeded and retained_record.operation_id == operation.operation_id

        closed = await WorkspaceMutationClosure(
            repository=repository_port,
            release_verifier=release_verified,
        ).close(operation=succeeded, request=request)
        assert closed is succeeded
        assert repository.fence.active_operation_id is None

    assert access.change_operation_id is None
    assert repository.authorisation is not None
    assert repository.authorisation.required_scope_digest == "e" * 64


@pytest.mark.anyio
async def test_uncertain_mutation_retains_fence_and_recovery_closes_access() -> None:
    filesystem = FixtureFilesystem()
    operation = _received_operation()
    record = _workspace_record(operation)
    repository = FixtureWorkspaceRepository(
        root=filesystem.root,
        operation=operation,
        record=record,
    )
    repository_port = cast(WorkspaceRepository, repository)
    repository.fence = WorkspaceFence(
        "workspace",
        2,
        operation.operation_id,
        operation.intent.operation_contract,
    )
    access = WorkspaceAccessGate("workspace")
    await access.open_after_recovery(
        fence=WorkspaceFence("workspace", 1, None, None),
        search_children_quiesced=True,
        root_mount_verified=True,
    )
    authority = WorkspaceChangePostPolicyAuthority(
        workspace_id="workspace",
        access_gate=access,
        repository=repository_port,
    )
    request = _coordinated_request(operation)
    async with authority.hold(
        operation=operation,
        decision=_decision(operation),
        request=request,
    ):
        assert access.change_operation_id == operation.operation_id

    assert access.state.value == "recovery_closed"
    assert repository.fence.active_operation_id == operation.operation_id


@pytest.mark.anyio
async def test_dispatch_and_final_boundary_require_exact_session_fence_and_mount() -> None:
    filesystem = FixtureFilesystem()
    operation = _received_operation()
    record = _workspace_record(operation)
    repository = FixtureWorkspaceRepository(
        root=filesystem.root,
        operation=operation,
        record=record,
    )
    repository_port = cast(WorkspaceRepository, repository)
    repository.fence = WorkspaceFence(
        "workspace",
        2,
        operation.operation_id,
        operation.intent.operation_contract,
    )
    snapshot = _session()

    async def read_session(session_id: str) -> DevelopmentSessionSnapshot | None:
        return snapshot if session_id == snapshot.session_id else None

    async def read_facts(_snapshot: DevelopmentSessionSnapshot) -> SessionAuthorityFacts:
        return _facts()

    dispatch = WorkspaceMutationDispatchAuthority(
        repository=repository_port,
        session_gate=DevelopmentSessionAuthorityGate(
            session_reader=read_session,
            facts_reader=read_facts,
        ),
    )
    request = _coordinated_request(operation)
    async with dispatch.hold(operation=operation, request=request):
        verifier = WorkspaceMutationBoundaryVerifier(
            repository=repository_port,
            filesystem=filesystem,
        )
        decision = await verifier.verify(
            OperationBoundaryCheck(
                operation.operation_id,
                3,
                request.boundary_predicates,
            )
        )
        assert decision.allowed
        assert filesystem.verified_scopes == ["src"]

        stale = await verifier.verify(
            OperationBoundaryCheck(
                operation.operation_id,
                3,
                {**request.boundary_predicates, "mount_identity_sha256": "0" * 64},
            )
        )
        assert not stale.allowed
        assert stale.reason_code == "workspace_boundary_identity_mismatch"

    repository.fence = replace(repository.fence, active_operation_id=None, active_contract=None)
    with pytest.raises(WorkspaceCapabilityUnavailable, match="not exact-self"):
        async with dispatch.hold(operation=operation, request=request):
            pytest.fail("foreign/missing fence must not enter the session gate")


@pytest.mark.anyio
async def test_effect_boundary_dispatches_only_closed_create_and_write_shapes() -> None:
    filesystem = FixtureFilesystem()
    boundary = WorkspaceMutationEffectBoundary(filesystem)
    create = await boundary.start(
        EffectRequest(
            "op_create",
            3,
            "workspace_create",
            {
                "relative_path": "src/file.py",
                "kind": "regular_file",
                "content": b"content",
                "mode": 0o644,
                "root_identity_sha256": DIGEST,
                "mount_identity_sha256": DIGEST,
            },
        )
    )
    assert create.crossing is BoundaryCrossing.CROSSED
    assert create.effect_knowledge is EffectKnowledge.KNOWN_EFFECT
    assert create.terminal_state is OperationState.SUCCEEDED
    assert filesystem.create_count == 1

    rejected = await boundary.start(
        EffectRequest("op_other", 3, "workspace_delete", {"relative_path": "src/file.py"})
    )
    assert rejected.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED
    assert filesystem.create_count == 1

    write = await boundary.start(
        EffectRequest(
            "op_write",
            3,
            "workspace_write",
            {
                "relative_path": "src/file.py",
                "content": b"replacement",
                "expected_object_version": DIGEST,
                "expected_content_sha256": DIGEST,
                "root_identity_sha256": DIGEST,
                "mount_identity_sha256": DIGEST,
            },
        )
    )
    assert write.crossing is BoundaryCrossing.CROSSED


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"kind": "not-a-kind"},
        {"kind": "symlink"},
        {"kind": "regular_file", "relative_path": 7},
        {"kind": "regular_file", "relative_path": "src/new", "content": "text"},
        {
            "kind": "regular_file",
            "relative_path": "src/new",
            "content": b"x",
            "mode": True,
        },
        {
            "kind": "regular_file",
            "relative_path": "src/new",
            "content": b"x",
            "mode": 0o644,
            "root_identity_sha256": "invalid",
            "mount_identity_sha256": DIGEST,
        },
    ],
)
async def test_effect_boundary_rejects_every_malformed_protected_shape(
    arguments: dict[str, object],
) -> None:
    boundary = WorkspaceMutationEffectBoundary(FixtureFilesystem())
    receipt = await boundary.start(EffectRequest("op_create", 3, "workspace_create", arguments))
    assert receipt.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED
    assert receipt.reason_code == "workspace_effect_not_started"


@pytest.mark.anyio
async def test_boundary_reports_missing_and_path_mismatch_without_filesystem_effect() -> None:
    filesystem = FixtureFilesystem()
    operation = _received_operation()
    record = _workspace_record(operation)
    repository = FixtureWorkspaceRepository(
        root=filesystem.root,
        operation=operation,
        record=record,
    )
    repository_port = cast(WorkspaceRepository, repository)
    verifier = WorkspaceMutationBoundaryVerifier(
        repository=repository_port,
        filesystem=filesystem,
    )
    request = _coordinated_request(operation)

    missing = await verifier.verify(
        OperationBoundaryCheck("op_missing", 3, request.boundary_predicates)
    )
    assert missing.reason_code == "workspace_operation_missing"

    repository.fence = WorkspaceFence(
        "workspace", 2, operation.operation_id, operation.intent.operation_contract
    )
    no_path = await verifier.verify(
        OperationBoundaryCheck(
            operation.operation_id,
            3,
            {**request.boundary_predicates, "relative_path": None},
        )
    )
    assert no_path.reason_code == "workspace_boundary_path_missing"
    wrong_path = await verifier.verify(
        OperationBoundaryCheck(
            operation.operation_id,
            3,
            {**request.boundary_predicates, "relative_path": "src/other.py"},
        )
    )
    assert wrong_path.reason_code == "workspace_boundary_path_mismatch"

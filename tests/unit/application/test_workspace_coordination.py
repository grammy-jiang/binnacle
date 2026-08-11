from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from binnacle.application.workspace_coordination import (
    WorkspaceAccessCoordinator,
    WorkspaceAccessGate,
    WorkspaceAccessState,
    WorkspaceCoordinationError,
)
from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.workspace import WorkspaceFence
from binnacle.ports.workspace import (
    RegisteredWorkspaceSnapshot,
    WorkspaceAuthorisationRequest,
    WorkspaceOperationRecord,
)

NOW = datetime(2026, 8, 12, 2, 0, tzinfo=UTC)


class FenceRepository:
    def __init__(self) -> None:
        self.fence = WorkspaceFence("workspace", 1, None, None)
        self.fail_acquire = False
        self.release_started = asyncio.Event()
        self.release_continue = asyncio.Event()
        self.block_release = False

    async def get_fence(self, workspace_id: str) -> WorkspaceFence:
        assert workspace_id == "workspace"
        return self.fence

    async def acquire_fence(
        self,
        *,
        workspace_id: str,
        expected_version: int,
        operation_id: str,
        contract: str,
        acquired_at: datetime,
    ) -> WorkspaceFence:
        del acquired_at
        if self.fail_acquire:
            raise RuntimeError("injected acquire failure")
        assert workspace_id == self.fence.workspace_id
        assert expected_version == self.fence.fence_version
        assert self.fence.active_operation_id is None
        self.fence = WorkspaceFence(
            workspace_id,
            expected_version + 1,
            operation_id,
            contract,
        )
        return self.fence

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
        self.release_started.set()
        if self.block_release:
            await self.release_continue.wait()
        self.fence = WorkspaceFence(workspace_id, expected_version + 1, None, None)
        return self.fence

    async def register_workspace(
        self, registration: RegisteredWorkspaceSnapshot
    ) -> RegisteredWorkspaceSnapshot:
        raise NotImplementedError

    async def get_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot | None:
        del workspace_id
        raise NotImplementedError

    async def require_registration(self, workspace_id: str) -> RegisteredWorkspaceSnapshot:
        del workspace_id
        raise NotImplementedError

    async def authorise_mutation(
        self,
        request: WorkspaceAuthorisationRequest,
    ) -> tuple[OperationSnapshot, WorkspaceFence]:
        del request
        raise NotImplementedError

    async def get_operation(self, operation_id: str) -> WorkspaceOperationRecord | None:
        del operation_id
        raise NotImplementedError

    async def list_operations(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[WorkspaceOperationRecord, ...]:
        del limit, after_created_at, after_operation_id
        raise NotImplementedError

    async def verify_integrity(self) -> None:
        raise NotImplementedError


async def _open(gate: WorkspaceAccessGate, repository: FenceRepository) -> None:
    await gate.open_after_recovery(
        fence=repository.fence,
        search_children_quiesced=True,
        root_mount_verified=True,
    )


@pytest.mark.anyio
async def test_content_guards_share_but_exclude_change() -> None:
    repository = FenceRepository()
    gate = WorkspaceAccessGate("workspace")
    await _open(gate, repository)
    first = await gate.acquire_content_read()
    second = await gate.acquire_content_read()
    waiting_change = asyncio.create_task(gate.acquire_change("op_change"))
    await asyncio.sleep(0)
    assert not waiting_change.done()
    await gate.release_content_read(first)
    assert not waiting_change.done()
    await gate.release_content_read(second)
    change = await waiting_change
    waiting_content = asyncio.create_task(gate.acquire_content_read())
    await asyncio.sleep(0)
    assert not waiting_content.done()
    await gate.release_change(change)
    content = await waiting_content
    await gate.release_content_read(content)


@pytest.mark.anyio
async def test_recovery_never_opens_with_retained_fence_or_missing_predicate() -> None:
    repository = FenceRepository()
    gate = WorkspaceAccessGate("workspace")
    repository.fence = WorkspaceFence("workspace", 2, "op_uncertain", "workspace_write")
    coordinator = WorkspaceAccessCoordinator(gate=gate, repository=repository)
    retained = await coordinator.recover(
        workspace_id="workspace",
        search_children_quiesced=True,
        root_mount_verified=True,
    )
    assert retained.active_operation_id == "op_uncertain"
    assert gate.state is WorkspaceAccessState.RECOVERY_CLOSED
    with pytest.raises(WorkspaceCoordinationError, match="recovery-closed"):
        await gate.acquire_content_read()

    repository.fence = WorkspaceFence("workspace", 3, None, None)
    with pytest.raises(WorkspaceCoordinationError, match="incomplete"):
        await coordinator.recover(
            workspace_id="workspace",
            search_children_quiesced=False,
            root_mount_verified=True,
        )


@pytest.mark.anyio
async def test_durable_acquire_failure_releases_process_guard() -> None:
    repository = FenceRepository()
    repository.fail_acquire = True
    gate = WorkspaceAccessGate("workspace")
    await _open(gate, repository)
    coordinator = WorkspaceAccessCoordinator(gate=gate, repository=repository)
    with pytest.raises(RuntimeError, match="injected"):
        await coordinator.acquire_change(
            workspace_id="workspace",
            operation_id="op_change",
            contract="workspace_write",
            now=NOW,
        )
    assert gate.change_operation_id is None
    content = await gate.acquire_content_read()
    await gate.release_content_read(content)


@pytest.mark.anyio
async def test_release_keeps_change_exclusive_until_durable_fence_is_free() -> None:
    repository = FenceRepository()
    repository.block_release = True
    gate = WorkspaceAccessGate("workspace")
    await _open(gate, repository)
    coordinator = WorkspaceAccessCoordinator(gate=gate, repository=repository)
    lease = await coordinator.acquire_change(
        workspace_id="workspace",
        operation_id="op_change",
        contract="workspace_write",
        now=NOW,
    )
    release = asyncio.create_task(coordinator.release_change(lease, now=NOW))
    await repository.release_started.wait()
    waiting_content = asyncio.create_task(gate.acquire_content_read())
    await asyncio.sleep(0)
    assert not waiting_content.done()
    repository.release_continue.set()
    free = await release
    assert free.active_operation_id is None
    content = await waiting_content
    await gate.release_content_read(content)


@pytest.mark.anyio
async def test_uncertain_change_retains_fence_and_closes_future_access() -> None:
    repository = FenceRepository()
    gate = WorkspaceAccessGate("workspace")
    await _open(gate, repository)
    coordinator = WorkspaceAccessCoordinator(gate=gate, repository=repository)
    lease = await coordinator.acquire_change(
        workspace_id="workspace",
        operation_id="op_uncertain",
        contract="workspace_write",
        now=NOW,
    )
    await coordinator.retain_uncertain(lease)
    assert repository.fence.active_operation_id == "op_uncertain"
    assert gate.state is WorkspaceAccessState.RECOVERY_CLOSED
    with pytest.raises(WorkspaceCoordinationError, match="recovery-closed"):
        await gate.acquire_change("op_other")

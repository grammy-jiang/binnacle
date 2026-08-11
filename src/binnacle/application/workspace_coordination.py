"""Process-local access gate coordinated with the durable workspace fence."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from binnacle.domain.workspace import WorkspaceFence
from binnacle.ports.workspace import WorkspaceRepository


class WorkspaceCoordinationError(RuntimeError):
    """Workspace access cannot be admitted without violating the shared seam."""


class WorkspaceAccessState(StrEnum):
    RECOVERY_CLOSED = "recovery_closed"
    OPEN = "open"


@dataclass(slots=True, eq=False)
class ContentReadGuard:
    guard_id: str
    workspace_id: str
    epoch: int
    released: bool = False


@dataclass(slots=True, eq=False)
class WorkspaceChangeGuard:
    guard_id: str
    operation_id: str
    workspace_id: str
    epoch: int
    released: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceChangeLease:
    guard: WorkspaceChangeGuard
    fence: WorkspaceFence


class WorkspaceAccessGate:
    """Linearize shared content reads against one workspace changer.

    This process-local gate is deliberately not authority.  Every invocation begins
    recovery-closed and opens only after the durable fence, child lifecycle, and mount
    predicates are independently proven.
    """

    def __init__(self, workspace_id: str) -> None:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        self._workspace_id = workspace_id
        self._condition = asyncio.Condition()
        self._state = WorkspaceAccessState.RECOVERY_CLOSED
        self._epoch = 1
        self._content_guards: set[ContentReadGuard] = set()
        self._change_guard: WorkspaceChangeGuard | None = None

    @property
    def state(self) -> WorkspaceAccessState:
        return self._state

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def content_reader_count(self) -> int:
        return len(self._content_guards)

    @property
    def change_operation_id(self) -> str | None:
        return None if self._change_guard is None else self._change_guard.operation_id

    async def open_after_recovery(
        self,
        *,
        fence: WorkspaceFence,
        search_children_quiesced: bool,
        root_mount_verified: bool,
    ) -> None:
        async with self._condition:
            if self._content_guards or self._change_guard is not None:
                raise WorkspaceCoordinationError("cannot open access while guards are active")
            if fence.workspace_id != self._workspace_id:
                raise WorkspaceCoordinationError("workspace recovery fence identity mismatch")
            if fence.active_operation_id is not None:
                raise WorkspaceCoordinationError("workspace mutation fence remains owned")
            if not search_children_quiesced or not root_mount_verified:
                raise WorkspaceCoordinationError("workspace recovery predicates are incomplete")
            self._epoch += 1
            self._state = WorkspaceAccessState.OPEN
            self._condition.notify_all()

    async def close_for_recovery(self) -> None:
        async with self._condition:
            self._state = WorkspaceAccessState.RECOVERY_CLOSED
            self._epoch += 1
            self._condition.notify_all()

    async def acquire_content_read(self) -> ContentReadGuard:
        async with self._condition:
            self._require_open()
            await self._condition.wait_for(
                lambda: self._state is not WorkspaceAccessState.OPEN or self._change_guard is None
            )
            self._require_open()
            guard = ContentReadGuard(
                guard_id=f"content_{secrets.token_hex(12)}",
                workspace_id=self._workspace_id,
                epoch=self._epoch,
            )
            self._content_guards.add(guard)
            return guard

    async def release_content_read(self, guard: ContentReadGuard) -> None:
        async with self._condition:
            if (
                guard.released
                or guard.workspace_id != self._workspace_id
                or guard not in self._content_guards
            ):
                raise WorkspaceCoordinationError("content guard is stale or foreign")
            guard.released = True
            self._content_guards.remove(guard)
            self._condition.notify_all()

    async def acquire_change(self, operation_id: str) -> WorkspaceChangeGuard:
        if not operation_id:
            raise ValueError("operation_id is required")
        async with self._condition:
            self._require_open()
            await self._condition.wait_for(
                lambda: (
                    self._state is not WorkspaceAccessState.OPEN
                    or (not self._content_guards and self._change_guard is None)
                )
            )
            self._require_open()
            guard = WorkspaceChangeGuard(
                guard_id=f"change_{secrets.token_hex(12)}",
                operation_id=operation_id,
                workspace_id=self._workspace_id,
                epoch=self._epoch,
            )
            self._change_guard = guard
            return guard

    async def release_change(self, guard: WorkspaceChangeGuard) -> None:
        async with self._condition:
            self._require_exact_change(guard)
            guard.released = True
            self._change_guard = None
            self._condition.notify_all()

    async def retain_uncertain_change(self, guard: WorkspaceChangeGuard) -> None:
        """Release process ownership while durable ownership keeps recovery closed."""

        async with self._condition:
            self._require_exact_change(guard)
            guard.released = True
            self._change_guard = None
            self._state = WorkspaceAccessState.RECOVERY_CLOSED
            self._epoch += 1
            self._condition.notify_all()

    def _require_open(self) -> None:
        if self._state is not WorkspaceAccessState.OPEN:
            raise WorkspaceCoordinationError("workspace access is recovery-closed")

    def _require_exact_change(self, guard: WorkspaceChangeGuard) -> None:
        if (
            guard.released
            or guard.workspace_id != self._workspace_id
            or guard is not self._change_guard
        ):
            raise WorkspaceCoordinationError("change guard is stale or foreign")


class WorkspaceAccessCoordinator:
    """Acquire/release the process guard and durable fence in one fixed order."""

    def __init__(
        self,
        *,
        gate: WorkspaceAccessGate,
        repository: WorkspaceRepository,
    ) -> None:
        self._gate = gate
        self._repository = repository

    async def recover(
        self,
        *,
        workspace_id: str,
        search_children_quiesced: bool,
        root_mount_verified: bool,
    ) -> WorkspaceFence:
        await self._gate.close_for_recovery()
        fence = await self._repository.get_fence(workspace_id)
        if fence.active_operation_id is None:
            await self._gate.open_after_recovery(
                fence=fence,
                search_children_quiesced=search_children_quiesced,
                root_mount_verified=root_mount_verified,
            )
        return fence

    async def acquire_change(
        self,
        *,
        workspace_id: str,
        operation_id: str,
        contract: str,
        now: datetime | None = None,
    ) -> WorkspaceChangeLease:
        guard = await self._gate.acquire_change(operation_id)
        try:
            current = await self._repository.get_fence(workspace_id)
            fence = await self._repository.acquire_fence(
                workspace_id=workspace_id,
                expected_version=current.fence_version,
                operation_id=operation_id,
                contract=contract,
                acquired_at=now or datetime.now(UTC),
            )
        except BaseException:
            await asyncio.shield(self._gate.release_change(guard))
            raise
        return WorkspaceChangeLease(guard, fence)

    async def release_change(
        self,
        lease: WorkspaceChangeLease,
        *,
        now: datetime | None = None,
    ) -> WorkspaceFence:
        fence = await self._repository.release_fence(
            workspace_id=lease.fence.workspace_id,
            expected_version=lease.fence.fence_version,
            operation_id=lease.guard.operation_id,
            released_at=now or datetime.now(UTC),
        )
        await asyncio.shield(self._gate.release_change(lease.guard))
        return fence

    async def retain_uncertain(self, lease: WorkspaceChangeLease) -> None:
        await asyncio.shield(self._gate.retain_uncertain_change(lease.guard))


__all__ = [
    "ContentReadGuard",
    "WorkspaceAccessCoordinator",
    "WorkspaceAccessGate",
    "WorkspaceAccessState",
    "WorkspaceChangeGuard",
    "WorkspaceChangeLease",
    "WorkspaceCoordinationError",
]

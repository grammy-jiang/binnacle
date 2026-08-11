"""Persistence boundary for durable Phase 6 development sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from binnacle.domain.development_session import (
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
)
from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.policy import PolicyDecision


@dataclass(frozen=True, slots=True)
class SessionAuthorisationRequest:
    """Exact post-policy facts committed with one pending live-slot reservation."""

    operation: OperationSnapshot
    decision: PolicyDecision
    snapshot: DevelopmentSessionSnapshot
    required_scope_digest: str | None
    normalized_target_digest: str
    authorised_at: datetime


class DevelopmentSessionRepository(Protocol):
    async def authorise_begin(
        self, request: SessionAuthorisationRequest
    ) -> tuple[OperationSnapshot, DevelopmentSessionSnapshot]: ...

    async def get_session(self, session_id: str) -> DevelopmentSessionSnapshot | None: ...

    async def require_session(self, session_id: str) -> DevelopmentSessionSnapshot: ...

    async def get_by_begin_operation(
        self, begin_operation_id: str
    ) -> DevelopmentSessionSnapshot | None: ...

    async def activate(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        effect_reference: str,
        effect_reference_sha256: str,
        started_at: datetime,
    ) -> DevelopmentSessionSnapshot: ...

    async def complete_activation(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        closed_at: datetime,
    ) -> DevelopmentSessionSnapshot: ...

    async def reduce(
        self,
        *,
        session_id: str,
        expected_state_version: int,
        target: DevelopmentSessionState,
        reason: str,
        terminal_at: datetime,
    ) -> DevelopmentSessionSnapshot: ...

    async def list_live(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]: ...

    async def list_activation_closures(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_session_id: str | None = None,
    ) -> tuple[DevelopmentSessionSnapshot, ...]: ...

    async def verify_integrity(self) -> None: ...


__all__ = ["DevelopmentSessionRepository", "SessionAuthorisationRequest"]

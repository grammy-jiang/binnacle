"""Typed Phase 8 Git boundaries; no public MCP capability is composed here."""

from __future__ import annotations

from typing import Protocol

from binnacle.domain.git import (
    GitDiffResult,
    GitExecutionPlan,
    GitReadPermit,
    GitRepositorySnapshot,
    GitStatusResult,
    RegisteredGitRepositoryProfile,
    RepositorySafetyAssessment,
)


class GitRepositoryInspector(Protocol):
    """Return a bounded snapshot without granting repository authority."""

    async def snapshot(
        self,
        profile: RegisteredGitRepositoryProfile,
    ) -> GitRepositorySnapshot: ...


class GitRepositoryProfileValidator(Protocol):
    """Inspect repository-controlled helper surfaces without executing them."""

    def validate(
        self,
        profile: RegisteredGitRepositoryProfile,
    ) -> RepositorySafetyAssessment: ...


class GitReadExecutionDispatcher(Protocol):
    """Dispatch a no-effect read plan through the Phase 7 supervisor lane."""

    async def status(
        self,
        permit: GitReadPermit,
        plan: GitExecutionPlan,
    ) -> GitStatusResult: ...

    async def diff(
        self,
        permit: GitReadPermit,
        plan: GitExecutionPlan,
    ) -> GitDiffResult: ...


class GitReadRecoveryBarrier(Protocol):
    """Close and drain a prior application generation before reopening reads."""

    async def close_and_drain(
        self,
        previous_generation: int,
        new_generation: int,
    ) -> str: ...


__all__ = [
    "GitReadExecutionDispatcher",
    "GitReadRecoveryBarrier",
    "GitRepositoryInspector",
    "GitRepositoryProfileValidator",
]

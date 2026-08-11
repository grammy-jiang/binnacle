"""Ports for the bounded Phase 5 probe workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from binnacle.domain.operation import OperationSnapshot
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.probe_workspace import (
    ProbeFileObservation,
    ProbeOperationKind,
    ProbeOperationRecord,
    ProbePathSnapshot,
    ProbePreparedState,
    ProbeRootIdentity,
)


@dataclass(frozen=True, slots=True)
class ProbeAuthorisationRequest:
    operation: OperationSnapshot
    decision: PolicyDecision
    probe_operation: ProbeOperationKind
    relative_path: str
    expected_content_sha256: str
    expected_byte_count: int | None
    artifact_id: str | None
    prepared_state_binding_sha256: str
    prepared_state: ProbePreparedState


@dataclass(frozen=True, slots=True)
class ProbeBoundarySnapshot:
    """One coherent, provenance-validated repository view for final dispatch."""

    probe_operation: ProbeOperationRecord
    path: ProbePathSnapshot
    prepared_state_binding_sha256: str


class ProbeWorkspaceRepository(Protocol):
    async def ensure_path_anchor(self, relative_path: str) -> ProbePathSnapshot: ...

    async def get_path_snapshot(self, relative_path: str) -> ProbePathSnapshot: ...

    async def get_probe_operation(self, operation_id: str) -> ProbeOperationRecord | None: ...

    async def get_prepared_state_binding_sha256(self, prepared_operation_id: str) -> str | None: ...

    async def get_boundary_snapshot(
        self,
        *,
        operation_id: str,
        prepared_operation_id: str,
        relative_path: str,
    ) -> ProbeBoundarySnapshot: ...

    async def authorise(self, request: ProbeAuthorisationRequest) -> OperationSnapshot: ...

    async def mark_write_uncertain(self, operation_id: str) -> None: ...

    async def close_write_created(
        self,
        operation_id: str,
        *,
        file_identity_digest: str,
    ) -> OperationSnapshot: ...

    async def close_write_abandoned(self, operation_id: str) -> None: ...

    async def close_cleanup_removed(
        self,
        operation_id: str,
        *,
        removed_by_operation: bool,
    ) -> OperationSnapshot | None: ...

    async def clear_cleanup_claim(self, operation_id: str) -> None: ...

    async def list_probe_operations(self) -> tuple[ProbeOperationRecord, ...]: ...

    async def list_probe_operations_for_closure(
        self,
        *,
        limit: int,
        after_created_at: datetime | None = None,
        after_operation_id: str | None = None,
    ) -> tuple[ProbeOperationRecord, ...]: ...

    async def verify_integrity(self) -> None: ...


class ProbeWorkspaceFilesystem(Protocol):
    async def initialize(self) -> None: ...

    async def root_identity(self) -> ProbeRootIdentity: ...

    async def observe(self, relative_path: str) -> ProbeFileObservation: ...

    async def create(
        self,
        *,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        content: bytes,
        expected_content_sha256: str,
    ) -> str: ...

    async def remove(
        self,
        *,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        expected_content_sha256: str,
        expected_file_identity_digest: str,
    ) -> str | None: ...


__all__ = [
    "ProbeAuthorisationRequest",
    "ProbeBoundarySnapshot",
    "ProbeWorkspaceFilesystem",
    "ProbeWorkspaceRepository",
]

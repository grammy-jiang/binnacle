"""Conservative supervisor-restart reconciliation for the unavailable backend profile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from binnacle.domain.execution import (
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
    ExecutorSnapshot,
    canonical_sha256,
)
from binnacle.ports.execution import ExecutorEvidenceStore


@dataclass(frozen=True, slots=True)
class ExecutorReconciliationReport:
    closed_without_launch: int
    unresolved_after_launch_commit: int
    readiness: str


class ExecutorRestartReconciler:
    """Never respawn; close only rows that durably prove launch was not committed."""

    def __init__(self, store: ExecutorEvidenceStore) -> None:
        self._store = store

    async def reconcile(self) -> ExecutorReconciliationReport:
        closed = 0
        unresolved = 0
        after: str | None = None
        while True:
            page = await self._store.list_outstanding(
                after_operation_id=after,
                limit=256,
            )
            if not page:
                break
            for snapshot in page:
                if snapshot.launch_generation == 0:
                    await self._close_no_launch(snapshot)
                    closed += 1
                else:
                    await self._mark_committed_unknown(snapshot)
                    unresolved += 1
                after = snapshot.operation_id
            if len(page) < 256:
                break
        readiness = "ready" if unresolved == 0 else "recovering"
        await self._store.set_readiness(readiness)
        return ExecutorReconciliationReport(
            closed_without_launch=closed,
            unresolved_after_launch_commit=unresolved,
            readiness=readiness,
        )

    async def _close_no_launch(self, snapshot: ExecutorSnapshot) -> None:
        current = snapshot
        now = datetime.now(UTC)
        if current.state is not ExecutorEvidenceState.EXECUTOR_UNCERTAIN:
            current = await self._store.apply_event(
                ExecutorEvidenceEvent(
                    event_id=f"restart_uncertain_{current.execution_id}_{current.state_version}",
                    operation_id=current.operation_id,
                    expected_state=current.state,
                    expected_state_version=current.state_version,
                    target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                    reason_code="restart_before_launch_commit",
                    recorded_at=now,
                )
            )
        terminal_sha256 = canonical_sha256(
            {
                "create_receipt": current.create_receipt_disposition.value,
                "execution_id": current.execution_id,
                "launch_generation": current.launch_generation,
                "outcome": "no_domain_created",
            }
        )
        cleanup_sha256 = canonical_sha256(
            {
                "descendants_stopped": True,
                "execution_id": current.execution_id,
                "output_finalized": True,
                "private_resources_removed": True,
            }
        )
        await self._store.apply_event(
            ExecutorEvidenceEvent(
                event_id=f"restart_closed_{current.execution_id}_{current.state_version}",
                operation_id=current.operation_id,
                expected_state=current.state,
                expected_state_version=current.state_version,
                target_state=ExecutorEvidenceState.CLOSED,
                reason_code="restart_no_launch_commit",
                recorded_at=datetime.now(UTC),
                terminal_reason="no_domain_created",
                descendants_stopped=True,
                output_finalized=True,
                cleanup_complete=True,
                terminal_evidence_sha256=terminal_sha256,
                cleanup_evidence_sha256=cleanup_sha256,
            )
        )

    async def _mark_committed_unknown(self, snapshot: ExecutorSnapshot) -> None:
        if snapshot.state in {
            ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
            ExecutorEvidenceState.EXITED,
            ExecutorEvidenceState.CLEANUP_PENDING,
        }:
            return
        await self._store.apply_event(
            ExecutorEvidenceEvent(
                event_id=f"restart_committed_{snapshot.execution_id}_{snapshot.state_version}",
                operation_id=snapshot.operation_id,
                expected_state=snapshot.state,
                expected_state_version=snapshot.state_version,
                target_state=ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
                reason_code="restart_after_launch_commit",
                recorded_at=datetime.now(UTC),
            )
        )


__all__ = ["ExecutorReconciliationReport", "ExecutorRestartReconciler"]

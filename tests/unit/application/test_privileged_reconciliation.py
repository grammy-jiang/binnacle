"""Replacement-application routing for retained Phase 9 restart operations."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from tests.phase4_support import NOW, intent, owner
from tests.phase9_support import SHA_C, binding_snapshot

from binnacle.application.privileged_reconciliation import PrivilegedRestartReconciler
from binnacle.domain.operation import OperationSnapshot, new_received_operation
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    PrivilegedEffectKnowledge,
)
from binnacle.ports.privileged import (
    PrivilegedApplicationRepository,
    PrivilegedBrokerPort,
    PrivilegedBrokerUnavailable,
)


def _operation() -> OperationSnapshot:
    return new_received_operation(
        owner=owner(),
        intent=intent(),
        operation_id="operation:fixture",
        now=NOW,
    )


def _dependencies(
    *,
    retained: bool = True,
    snapshot: BrokerBindingSnapshot | None = None,
    broker_error: Exception | None = None,
) -> tuple[PrivilegedRestartReconciler, AsyncMock, AsyncMock]:
    record_snapshot = AsyncMock()
    repository = cast(
        PrivilegedApplicationRepository,
        SimpleNamespace(
            get_restart=AsyncMock(
                return_value=(
                    SimpleNamespace(operation_id="operation:fixture") if retained else None
                )
            ),
            record_broker_snapshot=record_snapshot,
        ),
    )
    broker_get = AsyncMock(return_value=snapshot)
    if broker_error is not None:
        broker_get.side_effect = broker_error
    broker = cast(PrivilegedBrokerPort, SimpleNamespace(get=broker_get))
    return (
        PrivilegedRestartReconciler(
            repository=repository,
            broker=broker,
            clock=lambda: NOW,
        ),
        record_snapshot,
        broker_get,
    )


@pytest.mark.anyio
async def test_non_privileged_operation_falls_through_to_other_reconcilers() -> None:
    reconciler, record, broker_get = _dependencies(retained=False)

    assert await reconciler.reconcile(_operation()) is None
    broker_get.assert_not_awaited()
    record.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_or_unavailable_broker_keeps_restart_recovery_closed() -> None:
    operation = _operation()
    missing, missing_record, _ = _dependencies(snapshot=None)
    unavailable, unavailable_record, _ = _dependencies(
        broker_error=PrivilegedBrokerUnavailable("broker unavailable")
    )

    assert await missing.reconcile(operation) is operation
    assert await unavailable.reconcile(operation) is operation
    missing_record.assert_not_awaited()
    unavailable_record.assert_not_awaited()


@pytest.mark.anyio
async def test_exact_accepted_snapshot_is_recorded_without_generic_closure() -> None:
    operation = _operation()
    snapshot = binding_snapshot()
    reconciler, record, _ = _dependencies(snapshot=snapshot)

    assert await reconciler.reconcile(operation) is operation
    record.assert_awaited_once_with(snapshot, reconciled_at=NOW)
    assert await reconciler.reconcile_terminal_closures() == ()


@pytest.mark.anyio
async def test_no_accept_snapshot_waits_for_atomic_terminal_closure() -> None:
    operation = _operation()
    accepted = binding_snapshot()
    sealed = replace(
        accepted,
        acceptance_state=BrokerAcceptanceState.SEALED_NO_ACCEPT,
        acceptance_evidence_sha256=SHA_C,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT,
        result_evidence_sha256=SHA_C,
        accepted_at=None,
        sealed_at=NOW,
        closed_at=NOW,
    )
    reconciler, record, _ = _dependencies(snapshot=sealed)

    assert await reconciler.reconcile(operation) is operation
    record.assert_not_awaited()

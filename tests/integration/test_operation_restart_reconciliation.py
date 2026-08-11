"""Fresh-process durable state and conservative reconciliation tests."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from tests.phase4_support import NOW, intent, migrate_database, operation_runtime, owner

from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.adapters.sqlite.engine import (
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.application.boundary import ConsequentialBoundaryGate, GateState
from binnacle.application.reconciliation import OperationReconciler
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import EffectKnowledge, OperationState, TransitionRequest
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.ports.audit import AuditObligation
from binnacle.ports.effect import EffectObservation, EffectReference
from binnacle.ports.operation_store import CreateOrFindRequest


def _decision(operation_id: str) -> PolicyDecision:
    return PolicyDecision(
        f"policy_{secrets.token_hex(16)}",
        operation_id,
        "test-policy",
        "1.0.0",
        PolicyDecisionValue.ALLOW,
        ("allowed",),
        "a" * 64,
        "b" * 64,
        NOW,
    )


@pytest.mark.anyio
async def test_fresh_process_reconstructs_identity_and_rejects_received(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    runtime = await create_database_runtime(settings)
    first_store = SqliteOperationStore(runtime)
    await first_store.initialize_kernel(
        device_id="device-fixture", audit_stream_id="stream-fixture"
    )
    key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
    created = await first_store.create_or_find(
        CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
    )
    assert created.operation is not None
    operation_id = created.operation.operation_id
    await close_database_runtime(runtime)

    fresh_runtime = await create_database_runtime(settings)
    try:
        fresh_store = SqliteOperationStore(fresh_runtime)
        retained = await fresh_store.create_or_find(
            CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
        )
        assert retained.operation is not None
        assert retained.operation.operation_id == operation_id
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        gate = ConsequentialBoundaryGate()
        reconciler = OperationReconciler(store=fresh_store, obligations=obligations, gate=gate)
        results = await reconciler.reconcile_startup()
        assert len(results) == 1
        assert results[0].state is OperationState.REJECTED
        assert await fresh_store.get_policy_decision(operation_id) is not None
        assert gate.state is GateState.OPEN
    finally:
        await close_database_runtime(fresh_runtime)


@pytest.mark.anyio
async def test_authorised_becomes_known_no_effect_and_running_becomes_uncertain(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    runtime = await create_database_runtime(settings)
    try:
        store = SqliteOperationStore(runtime)
        await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
        operations = []
        for target in (OperationState.AUTHORISED, OperationState.RUNNING):
            key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
            created = await store.create_or_find(
                CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
            )
            assert created.operation is not None
            await store.store_policy_decision(_decision(created.operation.operation_id))
            authorised = await store.transition(
                created.operation.operation_id,
                TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
            )
            operation = authorised
            if target is OperationState.RUNNING:
                operation = await store.transition(
                    authorised.operation_id,
                    TransitionRequest(2, OperationState.RUNNING, EffectKnowledge.NONE, "running"),
                )
            operations.append(operation)
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        gate = ConsequentialBoundaryGate()
        reconciled = await OperationReconciler(
            store=store, obligations=obligations, gate=gate
        ).reconcile_startup()
        states = {item.operation_id: item.state for item in reconciled}
        assert states[operations[0].operation_id] is OperationState.FAILED
        assert states[operations[1].operation_id] is OperationState.UNCERTAIN
    finally:
        await close_database_runtime(runtime)


@pytest.mark.anyio
async def test_surviving_obligation_never_auto_clears_and_keeps_gate_closed(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    runtime = await create_database_runtime(settings)
    try:
        store = SqliteOperationStore(runtime)
        await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        marker = AuditObligation("1", "obl-survivor", "op-historical", 3)
        await obligations.publish(marker)
        gate = ConsequentialBoundaryGate()
        await OperationReconciler(
            store=store, obligations=obligations, gate=gate
        ).reconcile_startup()
        assert gate.state is GateState.CLOSED
        assert await obligations.scan() == (marker,)
        assert (await store.audit_failure_state())[0]
    finally:
        await close_database_runtime(runtime)


@pytest.mark.anyio
async def test_nonterminal_effect_reference_survives_restart_and_reconciles(
    tmp_path: Path, repo_root: Path
) -> None:
    class Reconciler:
        async def reconcile(self, reference: EffectReference) -> EffectObservation:
            assert reference.reference == "effect-reference"
            return EffectObservation(
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "effect_reconciled",
            )

    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    runtime = await create_database_runtime(settings)
    store = SqliteOperationStore(runtime)
    await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
    key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
    created = await store.create_or_find(
        CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
    )
    assert created.operation is not None
    operation_id = created.operation.operation_id
    await store.store_policy_decision(_decision(operation_id))
    await store.transition(
        operation_id,
        TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
    )
    running = await store.transition(
        operation_id,
        TransitionRequest(2, OperationState.RUNNING, EffectKnowledge.NONE, "running"),
    )
    retained = await store.record_effect_start(
        operation_id,
        expected_state_version=running.state_version,
        effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
        effect_reference="effect-reference",
        effect_reference_digest="f" * 64,
    )
    assert retained.effect_reference == "effect-reference"
    await close_database_runtime(runtime)

    fresh_runtime = await create_database_runtime(settings)
    try:
        fresh_store = SqliteOperationStore(fresh_runtime)
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        reconciled = await OperationReconciler(
            store=fresh_store,
            obligations=obligations,
            gate=ConsequentialBoundaryGate(),
            effect_reconciler=Reconciler(),
        ).reconcile_startup()
        assert reconciled[0].state is OperationState.SUCCEEDED
    finally:
        await close_database_runtime(fresh_runtime)


@pytest.mark.anyio
async def test_reconciliation_scans_every_page_before_opening_gate(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        for _ in range(101):
            created = await store.create_or_find(
                CreateOrFindRequest(
                    validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                    owner(),
                    intent(),
                    "internal.synthetic",
                    "1.0.0",
                )
            )
            assert created.operation is not None
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        gate = ConsequentialBoundaryGate()
        reconciled = await OperationReconciler(
            store=store, obligations=obligations, gate=gate
        ).reconcile_startup()
        assert len(reconciled) == 101
        assert all(item.state is OperationState.REJECTED for item in reconciled)
        assert await store.list_reconcilable() == ()
        assert gate.state is GateState.OPEN

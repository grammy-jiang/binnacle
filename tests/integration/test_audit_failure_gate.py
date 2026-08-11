"""Durable audit-failure generation and explicit obligation closure tests."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from tests.phase4_support import NOW, audit_identity, audit_schema, intent, operation_runtime, owner

from binnacle.adapters.audit.journal import FileAuditJournal
from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.application.boundary import ConsequentialBoundaryGate, GateState
from binnacle.application.reconciliation import (
    AuditObligationClosure,
    AuditRecoveryService,
    OperationReconciler,
    audit_closure_evidence_digest,
)
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import EffectKnowledge, OperationState, TransitionRequest
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue
from binnacle.ports.audit import AuditObligation
from binnacle.ports.operation_store import CreateOrFindRequest


@pytest.mark.anyio
async def test_only_exact_generation_with_all_closures_can_recover(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        journal = FileAuditJournal(
            directory=tmp_path / "audit",
            identity=audit_identity(),
            schema=audit_schema(repo_root),
        )
        await journal.open()
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
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
        operation_id = created.operation.operation_id
        await store.store_policy_decision(
            PolicyDecision(
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
        )
        await store.transition(
            operation_id,
            TransitionRequest(1, OperationState.AUTHORISED, EffectKnowledge.NONE, "allowed"),
        )
        running = await store.transition(
            operation_id,
            TransitionRequest(2, OperationState.RUNNING, EffectKnowledge.NONE, "running"),
        )
        succeeded = await store.transition(
            operation_id,
            TransitionRequest(
                3,
                OperationState.SUCCEEDED,
                EffectKnowledge.KNOWN_EFFECT,
                "effect_verified",
            ),
        )
        marker = AuditObligation("1", "obl-fixture", operation_id, running.state_version)
        await obligations.publish(marker)
        generation = await store.latch_audit_failure("post_effect_audit_failed")
        recovery = AuditRecoveryService(store=store, obligations=obligations, audit=journal)
        closure = AuditObligationClosure(
            "obl-fixture",
            "known_effect",
            audit_closure_evidence_digest(
                generation=generation,
                marker=marker,
                operation=succeeded,
                effect_outcome="known_effect",
            ),
        )
        with pytest.raises(RuntimeError, match="generation"):
            await recovery.recover(generation=generation + 1, closures=(closure,))
        with pytest.raises(RuntimeError, match="match every"):
            await recovery.recover(generation=generation, closures=())
        with pytest.raises(RuntimeError, match="invalid"):
            await recovery.recover(
                generation=generation,
                closures=(
                    AuditObligationClosure(
                        "obl-fixture",
                        "uncertain",
                        audit_closure_evidence_digest(
                            generation=generation,
                            marker=marker,
                            operation=succeeded,
                            effect_outcome="uncertain",
                        ),
                    ),
                ),
            )
        with pytest.raises(RuntimeError, match="bound to durable truth"):
            await recovery.recover(
                generation=generation,
                closures=(AuditObligationClosure("obl-fixture", "known_effect", "a" * 64),),
            )
        original_clear = store.clear_audit_failure

        async def fail_after_fsync(_generation: int, _evidence: str) -> None:
            raise RuntimeError("simulated crash before latch clear")

        monkeypatch.setattr(store, "clear_audit_failure", fail_after_fsync)
        with pytest.raises(RuntimeError, match="simulated crash"):
            await recovery.recover(generation=generation, closures=(closure,))
        assert await obligations.scan() == ()
        assert (await store.audit_failure_state())[0]
        monkeypatch.setattr(store, "clear_audit_failure", original_clear)
        evidence = await recovery.recover(generation=generation, closures=())
        assert len(evidence) == 64
        assert await obligations.scan() == ()
        assert await store.audit_failure_state() == (False, generation, generation)
        gate = ConsequentialBoundaryGate()
        await OperationReconciler(
            store=store, obligations=obligations, gate=gate
        ).reconcile_startup()
        assert gate.state is GateState.OPEN


@pytest.mark.anyio
async def test_invalid_closure_evidence_never_removes_marker(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        journal = FileAuditJournal(
            directory=tmp_path / "audit",
            identity=audit_identity(),
            schema=audit_schema(repo_root),
        )
        await journal.open()
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        marker = AuditObligation("1", "obl-fixture", "op-fixture", 3)
        await obligations.publish(marker)
        generation = await store.latch_audit_failure("post_effect_audit_failed")
        recovery = AuditRecoveryService(store=store, obligations=obligations, audit=journal)
        with pytest.raises(RuntimeError, match="invalid"):
            await recovery.recover(
                generation=generation,
                closures=(AuditObligationClosure("obl-fixture", "guessed", "not-a-digest"),),
            )
        assert await obligations.scan() == (marker,)
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_valid_shaped_evidence_cannot_close_an_unknown_operation(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        journal = FileAuditJournal(
            directory=tmp_path / "audit",
            identity=audit_identity(),
            schema=audit_schema(repo_root),
        )
        await journal.open()
        obligations = FileAuditObligationStore(tmp_path / "state/audit-obligations")
        await obligations.initialize()
        marker = AuditObligation("1", "obl-fixture", "op-does-not-exist", 3)
        await obligations.publish(marker)
        generation = await store.latch_audit_failure("post_effect_audit_failed")
        recovery = AuditRecoveryService(store=store, obligations=obligations, audit=journal)
        with pytest.raises(RuntimeError, match="operation truth is unavailable"):
            await recovery.recover(
                generation=generation,
                closures=(AuditObligationClosure("obl-fixture", "known_effect", "a" * 64),),
            )
        assert await obligations.scan() == (marker,)
        assert (await store.audit_failure_state())[0]

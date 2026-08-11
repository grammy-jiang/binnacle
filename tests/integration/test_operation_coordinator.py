"""End-to-end durable admission, audit ordering, and synthetic effect tests."""

from __future__ import annotations

import secrets
from dataclasses import replace
from pathlib import Path

import pytest
from tests.phase4_support import (
    audit_identity,
    audit_schema,
    intent,
    operation_runtime,
    owner,
)

from binnacle.adapters.audit.journal import FileAuditJournal
from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.adapters.policy.bootstrap import BootstrapPolicyEngine
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.application.boundary import (
    ConsequentialBoundaryGate,
    DispatchHandoffGate,
    FinalBoundaryService,
)
from binnacle.application.kernel_health import KernelAvailability, KernelHealth
from binnacle.application.operations import (
    CoordinatedOperationRequest,
    OperationCoordinator,
    RequiredAuditError,
)
from binnacle.domain.audit import AuditAppendResult, AuditEventDraft, AuditTail
from binnacle.domain.idempotency import (
    IdempotencyKey,
    IdempotencyKeyMode,
    IdempotencyOutcome,
    validate_and_digest_key,
)
from binnacle.domain.operation import EffectKnowledge, OperationState
from binnacle.ports.boundary import BoundaryCheckResult, OperationBoundaryCheck
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectBoundary,
    EffectRequest,
    EffectStartReceipt,
    UnavailableEffectBoundary,
)
from binnacle.ports.operation_store import CreateOrFindRequest


class FixtureBoundaryVerifier:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult:
        assert request.predicates["controller_trusted"] is True
        return BoundaryCheckResult(self.allowed, "fixture_allowed" if self.allowed else "stale")


class CountingBoundary:
    def __init__(self, *, fail_response: bool = False) -> None:
        self.count = 0
        self.fail_response = fail_response

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        self.count += 1
        assert request.running_state_version == 3
        if self.fail_response:
            raise RuntimeError("lost response")
        return EffectStartReceipt(
            crossing=BoundaryCrossing.CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference="effect-fixture",
            terminal_state=OperationState.SUCCEEDED,
            reason_code="synthetic_effect_verified",
        )


class StaticReceiptBoundary:
    def __init__(self, receipt: EffectStartReceipt) -> None:
        self.receipt = receipt

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        assert request.running_state_version == 3
        return self.receipt


class FaultJournal:
    def __init__(self, delegate: FileAuditJournal, fail_kind: str) -> None:
        self.delegate = delegate
        self.fail_kind = fail_kind

    @property
    def tail(self) -> AuditTail:
        return self.delegate.tail

    async def append(self, draft: AuditEventDraft) -> AuditAppendResult:
        if draft.payload["kind"] == self.fail_kind:
            raise OSError("injected audit failure")
        return await self.delegate.append(draft)

    async def find_obligation_evidence(
        self,
        *,
        obligation_id: str,
        operation_id: str,
        running_state_version: int,
    ) -> str | None:
        return await self.delegate.find_obligation_evidence(
            obligation_id=obligation_id,
            operation_id=operation_id,
            running_state_version=running_state_version,
        )

    async def find_generation_recovery(self, generation: int) -> str | None:
        return await self.delegate.find_generation_recovery(generation)


async def _coordinator(
    *,
    root: Path,
    repo_root: Path,
    store: SqliteOperationStore,
    boundary: EffectBoundary,
    verifier_allowed: bool = True,
    fail_audit_kind: str | None = None,
) -> tuple[
    OperationCoordinator,
    FileAuditJournal,
    FileAuditObligationStore,
    ConsequentialBoundaryGate,
]:
    journal = FileAuditJournal(
        directory=root / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    await journal.open()
    audit = journal if fail_audit_kind is None else FaultJournal(journal, fail_audit_kind)
    obligations = FileAuditObligationStore(root / "state/audit-obligations")
    await obligations.initialize()
    gate = ConsequentialBoundaryGate()
    await gate.open()

    async def health() -> KernelHealth:
        return KernelHealth(KernelAvailability.AVAILABLE, True, True, True, 0, False)

    coordinator = OperationCoordinator(
        store=store,
        policy=BootstrapPolicyEngine(allowed_contracts=frozenset({("synthetic.effect", "1.0.0")})),
        audit=audit,
        obligations=obligations,
        handoff_gate=DispatchHandoffGate(),
        consequential_gate=gate,
        final_boundary=FinalBoundaryService(
            health_reader=health,
            verifier=FixtureBoundaryVerifier(verifier_allowed),
        ),
        effect_boundary=boundary,
    )
    return coordinator, journal, obligations, gate


def _request(
    key: IdempotencyKey, *, operation_contract: str = "synthetic.effect"
) -> CoordinatedOperationRequest:
    operation_intent = intent()
    if operation_contract != operation_intent.operation_contract:
        operation_intent = replace(operation_intent, operation_contract=operation_contract)
    return CoordinatedOperationRequest(
        admission=CreateOrFindRequest(
            key=key,
            owner=owner(),
            intent=operation_intent,
            tool_name="internal.synthetic",
            contract_version="1.0.0",
        ),
        required_scope_digest=None,
        normalized_target_digest="d" * 64,
        boundary_predicates={"controller_trusted": True},
        effect_type="synthetic",
        protected_effect_arguments={"bounded": True},
    )


@pytest.mark.anyio
async def test_successful_dispatch_is_audited_once_and_duplicate_reconciles(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, journal, obligations, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
        )
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        first = await coordinator.execute(_request(key))
        second = await coordinator.execute(_request(key))
        assert first.operation is not None
        assert first.operation.state is OperationState.SUCCEEDED
        assert first.operation.state_version == 4
        assert second.outcome is IdempotencyOutcome.RETAINED_OPERATION
        assert second.operation is not None
        assert second.operation.operation_id == first.operation.operation_id
        assert boundary.count == 1
        assert await obligations.scan() == ()
        assert journal.tail.sequence == 7


@pytest.mark.anyio
async def test_final_boundary_rejection_suppresses_effect(tmp_path: Path, repo_root: Path) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, obligations, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
            verifier_allowed=False,
        )
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.FAILED
        assert result.operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
        assert boundary.count == 0
        assert await obligations.scan() == ()


@pytest.mark.anyio
async def test_lost_start_response_is_uncertain_not_retried(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary(fail_response=True)
        coordinator, _, obligations, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
        )
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        first = await coordinator.execute(_request(key))
        second = await coordinator.execute(_request(key))
        assert first.operation is not None
        assert first.operation.state is OperationState.UNCERTAIN
        assert second.outcome is IdempotencyOutcome.RETAINED_OPERATION
        assert boundary.count == 1
        assert await obligations.scan() == ()


@pytest.mark.anyio
async def test_intent_audit_failure_trips_gate_and_calls_no_effect(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, _, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
            fail_audit_kind="effect.intent_recorded",
        )
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.FAILED
        assert result.operation.error is not None
        assert result.operation.error.code == "audit_unavailable"
        assert boundary.count == 0
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_post_effect_audit_failure_leaves_marker_and_latch(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
            fail_audit_kind="effect.observed",
        )
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.SUCCEEDED
        assert boundary.count == 1
        assert len(await obligations.scan()) == 1
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_policy_denial_is_durable_and_never_reaches_boundary(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, journal, obligations, _ = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=boundary
        )
        result = await coordinator.execute(
            _request(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                operation_contract="unapproved.effect",
            )
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.REJECTED
        assert result.operation.error is not None
        assert result.operation.error.code == "policy_rejected"
        assert boundary.count == 0
        assert await obligations.scan() == ()
        assert journal.tail.sequence == 3


@pytest.mark.anyio
async def test_authorization_audit_failure_is_known_no_effect_even_if_latch_write_fails(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, _, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
            fail_audit_kind="policy.decision",
        )

        async def fail_latch(_reason: str) -> int:
            raise OSError("injected latch failure")

        monkeypatch.setattr(store, "latch_audit_failure", fail_latch)
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.FAILED
        assert result.operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
        assert boundary.count == 0
        assert gate.state.value == "tripped"


@pytest.mark.anyio
async def test_obligation_publish_failure_trips_and_latches_before_effect(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=boundary
        )

        async def fail_publish(_obligation: object) -> None:
            raise OSError("injected marker failure")

        monkeypatch.setattr(obligations, "publish", fail_publish)
        with pytest.raises(RequiredAuditError, match="made durable"):
            await coordinator.execute(
                _request(
                    validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
                )
            )
        assert boundary.count == 0
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_post_effect_marker_cleanup_failure_remains_recovery_visible(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = CountingBoundary()
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=boundary
        )

        async def fail_remove(_obligation_id: str) -> None:
            raise OSError("injected cleanup failure")

        monkeypatch.setattr(obligations, "remove", fail_remove)
        with pytest.raises(RequiredAuditError, match="cleanup"):
            await coordinator.execute(
                _request(
                    validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
                )
            )
        assert boundary.count == 1
        assert len(await obligations.scan()) == 1
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_nonterminal_reference_and_terminal_failure_receipts_are_classified(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        nonterminal = StaticReceiptBoundary(
            EffectStartReceipt(
                BoundaryCrossing.CROSSED,
                EffectKnowledge.KNOWN_EFFECT,
                reference="reference-with-derived-digest",
                terminal_state=None,
                reason_code="effect_accepted",
            )
        )
        coordinator, _, obligations, _ = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=nonterminal
        )
        running = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert running.operation is not None
        assert running.operation.state is OperationState.RUNNING
        assert running.operation.effect_reference == "reference-with-derived-digest"
        assert running.operation.effect_reference_digest is not None
        assert await obligations.scan() == ()

        failed_coordinator, _, failed_obligations, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=UnavailableEffectBoundary(),
        )
        failed = await failed_coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert failed.operation is not None
        assert failed.operation.state is OperationState.FAILED
        assert failed.operation.error is not None
        assert failed.operation.error.code == "effect_boundary_unavailable"
        assert await failed_obligations.scan() == ()


@pytest.mark.anyio
async def test_uncertain_receipt_and_revoked_prestart_are_never_retried(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        uncertain_boundary = StaticReceiptBoundary(
            EffectStartReceipt(
                BoundaryCrossing.UNCERTAIN,
                EffectKnowledge.UNCERTAIN,
                terminal_state=OperationState.UNCERTAIN,
                reason_code="adapter_uncertain",
            )
        )
        coordinator, _, obligations, _ = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=uncertain_boundary
        )
        uncertain = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert uncertain.operation is not None
        assert uncertain.operation.state is OperationState.UNCERTAIN
        assert uncertain.operation.error is not None
        assert uncertain.operation.error.retry_action == "reconcile"
        assert await obligations.scan() == ()

        boundary = CountingBoundary()
        revoked, _, revoked_obligations, gate = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=boundary
        )
        original_publish = revoked_obligations.publish

        async def publish_then_trip(obligation: object) -> None:
            await original_publish(obligation)  # type: ignore[arg-type]
            await gate.trip("concurrent_integrity_failure")

        monkeypatch.setattr(revoked_obligations, "publish", publish_then_trip)
        result = await revoked.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.RUNNING
        assert boundary.count == 0
        assert len(await revoked_obligations.scan()) == 1


@pytest.mark.anyio
async def test_receipt_classification_failure_trips_gate_and_preserves_marker(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = StaticReceiptBoundary(
            EffectStartReceipt(
                BoundaryCrossing.CROSSED,
                EffectKnowledge.KNOWN_EFFECT,
                reference="reference",
                terminal_state=None,
            )
        )
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path, repo_root=repo_root, store=store, boundary=boundary
        )

        async def fail_classification(*_args: object, **_kwargs: object) -> object:
            raise OSError("injected classification failure")

        monkeypatch.setattr(store, "record_effect_start", fail_classification)
        with pytest.raises(OSError, match="classification"):
            await coordinator.execute(
                _request(
                    validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
                )
            )
        assert len(await obligations.scan()) == 1
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]

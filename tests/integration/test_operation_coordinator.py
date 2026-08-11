"""End-to-end durable admission, audit ordering, and synthetic effect tests."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from tests.phase4_support import (
    NOW,
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
    BoundaryGateError,
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
from binnacle.application.trusted_time import TrustedTimeGuard
from binnacle.domain.audit import AuditAppendResult, AuditEventDraft, AuditTail
from binnacle.domain.idempotency import (
    IdempotencyKey,
    IdempotencyKeyMode,
    IdempotencyOutcome,
    validate_and_digest_key,
)
from binnacle.domain.operation import EffectKnowledge, OperationState
from binnacle.domain.trusted_time import TrustedTimeSnapshot
from binnacle.ports.audit import AuditObligationRecovery
from binnacle.ports.boundary import (
    BoundaryCheckResult,
    OperationBoundaryCheck,
    PreparedStateCheck,
)
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectBoundary,
    EffectReceiptError,
    EffectRequest,
    EffectStartReceipt,
    UnavailableEffectBoundary,
)
from binnacle.ports.operation_store import CreateOrFindRequest, PreparedNonceRegistration


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


class BlockingBoundary(CountingBoundary):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        self.count += 1
        assert request.running_state_version == 3
        self.started.set()
        await self.release.wait()
        return EffectStartReceipt(
            crossing=BoundaryCrossing.CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference="effect-fixture",
            terminal_state=OperationState.SUCCEEDED,
            reason_code="synthetic_effect_verified",
        )


class CancellingBoundary:
    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        assert request.running_state_version == 3
        raise asyncio.CancelledError


class BoundaryGateErrorBoundary:
    def __init__(self) -> None:
        self.count = 0

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        self.count += 1
        assert request.running_state_version == 3
        raise BoundaryGateError("adapter response lost")


class StaticTrustedTimeSource:
    async def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(NOW, 100, "3" * 64, True)


class SequencedPreparedStateVerifier:
    def __init__(self, *digests: str) -> None:
        self._digests = list(digests)
        self.checks: list[PreparedStateCheck] = []

    async def current_state_digest(self, request: PreparedStateCheck) -> str:
        self.checks.append(request)
        return self._digests.pop(0)


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

    async def append_emergency(
        self,
        *,
        reason_code: str,
        operation_id: str | None,
        source_event_id: str,
    ) -> None:
        await self.delegate.append_emergency(
            reason_code=reason_code,
            operation_id=operation_id,
            source_event_id=source_event_id,
        )

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

    async def list_obligation_recoveries(
        self, generation: int
    ) -> tuple[AuditObligationRecovery, ...]:
        return await self.delegate.list_obligation_recoveries(generation)

    async def find_generation_verification(self, generation: int) -> str | None:
        return await self.delegate.find_generation_verification(generation)


async def _coordinator(
    *,
    root: Path,
    repo_root: Path,
    store: SqliteOperationStore,
    boundary: EffectBoundary,
    verifier_allowed: bool = True,
    fail_audit_kind: str | None = None,
    trusted_time_guard: TrustedTimeGuard | None = None,
    prepared_state_verifier: SequencedPreparedStateVerifier | None = None,
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
        trusted_time_guard=trusted_time_guard,
        prepared_state_verifier=prepared_state_verifier,
    )
    return coordinator, journal, obligations, gate


def _request(
    key: IdempotencyKey,
    *,
    operation_contract: str = "synthetic.effect",
    fingerprint: str = "a" * 64,
) -> CoordinatedOperationRequest:
    operation_intent = intent(fingerprint=fingerprint)
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
        emergency = (tmp_path / "audit/emergency/events.jsonl").read_text().splitlines()
        assert len(emergency) == 1
        assert json.loads(emergency[0])["kind"] == "audit.storage_degraded"


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
        assert result.operation.state is OperationState.FAILED
        assert result.operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
        assert result.operation.error is not None
        assert result.operation.error.code == "audit_unavailable"
        assert boundary.count == 0
        assert await revoked_obligations.scan() == ()


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


@pytest.mark.parametrize(
    "receipt",
    (
        pytest.param(
            EffectStartReceipt(
                BoundaryCrossing.DEFINITELY_NOT_CROSSED,
                EffectKnowledge.KNOWN_EFFECT,
                reference="contradictory-reference",
                terminal_state=OperationState.SUCCEEDED,
            ),
            id="not-crossed-cannot-succeed-with-effect",
        ),
        pytest.param(
            EffectStartReceipt(
                BoundaryCrossing.CROSSED,
                EffectKnowledge.KNOWN_NO_EFFECT,
                reference="contradictory-reference",
                terminal_state=OperationState.FAILED,
            ),
            id="crossed-cannot-prove-no-effect",
        ),
        pytest.param(
            EffectStartReceipt(
                BoundaryCrossing.UNCERTAIN,
                EffectKnowledge.KNOWN_EFFECT,
                terminal_state=OperationState.SUCCEEDED,
            ),
            id="uncertain-crossing-cannot-prove-success",
        ),
    ),
)
@pytest.mark.anyio
async def test_contradictory_effect_receipt_trips_gate_without_persisting_claims(
    receipt: EffectStartReceipt, tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=StaticReceiptBoundary(receipt),
        )
        with pytest.raises(EffectReceiptError, match="outside the matrix"):
            await coordinator.execute(
                _request(
                    validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
                )
            )
        markers = await obligations.scan()
        assert len(markers) == 1
        operation = await store.get_operation(markers[0].operation_id)
        assert operation is not None
        assert operation.state is OperationState.RUNNING
        assert operation.effect_knowledge is EffectKnowledge.NONE
        assert gate.state.value == "tripped"
        assert (await store.audit_failure_state())[0]


@pytest.mark.anyio
async def test_transport_cancellation_cannot_leak_start_permit_or_interrupt_classification(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = BlockingBoundary()
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
        )
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        execution = asyncio.create_task(coordinator.execute(_request(key)))
        await boundary.started.wait()
        execution.cancel()
        trip = asyncio.create_task(gate.trip("concurrent_audit_failure"))
        await asyncio.sleep(0)
        assert not trip.done()

        boundary.release.set()
        with pytest.raises(asyncio.CancelledError):
            await execution
        await trip

        retained = await store.create_or_find(_request(key).admission)
        assert retained.operation is not None
        assert retained.operation.state is OperationState.SUCCEEDED
        assert boundary.count == 1
        assert await obligations.scan() == ()


@pytest.mark.anyio
async def test_adapter_cancelled_error_is_durably_uncertain_and_releases_permit(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=CancellingBoundary(),
        )
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.UNCERTAIN
        assert result.operation.effect_knowledge is EffectKnowledge.UNCERTAIN
        assert await obligations.scan() == ()
        await gate.trip("post_classification_check")


@pytest.mark.anyio
async def test_adapter_boundary_gate_error_after_start_is_uncertain_and_releases_permit(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        boundary = BoundaryGateErrorBoundary()
        coordinator, _, obligations, gate = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
        )
        result = await coordinator.execute(
            _request(validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY))
        )
        assert result.operation is not None
        assert result.operation.state is OperationState.UNCERTAIN
        assert result.operation.effect_knowledge is EffectKnowledge.UNCERTAIN
        assert boundary.count == 1
        assert await obligations.scan() == ()
        await asyncio.wait_for(gate.trip("post_classification_check"), timeout=1)


@pytest.mark.anyio
async def test_prepared_state_and_trusted_time_are_revalidated_at_admission_and_final_boundary(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        key = validate_and_digest_key(
            secrets.token_hex(32), IdempotencyKeyMode.PREPARED_EXECUTION_NONCE
        )
        await store.register_prepared_execution_nonce(
            PreparedNonceRegistration(
                key=key,
                owner=owner(),
                device_id="device-fixture",
                device_epoch=1,
                tool_name="internal.synthetic",
                contract_version="1.0.0",
                request_fingerprint_sha256="a" * 64,
                prepared_operation_id="prepared-fixture",
                prepared_input_sha256="1" * 64,
                prepared_expires_at=NOW + timedelta(minutes=5),
                prepared_state_binding_sha256="2" * 64,
                registered_boot_id_digest="3" * 64,
                monotonic_deadline_ns=1_000,
            )
        )
        verifier = SequencedPreparedStateVerifier("2" * 64, "4" * 64)
        boundary = CountingBoundary()
        coordinator, _, obligations, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=boundary,
            trusted_time_guard=TrustedTimeGuard(source=StaticTrustedTimeSource(), store=store),
            prepared_state_verifier=verifier,
        )
        base = _request(key)
        request = replace(
            base,
            admission=replace(
                base.admission,
                prepared_operation_id="prepared-fixture",
                prepared_input_sha256="1" * 64,
                prepared_state_binding_sha256="2" * 64,
            ),
            prepared_state_facts={"target_state": "protected-fixture"},
        )
        result = await coordinator.execute(request)
        assert result.operation is not None
        assert result.operation.state is OperationState.FAILED
        assert result.operation.error is not None
        assert result.operation.error.code == IdempotencyOutcome.PREPARED_MISMATCH.value
        assert boundary.count == 0
        assert [check.operation_id for check in verifier.checks] == [
            None,
            result.operation.operation_id,
        ]
        assert await obligations.scan() == ()


@pytest.mark.anyio
async def test_idempotency_conflict_and_cross_controller_tombstone_replay_are_audited(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        coordinator, _, _, _ = await _coordinator(
            root=tmp_path,
            repo_root=repo_root,
            store=store,
            boundary=CountingBoundary(),
        )
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        created = await coordinator.execute(_request(key))
        assert created.operation is not None
        conflict = await coordinator.execute(_request(key, fingerprint="f" * 64))
        assert conflict.outcome is IdempotencyOutcome.CONFLICT
        segment = tmp_path / "audit/epochs/epoch-1/segment-000001.jsonl"
        conflict_event = json.loads(segment.read_text().splitlines()[-1])
        assert conflict_event["payload"]["kind"] == "operation.idempotency_conflict"
        assert conflict_event["operation_id"] == created.operation.operation_id

        await store.compact_idempotency_binding(
            device_id="device-fixture",
            device_epoch=1,
            tool_name="internal.synthetic",
            contract_version="1.0.0",
            key_digest_sha256=key.digest_sha256,
            retired_at=NOW + timedelta(days=1),
        )
        foreign = _request(key)
        foreign = replace(
            foreign,
            admission=replace(foreign.admission, owner=owner("foreign-controller")),
        )
        replay = await coordinator.execute(foreign)
        assert replay.outcome is IdempotencyOutcome.OWNER_MISMATCH
        replay_event = json.loads(segment.read_text().splitlines()[-1])
        assert replay_event["payload"]["kind"] == "policy.decision"
        assert replay_event["payload"]["reason_code"] == "idempotency_owner_mismatch"
        assert replay_event["operation_id"] is None

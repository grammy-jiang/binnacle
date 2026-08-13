"""Accepted controlled-restart checkpoint, replay, rollback, and restriction tests."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from tests.phase9_support import controlled_restart_intent_and_ticket as _intent_and_ticket

from binnacle.domain.privileged import (
    BrokerExecutionState,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedTicket,
)
from binnacle.domain.privileged_observation import RuntimeSlotRole, RuntimeSlotState
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointIntent
from binnacle.privileged_broker.integrity import verify_privileged_broker_connection
from binnacle.privileged_broker.restart import (
    PrivilegedRestartCoordinator,
    PrivilegedRestartExecutionError,
    RestartDriverOutcome,
    RestartDriverResult,
)
from binnacle.privileged_broker.state import (
    PrivilegedStoreConflict,
    PrivilegedStoreError,
    PrivilegedStoreIdentity,
    PrivilegedStoreSettings,
    RetainedRestartSubeffect,
    SqlitePrivilegedEvidenceStore,
    open_privileged_store,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Verifier:
    def validate(self, ticket: PrivilegedTicket) -> None:
        assert ticket.action is PrivilegedAction.CONTROLLED_RESTART


class _Driver:
    def __init__(
        self,
        now: datetime,
        *,
        candidate_verification: RestartDriverOutcome = RestartDriverOutcome.SUCCEEDED,
        rollback_selection: RestartDriverOutcome = RestartDriverOutcome.SUCCEEDED,
        phase_outcomes: dict[str, RestartDriverOutcome] | None = None,
        raise_phase: str | None = None,
    ) -> None:
        self.now = now
        self.candidate_verification = candidate_verification
        self.rollback_selection = rollback_selection
        self.phase_outcomes = phase_outcomes or {}
        self.raise_phase = raise_phase
        self.calls: list[str] = []

    def _result(self, phase: str, outcome: RestartDriverOutcome) -> RestartDriverResult:
        self.calls.append(phase)
        if self.raise_phase == phase:
            raise OSError(f"{phase} boundary unavailable")
        outcome = self.phase_outcomes.get(phase, outcome)
        crossed = outcome is not RestartDriverOutcome.FAILED
        return RestartDriverResult(
            outcome=outcome,
            effect_started=crossed,
            effect_reference=f"effect:{phase}" if crossed else None,
            boundary_receipt_sha256=_digest(f"boundary:{phase}") if crossed else None,
            result_evidence_sha256=_digest(f"result:{phase}:{outcome.value}"),
            observed_at=self.now + timedelta(seconds=len(self.calls)),
        )

    async def stop_service(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("service_stop", RestartDriverOutcome.SUCCEEDED)

    async def stop_service_for_rollback(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("rollback_service_stop", RestartDriverOutcome.SUCCEEDED)

    async def activate_candidate(self, _checkpoint: object, request: object) -> RestartDriverResult:
        del request
        return self._result("candidate_select", RestartDriverOutcome.SUCCEEDED)

    async def start_candidate(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("candidate_start", RestartDriverOutcome.SUCCEEDED)

    async def verify_candidate(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("candidate_verify", self.candidate_verification)

    async def restore_lkg(self, _checkpoint: object, request: object) -> RestartDriverResult:
        del request
        return self._result("lkg_select", self.rollback_selection)

    async def start_lkg(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("lkg_start", RestartDriverOutcome.SUCCEEDED)

    async def verify_lkg(self, _checkpoint: object) -> RestartDriverResult:
        return self._result("lkg_verify", RestartDriverOutcome.SUCCEEDED)


def _migrate(database: Path, repo_root: Path) -> None:
    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")


async def _open(
    database: Path,
    runtime: Path,
    *,
    now: datetime,
    instance: str,
) -> SqlitePrivilegedEvidenceStore:
    return await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id=instance,
            boot_id_sha256=_digest("boot"),
            protocol_version="v1",
            build_sha256=_digest("build"),
            profile_sha256=_digest("profile"),
        ),
        ticket_verifier=_Verifier(),
        acceptance_enabled=True,
    )


async def _bootstrap_selector(
    store: SqlitePrivilegedEvidenceStore,
    intent: PrivilegedRestartCheckpointIntent,
    *,
    now: datetime,
) -> None:
    await store.record_initial_selector(
        slot=intent.lkg_slot,
        publication_receipt_sha256=_digest("offline-selector-publication"),
        verification_evidence_sha256=_digest("offline-selector-verification"),
        recorded_at=now - timedelta(seconds=2),
    )


@pytest.mark.anyio
async def test_candidate_success_closes_exact_checkpoint_and_binding(
    tmp_path: Path, repo_root: Path
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-1")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    driver = _Driver(now)
    try:
        receipt = await PrivilegedRestartCoordinator(
            store=store, driver=driver, clock=lambda: now
        ).start(ticket, intent)
        checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
        binding = await store.get(ticket.operation_id)
        assert receipt.operation_id == ticket.operation_id
        assert checkpoint is not None and binding is not None
        assert checkpoint.state is BrokerRestartCheckpointState.TERMINAL
        assert checkpoint.outcome is BrokerRestartOutcome.CANDIDATE_READY
        assert checkpoint.selected_slot_id == intent.candidate_slot.slot_id
        assert binding.execution_state is BrokerExecutionState.TERMINAL
        assert binding.restart_checkpoint_sha256 == checkpoint.checkpoint_sha256
        assert binding.lkg_promotion_evidence_sha256 is None
        with closing(sqlite3.connect(database)) as connection:
            pending_report = verify_privileged_broker_connection(connection)
        assert pending_report.outstanding_accepted_bindings == 1
        assert driver.calls == [
            "service_stop",
            "candidate_select",
            "candidate_start",
            "candidate_verify",
        ]
        assert checkpoint.closed_at is not None
        promotion_audit = _digest("candidate-ready-audit-closure")
        promoted_at = checkpoint.closed_at + timedelta(seconds=1)
        with pytest.raises(PrivilegedStoreConflict, match="lacks audited"):
            await store.promote_restart_lkg(
                ticket.operation_id,
                audit_closure_evidence_sha256=promotion_audit,
                promoted_at=checkpoint.closed_at - timedelta(microseconds=1),
            )
        promoted = await store.promote_restart_lkg(
            ticket.operation_id,
            audit_closure_evidence_sha256=promotion_audit,
            promoted_at=promoted_at,
        )
        assert promoted.lkg_promotion_audit_sha256 == promotion_audit
        assert promoted.lkg_promotion_evidence_sha256 is not None
        assert promoted.lkg_promoted_at == promoted_at
        retained_checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
        assert retained_checkpoint is not None
        assert retained_checkpoint.intent == intent
        replay = await store.promote_restart_lkg(
            ticket.operation_id,
            audit_closure_evidence_sha256=promotion_audit,
            promoted_at=promoted_at + timedelta(seconds=1),
        )
        assert replay == promoted
        with pytest.raises(PrivilegedStoreConflict, match="replay differs"):
            await store.promote_restart_lkg(
                ticket.operation_id,
                audit_closure_evidence_sha256=_digest("different-audit-closure"),
                promoted_at=promoted_at,
            )
        with closing(sqlite3.connect(database)) as connection:
            rows = tuple(
                connection.execute(
                    "SELECT selector_generation,new_slot_id,state "
                    "FROM privileged_selector_generations ORDER BY selector_generation"
                )
            )
            slots = tuple(
                connection.execute(
                    "SELECT slot_id,role,state FROM privileged_runtime_slots "
                    "ORDER BY slot_generation"
                )
            )
            selector_requested_at = datetime.fromisoformat(
                connection.execute(
                    "SELECT created_at FROM privileged_selector_generations "
                    "WHERE selector_generation=2"
                ).fetchone()[0]
            )
            report = verify_privileged_broker_connection(connection)
        assert rows == (
            (1, "lkg-slot", "verified"),
            (2, "candidate-slot", "verified"),
        )
        assert slots == (
            ("lkg-slot", "prior", "prior"),
            ("candidate-slot", "lkg", "lkg"),
        )
        assert report.selector_generations == 2
        assert report.outstanding_accepted_bindings == 0
        selector_replay = await store.begin_selector_change(
            operation_id=ticket.operation_id,
            expected_current_slot_id=intent.lkg_slot.slot_id,
            target_slot_id=intent.candidate_slot.slot_id,
            requested_at=selector_requested_at,
        )
        assert (
            selector_replay.request.target_slot_identity_sha256
            == intent.candidate_slot.slot_identity_sha256
        )
        next_lkg = replace(
            intent.candidate_slot,
            role=RuntimeSlotRole.LKG,
            state=RuntimeSlotState.LKG,
        )
        next_candidate = replace(
            intent.candidate_slot,
            slot_id="candidate-slot-next",
            slot_generation=3,
            slot_path="/srv/binnacle-runtime/slots/candidate-slot-next",
            source_sha256=_digest("next-source"),
            environment_sha256=_digest("next-environment"),
            candidate_verification_sha256=_digest("next-verification"),
            complete_manifest_sha256=_digest("next-complete-manifest"),
        )
        next_preflight = replace(
            intent.preflight,
            current_runtime_identity_sha256=next_lkg.slot_identity_sha256,
            current_service_observation_sha256=_digest("next-service-observation"),
            lkg_slot_identity_sha256=next_lkg.slot_identity_sha256,
            candidate_slot_identity_sha256=next_candidate.slot_identity_sha256,
            candidate_verification_sha256=(next_candidate.candidate_verification_sha256),
            outstanding_state_sha256=_digest("next-outstanding"),
            state_binding_sha256=_digest("next-state-binding"),
            observed_at=now - timedelta(milliseconds=200),
        )
        next_issued_at = now - timedelta(milliseconds=100)
        next_ticket = replace(
            ticket,
            operation_id="operation:restart-next",
            ticket_id="ticket:restart-next",
            nonce="2" * 64,
            request_fingerprint_sha256=_digest("next-request"),
            current_state_binding_sha256=next_preflight.state_binding_sha256,
            operation_specific_evidence_sha256=_digest("next-preparation"),
            issued_at=next_issued_at,
        )
        next_intent = PrivilegedRestartCheckpointIntent(
            operation_id=next_ticket.operation_id,
            ticket_id=next_ticket.ticket_id,
            ticket_sha256=next_ticket.ticket_sha256,
            service_profile_sha256=next_ticket.target_profile_sha256,
            workspace_id=intent.workspace_id,
            workspace_fence_version=intent.workspace_fence_version + 1,
            preflight=next_preflight,
            candidate_slot=next_candidate,
            lkg_slot=next_lkg,
            restart_deadline_seconds=intent.restart_deadline_seconds,
            created_at=next_issued_at,
        )
        await store.accept_once(next_ticket)
        next_checkpoint = await store.create_restart_checkpoint(
            ticket=next_ticket,
            intent=next_intent,
        )
        assert next_checkpoint.intent.lkg_slot == next_lkg
        await store.advance_restart_checkpoint(
            operation_id=next_ticket.operation_id,
            expected_state=BrokerRestartCheckpointState.CHECKPOINTED,
            next_state=BrokerRestartCheckpointState.TERMINAL,
            selected_slot_id=None,
            outcome=BrokerRestartOutcome.NO_SUBEFFECT,
            result_evidence_sha256=_digest("next-no-subeffect"),
            recorded_at=max(next_checkpoint.updated_at, promoted_at) + timedelta(seconds=1),
        )
    finally:
        await store.close()

    upgraded = await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id="broker-upgraded",
            boot_id_sha256=_digest("new-boot"),
            protocol_version="v2",
            build_sha256=_digest("new-build"),
            profile_sha256=_digest("new-profile"),
        ),
        ticket_verifier=_Verifier(),
        acceptance_enabled=True,
    )
    try:
        assert upgraded.readiness == "ready"
        retained = await upgraded.get(ticket.operation_id)
        assert retained is not None
        assert retained.lkg_promotion_audit_sha256 == promotion_audit
    finally:
        await upgraded.close()


@pytest.mark.anyio
async def test_candidate_failure_restores_and_verifies_exact_lkg(
    tmp_path: Path, repo_root: Path
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-1")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    driver = _Driver(now, candidate_verification=RestartDriverOutcome.FAILED)
    try:
        await PrivilegedRestartCoordinator(store=store, driver=driver, clock=lambda: now).start(
            ticket, intent
        )
        checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
        assert checkpoint is not None
        assert checkpoint.outcome is BrokerRestartOutcome.ROLLBACK_READY
        assert checkpoint.selected_slot_id == intent.lkg_slot.slot_id
        assert driver.calls[-4:] == [
            "rollback_service_stop",
            "lkg_select",
            "lkg_start",
            "lkg_verify",
        ]
        with closing(sqlite3.connect(database)) as connection:
            rows = tuple(
                connection.execute(
                    "SELECT new_slot_id,state FROM privileged_selector_generations "
                    "ORDER BY selector_generation"
                )
            )
            verify_privileged_broker_connection(connection)
        assert rows == (
            ("lkg-slot", "verified"),
            ("candidate-slot", "published"),
            ("lkg-slot", "restored"),
        )
    finally:
        await store.close()


@pytest.mark.anyio
async def test_pending_candidate_promotion_pins_exact_broker_identity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    intent, ticket = _intent_and_ticket(now)
    store = await _open(database, runtime, now=now, instance="broker-1")
    await _bootstrap_selector(store, intent, now=now)
    await PrivilegedRestartCoordinator(
        store=store,
        driver=_Driver(now),
        clock=lambda: now,
    ).start(ticket, intent)
    checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
    assert checkpoint is not None and checkpoint.closed_at is not None
    await store.close()

    with pytest.raises(PrivilegedStoreError, match=r"outstanding.*exact identity"):
        await open_privileged_store(
            settings=PrivilegedStoreSettings(
                path=database,
                runtime_directory=runtime,
                verify_permissions=False,
            ),
            identity=PrivilegedStoreIdentity(
                broker_instance_id="broker-upgraded",
                boot_id_sha256=_digest("new-boot"),
                protocol_version="v2",
                build_sha256=_digest("new-build"),
                profile_sha256=_digest("new-profile"),
            ),
            ticket_verifier=_Verifier(),
            acceptance_enabled=True,
        )

    recovery = await _open(database, runtime, now=now, instance="broker-recovery")
    try:
        assert recovery.readiness == "restricted_recovery"
        promoted = await recovery.promote_restart_lkg(
            ticket.operation_id,
            audit_closure_evidence_sha256=_digest("recovered-audit-closure"),
            promoted_at=checkpoint.closed_at + timedelta(seconds=1),
        )
        assert promoted.lkg_promotion_evidence_sha256 is not None
    finally:
        await recovery.close()


@pytest.mark.anyio
async def test_unverifiable_rollback_enters_restricted_recovery(
    tmp_path: Path, repo_root: Path
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-1")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    driver = _Driver(
        now,
        candidate_verification=RestartDriverOutcome.FAILED,
        rollback_selection=RestartDriverOutcome.UNCERTAIN,
    )
    try:
        await PrivilegedRestartCoordinator(store=store, driver=driver, clock=lambda: now).start(
            ticket, intent
        )
        checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
        binding = await store.get(ticket.operation_id)
        assert checkpoint is not None and binding is not None
        assert checkpoint.state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY
        assert checkpoint.outcome is BrokerRestartOutcome.RESTRICTED_RECOVERY
        assert binding.execution_state is BrokerExecutionState.RESTRICTED_RECOVERY
    finally:
        await store.close()


@pytest.mark.anyio
async def test_reopen_reuses_terminal_subeffect_instead_of_repeating_stop(
    tmp_path: Path, repo_root: Path
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    intent, ticket = _intent_and_ticket(now)
    first = await _open(database, runtime, now=now, instance="broker-1")
    await _bootstrap_selector(first, intent, now=now)
    await first.accept_once(ticket)
    checkpoint = await first.create_restart_checkpoint(ticket=ticket, intent=intent)
    subeffect = await first.begin_restart_subeffect(
        operation_id=ticket.operation_id,
        phase="service_stop",
        kind="service_stop",
        intent_sha256=_digest("retained-stop-intent"),
        recorded_at=now,
    )
    await first.finish_restart_subeffect(
        operation_id=ticket.operation_id,
        subeffect_id=subeffect.subeffect_id,
        effect_started=True,
        effect_reference="effect:service_stop",
        boundary_receipt_sha256=_digest("boundary:service_stop"),
        result_evidence_sha256=_digest("result:service_stop:succeeded"),
        succeeded=True,
        uncertain=False,
        recorded_at=now,
    )
    await first.close()

    reopened = await _open(database, runtime, now=now, instance="broker-2")
    driver = _Driver(now)
    # The coordinator derives its own exact phase-intent digest. Replace the synthetic
    # retained digest with that value by recreating the same checkpoint-derived preimage.
    expected_intent = _digest("retained-stop-intent")
    assert checkpoint.state is BrokerRestartCheckpointState.CHECKPOINTED
    # A conflicting retained intent is fail-closed and proves no duplicate effect occurs.
    with pytest.raises(PrivilegedStoreConflict, match="intent changed"):
        await PrivilegedRestartCoordinator(store=reopened, driver=driver, clock=lambda: now).resume(
            ticket.operation_id
        )
    assert expected_intent and driver.calls == []
    await reopened.close()


@pytest.mark.anyio
async def test_exact_retained_phase_result_is_reused_after_crash(
    tmp_path: Path, repo_root: Path
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    intent, ticket = _intent_and_ticket(now)
    first = await _open(database, runtime, now=now, instance="broker-1")
    await _bootstrap_selector(first, intent, now=now)
    await first.accept_once(ticket)
    checkpoint = await first.create_restart_checkpoint(ticket=ticket, intent=intent)
    phase_intent = hashlib.sha256(b"unused").hexdigest()
    # Match the coordinator's canonical intent exactly.
    from binnacle.domain.privileged import canonical_sha256

    phase_intent = canonical_sha256(
        {
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "expected_state": checkpoint.state,
            "phase": "service_stop",
            "selected_slot_id": checkpoint.selected_slot_id,
        }
    )
    subeffect = await first.begin_restart_subeffect(
        operation_id=ticket.operation_id,
        phase="service_stop",
        kind="service_stop",
        intent_sha256=phase_intent,
        recorded_at=now,
    )
    await first.finish_restart_subeffect(
        operation_id=ticket.operation_id,
        subeffect_id=subeffect.subeffect_id,
        effect_started=True,
        effect_reference="effect:service_stop",
        boundary_receipt_sha256=_digest("boundary:service_stop"),
        result_evidence_sha256=_digest("result:service_stop:succeeded"),
        succeeded=True,
        uncertain=False,
        recorded_at=now,
    )
    await first.close()

    reopened = await _open(database, runtime, now=now, instance="broker-2")
    driver = _Driver(now)
    try:
        result = await PrivilegedRestartCoordinator(
            store=reopened, driver=driver, clock=lambda: now
        ).resume(ticket.operation_id)
        assert result.outcome is BrokerRestartOutcome.CANDIDATE_READY
        assert driver.calls[0] == "candidate_select"
        assert "service_stop" not in driver.calls
    finally:
        await reopened.close()


@pytest.mark.anyio
async def test_published_selector_receipt_is_reused_without_duplicate_generation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    intent, ticket = _intent_and_ticket(now)
    first = await _open(database, runtime, now=now, instance="broker-1")
    await _bootstrap_selector(first, intent, now=now)
    await first.accept_once(ticket)
    checkpoint = await first.create_restart_checkpoint(ticket=ticket, intent=intent)
    checkpoint = await first.advance_restart_checkpoint(
        operation_id=ticket.operation_id,
        expected_state=checkpoint.state,
        next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
        selected_slot_id=None,
        service_stopped=True,
        recorded_at=checkpoint.updated_at,
    )
    effect_time = checkpoint.updated_at + timedelta(milliseconds=1)
    selector = await first.begin_selector_change(
        operation_id=ticket.operation_id,
        expected_current_slot_id=intent.lkg_slot.slot_id,
        target_slot_id=intent.candidate_slot.slot_id,
        requested_at=checkpoint.updated_at,
    )
    from binnacle.domain.privileged import canonical_sha256

    phase_intent = canonical_sha256(
        {
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "expected_state": checkpoint.state,
            "phase": "candidate_select",
            "selected_slot_id": checkpoint.selected_slot_id,
        }
    )
    subeffect = await first.begin_restart_subeffect(
        operation_id=ticket.operation_id,
        phase="candidate_select",
        kind="selector_activate",
        intent_sha256=phase_intent,
        recorded_at=effect_time,
    )
    result_sha256 = _digest("published-candidate-selector")
    await first.finish_restart_subeffect(
        operation_id=ticket.operation_id,
        subeffect_id=subeffect.subeffect_id,
        effect_started=True,
        effect_reference="selector:2",
        boundary_receipt_sha256=result_sha256,
        result_evidence_sha256=result_sha256,
        succeeded=True,
        uncertain=False,
        recorded_at=effect_time,
    )
    await first.finish_selector_change(
        request=selector.request,
        succeeded=True,
        uncertain=False,
        effect_started=True,
        evidence_sha256=result_sha256,
        recorded_at=effect_time,
    )
    await first.close()

    reopened = await _open(database, runtime, now=now, instance="broker-2")
    driver = _Driver(now)
    try:
        result = await PrivilegedRestartCoordinator(
            store=reopened,
            driver=driver,
            clock=lambda: now,
        ).resume(ticket.operation_id)
        assert result.outcome is BrokerRestartOutcome.CANDIDATE_READY
        assert "candidate_select" not in driver.calls
        with closing(sqlite3.connect(database)) as connection:
            generations = connection.execute(
                "SELECT COUNT(*) FROM privileged_selector_generations"
            ).fetchone()[0]
            verify_privileged_broker_connection(connection)
        assert generations == 2
    finally:
        await reopened.close()


def test_checkpoint_intent_rejects_mixed_candidate_lkg_generation() -> None:
    now = datetime.now(UTC)
    intent, _ticket = _intent_and_ticket(now)
    with pytest.raises(ValueError, match=r"slots differ|incompatible"):
        replace(
            intent,
            lkg_slot=replace(intent.lkg_slot, policy_sha256=_digest("other-policy")),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("phase", "phase_outcome", "expected_calls"),
    (
        ("service_stop", RestartDriverOutcome.FAILED, ("service_stop",)),
        ("service_stop", RestartDriverOutcome.UNCERTAIN, ("service_stop",)),
        (
            "candidate_select",
            RestartDriverOutcome.FAILED,
            ("candidate_select", "rollback_service_stop", "lkg_select", "lkg_start", "lkg_verify"),
        ),
        ("candidate_select", RestartDriverOutcome.UNCERTAIN, ("candidate_select",)),
        (
            "candidate_start",
            RestartDriverOutcome.FAILED,
            ("candidate_start", "rollback_service_stop", "lkg_select", "lkg_start", "lkg_verify"),
        ),
        ("candidate_start", RestartDriverOutcome.UNCERTAIN, ("candidate_start",)),
        ("candidate_verify", RestartDriverOutcome.UNCERTAIN, ("candidate_verify",)),
        ("rollback_service_stop", RestartDriverOutcome.FAILED, ("rollback_service_stop",)),
        ("lkg_start", RestartDriverOutcome.FAILED, ("lkg_start",)),
        ("lkg_verify", RestartDriverOutcome.FAILED, ("lkg_verify",)),
    ),
)
async def test_each_restart_fault_is_terminal_or_restricted_without_widening(
    tmp_path: Path,
    repo_root: Path,
    phase: str,
    phase_outcome: RestartDriverOutcome,
    expected_calls: tuple[str, ...],
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-fault")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    baseline = (
        {"candidate_verify": RestartDriverOutcome.FAILED}
        if phase in {"rollback_service_stop", "lkg_start", "lkg_verify"}
        else {}
    )
    driver = _Driver(now, phase_outcomes={**baseline, phase: phase_outcome})
    try:
        await PrivilegedRestartCoordinator(
            store=store,
            driver=driver,
            clock=lambda: now,
        ).start(ticket, intent)
        checkpoint = await store.get_restart_checkpoint(ticket.operation_id)
        binding = await store.get(ticket.operation_id)
        assert checkpoint is not None and binding is not None
        assert tuple(call for call in driver.calls if call in expected_calls) == expected_calls
        if phase == "service_stop" and phase_outcome is RestartDriverOutcome.FAILED:
            assert checkpoint.state is BrokerRestartCheckpointState.TERMINAL
            assert checkpoint.outcome is BrokerRestartOutcome.NO_SUBEFFECT
            assert binding.execution_state is BrokerExecutionState.TERMINAL
        elif phase_outcome is RestartDriverOutcome.FAILED and phase in {
            "candidate_select",
            "candidate_start",
        }:
            assert checkpoint.outcome is BrokerRestartOutcome.ROLLBACK_READY
        else:
            assert checkpoint.state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY
            assert checkpoint.outcome is BrokerRestartOutcome.RESTRICTED_RECOVERY
            assert binding.execution_state is BrokerExecutionState.RESTRICTED_RECOVERY
    finally:
        await store.close()


@pytest.mark.anyio
async def test_driver_exception_is_retained_as_uncertain_and_replayed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-exception")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    driver = _Driver(now, raise_phase="candidate_start")
    coordinator = PrivilegedRestartCoordinator(store=store, driver=driver, clock=lambda: now)
    try:
        await coordinator.start(ticket, intent)
        first = await store.get_restart_checkpoint(ticket.operation_id)
        replay = await coordinator.resume(ticket.operation_id)
        assert first == replay
        assert replay.state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY
        assert driver.calls.count("candidate_start") == 1
    finally:
        await store.close()


@pytest.mark.anyio
async def test_recovery_scan_resumes_checkpoint_and_retains_acceptance_gap(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-recovery")
    intent, ticket = _intent_and_ticket(now)
    await _bootstrap_selector(store, intent, now=now)
    await store.accept_once(ticket)
    coordinator = PrivilegedRestartCoordinator(store=store, driver=_Driver(now), clock=lambda: now)
    try:
        assert await coordinator.recover_all() == ()
        await store.create_restart_checkpoint(ticket=ticket, intent=intent)
        recovered = await coordinator.recover_all()
        assert len(recovered) == 1
        assert recovered[0].outcome is BrokerRestartOutcome.CANDIDATE_READY
        assert await coordinator.resume(ticket.operation_id) == recovered[0]
        with pytest.raises(PrivilegedRestartExecutionError, match="checkpoint is absent"):
            await coordinator.resume("operation:absent")
    finally:
        await store.close()


@pytest.mark.anyio
async def test_selector_and_subeffect_ledgers_reject_conflicting_replays(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await _open(database, runtime, now=now, instance="broker-ledger")
    intent, ticket = _intent_and_ticket(now)
    initial_receipt = _digest("offline-selector-publication")
    initial_verification = _digest("offline-selector-verification")
    await _bootstrap_selector(store, intent, now=now)
    await store.accept_once(ticket)
    checkpoint = await store.create_restart_checkpoint(ticket=ticket, intent=intent)
    try:
        initial = await store.record_initial_selector(
            slot=intent.lkg_slot,
            publication_receipt_sha256=initial_receipt,
            verification_evidence_sha256=initial_verification,
            recorded_at=now - timedelta(seconds=2),
        )
        assert initial.state == "verified"
        with pytest.raises(PrivilegedStoreConflict, match="initial selector conflicts"):
            await store.record_initial_selector(
                slot=intent.lkg_slot,
                publication_receipt_sha256=_digest("changed-initial-receipt"),
                verification_evidence_sha256=initial_verification,
                recorded_at=now - timedelta(seconds=2),
            )

        with pytest.raises(PrivilegedStoreConflict, match="lacks accepted checkpoint"):
            await store.begin_selector_change(
                operation_id=ticket.operation_id,
                expected_current_slot_id=intent.lkg_slot.slot_id,
                target_slot_id="foreign-slot",
                requested_at=checkpoint.updated_at,
            )
        selector = await store.begin_selector_change(
            operation_id=ticket.operation_id,
            expected_current_slot_id=intent.lkg_slot.slot_id,
            target_slot_id=intent.candidate_slot.slot_id,
            requested_at=checkpoint.updated_at,
        )
        assert (
            await store.begin_selector_change(
                operation_id=ticket.operation_id,
                expected_current_slot_id=intent.lkg_slot.slot_id,
                target_slot_id=intent.candidate_slot.slot_id,
                requested_at=checkpoint.updated_at,
            )
        ) == selector
        with pytest.raises(PrivilegedStoreConflict, match="selector replay differs"):
            await store.begin_selector_change(
                operation_id=ticket.operation_id,
                expected_current_slot_id=intent.lkg_slot.slot_id,
                target_slot_id=intent.candidate_slot.slot_id,
                requested_at=checkpoint.updated_at + timedelta(seconds=1),
            )
        with pytest.raises(PrivilegedStoreConflict, match="contradictory"):
            await store.finish_selector_change(
                request=selector.request,
                succeeded=True,
                uncertain=True,
                effect_started=True,
                evidence_sha256=_digest("selector-result"),
                recorded_at=checkpoint.updated_at + timedelta(seconds=1),
            )

        selector_evidence = _digest("selector-published")
        published = await store.finish_selector_change(
            request=selector.request,
            succeeded=True,
            uncertain=False,
            effect_started=True,
            evidence_sha256=selector_evidence,
            recorded_at=checkpoint.updated_at + timedelta(seconds=1),
        )
        assert (
            await store.finish_selector_change(
                request=selector.request,
                succeeded=True,
                uncertain=False,
                effect_started=True,
                evidence_sha256=selector_evidence,
                recorded_at=checkpoint.updated_at + timedelta(seconds=1),
            )
        ) == published
        with pytest.raises(PrivilegedStoreConflict, match="conflicts with retained truth"):
            await store.finish_selector_change(
                request=selector.request,
                succeeded=True,
                uncertain=False,
                effect_started=True,
                evidence_sha256=_digest("changed-selector-result"),
                recorded_at=checkpoint.updated_at + timedelta(seconds=1),
            )

        with pytest.raises(PrivilegedStoreConflict, match="verification intent is absent"):
            await store.verify_selector_change(
                operation_id=ticket.operation_id,
                target_slot_id="foreign-slot",
                verification_evidence_sha256=_digest("foreign-verification"),
                restored=False,
                recorded_at=checkpoint.updated_at + timedelta(seconds=2),
            )
        verification = _digest("candidate-verification")
        verified = await store.verify_selector_change(
            operation_id=ticket.operation_id,
            target_slot_id=intent.candidate_slot.slot_id,
            verification_evidence_sha256=verification,
            restored=False,
            recorded_at=checkpoint.updated_at + timedelta(seconds=2),
        )
        assert (
            await store.verify_selector_change(
                operation_id=ticket.operation_id,
                target_slot_id=intent.candidate_slot.slot_id,
                verification_evidence_sha256=verification,
                restored=False,
                recorded_at=checkpoint.updated_at + timedelta(seconds=2),
            )
        ) == verified
        with pytest.raises(PrivilegedStoreConflict, match="verification conflicts"):
            await store.verify_selector_change(
                operation_id=ticket.operation_id,
                target_slot_id=intent.candidate_slot.slot_id,
                verification_evidence_sha256=verification,
                restored=True,
                recorded_at=checkpoint.updated_at + timedelta(seconds=2),
            )

        for phase, kind, digest in (
            ("service_stop", "shell", _digest("intent")),
            ("Bad Phase", "service_stop", _digest("intent")),
            ("service_stop", "service_stop", "bad"),
        ):
            with pytest.raises(PrivilegedStoreError):
                await store.begin_restart_subeffect(
                    operation_id=ticket.operation_id,
                    phase=phase,
                    kind=kind,
                    intent_sha256=digest,
                    recorded_at=checkpoint.updated_at,
                )
        phase_intent = _digest("service-stop-intent")
        subeffect = await store.begin_restart_subeffect(
            operation_id=ticket.operation_id,
            phase="service_stop",
            kind="service_stop",
            intent_sha256=phase_intent,
            recorded_at=checkpoint.updated_at,
        )
        assert not subeffect.complete and not subeffect.uncertain
        assert (
            await store.begin_restart_subeffect(
                operation_id=ticket.operation_id,
                phase="service_stop",
                kind="service_stop",
                intent_sha256=phase_intent,
                recorded_at=checkpoint.updated_at,
            )
        ) == subeffect
        with pytest.raises(PrivilegedStoreConflict, match="intent changed"):
            await store.begin_restart_subeffect(
                operation_id=ticket.operation_id,
                phase="service_stop",
                kind="service_start",
                intent_sha256=phase_intent,
                recorded_at=checkpoint.updated_at,
            )
        with pytest.raises(PrivilegedStoreConflict, match="another restart subeffect"):
            await store.begin_restart_subeffect(
                operation_id=ticket.operation_id,
                phase="candidate_start",
                kind="service_start",
                intent_sha256=_digest("candidate-start-intent"),
                recorded_at=checkpoint.updated_at,
            )

        result_evidence = _digest("service-stop-failed")

        async def finish_subeffect(
            *,
            effect_started: bool = False,
            effect_reference: str | None = None,
            boundary_receipt_sha256: str | None = None,
            result_evidence_sha256: str = result_evidence,
            succeeded: bool = False,
            uncertain: bool = False,
        ) -> RetainedRestartSubeffect:
            return await store.finish_restart_subeffect(
                operation_id=ticket.operation_id,
                subeffect_id=subeffect.subeffect_id,
                effect_started=effect_started,
                effect_reference=effect_reference,
                boundary_receipt_sha256=boundary_receipt_sha256,
                result_evidence_sha256=result_evidence_sha256,
                succeeded=succeeded,
                uncertain=uncertain,
                recorded_at=checkpoint.updated_at + timedelta(seconds=3),
            )

        with pytest.raises(PrivilegedStoreError):
            await finish_subeffect(result_evidence_sha256="bad")
        with pytest.raises(PrivilegedStoreError):
            await finish_subeffect(boundary_receipt_sha256="bad")
        with pytest.raises(PrivilegedStoreError):
            await finish_subeffect(effect_reference="")
        with pytest.raises(PrivilegedStoreError):
            await finish_subeffect(uncertain=True)
        with pytest.raises(PrivilegedStoreError):
            await finish_subeffect(uncertain=True, effect_started=True, succeeded=True)

        finished = await finish_subeffect()
        assert finished.complete and not finished.uncertain
        assert await finish_subeffect() == finished
        with pytest.raises(PrivilegedStoreConflict, match="result changed"):
            await finish_subeffect(result_evidence_sha256=_digest("changed-result"))

        with pytest.raises(PrivilegedStoreError, match="digest is invalid"):
            await store.advance_restart_checkpoint(
                operation_id=ticket.operation_id,
                expected_state=checkpoint.state,
                next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
                selected_slot_id=None,
                result_evidence_sha256="bad",
                recorded_at=checkpoint.updated_at + timedelta(seconds=4),
            )
        advanced = await store.advance_restart_checkpoint(
            operation_id=ticket.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
            selected_slot_id=None,
            service_stopped=True,
            recorded_at=checkpoint.updated_at + timedelta(seconds=4),
        )
        replay = await store.advance_restart_checkpoint(
            operation_id=ticket.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
            selected_slot_id=None,
            recorded_at=checkpoint.updated_at + timedelta(seconds=4),
        )
        assert replay == advanced
        with pytest.raises(PrivilegedStoreConflict, match="preimage changed"):
            await store.advance_restart_checkpoint(
                operation_id=ticket.operation_id,
                expected_state=checkpoint.state,
                next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
                selected_slot_id=intent.candidate_slot.slot_id,
                recorded_at=checkpoint.updated_at + timedelta(seconds=4),
            )
    finally:
        await store.close()

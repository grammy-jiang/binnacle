"""Fixed systemd, selector, and exact readiness driver tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from binnacle.domain.privileged import (
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
)
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightResult,
    RuntimeIdentity,
    RuntimeSlotRole,
    RuntimeSlotState,
    ServiceInspectionResult,
    SourceDirtyState,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import (
    PrivilegedRestartCheckpointIntent,
    PrivilegedRestartCheckpointSnapshot,
    PrivilegedRestartError,
)
from binnacle.privileged_broker.restart import RestartDriverOutcome, RestartDriverResult
from binnacle.privileged_broker.restart_driver import (
    ExactRestartRuntimeVerifier,
    FixedControlledRestartDriver,
    FixedSystemdServiceManager,
    FixedSystemdSettings,
    RestartDriverAdapterError,
    RestartRuntimeObservation,
)
from binnacle.privileged_broker.runtime_publication import (
    FilesystemRuntimeSlotPublisher,
    RuntimeSelectorActivationReceipt,
    RuntimeSelectorActivationRequest,
    RuntimeSelectorConflict,
    RuntimeSelectorPublicationUncertain,
    runtime_selector_intent_sha256,
)

NOW = datetime(2026, 8, 13, 3, 4, 5, tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _slot(*, candidate: bool) -> VerifiedRuntimeSlot:
    slot_id = "candidate-slot" if candidate else "lkg-slot"
    return VerifiedRuntimeSlot(
        slot_id=slot_id,
        slot_generation=2 if candidate else 1,
        slot_path=f"/srv/binnacle-runtime/slots/{slot_id}",
        role=RuntimeSlotRole.CANDIDATE if candidate else RuntimeSlotRole.LKG,
        state=RuntimeSlotState.COMPLETE if candidate else RuntimeSlotState.LKG,
        source_sha256=_digest(f"source:{slot_id}"),
        environment_sha256=_digest(f"environment:{slot_id}"),
        config_sha256=_digest("config"),
        policy_sha256=_digest("policy"),
        manifest_sha256=_digest("manifest"),
        service_definition_sha256=_digest("service"),
        deployed_peer_set_sha256=_digest("peers"),
        migration_heads_sha256=_digest("heads"),
        layout_sha256=_digest("layout"),
        candidate_verification_sha256=_digest(f"verify:{slot_id}"),
        complete_manifest_sha256=_digest(f"complete:{slot_id}"),
        byte_count=4096,
        inode_count=64,
        completed_at=NOW - timedelta(minutes=2),
    )


def _checkpoint() -> PrivilegedRestartCheckpointSnapshot:
    candidate = _slot(candidate=True)
    lkg = _slot(candidate=False)
    preflight = RestartPreflightResult(
        kind=RestartPreflightKind.CONTROLLED_SELF,
        available=True,
        reason_codes=(),
        predicted_impacts=tuple(sorted(RestartImpact, key=lambda item: item.value)),
        current_runtime_identity_sha256=_digest("current-runtime"),
        current_service_observation_sha256=_digest("service-observation"),
        lkg_slot_identity_sha256=lkg.slot_identity_sha256,
        candidate_slot_identity_sha256=candidate.slot_identity_sha256,
        candidate_verification_sha256=candidate.candidate_verification_sha256,
        outstanding_state_sha256=_digest("outstanding"),
        state_binding_sha256=_digest("state-binding"),
        observed_at=NOW - timedelta(minutes=1),
    )
    intent = PrivilegedRestartCheckpointIntent(
        operation_id="operation:restart",
        ticket_id="ticket:restart",
        ticket_sha256=_digest("ticket"),
        service_profile_sha256=_digest("service-profile"),
        workspace_id="workspace:fixture",
        workspace_fence_version=7,
        preflight=preflight,
        candidate_slot=candidate,
        lkg_slot=lkg,
        restart_deadline_seconds=1,
        created_at=NOW - timedelta(seconds=30),
    )
    return PrivilegedRestartCheckpointSnapshot(
        intent=intent,
        checkpoint_sha256=intent.intent_sha256,
        evidence_generation=5,
        state=BrokerRestartCheckpointState.VERIFYING,
        outcome=BrokerRestartOutcome.PENDING,
        selected_slot_id=candidate.slot_id,
        result_evidence_sha256=None,
        service_stopped_at=NOW - timedelta(seconds=20),
        closed_at=None,
        updated_at=NOW - timedelta(seconds=10),
    )


def _runtime(checkpoint: PrivilegedRestartCheckpointSnapshot) -> RuntimeIdentity:
    slot = checkpoint.intent.candidate_slot
    return RuntimeIdentity(
        source_git_oid="1" * 40,
        source_dirty_state=SourceDirtyState.CLEAN,
        source_state_sha256=slot.source_sha256,
        workspace_identity_sha256=_digest("workspace"),
        workspace_mount_identity_sha256=_digest("mount"),
        python_executable="/srv/binnacle-runtime/current/.venv/bin/python",
        python_version="3.13.14",
        environment_root="/srv/binnacle-runtime/current/.venv",
        environment_sha256=slot.environment_sha256,
        runtime_slot_identity_sha256=slot.slot_identity_sha256,
        lock_sha256=_digest("lock"),
        build_sha256=_digest("build"),
        config_sha256=slot.config_sha256,
        policy_sha256=slot.policy_sha256,
        manifest_sha256=slot.manifest_sha256,
        service_profile_sha256=checkpoint.intent.service_profile_sha256,
        device_id="device-fixture",
        device_epoch=1,
        runtime_instance_id="runtime-fixture",
        process_started_at=NOW - timedelta(seconds=5),
        readiness_generation=2,
        schema_heads_sha256=slot.migration_heads_sha256,
        runtime_layout_sha256=slot.layout_sha256,
        deployed_peer_set_sha256=slot.deployed_peer_set_sha256,
    )


def _observation(
    checkpoint: PrivilegedRestartCheckpointSnapshot,
    *,
    active_state: str = "active",
    sub_state: str = "running",
    selected: VerifiedRuntimeSlot | None = None,
) -> RestartRuntimeObservation:
    runtime = _runtime(checkpoint)
    service = ServiceInspectionResult(
        service_profile_sha256=checkpoint.intent.service_profile_sha256,
        service_unit="binnacle-dev.service",
        load_state="loaded",
        active_state=active_state,
        sub_state=sub_state,
        result="success",
        main_pid=123 if active_state == "active" else 0,
        main_process_started_at=(NOW - timedelta(seconds=5) if active_state == "active" else None),
        application_ready=True if active_state == "active" else None,
        runtime_identity_sha256=(
            runtime.runtime_identity_sha256 if active_state == "active" else None
        ),
        observed_at=NOW,
    )
    return RestartRuntimeObservation(
        service=service,
        runtime=runtime if active_state == "active" else None,
        current_slot=(checkpoint.intent.candidate_slot if selected is None else selected),
        observed_at=NOW,
    )


class _Probe:
    def __init__(self, *values: RestartRuntimeObservation | Exception) -> None:
        self.values = list(values)

    async def observe(self) -> RestartRuntimeObservation:
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.anyio
async def test_exact_runtime_verifier_accepts_only_correlated_selected_identity() -> None:
    checkpoint = _checkpoint()
    verifier = ExactRestartRuntimeVerifier(
        probe=_Probe(_observation(checkpoint)),
        monotonic=lambda: 0.0,
    )

    result = await verifier.verify(
        checkpoint,
        expected_slot=checkpoint.intent.candidate_slot,
    )

    assert result.outcome is RestartDriverOutcome.SUCCEEDED
    assert result.effect_started is False
    assert result.boundary_receipt_sha256 is None


@pytest.mark.anyio
@pytest.mark.parametrize("missing_runtime", (False, True))
async def test_exact_runtime_verifier_polls_active_service_until_readiness(
    missing_runtime: bool,
) -> None:
    checkpoint = _checkpoint()
    transient = _observation(checkpoint)
    transient = replace(
        transient,
        service=replace(
            transient.service,
            application_ready=None if missing_runtime else False,
            runtime_identity_sha256=(
                None if missing_runtime else transient.service.runtime_identity_sha256
            ),
        ),
        runtime=None if missing_runtime else transient.runtime,
    )
    sleep = AsyncMock()
    verifier = ExactRestartRuntimeVerifier(
        probe=_Probe(transient, _observation(checkpoint)),
        monotonic=lambda: 0.0,
        sleep=sleep,
    )

    result = await verifier.verify(
        checkpoint,
        expected_slot=checkpoint.intent.candidate_slot,
    )

    assert result.outcome is RestartDriverOutcome.SUCCEEDED
    sleep.assert_awaited_once_with(0.25)


@pytest.mark.anyio
async def test_exact_runtime_verifier_fails_definitive_identity_before_readiness() -> None:
    checkpoint = _checkpoint()
    observation = _observation(checkpoint)
    assert observation.runtime is not None
    runtime = replace(observation.runtime, config_sha256=_digest("wrong-config"))
    observation = replace(
        observation,
        service=replace(
            observation.service,
            application_ready=False,
            runtime_identity_sha256=runtime.runtime_identity_sha256,
        ),
        runtime=runtime,
    )
    sleep = AsyncMock()
    verifier = ExactRestartRuntimeVerifier(
        probe=_Probe(observation),
        monotonic=lambda: 0.0,
        sleep=sleep,
    )

    result = await verifier.verify(
        checkpoint,
        expected_slot=checkpoint.intent.candidate_slot,
    )

    assert result.outcome is RestartDriverOutcome.FAILED
    sleep.assert_not_awaited()


@pytest.mark.anyio
async def test_exact_runtime_verifier_rejects_late_readiness_and_bounds_final_sleep() -> None:
    checkpoint = _checkpoint()
    transient = _observation(checkpoint, active_state="inactive", sub_state="dead")
    monotonic_values = iter((10.0, 10.8, 11.01))
    sleep = AsyncMock()
    verifier = ExactRestartRuntimeVerifier(
        probe=_Probe(transient, _observation(checkpoint)),
        monotonic=lambda: next(monotonic_values),
        sleep=sleep,
    )

    result = await verifier.verify(
        checkpoint,
        expected_slot=checkpoint.intent.candidate_slot,
    )

    assert result.outcome is RestartDriverOutcome.FAILED
    sleep.assert_awaited_once_with(pytest.approx(0.2))


@pytest.mark.anyio
async def test_exact_runtime_verifier_fails_wrong_slot_or_deadline_and_restricts_unknown() -> None:
    checkpoint = _checkpoint()
    wrong = ExactRestartRuntimeVerifier(
        probe=_Probe(_observation(checkpoint, selected=checkpoint.intent.lkg_slot)),
        monotonic=lambda: 0.0,
    )
    monotonic_values = iter((0.0, 2.0))
    deadline = ExactRestartRuntimeVerifier(
        probe=_Probe(_observation(checkpoint, active_state="inactive", sub_state="dead")),
        monotonic=lambda: next(monotonic_values),
    )
    unavailable = ExactRestartRuntimeVerifier(
        probe=_Probe(OSError("readiness unavailable")),
        monotonic=lambda: 0.0,
    )

    assert (
        await wrong.verify(checkpoint, expected_slot=checkpoint.intent.candidate_slot)
    ).outcome is RestartDriverOutcome.FAILED
    assert (
        await deadline.verify(checkpoint, expected_slot=checkpoint.intent.candidate_slot)
    ).outcome is RestartDriverOutcome.FAILED
    uncertain = await unavailable.verify(
        checkpoint,
        expected_slot=checkpoint.intent.candidate_slot,
    )
    assert uncertain.outcome is RestartDriverOutcome.UNCERTAIN
    assert uncertain.effect_started is True


class _Process:
    def __init__(self, return_code: int) -> None:
        self.pid = 42
        self.return_code = return_code
        self.killed = False

    async def wait(self) -> int:
        return self.return_code

    def kill(self) -> None:
        self.killed = True


@pytest.mark.anyio
async def test_systemd_manager_executes_only_fixed_unit_and_sanitizes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    process = _Process(0)

    async def create(*args: object, **kwargs: object) -> _Process:
        calls.append((*args, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    manager = FixedSystemdServiceManager(clock=lambda: NOW)

    result = await manager.start()

    assert calls[0][:4] == (
        "/usr/bin/systemctl",
        "--no-ask-password",
        "start",
        "binnacle-dev.service",
    )
    assert result.outcome is RestartDriverOutcome.SUCCEEDED
    assert result.effect_reference == "systemd:start:42"
    assert result.effect_started is True

    process.return_code = 1
    assert (await manager.stop()).outcome is RestartDriverOutcome.FAILED


@pytest.mark.anyio
async def test_systemd_manager_distinguishes_not_started_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> _Process:
        raise OSError("systemctl unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unavailable)
    manager = FixedSystemdServiceManager(clock=lambda: NOW)
    not_started = await manager.stop()
    assert not_started.outcome is RestartDriverOutcome.FAILED
    assert not_started.effect_started is False

    process = _Process(0)

    async def create(*_args: object, **_kwargs: object) -> _Process:
        return process

    async def timeout(
        awaitable: Coroutine[Any, Any, int],
        *,
        timeout: float,
    ) -> int:
        del timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(asyncio, "wait_for", timeout)
    uncertain = await manager.start()
    assert uncertain.outcome is RestartDriverOutcome.UNCERTAIN
    assert uncertain.effect_started is True
    assert process.killed is True


def _selector_request(
    checkpoint: PrivilegedRestartCheckpointSnapshot,
) -> RuntimeSelectorActivationRequest:
    target = checkpoint.intent.candidate_slot
    intent = runtime_selector_intent_sha256(
        selector_generation=2,
        operation_id=checkpoint.intent.operation_id,
        initial_bootstrap=False,
        expected_current_slot_id=checkpoint.intent.lkg_slot.slot_id,
        target_slot_id=target.slot_id,
        target_slot_identity_sha256=target.slot_identity_sha256,
        requested_at=checkpoint.updated_at,
    )
    return RuntimeSelectorActivationRequest(
        selector_generation=2,
        operation_id=checkpoint.intent.operation_id,
        initial_bootstrap=False,
        expected_current_slot_id=checkpoint.intent.lkg_slot.slot_id,
        target_slot_id=target.slot_id,
        target_slot_identity_sha256=target.slot_identity_sha256,
        retained_intent_sha256=intent,
        requested_at=checkpoint.updated_at,
    )


class _Publisher:
    def __init__(self, result: RuntimeSelectorActivationReceipt | Exception) -> None:
        self.result = result

    def activate_complete_slot(
        self,
        request: RuntimeSelectorActivationRequest,
        *,
        observed_at: datetime,
    ) -> RuntimeSelectorActivationReceipt:
        if isinstance(self.result, Exception):
            raise self.result
        assert request.selector_generation == self.result.selector_generation
        assert observed_at == self.result.observed_at
        return self.result


def _driver(
    publisher: _Publisher,
    checkpoint: PrivilegedRestartCheckpointSnapshot,
) -> FixedControlledRestartDriver:
    success = RestartDriverResult(
        outcome=RestartDriverOutcome.SUCCEEDED,
        effect_started=True,
        effect_reference="systemd:start:1",
        boundary_receipt_sha256=_digest("boundary"),
        result_evidence_sha256=_digest("result"),
        observed_at=NOW,
    )
    service = cast(
        FixedSystemdServiceManager,
        SimpleNamespace(start=lambda: success, stop=lambda: success),
    )
    verifier = cast(
        ExactRestartRuntimeVerifier,
        SimpleNamespace(
            verify=lambda *_args, **_kwargs: success,
        ),
    )
    return FixedControlledRestartDriver(
        service=service,
        publisher=cast(FilesystemRuntimeSlotPublisher, publisher),
        verifier=verifier,
        clock=lambda: NOW,
    )


@pytest.mark.anyio
async def test_fixed_driver_classifies_selector_receipt_conflict_and_uncertainty() -> None:
    checkpoint = _checkpoint()
    request = _selector_request(checkpoint)
    receipt = RuntimeSelectorActivationReceipt(
        selector_generation=request.selector_generation,
        operation_id=request.operation_id,
        previous_slot_id=request.expected_current_slot_id,
        selected_slot_id=request.target_slot_id,
        selected_slot_identity_sha256=request.target_slot_identity_sha256,
        retained_intent_sha256=request.retained_intent_sha256,
        selector_changed=True,
        observed_at=NOW,
    )
    selected = await _driver(_Publisher(receipt), checkpoint).activate_candidate(
        checkpoint,
        request,
    )
    conflict = await _driver(
        _Publisher(RuntimeSelectorConflict("changed")), checkpoint
    ).activate_candidate(checkpoint, request)
    uncertain = await _driver(
        _Publisher(RuntimeSelectorPublicationUncertain("unknown")), checkpoint
    ).activate_candidate(checkpoint, request)

    assert selected.outcome is RestartDriverOutcome.SUCCEEDED
    assert selected.result_evidence_sha256 == receipt.receipt_sha256
    assert conflict.outcome is RestartDriverOutcome.FAILED
    assert conflict.effect_started is False
    assert uncertain.outcome is RestartDriverOutcome.UNCERTAIN
    assert uncertain.effect_started is True

    wrong_target = checkpoint.intent.lkg_slot
    wrong_intent = runtime_selector_intent_sha256(
        selector_generation=3,
        operation_id=checkpoint.intent.operation_id,
        initial_bootstrap=False,
        expected_current_slot_id=checkpoint.intent.candidate_slot.slot_id,
        target_slot_id=wrong_target.slot_id,
        target_slot_identity_sha256=wrong_target.slot_identity_sha256,
        requested_at=checkpoint.updated_at,
    )
    wrong_request = RuntimeSelectorActivationRequest(
        selector_generation=3,
        operation_id=checkpoint.intent.operation_id,
        initial_bootstrap=False,
        expected_current_slot_id=checkpoint.intent.candidate_slot.slot_id,
        target_slot_id=wrong_target.slot_id,
        target_slot_identity_sha256=wrong_target.slot_identity_sha256,
        retained_intent_sha256=wrong_intent,
        requested_at=checkpoint.updated_at,
    )
    with pytest.raises(RestartDriverAdapterError, match="candidate"):
        await _driver(_Publisher(receipt), checkpoint).activate_candidate(
            checkpoint,
            wrong_request,
        )


def test_fixed_adapter_settings_and_observation_reject_widening() -> None:
    with pytest.raises(RestartDriverAdapterError, match="fixed"):
        FixedSystemdSettings(systemctl_path=Path("/bin/other"))
    checkpoint = _checkpoint()
    observation = _observation(checkpoint)
    with pytest.raises(RestartDriverAdapterError, match="future"):
        replace(observation, observed_at=NOW - timedelta(seconds=1))


def test_restart_checkpoint_intent_rejects_stale_or_mismatched_authority() -> None:
    checkpoint = _checkpoint()
    intent = checkpoint.intent
    invalid: tuple[Callable[[], object], ...] = (
        lambda: replace(intent, workspace_fence_version=0),
        lambda: replace(intent, restart_deadline_seconds=0),
        lambda: replace(intent, restart_deadline_seconds=901),
        lambda: replace(intent, created_at=intent.created_at.replace(tzinfo=None)),
        lambda: replace(
            intent,
            preflight=replace(
                intent.preflight,
                observed_at=intent.created_at + timedelta(seconds=1),
            ),
        ),
        lambda: replace(intent, lkg_slot=intent.candidate_slot),
        lambda: replace(
            intent,
            preflight=replace(
                intent.preflight,
                candidate_slot_identity_sha256=_digest("different-candidate"),
            ),
        ),
    )
    for construct in invalid:
        with pytest.raises(PrivilegedRestartError):
            construct()


def test_restart_checkpoint_snapshot_rejects_foreign_or_incomplete_truth() -> None:
    checkpoint = _checkpoint()
    terminal = replace(
        checkpoint,
        state=BrokerRestartCheckpointState.TERMINAL,
        outcome=BrokerRestartOutcome.CANDIDATE_READY,
        result_evidence_sha256=_digest("terminal-result"),
        closed_at=NOW,
    )
    restricted = replace(
        checkpoint,
        state=BrokerRestartCheckpointState.RESTRICTED_RECOVERY,
        outcome=BrokerRestartOutcome.RESTRICTED_RECOVERY,
        result_evidence_sha256=_digest("restricted-result"),
    )
    assert terminal.selected_slot_id == checkpoint.intent.candidate_slot.slot_id
    assert restricted.closed_at is None

    invalid: tuple[Callable[[], object], ...] = (
        lambda: replace(checkpoint, checkpoint_sha256="bad"),
        lambda: replace(checkpoint, evidence_generation=0),
        lambda: replace(
            checkpoint,
            service_stopped_at=checkpoint.updated_at.replace(tzinfo=None),
        ),
        lambda: replace(
            checkpoint,
            updated_at=checkpoint.intent.created_at - timedelta(seconds=1),
        ),
        lambda: replace(checkpoint, result_evidence_sha256="bad"),
        lambda: replace(checkpoint, selected_slot_id="foreign-slot"),
        lambda: replace(
            checkpoint,
            state=BrokerRestartCheckpointState.TERMINAL,
            outcome=BrokerRestartOutcome.CANDIDATE_READY,
        ),
        lambda: replace(
            checkpoint,
            state=BrokerRestartCheckpointState.RESTRICTED_RECOVERY,
            outcome=BrokerRestartOutcome.RESTRICTED_RECOVERY,
        ),
        lambda: replace(checkpoint, outcome=BrokerRestartOutcome.FAILED),
        lambda: replace(terminal, outcome=BrokerRestartOutcome.RESTRICTED_RECOVERY),
        lambda: replace(restricted, outcome=BrokerRestartOutcome.CANDIDATE_READY),
        lambda: replace(
            terminal,
            selected_slot_id=terminal.intent.lkg_slot.slot_id,
        ),
        lambda: replace(
            terminal,
            outcome=BrokerRestartOutcome.ROLLBACK_READY,
            selected_slot_id=terminal.intent.candidate_slot.slot_id,
        ),
    )
    for construct in invalid:
        with pytest.raises(PrivilegedRestartError):
            construct()

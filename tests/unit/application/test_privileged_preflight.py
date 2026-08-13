"""Runtime-identity binding and advisory restart-preflight tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from binnacle.application.privileged_preflight import (
    PrivilegedPreflightError,
    RestartOutstandingFacts,
    RestartPreflightEvaluator,
    RuntimeIdentityBuilder,
    RuntimeIdentityEvidence,
)
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightReason,
    RuntimeIdentity,
    RuntimeSlotRole,
    RuntimeSlotState,
    ServiceInspectionResult,
    SourceDirtyState,
    VerifiedRuntimeSlot,
)

NOW = datetime(2026, 8, 13, 5, 6, 7, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _slot(
    *,
    slot_id: str = "slot-0001",
    role: RuntimeSlotRole = RuntimeSlotRole.CANDIDATE,
    state: RuntimeSlotState = RuntimeSlotState.ACTIVE,
) -> VerifiedRuntimeSlot:
    return VerifiedRuntimeSlot(
        slot_id=slot_id,
        slot_generation=1,
        slot_path=f"/srv/binnacle-runtime/slots/{slot_id}",
        role=role,
        state=state,
        source_sha256=SHA_A,
        environment_sha256=SHA_B,
        config_sha256=SHA_C,
        policy_sha256=SHA_A,
        manifest_sha256=SHA_B,
        service_definition_sha256=SHA_C,
        deployed_peer_set_sha256=SHA_A,
        migration_heads_sha256=SHA_B,
        layout_sha256=SHA_C,
        candidate_verification_sha256=SHA_B,
        complete_manifest_sha256=SHA_A,
        byte_count=10_000,
        inode_count=100,
        completed_at=NOW - timedelta(hours=1),
    )


def _runtime_evidence() -> RuntimeIdentityEvidence:
    return RuntimeIdentityEvidence(
        source_git_oid="1" * 40,
        source_dirty_state=SourceDirtyState.CLEAN,
        source_state_sha256=SHA_A,
        workspace_identity_sha256=SHA_B,
        workspace_mount_identity_sha256=SHA_C,
        python_executable="/srv/binnacle-runtime/current/venv/bin/python",
        python_version="3.13.14",
        environment_root="/srv/binnacle-runtime/current/venv",
        environment_sha256=SHA_B,
        lock_sha256=SHA_A,
        build_sha256=SHA_C,
        config_sha256=SHA_C,
        policy_sha256=SHA_A,
        manifest_sha256=SHA_B,
        service_profile_sha256=SHA_C,
        device_id="device_fixture",
        device_epoch=2,
        runtime_instance_id="runtime_fixture",
        process_started_at=NOW - timedelta(minutes=2),
        readiness_generation=3,
        schema_heads_sha256=SHA_B,
        runtime_layout_sha256=SHA_C,
        deployed_peer_set_sha256=SHA_A,
        service_main_pid=123,
        readiness_main_pid=123,
        observed_at=NOW - timedelta(seconds=2),
    )


def _runtime() -> RuntimeIdentity:
    return RuntimeIdentityBuilder().build(_runtime_evidence(), slot=_slot())


def _service(*, ready: bool | None = True) -> ServiceInspectionResult:
    runtime = _runtime()
    return ServiceInspectionResult(
        service_profile_sha256=SHA_C,
        service_unit="binnacle-dev.service",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        result="success",
        main_pid=123,
        main_process_started_at=NOW - timedelta(minutes=2),
        application_ready=ready,
        runtime_identity_sha256=None if ready is None else runtime.runtime_identity_sha256,
        observed_at=NOW - timedelta(seconds=1),
    )


def _facts() -> RestartOutstandingFacts:
    return RestartOutstandingFacts(
        operation_state_sha256=SHA_A,
        command_state_sha256=SHA_B,
        workspace_fence_sha256=SHA_C,
        git_state_sha256=SHA_A,
        credential_state_sha256=SHA_B,
        privileged_state_sha256=SHA_C,
        audit_state_sha256=SHA_A,
        blocking_operation_count=0,
        uncertain_operation_count=0,
        open_command_count=0,
        non_survivable_command_count=0,
        source_changer_count=0,
        open_git_effect_count=0,
        open_credential_effect_count=0,
        open_privileged_effect_count=0,
        workspace_fence_held=False,
        package_mutation_open=False,
        prior_restart_unresolved=False,
        source_mutation_uncertain=False,
        audit_healthy=True,
        schema_heads_match=True,
        deployed_peer_set_matches=True,
        observed_at=NOW - timedelta(seconds=1),
    )


def test_runtime_identity_binds_complete_active_slot() -> None:
    runtime = _runtime()

    assert runtime.source_state_sha256 == _slot().source_sha256
    assert runtime.environment_sha256 == _slot().environment_sha256
    assert runtime.runtime_slot_identity_sha256 == _slot().slot_identity_sha256
    assert len(runtime.runtime_identity_sha256) == 64


@pytest.mark.parametrize(
    "factory,match",
    (
        (
            lambda: RuntimeIdentityBuilder().build(
                replace(_runtime_evidence(), readiness_main_pid=124), slot=_slot()
            ),
            "PIDs disagree",
        ),
        (
            lambda: RuntimeIdentityBuilder().build(
                replace(_runtime_evidence(), source_dirty_state=SourceDirtyState.DIRTY),
                slot=_slot(),
            ),
            "source is dirty",
        ),
        (
            lambda: RuntimeIdentityBuilder().build(
                replace(_runtime_evidence(), config_sha256=SHA_A), slot=_slot()
            ),
            "differs",
        ),
        (
            lambda: RuntimeIdentityBuilder().build(
                _runtime_evidence(),
                slot=_slot(role=RuntimeSlotRole.PRIOR, state=RuntimeSlotState.PRIOR),
            ),
            "not active or LKG",
        ),
        (
            lambda: RuntimeIdentityBuilder().build(
                replace(_runtime_evidence(), observed_at=NOW - timedelta(minutes=3)),
                slot=_slot(),
            ),
            "starts after",
        ),
    ),
)
def test_runtime_identity_rejects_uncorrelated_or_incomplete_evidence(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedPreflightError, match=match):
        factory()


def test_simple_restart_preflight_is_available_without_candidate_or_lkg() -> None:
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.SIMPLE_SERVICE,
        facts=_facts(),
        service=_service(),
        runtime=_runtime(),
        observed_at=NOW,
    )

    assert result.available is True
    assert result.reason_codes == ()
    assert set(result.predicted_impacts) == {
        RestartImpact.APPLICATION_PROCESS_REPLACED,
        RestartImpact.CONNECTION_INTERRUPTED,
    }
    assert result.candidate_slot_identity_sha256 is None


def test_restart_survivable_non_source_command_does_not_block_preflight() -> None:
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.SIMPLE_SERVICE,
        facts=replace(_facts(), open_command_count=1),
        service=_service(),
        runtime=_runtime(),
        observed_at=NOW,
    )

    assert result.available is True


def test_controlled_restart_preflight_binds_candidate_lkg_and_test_evidence() -> None:
    lkg = _slot(slot_id="slot-lkg", role=RuntimeSlotRole.LKG, state=RuntimeSlotState.LKG)
    candidate = _slot(state=RuntimeSlotState.COMPLETE)
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.CONTROLLED_SELF,
        facts=_facts(),
        service=_service(),
        runtime=_runtime(),
        lkg_slot=lkg,
        candidate_slot=candidate,
        candidate_verification_sha256=SHA_C,
        candidate_verification_fresh=True,
        candidate_tested_state_matches=True,
        observed_at=NOW,
    )

    assert result.available is True
    assert result.lkg_slot_identity_sha256 == lkg.slot_identity_sha256
    assert result.candidate_slot_identity_sha256 == candidate.slot_identity_sha256
    assert set(result.predicted_impacts) == set(RestartImpact)
    assert len(result.observation_sha256) == 64


def test_controlled_preflight_rejects_a_runtime_not_bound_to_a_complete_slot() -> None:
    runtime = RuntimeIdentityBuilder().build(_runtime_evidence(), slot=None)
    service = replace(_service(), runtime_identity_sha256=runtime.runtime_identity_sha256)
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.CONTROLLED_SELF,
        facts=_facts(),
        service=service,
        runtime=runtime,
        lkg_slot=_slot(
            slot_id="slot-lkg",
            role=RuntimeSlotRole.LKG,
            state=RuntimeSlotState.LKG,
        ),
        candidate_slot=_slot(state=RuntimeSlotState.COMPLETE),
        candidate_verification_sha256=SHA_C,
        candidate_verification_fresh=True,
        candidate_tested_state_matches=True,
        observed_at=NOW,
    )

    assert result.reason_codes == (RestartPreflightReason.CURRENT_RUNTIME_UNAVAILABLE,)


def test_preflight_reports_every_common_blocker_without_authorizing() -> None:
    blocked = replace(
        _facts(),
        blocking_operation_count=1,
        uncertain_operation_count=1,
        open_command_count=2,
        non_survivable_command_count=1,
        source_changer_count=1,
        open_git_effect_count=1,
        open_credential_effect_count=1,
        open_privileged_effect_count=1,
        workspace_fence_held=True,
        package_mutation_open=True,
        prior_restart_unresolved=True,
        source_mutation_uncertain=True,
        audit_healthy=False,
        schema_heads_match=False,
        deployed_peer_set_matches=False,
    )
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.SIMPLE_SERVICE,
        facts=blocked,
        service=_service(ready=None),
        runtime=None,
        observed_at=NOW,
    )

    assert result.available is False
    assert set(result.reason_codes) == {
        RestartPreflightReason.BLOCKING_OPERATION,
        RestartPreflightReason.AUDIT_UNAVAILABLE,
        RestartPreflightReason.COMMAND_EXECUTION_UNSAFE,
        RestartPreflightReason.CREDENTIAL_EFFECT_OPEN,
        RestartPreflightReason.CURRENT_RUNTIME_UNAVAILABLE,
        RestartPreflightReason.GIT_EFFECT_OPEN,
        RestartPreflightReason.PACKAGE_MUTATION_OPEN,
        RestartPreflightReason.PEER_SET_MISMATCH,
        RestartPreflightReason.PRIOR_RESTART_UNRESOLVED,
        RestartPreflightReason.PRIVILEGED_EFFECT_OPEN,
        RestartPreflightReason.SCHEMA_HEAD_MISMATCH,
        RestartPreflightReason.SERVICE_NOT_READY,
        RestartPreflightReason.SOURCE_CHANGER_OPEN,
        RestartPreflightReason.SOURCE_MUTATION_UNCERTAIN,
        RestartPreflightReason.UNCERTAIN_OPERATION,
        RestartPreflightReason.WORKSPACE_FENCE_HELD,
    }


def test_controlled_preflight_reports_missing_stale_or_mismatched_evidence() -> None:
    result = RestartPreflightEvaluator().inspect(
        kind=RestartPreflightKind.CONTROLLED_SELF,
        facts=_facts(),
        service=_service(),
        runtime=_runtime(),
        candidate_verification_sha256=SHA_C,
        candidate_verification_fresh=False,
        candidate_tested_state_matches=False,
        observed_at=NOW,
    )

    assert set(result.reason_codes) == {
        RestartPreflightReason.CANDIDATE_VERIFICATION_MISSING,
        RestartPreflightReason.CANDIDATE_VERIFICATION_STALE,
        RestartPreflightReason.CANDIDATE_TESTED_STATE_MISMATCH,
        RestartPreflightReason.LKG_UNAVAILABLE,
    }


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_facts(), operation_state_sha256="bad"), "digest"),
        (lambda: replace(_facts(), blocking_operation_count=-1), "count"),
        (
            lambda: replace(_facts(), open_command_count=0, source_changer_count=1),
            "contradictory",
        ),
    ),
)
def test_preflight_facts_reject_unbounded_or_contradictory_state(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedPreflightError, match=match):
        factory()


def test_preflight_rejects_future_observations_and_bad_candidate_digest() -> None:
    evaluator = RestartPreflightEvaluator()
    with pytest.raises(PrivilegedPreflightError, match="future"):
        evaluator.inspect(
            kind=RestartPreflightKind.SIMPLE_SERVICE,
            facts=replace(_facts(), observed_at=NOW + timedelta(seconds=1)),
            service=_service(),
            runtime=_runtime(),
            observed_at=NOW,
        )
    with pytest.raises(PrivilegedPreflightError, match="digest"):
        evaluator.inspect(
            kind=RestartPreflightKind.CONTROLLED_SELF,
            facts=_facts(),
            service=_service(),
            runtime=_runtime(),
            candidate_verification_sha256="bad",
            observed_at=NOW,
        )

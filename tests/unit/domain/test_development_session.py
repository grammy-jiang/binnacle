from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from binnacle.domain.development_session import (
    ActivationClosure,
    DevelopmentSessionError,
    DevelopmentSessionSnapshot,
    DevelopmentSessionState,
    SessionAuthorityFacts,
    SessionIneffectiveReason,
    activate_session,
    complete_activation,
    evaluate_session_authority,
    new_pending_session,
    objective_sha256,
    reduce_session,
)

NOW = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _pending() -> DevelopmentSessionSnapshot:
    return new_pending_session(
        session_id="dev_fixture",
        begin_operation_id="op_begin",
        controller_id="controller_fixture",
        controller_epoch=2,
        device_id="device_fixture",
        device_epoch=3,
        workspace_id="workspace_fixture",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        objective_sha256=objective_sha256("Improve Binnacle"),
        expires_at=NOW + timedelta(hours=1),
        trusted_time_generation=1,
        activation_boot_id_digest=DIGEST,
        monotonic_deadline_ns=20_000,
        now=NOW,
    )


def _active() -> DevelopmentSessionSnapshot:
    pending = _pending()
    active = activate_session(
        pending,
        expected_state_version=1,
        effect_reference="activation_ref",
        effect_reference_sha256=DIGEST,
        now=NOW + timedelta(seconds=1),
    )
    return complete_activation(active, expected_state_version=2)


def _facts() -> SessionAuthorityFacts:
    return SessionAuthorityFacts(
        controller_id="controller_fixture",
        controller_epoch=2,
        device_id="device_fixture",
        device_epoch=3,
        workspace_id="workspace_fixture",
        workspace_profile_sha256=DIGEST,
        workspace_root_identity_sha256=DIGEST,
        workspace_mount_identity_sha256=DIGEST,
        policy_version="policy-v1",
        contract_profile_sha256=DIGEST,
        wall_time=NOW + timedelta(minutes=1),
        wall_time_trusted=True,
        trusted_time_generation=1,
        boot_id_digest=DIGEST,
        monotonic_ns=10_000,
        kernel_consequential_ready=True,
    )


def test_activation_requires_exact_pending_state_and_closure() -> None:
    pending = _pending()
    active = activate_session(
        pending,
        expected_state_version=1,
        effect_reference="activation_ref",
        effect_reference_sha256=DIGEST,
        now=NOW + timedelta(seconds=1),
    )
    assert active.state is DevelopmentSessionState.ACTIVE
    assert active.activation_closure is ActivationClosure.PENDING
    assert not evaluate_session_authority(active, _facts()).effective

    closed = complete_activation(active, expected_state_version=2)
    assert closed.activation_closure is ActivationClosure.COMPLETE
    assert evaluate_session_authority(closed, _facts()).effective

    with pytest.raises(DevelopmentSessionError, match="already closed"):
        complete_activation(closed, expected_state_version=3)


@pytest.mark.parametrize(
    "target",
    [
        DevelopmentSessionState.ENDED,
        DevelopmentSessionState.EXPIRED,
        DevelopmentSessionState.REVOKED,
    ],
)
def test_terminal_never_started_activation_has_durable_no_effect_closure(
    target: DevelopmentSessionState,
) -> None:
    terminal = reduce_session(
        _pending(),
        expected_state_version=1,
        target=target,
        reason=f"{target.value}_before_start",
        now=NOW + timedelta(seconds=1),
    )

    closed = complete_activation(terminal, expected_state_version=2)

    assert closed.state is target
    assert closed.state_version == 3
    assert closed.activation_closure is ActivationClosure.COMPLETE
    assert closed.activation_closure_version == 2
    assert closed.started_at is None
    assert closed.activation_effect_reference is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"controller_epoch": 9}, SessionIneffectiveReason.CONTROLLER_MISMATCH),
        ({"device_epoch": 9}, SessionIneffectiveReason.DEVICE_MISMATCH),
        ({"workspace_profile_sha256": "b" * 64}, SessionIneffectiveReason.WORKSPACE_MISMATCH),
        ({"workspace_root_identity_sha256": "b" * 64}, SessionIneffectiveReason.ROOT_MISMATCH),
        ({"workspace_mount_identity_sha256": "b" * 64}, SessionIneffectiveReason.MOUNT_MISMATCH),
        ({"policy_version": "policy-v2"}, SessionIneffectiveReason.POLICY_MISMATCH),
        ({"contract_profile_sha256": "b" * 64}, SessionIneffectiveReason.CONTRACT_MISMATCH),
        ({"kernel_consequential_ready": False}, SessionIneffectiveReason.KERNEL_UNAVAILABLE),
        ({"monotonic_ns": 20_000}, SessionIneffectiveReason.EXPIRED),
    ],
)
def test_effectiveness_fails_closed_on_exact_fact_drift(
    change: dict[str, object], reason: SessionIneffectiveReason
) -> None:
    result = evaluate_session_authority(
        _active(),
        replace(_facts(), **change),  # type: ignore[arg-type]
    )
    assert not result.effective
    assert result.reason is reason


def test_reboot_without_trusted_wall_time_never_extends_session() -> None:
    result = evaluate_session_authority(
        _active(),
        replace(_facts(), boot_id_digest="b" * 64, wall_time_trusted=False),
    )
    assert result.reason is SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE


def test_trusted_time_generation_must_be_guard_accepted_across_boots() -> None:
    active = _active()
    same_boot_drift = evaluate_session_authority(
        active,
        replace(_facts(), trusted_time_generation=2),
    )
    assert same_boot_drift.reason is SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE

    unchanged_reboot = evaluate_session_authority(
        active,
        replace(_facts(), boot_id_digest="b" * 64),
    )
    assert unchanged_reboot.reason is SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE

    accepted_reboot = evaluate_session_authority(
        active,
        replace(
            _facts(),
            boot_id_digest="b" * 64,
            trusted_time_generation=2,
            monotonic_ns=0,
        ),
    )
    assert accepted_reboot.effective


def test_authority_reduction_is_terminal_and_versioned() -> None:
    active = _active()
    ended = reduce_session(
        active,
        expected_state_version=3,
        target=DevelopmentSessionState.ENDED,
        reason="owner_end",
        now=NOW + timedelta(minutes=2),
    )
    assert ended.state is DevelopmentSessionState.ENDED
    assert ended.state_version == 4
    assert evaluate_session_authority(ended, _facts()).reason is SessionIneffectiveReason.NOT_ACTIVE
    with pytest.raises(DevelopmentSessionError, match="cannot be reduced again"):
        reduce_session(
            ended,
            expected_state_version=4,
            target=DevelopmentSessionState.REVOKED,
            reason="again",
            now=NOW + timedelta(minutes=3),
        )


def test_deadline_and_snapshot_shapes_are_bounded() -> None:
    with pytest.raises(DevelopmentSessionError, match="reviewed maximum"):
        new_pending_session(
            begin_operation_id="op_begin",
            controller_id="controller",
            controller_epoch=1,
            device_id="device",
            device_epoch=1,
            workspace_id="workspace",
            workspace_profile_sha256=DIGEST,
            workspace_root_identity_sha256=DIGEST,
            workspace_mount_identity_sha256=DIGEST,
            policy_version="policy-v1",
            contract_profile_sha256=DIGEST,
            objective_sha256=DIGEST,
            expires_at=NOW + timedelta(hours=5),
            trusted_time_generation=1,
            activation_boot_id_digest=DIGEST,
            monotonic_deadline_ns=1,
            now=NOW,
        )
    with pytest.raises(DevelopmentSessionError, match="outside the bounded contract"):
        objective_sha256("")

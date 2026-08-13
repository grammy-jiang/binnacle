"""Closed Phase 9 read-only and preparation contract tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from binnacle.domain.privileged_observation import (
    PackageAction,
    PackageInspectionReason,
    PackageInspectionResult,
    PackageTarget,
    PackageTransactionMember,
    PackageTransactionPlan,
    PrivilegedObservationError,
    RuntimeIdentity,
    RuntimeSlotRole,
    RuntimeSlotState,
    ServiceInspectionResult,
    SourceDirtyState,
    VerifiedRuntimeSlot,
)

NOW = datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _target() -> PackageTarget:
    return PackageTarget(name="ripgrep", architecture="arm64", requested_version="14.1.1-1")


def _member() -> PackageTransactionMember:
    return PackageTransactionMember(
        name="ripgrep",
        architecture="arm64",
        action=PackageAction.INSTALL,
        requested=True,
        old_version=None,
        target_version="14.1.1-1",
        origin_sha256=SHA_A,
        artifact_sha256=SHA_B,
        download_bytes=1_000,
        installed_bytes=2_000,
        maintainer_scripts=True,
    )


def _plan() -> PackageTransactionPlan:
    return PackageTransactionPlan(
        plan_version="apt-plan-v1",
        package_profile_id="development-packages",
        package_profile_sha256=SHA_A,
        repository_metadata_sha256=SHA_B,
        repository_metadata_observed_at=NOW - timedelta(minutes=1),
        requested_targets=(_target(),),
        members=(_member(),),
        artifact_set_sha256=SHA_C,
        dependency_closure_sha256=SHA_A,
        maintainer_script_set_sha256=SHA_B,
        installed_prestate_sha256=SHA_C,
        download_bytes=1_000,
        installed_bytes=2_000,
        prepared_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def _runtime() -> RuntimeIdentity:
    return RuntimeIdentity(
        source_git_oid="1" * 40,
        source_dirty_state=SourceDirtyState.CLEAN,
        source_state_sha256=SHA_A,
        workspace_identity_sha256=SHA_B,
        workspace_mount_identity_sha256=SHA_C,
        python_executable="/srv/binnacle-runtime/current/venv/bin/python",
        python_version="3.13.14",
        environment_root="/srv/binnacle-runtime/current/venv",
        environment_sha256=SHA_A,
        runtime_slot_identity_sha256=SHA_B,
        lock_sha256=SHA_B,
        build_sha256=SHA_C,
        config_sha256=SHA_A,
        policy_sha256=SHA_B,
        manifest_sha256=SHA_C,
        service_profile_sha256=SHA_A,
        device_id="device_fixture",
        device_epoch=2,
        runtime_instance_id="runtime_fixture",
        process_started_at=NOW,
        readiness_generation=3,
        schema_heads_sha256=SHA_B,
        runtime_layout_sha256=SHA_C,
        deployed_peer_set_sha256=SHA_A,
    )


def _slot() -> VerifiedRuntimeSlot:
    return VerifiedRuntimeSlot(
        slot_id="slot-0001",
        slot_generation=1,
        slot_path="/srv/binnacle-runtime/slots/slot-0001",
        role=RuntimeSlotRole.LKG,
        state=RuntimeSlotState.LKG,
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
        completed_at=NOW,
    )


def test_package_inspection_and_plan_are_canonical_and_digest_stable() -> None:
    inspection = PackageInspectionResult(
        target=_target(),
        package_profile_sha256=SHA_A,
        installed_version=None,
        candidate_version="14.1.1-1",
        repository_metadata_sha256=SHA_B,
        repository_metadata_observed_at=NOW - timedelta(seconds=30),
        repository_metadata_age_seconds=30,
        package_database_locked=False,
        preparation_available=True,
        reason_codes=(),
        observed_at=NOW,
    )
    plan = _plan()

    assert inspection.observation_sha256 == inspection.observation_sha256
    assert plan.transaction_plan_sha256 == plan.transaction_plan_sha256
    assert len(plan.transaction_plan_sha256) == 64


def test_package_inspection_requires_truthful_blocking_reasons() -> None:
    unavailable = PackageInspectionResult(
        target=_target(),
        package_profile_sha256=SHA_A,
        installed_version=None,
        candidate_version=None,
        repository_metadata_sha256=SHA_B,
        repository_metadata_observed_at=NOW,
        repository_metadata_age_seconds=0,
        package_database_locked=False,
        preparation_available=False,
        reason_codes=(PackageInspectionReason.PACKAGE_NOT_AVAILABLE,),
        observed_at=NOW,
    )
    assert unavailable.preparation_available is False

    with pytest.raises(PrivilegedObservationError, match="candidate and reason"):
        replace(unavailable, reason_codes=())
    with pytest.raises(PrivilegedObservationError, match="candidate and reason"):
        replace(unavailable, candidate_version="14.1.1-1")
    with pytest.raises(PrivilegedObservationError, match="availability"):
        replace(unavailable, preparation_available=True)
    with pytest.raises(PrivilegedObservationError, match="metadata age"):
        replace(unavailable, repository_metadata_age_seconds=1)


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_plan(), download_bytes=999), "size totals"),
        (
            lambda: replace(_plan(), requested_targets=(PackageTarget("git", "arm64"),)),
            "requested-member set",
        ),
        (lambda: replace(_plan(), expires_at=NOW), "expiry"),
        (lambda: replace(_plan(), members=(_member(), _member())), "duplicate"),
        (
            lambda: replace(
                _plan(),
                requested_targets=(
                    PackageTarget("ripgrep", "arm64", "14.1.1-1"),
                    PackageTarget("ripgrep", "arm64", "14.1.1-2"),
                ),
            ),
            "identity is duplicated",
        ),
        (
            lambda: replace(
                _plan(),
                requested_targets=(PackageTarget("ripgrep", "arm64", "14.1.1-2"),),
            ),
            "pinned version",
        ),
    ),
)
def test_package_plan_rejects_ambiguous_or_inconsistent_closure(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_member(), old_version="1.0"), "install unexpectedly"),
        (lambda: replace(_member(), action=PackageAction.UPGRADE), "lacks its old"),
        (
            lambda: replace(
                _member(),
                action=PackageAction.UPGRADE,
                old_version="14.1.1-1",
            ),
            "does not change",
        ),
        (lambda: replace(_member(), artifact_sha256="bad"), "SHA-256"),
    ),
)
def test_package_member_rejects_unsupported_effect_shapes(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


def test_service_runtime_and_slot_observations_bind_exact_identity() -> None:
    runtime = _runtime()
    service = ServiceInspectionResult(
        service_profile_sha256=SHA_A,
        service_unit="binnacle-dev.service",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        result="success",
        main_pid=123,
        main_process_started_at=NOW,
        application_ready=True,
        runtime_identity_sha256=runtime.runtime_identity_sha256,
        observed_at=NOW,
    )
    slot = _slot()

    assert len(runtime.runtime_identity_sha256) == 64
    assert len(service.observation_sha256) == 64
    assert len(slot.slot_identity_sha256) == 64


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_runtime(), python_executable="python"), "absolute POSIX"),
        (lambda: replace(_runtime(), device_epoch=0), "generation"),
        (
            lambda: replace(
                ServiceInspectionResult(
                    service_profile_sha256=SHA_A,
                    service_unit="binnacle-dev.service",
                    load_state="loaded",
                    active_state="inactive",
                    sub_state="dead",
                    result=None,
                    main_pid=0,
                    main_process_started_at=None,
                    application_ready=None,
                    runtime_identity_sha256=None,
                    observed_at=NOW,
                ),
                main_pid=1,
            ),
            "PID and start time",
        ),
        (lambda: replace(_slot(), slot_path="/tmp/slot-0001"), "fixed root"),
        (
            lambda: replace(_slot(), role=RuntimeSlotRole.CANDIDATE),
            "state and role",
        ),
    ),
)
def test_observation_contracts_reject_identity_or_state_contradictions(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


def test_paths_remain_plain_values_not_filesystem_authority() -> None:
    runtime = _runtime()
    assert Path(runtime.environment_root).is_absolute()


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: PackageTarget("Upper", "arm64"), "name"),
        (lambda: PackageTarget("git", "ARM64"), "architecture"),
        (lambda: PackageTarget("git", "arm64", "bad version"), "version"),
        (lambda: replace(_member(), download_bytes=20_000_000_001), "download size"),
        (lambda: replace(_member(), installed_bytes=100_000_000_001), "installed size"),
        (
            lambda: replace(
                _member(),
                action=PackageAction.CONFIGURE,
                old_version=None,
            ),
            "lacks its old",
        ),
    ),
)
def test_package_values_reject_unbounded_or_malformed_inputs(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


def test_package_inspection_rejects_noncanonical_reasons_and_time() -> None:
    base = PackageInspectionResult(
        target=_target(),
        package_profile_sha256=SHA_A,
        installed_version=None,
        candidate_version=None,
        repository_metadata_sha256=SHA_B,
        repository_metadata_observed_at=NOW,
        repository_metadata_age_seconds=0,
        package_database_locked=False,
        preparation_available=False,
        reason_codes=(PackageInspectionReason.PACKAGE_NOT_AVAILABLE,),
        observed_at=NOW,
    )

    with pytest.raises(PrivilegedObservationError, match="not canonical"):
        replace(
            base,
            reason_codes=(
                PackageInspectionReason.PROFILE_INACTIVE,
                PackageInspectionReason.PACKAGE_NOT_AVAILABLE,
            ),
        )
    with pytest.raises(PrivilegedObservationError, match="lock state"):
        replace(
            base,
            reason_codes=(
                PackageInspectionReason.PACKAGE_DATABASE_BUSY,
                PackageInspectionReason.PACKAGE_NOT_AVAILABLE,
            ),
        )
    with pytest.raises(PrivilegedObservationError, match="timezone-aware"):
        replace(base, observed_at=NOW.replace(tzinfo=None))


def test_package_plan_rejects_noncanonical_counts_order_and_times() -> None:
    git_target = PackageTarget("git", "arm64")
    git_member = replace(
        _member(),
        name="git",
        target_version="2.46.0-1",
        artifact_sha256=SHA_C,
    )

    cases: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: replace(_plan(), expires_at=NOW + timedelta(hours=2)), "lifetime"),
        (
            lambda: replace(_plan(), repository_metadata_observed_at=NOW + timedelta(seconds=1)),
            "metadata time",
        ),
        (lambda: replace(_plan(), requested_targets=()), "target count"),
        (
            lambda: replace(_plan(), requested_targets=(_target(), git_target)),
            "targets are not canonical",
        ),
        (
            lambda: replace(
                _plan(),
                requested_targets=(git_target, _target()),
                members=(_member(), git_member),
                download_bytes=2_000,
                installed_bytes=4_000,
            ),
            "members are not canonical",
        ),
        (lambda: replace(_plan(), download_bytes=20_000_000_001), "totals are outside"),
    )
    for factory, match in cases:
        with pytest.raises(PrivilegedObservationError, match=match):
            factory()


def _inactive_service() -> ServiceInspectionResult:
    return ServiceInspectionResult(
        service_profile_sha256=SHA_A,
        service_unit="binnacle-dev.service",
        load_state="loaded",
        active_state="inactive",
        sub_state="dead",
        result=None,
        main_pid=0,
        main_process_started_at=None,
        application_ready=None,
        runtime_identity_sha256=None,
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_inactive_service(), service_unit="other.service"), "unsupported"),
        (lambda: replace(_inactive_service(), main_pid=-1), "PID"),
        (
            lambda: replace(_inactive_service(), runtime_identity_sha256=SHA_A),
            "unqueried readiness",
        ),
        (
            lambda: replace(_inactive_service(), application_ready=False),
            "lacks runtime identity",
        ),
        (
            lambda: replace(_inactive_service(), observed_at=NOW.replace(tzinfo=None)),
            "timezone-aware",
        ),
    ),
)
def test_service_observation_rejects_ambiguous_identity(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_runtime(), source_git_oid="0" * 40), "object ID"),
        (lambda: replace(_runtime(), source_git_oid="bad"), "object ID"),
        (lambda: replace(_runtime(), environment_root="/srv/../tmp"), "absolute POSIX"),
        (lambda: replace(_runtime(), python_version="bad\nversion"), "invalid"),
        (lambda: replace(_runtime(), python_version="\ud800"), "invalid"),
        (
            lambda: replace(_runtime(), process_started_at=NOW.replace(tzinfo=None)),
            "timezone-aware",
        ),
    ),
)
def test_runtime_identity_rejects_ambiguous_build_facts(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_slot(), slot_generation=0), "generation"),
        (
            lambda: replace(
                _slot(),
                role=RuntimeSlotRole.LKG,
                state=RuntimeSlotState.PRIOR,
            ),
            "prior slot",
        ),
        (lambda: replace(_slot(), byte_count=0), "bytes"),
        (lambda: replace(_slot(), inode_count=0), "inodes"),
        (lambda: replace(_slot(), complete_manifest_sha256="bad"), "SHA-256"),
    ),
)
def test_verified_slot_rejects_incomplete_or_contradictory_evidence(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PrivilegedObservationError, match=match):
        factory()

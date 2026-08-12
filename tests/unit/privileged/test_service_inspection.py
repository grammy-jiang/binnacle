"""Fixed-unit read-only service and application-readiness inspection tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from binnacle.domain.privileged import BinnacleServiceProfile
from binnacle.privileged_broker.service_inspection import (
    ApplicationReadinessSnapshot,
    FixedServiceInspectionNormalizer,
    ServiceInspectionError,
    ServiceManagerSnapshot,
)

NOW = datetime(2026, 8, 13, 4, 5, 6, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _profile() -> BinnacleServiceProfile:
    return BinnacleServiceProfile(
        profile_id="binnacle-development-service",
        version="v1",
        service_unit="binnacle-dev.service",
        workspace_root="/srv/binnacle-dev/repo",
        workspace_identity_sha256=SHA_A,
        workspace_mount_identity_sha256=SHA_B,
        runtime_root="/srv/binnacle-runtime",
        runtime_mount_identity_sha256=SHA_C,
        current_selector="/srv/binnacle-runtime/current",
        slot_layout_version="v1",
        maximum_slot_bytes=2_000_000_000,
        maximum_slot_inodes=100_000,
        maximum_retained_slots=3,
        service_uid=1001,
        service_gid=1001,
        config_sha256=SHA_A,
        policy_sha256=SHA_B,
        manifest_sha256=SHA_C,
        executable_path="/srv/binnacle-runtime/current/.venv/bin/binnacle",
        stable_unit_sha256=SHA_A,
        application_migration_head="0006_privileged_operations",
        executor_migration_head="0002_git_members",
        git_credential_migration_head="0001_credential_evidence",
        privileged_migration_head="0001_privileged_evidence",
        deployed_peer_set_sha256=SHA_B,
        readiness_contract_version="v1",
        restart_deadline_seconds=120,
        checkpoint_root="/var/lib/binnacle-privileged/checkpoints",
        local_recovery_marker="/var/lib/binnacle-privileged/checkpoints/recovery.json",
        active=True,
    )


def _manager() -> ServiceManagerSnapshot:
    return ServiceManagerSnapshot(
        service_unit="binnacle-dev.service",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        result="success",
        main_pid=123,
        main_process_started_at=NOW - timedelta(minutes=1),
        unit_definition_sha256=SHA_A,
        observed_at=NOW,
    )


def _readiness() -> ApplicationReadinessSnapshot:
    return ApplicationReadinessSnapshot(
        service_unit="binnacle-dev.service",
        main_pid=123,
        runtime_instance_id="runtime_fixture",
        runtime_identity_sha256=SHA_C,
        ready=True,
        observed_at=NOW - timedelta(seconds=1),
    )


def test_service_inspection_correlates_exact_readiness_and_runtime_identity() -> None:
    result = FixedServiceInspectionNormalizer(_profile()).normalize(_manager(), _readiness())

    assert result.service_profile_sha256 == _profile().profile_sha256
    assert result.application_ready is True
    assert result.runtime_identity_sha256 == SHA_C
    assert result.active_state == "active"


def test_systemd_active_without_application_receipt_is_not_readiness() -> None:
    result = FixedServiceInspectionNormalizer(_profile()).normalize(_manager(), None)

    assert result.active_state == "active"
    assert result.application_ready is None
    assert result.runtime_identity_sha256 is None


def test_service_inspection_requires_an_active_protected_profile() -> None:
    with pytest.raises(ServiceInspectionError, match="profile is not active"):
        FixedServiceInspectionNormalizer(replace(_profile(), active=False)).normalize(
            _manager(), None
        )


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_manager(), service_unit="other.service"), "another unit"),
        (lambda: replace(_manager(), load_state="mystery"), "load state"),
        (lambda: replace(_manager(), active_state="mystery"), "active state"),
        (lambda: replace(_manager(), sub_state="mystery"), "sub-state"),
        (lambda: replace(_manager(), result="mystery"), "result"),
        (lambda: replace(_manager(), main_pid=-1), "PID"),
        (lambda: replace(_manager(), main_pid=0), "PID and start"),
        (
            lambda: replace(
                _manager(),
                main_process_started_at=NOW + timedelta(seconds=1),
            ),
            "starts after",
        ),
        (lambda: replace(_manager(), unit_definition_sha256="bad"), "digest"),
        (lambda: replace(_manager(), observed_at=NOW.replace(tzinfo=None)), "timezone-aware"),
    ),
)
def test_service_manager_snapshot_rejects_unbounded_or_ambiguous_facts(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(ServiceInspectionError, match=match):
        factory()


@pytest.mark.parametrize(
    "factory,match",
    (
        (lambda: replace(_readiness(), service_unit="other.service"), "another unit"),
        (lambda: replace(_readiness(), main_pid=0), "PID"),
        (lambda: replace(_readiness(), runtime_instance_id="bad runtime"), "instance"),
        (lambda: replace(_readiness(), runtime_identity_sha256="bad"), "digest"),
        (lambda: replace(_readiness(), observed_at=NOW.replace(tzinfo=None)), "timezone-aware"),
    ),
)
def test_readiness_snapshot_rejects_ambiguous_identity(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(ServiceInspectionError, match=match):
        factory()


@pytest.mark.parametrize(
    "manager,readiness,match",
    (
        (replace(_manager(), unit_definition_sha256=SHA_B), _readiness(), "definition differs"),
        (replace(_manager(), main_pid=124), _readiness(), "uncorrelated"),
        (
            _manager(),
            replace(_readiness(), observed_at=NOW + timedelta(seconds=1)),
            "stale or uncorrelated",
        ),
        (
            replace(
                _manager(),
                main_pid=0,
                main_process_started_at=None,
                active_state="inactive",
                sub_state="dead",
            ),
            _readiness(),
            "stale or uncorrelated",
        ),
    ),
)
def test_service_normalizer_rejects_stale_or_cross_process_readiness(
    manager: ServiceManagerSnapshot,
    readiness: ApplicationReadinessSnapshot,
    match: str,
) -> None:
    with pytest.raises(ServiceInspectionError, match=match):
        FixedServiceInspectionNormalizer(_profile()).normalize(manager, readiness)

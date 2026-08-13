"""No-effect deterministic package inspection and preparation tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from binnacle.domain.privileged import PackageProfile
from binnacle.domain.privileged_observation import (
    PackageAction,
    PackageInspectionReason,
    PackageTarget,
    PackageTransactionMember,
)
from binnacle.privileged_broker.package_plans import (
    DeterministicPackagePlanBuilder,
    PackagePreparationError,
    PackageResolutionSnapshot,
)

NOW = datetime(2026, 8, 13, 3, 4, 5, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _profile(*, active: bool = True, dependencies_allowed: bool = True) -> PackageProfile:
    return PackageProfile(
        profile_id="development-packages",
        version="v1",
        executable_path="/usr/bin/apt-get",
        executable_sha256=SHA_A,
        repository_profile_sha256=SHA_B,
        allowed_packages=("git", "ripgrep"),
        dependencies_allowed=dependencies_allowed,
        version_pin_required=True,
        removals_allowed=False,
        repository_metadata_maximum_age_seconds=86_400,
        maximum_download_bytes=2_000_000,
        maximum_install_seconds=600,
        maximum_output_bytes=2_000_000,
        parser_version="apt-v1",
        active=active,
    )


def _target() -> PackageTarget:
    return PackageTarget("ripgrep", "arm64", "14.1.1-1")


def _member(
    name: str,
    *,
    requested: bool,
    target_version: str,
    artifact_sha256: str,
) -> PackageTransactionMember:
    return PackageTransactionMember(
        name=name,
        architecture="arm64",
        action=PackageAction.INSTALL,
        requested=requested,
        old_version=None,
        target_version=target_version,
        origin_sha256=SHA_C,
        artifact_sha256=artifact_sha256,
        download_bytes=1_000,
        installed_bytes=2_000,
        maintainer_scripts=requested,
    )


def _snapshot() -> PackageResolutionSnapshot:
    return PackageResolutionSnapshot(
        package_executable_sha256=SHA_A,
        repository_profile_sha256=SHA_B,
        repository_metadata_sha256=SHA_C,
        repository_metadata_observed_at=NOW - timedelta(minutes=1),
        package_database_locked=False,
        requested_targets=(_target(),),
        members=(
            _member(
                "git",
                requested=False,
                target_version="1:2.46.0-1",
                artifact_sha256=SHA_C,
            ),
            _member(
                "ripgrep",
                requested=True,
                target_version="14.1.1-1",
                artifact_sha256=SHA_D,
            ),
        ),
        installed_prestate_sha256=SHA_D,
        resolver_output_sha256=SHA_A,
        resolved_at=NOW - timedelta(seconds=1),
    )


def test_package_inspection_derives_availability_without_refresh() -> None:
    builder = DeterministicPackagePlanBuilder(_profile())

    result = builder.inspect(
        target=_target(),
        installed_version=None,
        candidate_version="14.1.1-1",
        repository_metadata_sha256=SHA_C,
        repository_metadata_observed_at=NOW - timedelta(seconds=30),
        package_database_locked=False,
        observed_at=NOW,
    )

    assert result.preparation_available is True
    assert result.repository_metadata_age_seconds == 30
    assert result.reason_codes == ()


def test_package_inspection_reports_each_no_effect_blocker() -> None:
    target = PackageTarget("ripgrep", "arm64")
    result = DeterministicPackagePlanBuilder(_profile(active=False)).inspect(
        target=target,
        installed_version="14.1.0-1",
        candidate_version=None,
        repository_metadata_sha256=SHA_C,
        repository_metadata_observed_at=NOW - timedelta(days=2),
        package_database_locked=True,
        observed_at=NOW,
    )

    assert result.preparation_available is False
    assert result.reason_codes == tuple(
        sorted(PackageInspectionReason, key=lambda item: item.value)
    )


def test_package_plan_is_canonical_short_lived_and_reproducible() -> None:
    builder = DeterministicPackagePlanBuilder(_profile())
    snapshot = _snapshot()

    first = builder.prepare(snapshot, prepared_at=NOW)
    second = builder.prepare(snapshot, prepared_at=NOW)

    assert first == second
    assert first.expires_at == NOW + timedelta(minutes=5)
    assert first.download_bytes == 2_000
    assert first.installed_bytes == 4_000
    assert first.members == snapshot.members
    assert first.artifact_set_sha256 not in {SHA_A, SHA_B, SHA_C, SHA_D}
    assert builder.verify(first, snapshot, verified_at=NOW + timedelta(seconds=1)) is first
    assert (
        builder.verify(
            first,
            replace(snapshot, resolved_at=NOW + timedelta(milliseconds=500)),
            verified_at=NOW + timedelta(seconds=1),
        )
        is first
    )


def test_package_plan_verification_rejects_changed_solver_truth_and_expiry() -> None:
    builder = DeterministicPackagePlanBuilder(_profile())
    snapshot = _snapshot()
    plan = builder.prepare(snapshot, prepared_at=NOW)

    with pytest.raises(PackagePreparationError, match="closure differs"):
        builder.verify(
            plan,
            replace(snapshot, resolver_output_sha256=SHA_B),
            verified_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(PackagePreparationError, match="expired"):
        builder.verify(plan, snapshot, verified_at=plan.expires_at)
    with pytest.raises(PackagePreparationError, match="predates"):
        builder.verify(plan, snapshot, verified_at=NOW - timedelta(seconds=1))


@pytest.mark.parametrize(
    "profile,snapshot,match",
    (
        (_profile(active=False), _snapshot(), "not active"),
        (_profile(), replace(_snapshot(), package_executable_sha256=SHA_B), "executable"),
        (_profile(), replace(_snapshot(), repository_profile_sha256=SHA_A), "repository profile"),
        (_profile(), replace(_snapshot(), package_database_locked=True), "busy"),
        (
            _profile(),
            replace(
                _snapshot(),
                repository_metadata_observed_at=NOW - timedelta(days=2),
            ),
            "metadata is stale",
        ),
        (
            _profile(dependencies_allowed=False),
            _snapshot(),
            "dependency expansion",
        ),
        (
            _profile(),
            replace(_snapshot(), requested_targets=(replace(_target(), requested_version=None),)),
            "version pin",
        ),
        (
            _profile(),
            replace(
                _snapshot(),
                members=(
                    _member(
                        "curl",
                        requested=False,
                        target_version="1:2.46.0-1",
                        artifact_sha256=SHA_C,
                    ),
                    _snapshot().members[1],
                ),
            ),
            "unapproved package",
        ),
        (
            replace(_profile(), maximum_download_bytes=1_048_576),
            replace(
                _snapshot(),
                members=(
                    replace(_snapshot().members[0], download_bytes=600_000),
                    replace(_snapshot().members[1], download_bytes=600_000),
                ),
            ),
            "download ceiling",
        ),
    ),
)
def test_package_plan_rejects_unpromoted_or_stale_closure(
    profile: PackageProfile,
    snapshot: PackageResolutionSnapshot,
    match: str,
) -> None:
    with pytest.raises(PackagePreparationError, match=match):
        DeterministicPackagePlanBuilder(profile).prepare(snapshot, prepared_at=NOW)


@pytest.mark.parametrize(
    "factory,match",
    (
        (
            lambda: replace(
                _snapshot(),
                repository_metadata_observed_at=NOW,
                resolved_at=NOW - timedelta(seconds=1),
            ),
            "predates",
        ),
        (
            lambda: replace(
                _snapshot(),
                requested_targets=(_target(), _target()),
            ),
            "targets are not canonical",
        ),
        (
            lambda: replace(
                _snapshot(),
                members=tuple(reversed(_snapshot().members)),
            ),
            "members are not canonical",
        ),
        (
            lambda: replace(_snapshot(), installed_prestate_sha256="bad"),
            "digest",
        ),
    ),
)
def test_package_resolution_snapshot_rejects_ambiguous_evidence(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(PackagePreparationError, match=match):
        factory()

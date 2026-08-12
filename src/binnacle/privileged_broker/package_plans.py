"""Deterministic, no-effect package inspection and transaction preparation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Final

from binnacle.domain.privileged import PackageProfile, canonical_sha256
from binnacle.domain.privileged_observation import (
    PackageInspectionReason,
    PackageInspectionResult,
    PackageTarget,
    PackageTransactionMember,
    PackageTransactionPlan,
    PrivilegedObservationError,
)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PREPARED_LIFETIME_SECONDS: Final = 300


class PackagePreparationError(RuntimeError):
    """A package observation or resolver closure cannot authorize preparation."""


@dataclass(frozen=True, slots=True)
class PackageResolutionSnapshot:
    """Bounded exact output of one separately verified package resolver invocation."""

    package_executable_sha256: str
    repository_profile_sha256: str
    repository_metadata_sha256: str
    repository_metadata_observed_at: datetime
    package_database_locked: bool
    requested_targets: tuple[PackageTarget, ...]
    members: tuple[PackageTransactionMember, ...]
    installed_prestate_sha256: str
    resolver_output_sha256: str
    resolved_at: datetime

    def __post_init__(self) -> None:
        for value in (
            self.package_executable_sha256,
            self.repository_profile_sha256,
            self.repository_metadata_sha256,
            self.installed_prestate_sha256,
            self.resolver_output_sha256,
        ):
            if _SHA256_RE.fullmatch(value) is None:
                raise PackagePreparationError("package resolution digest is invalid")
        _require_aware(self.repository_metadata_observed_at)
        _require_aware(self.resolved_at)
        if self.repository_metadata_observed_at > self.resolved_at:
            raise PackagePreparationError("package resolution predates repository metadata")
        if not 1 <= len(self.requested_targets) <= 64:
            raise PackagePreparationError("package resolution target count is outside the limit")
        if self.requested_targets != tuple(
            sorted(self.requested_targets, key=lambda item: item.identity)
        ) or len({item.identity for item in self.requested_targets}) != len(self.requested_targets):
            raise PackagePreparationError("package resolution targets are not canonical")
        if not 1 <= len(self.members) <= 256:
            raise PackagePreparationError("package resolution member count is outside the limit")
        if self.members != tuple(sorted(self.members, key=lambda item: item.identity)) or len(
            {item.identity for item in self.members}
        ) != len(self.members):
            raise PackagePreparationError("package resolution members are not canonical")


class DeterministicPackagePlanBuilder:
    """Normalize and re-verify an exact closure; never invoke a package manager."""

    def __init__(self, profile: PackageProfile) -> None:
        self._profile = profile

    def inspect(
        self,
        *,
        target: PackageTarget,
        installed_version: str | None,
        candidate_version: str | None,
        repository_metadata_sha256: str,
        repository_metadata_observed_at: datetime,
        package_database_locked: bool,
        observed_at: datetime,
    ) -> PackageInspectionResult:
        """Normalize already-read package facts without refreshing repository metadata."""

        _require_aware(repository_metadata_observed_at)
        _require_aware(observed_at)
        age_seconds = int((observed_at - repository_metadata_observed_at).total_seconds())
        if age_seconds < 0:
            raise PackagePreparationError("package observation predates repository metadata")
        reasons: set[PackageInspectionReason] = set()
        if package_database_locked:
            reasons.add(PackageInspectionReason.PACKAGE_DATABASE_BUSY)
        if candidate_version is None:
            reasons.add(PackageInspectionReason.PACKAGE_NOT_AVAILABLE)
        if age_seconds > self._profile.repository_metadata_maximum_age_seconds:
            reasons.add(PackageInspectionReason.REPOSITORY_METADATA_STALE)
        if not self._profile.active:
            reasons.add(PackageInspectionReason.PROFILE_INACTIVE)
        if (
            target.name not in self._profile.allowed_packages
            or (self._profile.version_pin_required and target.requested_version is None)
            or (
                target.requested_version is not None
                and candidate_version is not None
                and target.requested_version != candidate_version
            )
        ):
            reasons.add(PackageInspectionReason.PREPARATION_UNSUPPORTED)
        try:
            return PackageInspectionResult(
                target=target,
                package_profile_sha256=self._profile.profile_sha256,
                installed_version=installed_version,
                candidate_version=candidate_version,
                repository_metadata_sha256=repository_metadata_sha256,
                repository_metadata_observed_at=repository_metadata_observed_at,
                repository_metadata_age_seconds=age_seconds,
                package_database_locked=package_database_locked,
                preparation_available=candidate_version is not None
                and not package_database_locked
                and not reasons,
                reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
                observed_at=observed_at,
            )
        except PrivilegedObservationError as exc:
            raise PackagePreparationError("package inspection facts are invalid") from exc

    def prepare(
        self,
        snapshot: PackageResolutionSnapshot,
        *,
        prepared_at: datetime,
    ) -> PackageTransactionPlan:
        """Create one immutable short-lived plan from an exact resolver snapshot."""

        return self._build(
            snapshot,
            prepared_at=prepared_at,
            resolution_deadline=prepared_at,
        )

    def verify(
        self,
        plan: PackageTransactionPlan,
        snapshot: PackageResolutionSnapshot,
        *,
        verified_at: datetime,
    ) -> PackageTransactionPlan:
        """Require current resolver truth to reproduce the exact prepared plan."""

        _require_aware(verified_at)
        if verified_at < plan.prepared_at:
            raise PackagePreparationError("package verification predates preparation")
        if verified_at >= plan.expires_at:
            raise PackagePreparationError("prepared package transaction has expired")
        expected = self._build(
            snapshot,
            prepared_at=plan.prepared_at,
            resolution_deadline=verified_at,
        )
        if expected != plan:
            raise PackagePreparationError("package resolver closure differs from the prepared plan")
        return plan

    def _build(
        self,
        snapshot: PackageResolutionSnapshot,
        *,
        prepared_at: datetime,
        resolution_deadline: datetime,
    ) -> PackageTransactionPlan:
        _require_aware(prepared_at)
        _require_aware(resolution_deadline)
        if not self._profile.active:
            raise PackagePreparationError("package profile is not active")
        if snapshot.package_executable_sha256 != self._profile.executable_sha256:
            raise PackagePreparationError("package executable identity differs")
        if snapshot.repository_profile_sha256 != self._profile.repository_profile_sha256:
            raise PackagePreparationError("package repository profile differs")
        if snapshot.package_database_locked:
            raise PackagePreparationError("package database is busy")
        if snapshot.resolved_at > resolution_deadline:
            raise PackagePreparationError("package resolution is newer than its observation")
        metadata_expiry = snapshot.repository_metadata_observed_at + timedelta(
            seconds=self._profile.repository_metadata_maximum_age_seconds
        )
        expires_at = min(
            prepared_at + timedelta(seconds=_MAX_PREPARED_LIFETIME_SECONDS),
            metadata_expiry,
        )
        if expires_at <= prepared_at:
            raise PackagePreparationError("package repository metadata is stale")

        requested = {item.identity: item for item in snapshot.requested_targets}
        requested_members = {item.identity: item for item in snapshot.members if item.requested}
        if set(requested) != set(requested_members):
            raise PackagePreparationError("requested package closure differs")
        if any(item.name not in self._profile.allowed_packages for item in snapshot.members):
            raise PackagePreparationError("package closure contains an unapproved package")
        if not self._profile.dependencies_allowed and any(
            not item.requested for item in snapshot.members
        ):
            raise PackagePreparationError("package dependency expansion is not allowed")
        if self._profile.version_pin_required and any(
            item.requested_version is None for item in snapshot.requested_targets
        ):
            raise PackagePreparationError("package target lacks its required version pin")
        for identity, target in requested.items():
            if (
                target.requested_version is not None
                and requested_members[identity].target_version != target.requested_version
            ):
                raise PackagePreparationError("package resolver changed a requested version pin")

        download_bytes = sum(item.download_bytes for item in snapshot.members)
        installed_bytes = sum(item.installed_bytes for item in snapshot.members)
        if download_bytes > self._profile.maximum_download_bytes:
            raise PackagePreparationError("package closure exceeds the download ceiling")
        member_projection = tuple(asdict(item) for item in snapshot.members)
        artifact_projection = tuple(
            (item.name, item.architecture, item.target_version, item.artifact_sha256)
            for item in snapshot.members
        )
        script_projection = tuple(
            (item.name, item.architecture, item.target_version)
            for item in snapshot.members
            if item.maintainer_scripts
        )
        try:
            return PackageTransactionPlan(
                plan_version=self._profile.parser_version,
                package_profile_id=self._profile.profile_id,
                package_profile_sha256=self._profile.profile_sha256,
                repository_metadata_sha256=snapshot.repository_metadata_sha256,
                repository_metadata_observed_at=snapshot.repository_metadata_observed_at,
                requested_targets=snapshot.requested_targets,
                members=snapshot.members,
                artifact_set_sha256=canonical_sha256(artifact_projection),
                dependency_closure_sha256=canonical_sha256(
                    {
                        "members": member_projection,
                        "resolver_output_sha256": snapshot.resolver_output_sha256,
                    }
                ),
                maintainer_script_set_sha256=canonical_sha256(script_projection),
                installed_prestate_sha256=snapshot.installed_prestate_sha256,
                download_bytes=download_bytes,
                installed_bytes=installed_bytes,
                prepared_at=prepared_at,
                expires_at=expires_at,
            )
        except PrivilegedObservationError as exc:
            raise PackagePreparationError("package resolver closure is contradictory") from exc


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PackagePreparationError("package timestamp must be timezone-aware")


__all__ = [
    "DeterministicPackagePlanBuilder",
    "PackagePreparationError",
    "PackageResolutionSnapshot",
]

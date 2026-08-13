"""Closed read-only and preparation values for Phase 9 self-management."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from binnacle.domain.privileged import canonical_sha256

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_PACKAGE_RE: Final = re.compile(r"[a-z0-9][a-z0-9+.-]{0,127}\Z")
_ARCHITECTURE_RE: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")
_TOKEN_RE: Final = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")
_UNIT_RE: Final = re.compile(r"[A-Za-z0-9_.@-]{1,128}\.service\Z")
_OBJECT_ID_RE: Final = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class PrivilegedObservationError(ValueError):
    """An observation or prepared plan is ambiguous, widened, or unbounded."""


class PackageAction(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    CONFIGURE = "configure"


class PackageInspectionReason(StrEnum):
    PACKAGE_DATABASE_BUSY = "package_database_busy"
    PACKAGE_NOT_AVAILABLE = "package_not_available"
    REPOSITORY_METADATA_STALE = "repository_metadata_stale"
    PROFILE_INACTIVE = "profile_inactive"
    PREPARATION_UNSUPPORTED = "preparation_unsupported"


class SourceDirtyState(StrEnum):
    CLEAN = "clean"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


class RuntimeSlotRole(StrEnum):
    CANDIDATE = "candidate"
    LKG = "lkg"
    PRIOR = "prior"


class RuntimeSlotState(StrEnum):
    COMPLETE = "complete"
    ACTIVE = "active"
    LKG = "lkg"
    PRIOR = "prior"
    RESTRICTED = "restricted"


class RestartPreflightKind(StrEnum):
    SIMPLE_SERVICE = "simple_service"
    CONTROLLED_SELF = "controlled_self"


class RestartPreflightReason(StrEnum):
    AUDIT_UNAVAILABLE = "audit_unavailable"
    BLOCKING_OPERATION = "blocking_operation"
    UNCERTAIN_OPERATION = "uncertain_operation"
    COMMAND_EXECUTION_UNSAFE = "command_execution_unsafe"
    SOURCE_CHANGER_OPEN = "source_changer_open"
    WORKSPACE_FENCE_HELD = "workspace_fence_held"
    GIT_EFFECT_OPEN = "git_effect_open"
    CREDENTIAL_EFFECT_OPEN = "credential_effect_open"
    PRIVILEGED_EFFECT_OPEN = "privileged_effect_open"
    PACKAGE_MUTATION_OPEN = "package_mutation_open"
    PRIOR_RESTART_UNRESOLVED = "prior_restart_unresolved"
    SOURCE_MUTATION_UNCERTAIN = "source_mutation_uncertain"
    CURRENT_RUNTIME_UNAVAILABLE = "current_runtime_unavailable"
    SERVICE_NOT_READY = "service_not_ready"
    SCHEMA_HEAD_MISMATCH = "schema_head_mismatch"
    PEER_SET_MISMATCH = "peer_set_mismatch"
    LKG_UNAVAILABLE = "lkg_unavailable"
    CANDIDATE_VERIFICATION_MISSING = "candidate_verification_missing"
    CANDIDATE_VERIFICATION_STALE = "candidate_verification_stale"
    CANDIDATE_TESTED_STATE_MISMATCH = "candidate_tested_state_mismatch"


class RestartImpact(StrEnum):
    CONNECTION_INTERRUPTED = "connection_interrupted"
    APPLICATION_PROCESS_REPLACED = "application_process_replaced"
    RUNTIME_SELECTOR_CHANGED = "runtime_selector_changed"
    ROLLBACK_MAY_RUN = "rollback_may_run"


@dataclass(frozen=True, slots=True)
class CandidateVerificationEvidence:
    """Retained terminal verification bound to one exact candidate state."""

    source_sha256: str
    environment_sha256: str
    config_sha256: str
    policy_sha256: str
    manifest_sha256: str
    service_definition_sha256: str
    deployed_peer_set_sha256: str
    migration_heads_sha256: str
    runtime_layout_sha256: str
    verification_profile_sha256: str
    command_plan_sha256: str
    phase7_operation_id: str
    phase7_execution_set_sha256: str
    terminal_success: bool
    completed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_sha256, "candidate source"),
            (self.environment_sha256, "candidate environment"),
            (self.config_sha256, "candidate config"),
            (self.policy_sha256, "candidate policy"),
            (self.manifest_sha256, "candidate manifest"),
            (self.service_definition_sha256, "candidate service definition"),
            (self.deployed_peer_set_sha256, "candidate deployed-peer set"),
            (self.migration_heads_sha256, "candidate migration heads"),
            (self.runtime_layout_sha256, "candidate runtime layout"),
            (self.verification_profile_sha256, "candidate verification profile"),
            (self.command_plan_sha256, "candidate command plan"),
            (self.phase7_execution_set_sha256, "candidate Phase 7 execution set"),
        ):
            _require_sha256(value, name)
        _require_token(self.phase7_operation_id, "candidate Phase 7 operation")
        _require_utc(self.completed_at, "candidate verification completion time")
        _require_utc(self.expires_at, "candidate verification expiry")
        if not self.completed_at < self.expires_at:
            raise PrivilegedObservationError("candidate verification expiry is invalid")

    @property
    def evidence_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class PackageTarget:
    name: str
    architecture: str
    requested_version: str | None = None

    def __post_init__(self) -> None:
        if _PACKAGE_RE.fullmatch(self.name) is None:
            raise PrivilegedObservationError("package target name is invalid")
        if _ARCHITECTURE_RE.fullmatch(self.architecture) is None:
            raise PrivilegedObservationError("package target architecture is invalid")
        if self.requested_version is not None:
            _require_package_version(self.requested_version, "requested package")

    @property
    def identity(self) -> tuple[str, str]:
        return self.name, self.architecture


@dataclass(frozen=True, slots=True)
class PackageInspectionResult:
    target: PackageTarget
    package_profile_sha256: str
    installed_version: str | None
    candidate_version: str | None
    repository_metadata_sha256: str
    repository_metadata_observed_at: datetime
    repository_metadata_age_seconds: int
    package_database_locked: bool
    preparation_available: bool
    reason_codes: tuple[PackageInspectionReason, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.package_profile_sha256, "package profile")
        _require_sha256(self.repository_metadata_sha256, "package repository metadata")
        for value, name in (
            (self.installed_version, "installed package"),
            (self.candidate_version, "candidate package"),
        ):
            if value is not None:
                _require_package_version(value, name)
        _require_utc(self.repository_metadata_observed_at, "package metadata time")
        _require_utc(self.observed_at, "package observation time")
        observed_age = int(
            (self.observed_at - self.repository_metadata_observed_at).total_seconds()
        )
        if self.repository_metadata_age_seconds != observed_age or observed_age < 0:
            raise PrivilegedObservationError("package metadata age is contradictory")
        if self.reason_codes != tuple(sorted(set(self.reason_codes), key=lambda item: item.value)):
            raise PrivilegedObservationError("package reason codes are not canonical")
        if self.package_database_locked != (
            PackageInspectionReason.PACKAGE_DATABASE_BUSY in self.reason_codes
        ):
            raise PrivilegedObservationError("package lock state and reason code disagree")
        if (self.candidate_version is None) != (
            PackageInspectionReason.PACKAGE_NOT_AVAILABLE in self.reason_codes
        ):
            raise PrivilegedObservationError("package candidate and reason code disagree")
        expected_available = (
            self.candidate_version is not None
            and not self.package_database_locked
            and not self.reason_codes
        )
        if self.preparation_available != expected_available:
            raise PrivilegedObservationError("package preparation availability is contradictory")

    @property
    def observation_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class PackageTransactionMember:
    name: str
    architecture: str
    action: PackageAction
    requested: bool
    old_version: str | None
    target_version: str
    origin_sha256: str
    artifact_sha256: str
    download_bytes: int
    installed_bytes: int
    maintainer_scripts: bool

    def __post_init__(self) -> None:
        PackageTarget(name=self.name, architecture=self.architecture)
        if self.old_version is not None:
            _require_package_version(self.old_version, "old package")
        _require_package_version(self.target_version, "target package")
        _require_sha256(self.origin_sha256, "package origin")
        _require_sha256(self.artifact_sha256, "package artifact")
        if not 0 <= self.download_bytes <= 20_000_000_000:
            raise PrivilegedObservationError("package member download size is outside the limit")
        if not 0 <= self.installed_bytes <= 100_000_000_000:
            raise PrivilegedObservationError("package member installed size is outside the limit")
        if self.action is PackageAction.INSTALL and self.old_version is not None:
            raise PrivilegedObservationError("package install unexpectedly has an old version")
        if self.action in {PackageAction.UPGRADE, PackageAction.CONFIGURE} and (
            self.old_version is None
        ):
            raise PrivilegedObservationError("package update lacks its old version")
        if self.action is PackageAction.UPGRADE and self.old_version == self.target_version:
            raise PrivilegedObservationError("package upgrade does not change version")

    @property
    def identity(self) -> tuple[str, str]:
        return self.name, self.architecture


@dataclass(frozen=True, slots=True)
class PackageTransactionPlan:
    plan_version: str
    package_profile_id: str
    package_profile_sha256: str
    repository_metadata_sha256: str
    repository_metadata_observed_at: datetime
    requested_targets: tuple[PackageTarget, ...]
    members: tuple[PackageTransactionMember, ...]
    artifact_set_sha256: str
    dependency_closure_sha256: str
    maintainer_script_set_sha256: str
    installed_prestate_sha256: str
    download_bytes: int
    installed_bytes: int
    prepared_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_token(self.plan_version, "package plan version")
        _require_token(self.package_profile_id, "package profile")
        for value, name in (
            (self.package_profile_sha256, "package profile"),
            (self.repository_metadata_sha256, "package repository metadata"),
            (self.artifact_set_sha256, "package artifact set"),
            (self.dependency_closure_sha256, "package dependency closure"),
            (self.maintainer_script_set_sha256, "package maintainer-script set"),
            (self.installed_prestate_sha256, "installed package pre-state"),
        ):
            _require_sha256(value, name)
        _require_utc(self.repository_metadata_observed_at, "package metadata time")
        _require_utc(self.prepared_at, "package prepare time")
        _require_utc(self.expires_at, "package plan expiry")
        if not self.prepared_at < self.expires_at:
            raise PrivilegedObservationError("package plan expiry is invalid")
        if (self.expires_at - self.prepared_at).total_seconds() > 3_600:
            raise PrivilegedObservationError("package plan lifetime is outside the limit")
        if self.repository_metadata_observed_at > self.prepared_at:
            raise PrivilegedObservationError("package plan metadata time is contradictory")
        if not 1 <= len(self.requested_targets) <= 64:
            raise PrivilegedObservationError("requested package target count is outside the limit")
        target_identities = tuple(item.identity for item in self.requested_targets)
        if len(set(target_identities)) != len(target_identities):
            raise PrivilegedObservationError("requested package target identity is duplicated")
        if self.requested_targets != tuple(
            sorted(self.requested_targets, key=lambda item: item.identity)
        ):
            raise PrivilegedObservationError("requested package targets are not canonical")
        if not 1 <= len(self.members) <= 256 or self.members != tuple(
            sorted(self.members, key=lambda item: item.identity)
        ):
            raise PrivilegedObservationError("package transaction members are not canonical")
        identities = tuple(item.identity for item in self.members)
        if len(set(identities)) != len(identities):
            raise PrivilegedObservationError("package transaction has duplicate members")
        requested_identities = {item.identity for item in self.requested_targets}
        member_identities = {item.identity for item in self.members if item.requested}
        if requested_identities != member_identities:
            raise PrivilegedObservationError("package transaction requested-member set differs")
        targets_by_identity = {item.identity: item for item in self.requested_targets}
        for member in self.members:
            target = targets_by_identity.get(member.identity)
            if (
                member.requested
                and target is not None
                and target.requested_version is not None
                and target.requested_version != member.target_version
            ):
                raise PrivilegedObservationError("package transaction changed a pinned version")
        expected_download = sum(item.download_bytes for item in self.members)
        expected_installed = sum(item.installed_bytes for item in self.members)
        if not 0 <= self.download_bytes <= 20_000_000_000 or not 0 <= self.installed_bytes <= (
            100_000_000_000
        ):
            raise PrivilegedObservationError("package transaction totals are outside the limit")
        if (self.download_bytes, self.installed_bytes) != (
            expected_download,
            expected_installed,
        ):
            raise PrivilegedObservationError("package transaction size totals differ")

    @property
    def transaction_plan_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class ServiceInspectionResult:
    service_profile_sha256: str
    service_unit: str
    load_state: str
    active_state: str
    sub_state: str
    result: str | None
    main_pid: int
    main_process_started_at: datetime | None
    application_ready: bool | None
    runtime_identity_sha256: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.service_profile_sha256, "service profile")
        if (
            _UNIT_RE.fullmatch(self.service_unit) is None
            or self.service_unit != "binnacle-dev.service"
        ):
            raise PrivilegedObservationError("service inspection unit is unsupported")
        for value, name in (
            (self.load_state, "service load state"),
            (self.active_state, "service active state"),
            (self.sub_state, "service sub-state"),
        ):
            _require_token(value, name)
        if self.result is not None:
            _require_token(self.result, "service result")
        if not 0 <= self.main_pid <= 2_147_483_647:
            raise PrivilegedObservationError("service main PID is invalid")
        if self.main_process_started_at is not None:
            _require_utc(self.main_process_started_at, "service process start time")
        if (self.main_pid == 0) != (self.main_process_started_at is None):
            raise PrivilegedObservationError("service PID and start time disagree")
        if self.application_ready is None:
            if self.runtime_identity_sha256 is not None:
                raise PrivilegedObservationError("unqueried readiness carries runtime identity")
        elif self.runtime_identity_sha256 is None:
            raise PrivilegedObservationError("readiness result lacks runtime identity")
        else:
            _require_sha256(self.runtime_identity_sha256, "service runtime identity")
        _require_utc(self.observed_at, "service observation time")

    @property
    def observation_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    source_git_oid: str
    source_dirty_state: SourceDirtyState
    source_state_sha256: str
    workspace_identity_sha256: str
    workspace_mount_identity_sha256: str
    python_executable: str
    python_version: str
    environment_root: str
    environment_sha256: str
    runtime_slot_identity_sha256: str | None
    lock_sha256: str
    build_sha256: str
    config_sha256: str
    policy_sha256: str
    manifest_sha256: str
    service_profile_sha256: str
    device_id: str
    device_epoch: int
    runtime_instance_id: str
    process_started_at: datetime
    readiness_generation: int
    schema_heads_sha256: str
    runtime_layout_sha256: str
    deployed_peer_set_sha256: str

    def __post_init__(self) -> None:
        if _OBJECT_ID_RE.fullmatch(self.source_git_oid) is None or not set(self.source_git_oid) - {
            "0"
        }:
            raise PrivilegedObservationError("runtime Git object ID is invalid")
        for value, name in (
            (self.source_state_sha256, "runtime source state"),
            (self.workspace_identity_sha256, "runtime workspace"),
            (self.workspace_mount_identity_sha256, "runtime workspace mount"),
            (self.environment_sha256, "runtime environment"),
            (self.lock_sha256, "runtime lock"),
            (self.build_sha256, "runtime build"),
            (self.config_sha256, "runtime config"),
            (self.policy_sha256, "runtime policy"),
            (self.manifest_sha256, "runtime manifest"),
            (self.service_profile_sha256, "runtime service profile"),
            (self.schema_heads_sha256, "runtime schema heads"),
            (self.runtime_layout_sha256, "runtime layout"),
            (self.deployed_peer_set_sha256, "runtime deployed-peer set"),
        ):
            _require_sha256(value, name)
        if self.runtime_slot_identity_sha256 is not None:
            _require_sha256(self.runtime_slot_identity_sha256, "runtime slot identity")
        _require_absolute_path(self.python_executable, "runtime Python executable")
        _require_absolute_path(self.environment_root, "runtime environment root")
        _require_bounded_text(self.python_version, "runtime Python version", 128)
        _require_token(self.device_id, "runtime device")
        _require_token(self.runtime_instance_id, "runtime instance")
        _require_utc(self.process_started_at, "runtime process start time")
        if self.device_epoch < 1 or self.readiness_generation < 1:
            raise PrivilegedObservationError("runtime generation is invalid")

    @property
    def runtime_identity_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeSlot:
    slot_id: str
    slot_generation: int
    slot_path: str
    role: RuntimeSlotRole
    state: RuntimeSlotState
    source_sha256: str
    environment_sha256: str
    config_sha256: str
    policy_sha256: str
    manifest_sha256: str
    service_definition_sha256: str
    deployed_peer_set_sha256: str
    migration_heads_sha256: str
    layout_sha256: str
    candidate_verification_sha256: str
    complete_manifest_sha256: str
    byte_count: int
    inode_count: int
    completed_at: datetime

    def __post_init__(self) -> None:
        _require_token(self.slot_id, "runtime slot")
        expected_path = f"/srv/binnacle-runtime/slots/{self.slot_id}"
        if self.slot_path != expected_path:
            raise PrivilegedObservationError("runtime slot path is outside the fixed root")
        if self.slot_generation < 1:
            raise PrivilegedObservationError("runtime slot generation is invalid")
        if self.state is RuntimeSlotState.LKG and self.role is not RuntimeSlotRole.LKG:
            raise PrivilegedObservationError("LKG slot state and role disagree")
        if self.state is RuntimeSlotState.PRIOR and self.role is not RuntimeSlotRole.PRIOR:
            raise PrivilegedObservationError("prior slot state and role disagree")
        for value, name in (
            (self.source_sha256, "slot source"),
            (self.environment_sha256, "slot environment"),
            (self.config_sha256, "slot config"),
            (self.policy_sha256, "slot policy"),
            (self.manifest_sha256, "slot manifest"),
            (self.service_definition_sha256, "slot service definition"),
            (self.deployed_peer_set_sha256, "slot deployed-peer set"),
            (self.migration_heads_sha256, "slot migration heads"),
            (self.layout_sha256, "slot layout"),
            (self.candidate_verification_sha256, "slot candidate verification"),
            (self.complete_manifest_sha256, "slot complete manifest"),
        ):
            _require_sha256(value, name)
        if not 1 <= self.byte_count <= 100_000_000_000:
            raise PrivilegedObservationError("runtime slot bytes are outside the limit")
        if not 1 <= self.inode_count <= 10_000_000:
            raise PrivilegedObservationError("runtime slot inodes are outside the limit")
        _require_utc(self.completed_at, "runtime slot completion time")

    @property
    def slot_identity_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class RestartPreflightResult:
    kind: RestartPreflightKind
    available: bool
    reason_codes: tuple[RestartPreflightReason, ...]
    predicted_impacts: tuple[RestartImpact, ...]
    current_runtime_identity_sha256: str | None
    current_service_observation_sha256: str
    lkg_slot_identity_sha256: str | None
    candidate_slot_identity_sha256: str | None
    candidate_verification_sha256: str | None
    outstanding_state_sha256: str
    state_binding_sha256: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.available != (not self.reason_codes):
            raise PrivilegedObservationError("restart preflight availability is contradictory")
        if self.reason_codes != tuple(sorted(set(self.reason_codes), key=lambda item: item.value)):
            raise PrivilegedObservationError("restart preflight reasons are not canonical")
        if self.predicted_impacts != tuple(
            sorted(set(self.predicted_impacts), key=lambda item: item.value)
        ):
            raise PrivilegedObservationError("restart impacts are not canonical")
        expected_impacts = {
            RestartImpact.APPLICATION_PROCESS_REPLACED,
            RestartImpact.CONNECTION_INTERRUPTED,
        }
        if self.kind is RestartPreflightKind.CONTROLLED_SELF:
            expected_impacts.update(
                {
                    RestartImpact.RUNTIME_SELECTOR_CHANGED,
                    RestartImpact.ROLLBACK_MAY_RUN,
                }
            )
        if set(self.predicted_impacts) != expected_impacts:
            raise PrivilegedObservationError("restart impact set differs from its kind")
        for value, name in (
            (self.current_service_observation_sha256, "restart service observation"),
            (self.outstanding_state_sha256, "restart outstanding state"),
            (self.state_binding_sha256, "restart state binding"),
        ):
            _require_sha256(value, name)
        for optional_value, name in (
            (self.current_runtime_identity_sha256, "restart current runtime"),
            (self.lkg_slot_identity_sha256, "restart LKG slot"),
            (self.candidate_slot_identity_sha256, "restart candidate slot"),
            (self.candidate_verification_sha256, "restart candidate verification"),
        ):
            if optional_value is not None:
                _require_sha256(optional_value, name)
        if self.available and self.current_runtime_identity_sha256 is None:
            raise PrivilegedObservationError("available restart lacks current runtime identity")
        if (
            self.available
            and self.kind is RestartPreflightKind.CONTROLLED_SELF
            and any(
                value is None
                for value in (
                    self.lkg_slot_identity_sha256,
                    self.candidate_slot_identity_sha256,
                    self.candidate_verification_sha256,
                )
            )
        ):
            raise PrivilegedObservationError("controlled restart lacks candidate or LKG evidence")
        _require_utc(self.observed_at, "restart preflight observation time")

    @property
    def observation_sha256(self) -> str:
        return canonical_sha256(asdict(self))


def _require_sha256(value: str, name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise PrivilegedObservationError(f"{name} must be a lowercase SHA-256 digest")


def _require_token(value: str, name: str) -> None:
    if _TOKEN_RE.fullmatch(value) is None or ".." in value:
        raise PrivilegedObservationError(f"{name} identity is invalid")


def _require_package_version(value: str, name: str) -> None:
    _require_bounded_text(value, f"{name} version", 256)
    if any(
        character.isspace() or ord(character) < 0x21 or ord(character) > 0x7E for character in value
    ):
        raise PrivilegedObservationError(f"{name} version is invalid")


def _require_bounded_text(value: str, name: str, maximum_bytes: int) -> None:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PrivilegedObservationError(f"{name} is invalid") from exc
    if not value or len(encoded) > maximum_bytes or "\0" in value or "\n" in value:
        raise PrivilegedObservationError(f"{name} is invalid")


def _require_absolute_path(value: str, name: str) -> None:
    path = PurePosixPath(value)
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PrivilegedObservationError(f"{name} is invalid") from exc
    if (
        not path.is_absolute()
        or str(path) != value
        or encoded_length > 1_024
        or ".." in path.parts
        or "\0" in value
        or "\n" in value
    ):
        raise PrivilegedObservationError(f"{name} must be canonical absolute POSIX form")


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedObservationError(f"{name} must be timezone-aware")


__all__ = [
    "CandidateVerificationEvidence",
    "PackageAction",
    "PackageInspectionReason",
    "PackageInspectionResult",
    "PackageTarget",
    "PackageTransactionMember",
    "PackageTransactionPlan",
    "PrivilegedObservationError",
    "RestartImpact",
    "RestartPreflightKind",
    "RestartPreflightReason",
    "RestartPreflightResult",
    "RuntimeIdentity",
    "RuntimeSlotRole",
    "RuntimeSlotState",
    "ServiceInspectionResult",
    "SourceDirtyState",
    "VerifiedRuntimeSlot",
]

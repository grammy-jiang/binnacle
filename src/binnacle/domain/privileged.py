"""Closed evidence-independent Phase 9 privileged authority contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE: Final = re.compile(r"[a-z][a-z0-9._-]{0,95}\Z")
_TICKET_ID_RE: Final = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
_UNIT_RE: Final = re.compile(r"[A-Za-z0-9_.@-]{1,128}\.service\Z")
_PACKAGE_RE: Final = re.compile(r"[a-z0-9][a-z0-9+.-]{0,127}\Z")
_NONCE_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

PRIVILEGED_PROTOCOL_ID: Final = "binnacle-privileged"
PRIVILEGED_PROTOCOL_VERSION: Final = "v1"
MAX_PRIVILEGED_FRAME_BYTES: Final = 1_048_576


class PrivilegedError(ValueError):
    """A privileged value widens or contradicts its reviewed contract."""


class PrivilegedAction(StrEnum):
    PACKAGE_INSPECT = "package_inspect"
    PACKAGE_INSTALL = "package_install"
    SERVICE_INSPECT = "service_inspect"
    SERVICE_RESTART = "service_restart"
    RESTART_PREFLIGHT = "restart_preflight"
    CONTROLLED_RESTART = "controlled_restart"
    RUNTIME_INSPECT = "runtime_inspect"
    HOST_REBOOT = "host_reboot"

    @property
    def consequential(self) -> bool:
        return self in {
            PrivilegedAction.PACKAGE_INSTALL,
            PrivilegedAction.SERVICE_RESTART,
            PrivilegedAction.CONTROLLED_RESTART,
            PrivilegedAction.HOST_REBOOT,
        }


class PrivilegedMaximumEffect(StrEnum):
    OBSERVATION = "observation"
    PACKAGE_CHANGE = "package_change"
    SERVICE_RESTART = "service_restart"
    CONTROLLED_RESTART = "controlled_restart"
    HOST_REBOOT = "host_reboot"


class BrokerAcceptanceDisposition(StrEnum):
    ACCEPTED = "accepted"
    RETAINED_ACCEPTED = "retained_accepted"
    NO_ACCEPT_PROVEN = "no_accept_proven"
    CONFLICT = "conflict"


class BrokerAcceptanceState(StrEnum):
    UNRESOLVED = "unresolved"
    ACCEPTED = "accepted"
    SEALED_NO_ACCEPT = "sealed_no_accept"


class BrokerNoAcceptReason(StrEnum):
    PHASE4_NO_START = "phase4_no_start"
    REPLACEMENT_RECOVERY = "replacement_recovery"
    DISPATCH_CANCELLED = "dispatch_cancelled"


class BrokerExecutionState(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    ACCEPTED_PRE_EFFECT = "accepted_pre_effect"
    EXECUTING = "executing"
    RECONCILING = "reconciling"
    TERMINAL = "terminal"
    UNCERTAIN = "uncertain"
    RESTRICTED_RECOVERY = "restricted_recovery"


class PrivilegedEffectKnowledge(StrEnum):
    NONE = "none"
    KNOWN_NO_SUBEFFECT = "known_no_subeffect"
    KNOWN_EFFECT = "known_effect"
    UNCERTAIN = "uncertain"


class BrokerRestartCheckpointState(StrEnum):
    """Durable root-side controlled-restart progression."""

    PREPARED = "prepared"
    CHECKPOINTED = "checkpointed"
    SERVICE_STOPPED = "service_stopped"
    CANDIDATE_SELECTED = "candidate_selected"
    CANDIDATE_STARTED = "candidate_started"
    VERIFYING = "verifying"
    ROLLBACK_REQUIRED = "rollback_required"
    ROLLBACK_SERVICE_STOPPED = "rollback_service_stopped"
    ROLLBACK_SELECTED = "rollback_selected"
    ROLLBACK_STARTED = "rollback_started"
    TERMINAL = "terminal"
    UNCERTAIN = "uncertain"
    RESTRICTED_RECOVERY = "restricted_recovery"


class BrokerRestartOutcome(StrEnum):
    """Bounded restart result; never infer it from service presence alone."""

    PENDING = "pending"
    CANDIDATE_READY = "candidate_ready"
    ROLLBACK_READY = "rollback_ready"
    NO_SUBEFFECT = "no_subeffect"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    RESTRICTED_RECOVERY = "restricted_recovery"


class BrokerServiceRestartOutcome(StrEnum):
    """Explicit terminal truth for the unchanged fixed-service restart."""

    SERVICE_READY = "service_ready"
    NO_SUBEFFECT = "no_subeffect"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PrivilegedBrokerHello:
    """Authenticated broker identity and fail-closed readiness projection."""

    protocol_id: str
    protocol_version: str
    build_sha256: str
    profile_sha256: str
    broker_instance_id: str
    broker_generation: int
    backend_ready: bool
    readiness: str

    def __post_init__(self) -> None:
        if (
            self.protocol_id != PRIVILEGED_PROTOCOL_ID
            or self.protocol_version != PRIVILEGED_PROTOCOL_VERSION
        ):
            raise PrivilegedError("privileged broker protocol identity is incompatible")
        _require_sha256(self.build_sha256, "broker build")
        _require_sha256(self.profile_sha256, "broker profile")
        _require_ticket_id(self.broker_instance_id, "broker instance")
        if self.broker_generation < 1 or self.readiness not in {
            "disabled",
            "ready",
            "restricted_recovery",
            "integrity_failed",
        }:
            raise PrivilegedError("privileged broker readiness is invalid")


_ACTION_EFFECT: Final = {
    PrivilegedAction.PACKAGE_INSPECT: PrivilegedMaximumEffect.OBSERVATION,
    PrivilegedAction.PACKAGE_INSTALL: PrivilegedMaximumEffect.PACKAGE_CHANGE,
    PrivilegedAction.SERVICE_INSPECT: PrivilegedMaximumEffect.OBSERVATION,
    PrivilegedAction.SERVICE_RESTART: PrivilegedMaximumEffect.SERVICE_RESTART,
    PrivilegedAction.RESTART_PREFLIGHT: PrivilegedMaximumEffect.OBSERVATION,
    PrivilegedAction.CONTROLLED_RESTART: PrivilegedMaximumEffect.CONTROLLED_RESTART,
    PrivilegedAction.RUNTIME_INSPECT: PrivilegedMaximumEffect.OBSERVATION,
    PrivilegedAction.HOST_REBOOT: PrivilegedMaximumEffect.HOST_REBOOT,
}


@dataclass(frozen=True, slots=True)
class PrivilegedBrokerProfile:
    """Protected root-broker boundary; never constructed from model input."""

    profile_id: str
    version: str
    protocol_version: str
    socket_path: str
    broker_uid: int
    broker_gid: int
    application_peer_uid: int
    application_peer_gid: int
    allowed_actions: tuple[PrivilegedAction, ...]
    maximum_frame_bytes: int
    request_deadline_seconds: int
    maximum_requests_per_minute: int
    evidence_root: str
    evidence_mount_identity_sha256: str
    checkpoint_root: str
    checkpoint_mount_identity_sha256: str
    executable_path: str
    executable_sha256: str
    migration_head: str
    ticket_verification_key_reference_sha256: str
    ticket_integrity_algorithm: str
    service_hardening_sha256: str
    capability_evidence_sha256: str
    active: bool = False

    def __post_init__(self) -> None:
        _require_id(self.profile_id, "broker profile")
        _require_id(self.version, "broker profile version")
        _require_id(self.protocol_version, "broker protocol version")
        _require_absolute_path(self.socket_path, "broker socket")
        _require_absolute_path(self.evidence_root, "broker evidence root")
        _require_absolute_path(self.checkpoint_root, "broker checkpoint root")
        _require_absolute_path(self.executable_path, "broker executable")
        if self.broker_uid != 0 or self.broker_gid != 0:
            raise PrivilegedError("the initial privileged broker identity must be root")
        if self.application_peer_uid <= 0 or self.application_peer_gid <= 0:
            raise PrivilegedError("application peer identity must be unprivileged")
        if not self.allowed_actions or self.allowed_actions != tuple(
            sorted(set(self.allowed_actions), key=lambda value: value.value)
        ):
            raise PrivilegedError("allowed privileged actions must be unique and sorted")
        if PrivilegedAction.HOST_REBOOT in self.allowed_actions:
            raise PrivilegedError("host reboot remains unpromoted in the Bootstrap profile")
        if not 1_024 <= self.maximum_frame_bytes <= 1_048_576:
            raise PrivilegedError("broker frame ceiling is outside the reviewed range")
        if not 1 <= self.request_deadline_seconds <= 300:
            raise PrivilegedError("broker request deadline is outside the reviewed range")
        if not 1 <= self.maximum_requests_per_minute <= 600:
            raise PrivilegedError("broker rate ceiling is outside the reviewed range")
        if self.migration_head != "0001_privileged_evidence":
            raise PrivilegedError("broker migration head is not the Phase 9 head")
        if self.ticket_integrity_algorithm not in {"ed25519", "hmac-sha256"}:
            raise PrivilegedError("ticket integrity algorithm is unsupported")
        for name, value in (
            ("evidence mount", self.evidence_mount_identity_sha256),
            ("checkpoint mount", self.checkpoint_mount_identity_sha256),
            ("broker executable", self.executable_sha256),
            ("ticket verification key reference", self.ticket_verification_key_reference_sha256),
            ("service hardening", self.service_hardening_sha256),
            ("capability evidence", self.capability_evidence_sha256),
        ):
            _require_sha256(value, name)

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class BinnacleServiceProfile:
    """Exact fixed service and complete selector/LKG authority profile."""

    profile_id: str
    version: str
    service_unit: str
    workspace_root: str
    workspace_identity_sha256: str
    workspace_mount_identity_sha256: str
    runtime_root: str
    runtime_mount_identity_sha256: str
    current_selector: str
    slot_layout_version: str
    maximum_slot_bytes: int
    maximum_slot_inodes: int
    maximum_retained_slots: int
    service_uid: int
    service_gid: int
    config_sha256: str
    policy_sha256: str
    manifest_sha256: str
    executable_path: str
    stable_unit_sha256: str
    application_migration_head: str
    executor_migration_head: str
    git_credential_migration_head: str
    privileged_migration_head: str
    deployed_peer_set_sha256: str
    readiness_contract_version: str
    restart_deadline_seconds: int
    checkpoint_root: str
    local_recovery_marker: str
    active: bool = False

    def __post_init__(self) -> None:
        _require_id(self.profile_id, "service profile")
        _require_id(self.version, "service profile version")
        if (
            _UNIT_RE.fullmatch(self.service_unit) is None
            or self.service_unit != "binnacle-dev.service"
        ):
            raise PrivilegedError("service unit is not the exact Binnacle development service")
        for name, value in (
            ("workspace root", self.workspace_root),
            ("runtime root", self.runtime_root),
            ("current selector", self.current_selector),
            ("service executable", self.executable_path),
            ("checkpoint root", self.checkpoint_root),
            ("local recovery marker", self.local_recovery_marker),
        ):
            _require_absolute_path(value, name)
        runtime_root = PurePosixPath(self.runtime_root)
        if PurePosixPath(self.current_selector).parent != runtime_root:
            raise PrivilegedError("runtime selector is outside the registered runtime root")
        if PurePosixPath(self.local_recovery_marker).parent != PurePosixPath(self.checkpoint_root):
            raise PrivilegedError("local recovery marker is outside the checkpoint root")
        _require_id(self.slot_layout_version, "slot layout version")
        _require_id(self.readiness_contract_version, "readiness contract version")
        if not 1_048_576 <= self.maximum_slot_bytes <= 100_000_000_000:
            raise PrivilegedError("runtime slot byte ceiling is outside the reviewed range")
        if not 1_000 <= self.maximum_slot_inodes <= 10_000_000:
            raise PrivilegedError("runtime slot inode ceiling is outside the reviewed range")
        if not 3 <= self.maximum_retained_slots <= 16:
            raise PrivilegedError("runtime retained-slot ceiling is outside the reviewed range")
        if self.service_uid <= 0 or self.service_gid <= 0:
            raise PrivilegedError("Binnacle service identity must be unprivileged")
        if not 1 <= self.restart_deadline_seconds <= 900:
            raise PrivilegedError("service restart deadline is outside the reviewed range")
        expected_heads = {
            "application": "0006_privileged_operations",
            "executor": "0002_git_members",
            "Git credential": "0001_credential_evidence",
            "privileged": "0001_privileged_evidence",
        }
        actual_heads = {
            "application": self.application_migration_head,
            "executor": self.executor_migration_head,
            "Git credential": self.git_credential_migration_head,
            "privileged": self.privileged_migration_head,
        }
        if actual_heads != expected_heads:
            raise PrivilegedError("service profile migration heads are incompatible")
        for name, value in (
            ("workspace identity", self.workspace_identity_sha256),
            ("workspace mount", self.workspace_mount_identity_sha256),
            ("runtime mount", self.runtime_mount_identity_sha256),
            ("protected config", self.config_sha256),
            ("policy", self.policy_sha256),
            ("manifest", self.manifest_sha256),
            ("stable systemd unit", self.stable_unit_sha256),
            ("deployed peer set", self.deployed_peer_set_sha256),
        ):
            _require_sha256(value, name)

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class PackageProfile:
    """Exact package-manager authority; arbitrary flags and removals are absent."""

    profile_id: str
    version: str
    executable_path: str
    executable_sha256: str
    repository_profile_sha256: str
    allowed_packages: tuple[str, ...]
    dependencies_allowed: bool
    version_pin_required: bool
    removals_allowed: bool
    repository_metadata_maximum_age_seconds: int
    maximum_download_bytes: int
    maximum_install_seconds: int
    maximum_output_bytes: int
    parser_version: str
    active: bool = False

    def __post_init__(self) -> None:
        _require_id(self.profile_id, "package profile")
        _require_id(self.version, "package profile version")
        _require_id(self.parser_version, "package parser version")
        _require_absolute_path(self.executable_path, "package-manager executable")
        _require_sha256(self.executable_sha256, "package-manager executable")
        _require_sha256(self.repository_profile_sha256, "package repository profile")
        if not self.allowed_packages or self.allowed_packages != tuple(
            sorted(set(self.allowed_packages))
        ):
            raise PrivilegedError("allowed package names must be unique and sorted")
        if any(_PACKAGE_RE.fullmatch(value) is None for value in self.allowed_packages):
            raise PrivilegedError("allowed package name is invalid")
        if self.removals_allowed:
            raise PrivilegedError("package removal is outside the Bootstrap profile")
        if not 60 <= self.repository_metadata_maximum_age_seconds <= 604_800:
            raise PrivilegedError("package metadata age ceiling is outside the reviewed range")
        if not 1_048_576 <= self.maximum_download_bytes <= 20_000_000_000:
            raise PrivilegedError("package download ceiling is outside the reviewed range")
        if not 1 <= self.maximum_install_seconds <= 3_600:
            raise PrivilegedError("package install deadline is outside the reviewed range")
        if not 1_024 <= self.maximum_output_bytes <= 20_000_000:
            raise PrivilegedError("package output ceiling is outside the reviewed range")

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class PrivilegedTicket:
    """One operation-bound consequential authority ticket."""

    operation_id: str
    ticket_id: str
    nonce: str
    controller_identity_sha256: str
    device_id: str
    device_epoch: int
    operation_contract: str
    operation_contract_version: str
    broker_profile_id: str
    broker_profile_version: str
    broker_profile_sha256: str
    action: PrivilegedAction
    target_profile_id: str
    target_profile_sha256: str
    request_fingerprint_sha256: str
    maximum_effect: PrivilegedMaximumEffect
    current_state_binding_sha256: str
    policy_evidence_reference: str
    policy_evidence_sha256: str
    application_build_sha256: str
    application_config_sha256: str
    application_policy_sha256: str
    operation_specific_evidence_sha256: str
    issued_at: datetime
    expires_at: datetime
    integrity_algorithm: str
    integrity_proof: str

    def __post_init__(self) -> None:
        for name, value in (
            ("operation", self.operation_id),
            ("ticket", self.ticket_id),
            ("device", self.device_id),
            ("policy evidence reference", self.policy_evidence_reference),
        ):
            _require_ticket_id(value, name)
        for name, value in (
            ("operation contract", self.operation_contract),
            ("operation contract version", self.operation_contract_version),
            ("broker profile", self.broker_profile_id),
            ("broker profile version", self.broker_profile_version),
            ("target profile", self.target_profile_id),
        ):
            _require_id(value, name)
        if _NONCE_RE.fullmatch(self.nonce) is None:
            raise PrivilegedError("privileged ticket nonce must contain 256 random bits")
        if self.device_epoch < 1:
            raise PrivilegedError("device epoch must be positive")
        if not self.action.consequential:
            raise PrivilegedError("observation actions do not receive privileged tickets")
        if self.action is PrivilegedAction.HOST_REBOOT:
            raise PrivilegedError("host reboot remains unpromoted in the Bootstrap profile")
        if _ACTION_EFFECT[self.action] is not self.maximum_effect:
            raise PrivilegedError("privileged action and maximum effect disagree")
        for name, value in (
            ("controller identity", self.controller_identity_sha256),
            ("broker profile", self.broker_profile_sha256),
            ("target profile", self.target_profile_sha256),
            ("request fingerprint", self.request_fingerprint_sha256),
            ("current state binding", self.current_state_binding_sha256),
            ("policy evidence", self.policy_evidence_sha256),
            ("application build", self.application_build_sha256),
            ("application config", self.application_config_sha256),
            ("application policy", self.application_policy_sha256),
            ("operation-specific evidence", self.operation_specific_evidence_sha256),
        ):
            _require_sha256(value, name)
        _require_aware_utc(self.issued_at, "ticket issue time")
        _require_aware_utc(self.expires_at, "ticket expiry")
        if self.expires_at <= self.issued_at:
            raise PrivilegedError("privileged ticket must expire after issue")
        if self.expires_at.timestamp() - self.issued_at.timestamp() > 300:
            raise PrivilegedError("privileged ticket pre-accept lifetime is too long")
        if self.integrity_algorithm not in {"ed25519", "hmac-sha256"}:
            raise PrivilegedError("privileged ticket integrity algorithm is unsupported")
        if not 32 <= len(self.integrity_proof) <= 512 or not self.integrity_proof.isascii():
            raise PrivilegedError("privileged ticket integrity proof is invalid")

    @property
    def unsigned_payload_sha256(self) -> str:
        values = asdict(self)
        del values["integrity_proof"]
        return canonical_sha256(values)

    @property
    def ticket_sha256(self) -> str:
        return canonical_sha256(asdict(self))

    def to_wire(self) -> dict[str, object]:
        """Return the exact bounded JSON representation signed by the application."""

        document = _canonical(asdict(self))
        if not isinstance(document, dict):  # pragma: no cover - dataclass invariant.
            raise PrivilegedError("privileged ticket wire document is invalid")
        return {str(key): item for key, item in document.items()} | {
            "ticket_sha256": self.ticket_sha256
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> PrivilegedTicket:
        expected = {
            "operation_id",
            "ticket_id",
            "ticket_sha256",
            "nonce",
            "controller_identity_sha256",
            "device_id",
            "device_epoch",
            "operation_contract",
            "operation_contract_version",
            "broker_profile_id",
            "broker_profile_version",
            "broker_profile_sha256",
            "action",
            "target_profile_id",
            "target_profile_sha256",
            "request_fingerprint_sha256",
            "maximum_effect",
            "current_state_binding_sha256",
            "policy_evidence_reference",
            "policy_evidence_sha256",
            "application_build_sha256",
            "application_config_sha256",
            "application_policy_sha256",
            "operation_specific_evidence_sha256",
            "issued_at",
            "expires_at",
            "integrity_algorithm",
            "integrity_proof",
        }
        if set(value) != expected:
            raise PrivilegedError("privileged ticket wire fields are not exact")
        try:
            ticket = cls(
                operation_id=_wire_text(value, "operation_id"),
                ticket_id=_wire_text(value, "ticket_id"),
                nonce=_wire_text(value, "nonce"),
                controller_identity_sha256=_wire_text(value, "controller_identity_sha256"),
                device_id=_wire_text(value, "device_id"),
                device_epoch=_wire_integer(value, "device_epoch"),
                operation_contract=_wire_text(value, "operation_contract"),
                operation_contract_version=_wire_text(value, "operation_contract_version"),
                broker_profile_id=_wire_text(value, "broker_profile_id"),
                broker_profile_version=_wire_text(value, "broker_profile_version"),
                broker_profile_sha256=_wire_text(value, "broker_profile_sha256"),
                action=PrivilegedAction(_wire_text(value, "action")),
                target_profile_id=_wire_text(value, "target_profile_id"),
                target_profile_sha256=_wire_text(value, "target_profile_sha256"),
                request_fingerprint_sha256=_wire_text(value, "request_fingerprint_sha256"),
                maximum_effect=PrivilegedMaximumEffect(_wire_text(value, "maximum_effect")),
                current_state_binding_sha256=_wire_text(value, "current_state_binding_sha256"),
                policy_evidence_reference=_wire_text(value, "policy_evidence_reference"),
                policy_evidence_sha256=_wire_text(value, "policy_evidence_sha256"),
                application_build_sha256=_wire_text(value, "application_build_sha256"),
                application_config_sha256=_wire_text(value, "application_config_sha256"),
                application_policy_sha256=_wire_text(value, "application_policy_sha256"),
                operation_specific_evidence_sha256=_wire_text(
                    value, "operation_specific_evidence_sha256"
                ),
                issued_at=_wire_timestamp(value, "issued_at"),
                expires_at=_wire_timestamp(value, "expires_at"),
                integrity_algorithm=_wire_text(value, "integrity_algorithm"),
                integrity_proof=_wire_text(value, "integrity_proof"),
            )
        except ValueError as exc:
            raise PrivilegedError("privileged ticket wire enum is invalid") from exc
        if _wire_text(value, "ticket_sha256") != ticket.ticket_sha256:
            raise PrivilegedError("privileged ticket wire digest does not match")
        return ticket

    @property
    def routing_identity(self) -> PrivilegedTicketRoutingIdentity:
        return PrivilegedTicketRoutingIdentity(
            operation_id=self.operation_id,
            ticket_id=self.ticket_id,
            ticket_sha256=self.ticket_sha256,
            ticket_nonce_sha256=hashlib.sha256(bytes.fromhex(self.nonce)).hexdigest(),
            action=self.action,
            target_profile_id=self.target_profile_id,
            target_profile_sha256=self.target_profile_sha256,
            broker_profile_sha256=self.broker_profile_sha256,
            request_fingerprint_sha256=self.request_fingerprint_sha256,
            current_state_binding_sha256=self.current_state_binding_sha256,
            policy_evidence_sha256=self.policy_evidence_sha256,
            issued_at=self.issued_at,
            expires_at=self.expires_at,
        )


@dataclass(frozen=True, slots=True)
class PrivilegedTicketRoutingIdentity:
    """Complete immutable broker correlation without the reusable raw nonce."""

    operation_id: str
    ticket_id: str
    ticket_sha256: str
    ticket_nonce_sha256: str
    action: PrivilegedAction
    target_profile_id: str
    target_profile_sha256: str
    broker_profile_sha256: str
    request_fingerprint_sha256: str
    current_state_binding_sha256: str
    policy_evidence_sha256: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_ticket_id(self.operation_id, "operation")
        _require_ticket_id(self.ticket_id, "ticket")
        _require_id(self.target_profile_id, "target profile")
        if not self.action.consequential or self.action is PrivilegedAction.HOST_REBOOT:
            raise PrivilegedError("routing identity action is not promoted")
        for name, value in (
            ("ticket", self.ticket_sha256),
            ("ticket nonce", self.ticket_nonce_sha256),
            ("target profile", self.target_profile_sha256),
            ("broker profile", self.broker_profile_sha256),
            ("request fingerprint", self.request_fingerprint_sha256),
            ("current state binding", self.current_state_binding_sha256),
            ("policy evidence", self.policy_evidence_sha256),
        ):
            _require_sha256(value, name)
        _require_aware_utc(self.issued_at, "ticket issue time")
        _require_aware_utc(self.expires_at, "ticket expiry")
        if self.expires_at <= self.issued_at:
            raise PrivilegedError("routing identity expiry must follow issue time")


@dataclass(frozen=True, slots=True)
class BrokerBindingSnapshot:
    identity: PrivilegedTicketRoutingIdentity
    acceptance_state: BrokerAcceptanceState
    evidence_generation: int
    acceptance_evidence_sha256: str | None
    execution_state: BrokerExecutionState
    effect_knowledge: PrivilegedEffectKnowledge
    result_evidence_sha256: str | None
    accepted_at: datetime | None
    sealed_at: datetime | None
    closed_at: datetime | None
    last_reconciled_at: datetime | None
    restart_checkpoint_sha256: str | None = None
    restart_checkpoint_state: BrokerRestartCheckpointState | None = None
    restart_outcome: BrokerRestartOutcome | None = None
    candidate_slot_id: str | None = None
    lkg_slot_id: str | None = None
    selected_runtime_slot_id: str | None = None
    service_restart_outcome: BrokerServiceRestartOutcome | None = None
    service_readiness_evidence_sha256: str | None = None
    lkg_promotion_audit_sha256: str | None = None
    lkg_promotion_evidence_sha256: str | None = None
    lkg_promoted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.evidence_generation < 0:
            raise PrivilegedError("broker binding evidence generation is invalid")
        unresolved = self.acceptance_state is BrokerAcceptanceState.UNRESOLVED
        accepted = self.acceptance_state is BrokerAcceptanceState.ACCEPTED
        sealed = self.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT
        if unresolved != (
            self.evidence_generation == 0
            and self.acceptance_evidence_sha256 is None
            and self.accepted_at is None
            and self.sealed_at is None
        ):
            raise PrivilegedError("unresolved broker binding evidence is contradictory")
        if accepted != (self.accepted_at is not None and self.sealed_at is None):
            raise PrivilegedError("accepted broker binding evidence is contradictory")
        if sealed != (self.sealed_at is not None and self.accepted_at is None):
            raise PrivilegedError("sealed broker binding evidence is contradictory")
        if not unresolved:
            if self.evidence_generation < 1 or self.acceptance_evidence_sha256 is None:
                raise PrivilegedError("decided broker binding lacks evidence")
            _require_sha256(self.acceptance_evidence_sha256, "broker acceptance evidence")
        if unresolved != (self.execution_state is BrokerExecutionState.NOT_ACCEPTED):
            raise PrivilegedError("broker acceptance and execution states disagree")
        if sealed and not (
            self.execution_state is BrokerExecutionState.TERMINAL
            and self.effect_knowledge is PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
        ):
            raise PrivilegedError("sealed broker binding has contradictory effect truth")
        expected = {
            BrokerExecutionState.NOT_ACCEPTED: (PrivilegedEffectKnowledge.NONE, False),
            BrokerExecutionState.ACCEPTED_PRE_EFFECT: (PrivilegedEffectKnowledge.NONE, False),
            BrokerExecutionState.EXECUTING: (PrivilegedEffectKnowledge.KNOWN_EFFECT, False),
            BrokerExecutionState.RECONCILING: (PrivilegedEffectKnowledge.KNOWN_EFFECT, False),
            BrokerExecutionState.TERMINAL: (None, True),
            BrokerExecutionState.UNCERTAIN: (PrivilegedEffectKnowledge.UNCERTAIN, False),
            BrokerExecutionState.RESTRICTED_RECOVERY: (
                PrivilegedEffectKnowledge.UNCERTAIN,
                False,
            ),
        }[self.execution_state]
        expected_knowledge, terminal = expected
        if expected_knowledge is not None and self.effect_knowledge is not expected_knowledge:
            raise PrivilegedError("broker execution effect knowledge is contradictory")
        if terminal != (self.closed_at is not None):
            raise PrivilegedError("broker execution closure is contradictory")
        if terminal or self.execution_state in {
            BrokerExecutionState.UNCERTAIN,
            BrokerExecutionState.RESTRICTED_RECOVERY,
        }:
            if self.result_evidence_sha256 is None:
                raise PrivilegedError("broker execution result evidence is absent")
            _require_sha256(self.result_evidence_sha256, "broker execution result")
        elif self.result_evidence_sha256 is not None:
            raise PrivilegedError("open broker execution carries terminal result evidence")
        if self.execution_state is BrokerExecutionState.TERMINAL and self.effect_knowledge not in {
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT,
            PrivilegedEffectKnowledge.KNOWN_EFFECT,
        }:
            raise PrivilegedError("terminal broker execution effect truth is invalid")
        service_terminal = (
            self.identity.action is PrivilegedAction.SERVICE_RESTART
            and self.acceptance_state is BrokerAcceptanceState.ACCEPTED
            and self.execution_state is BrokerExecutionState.TERMINAL
        )
        if service_terminal != (self.service_restart_outcome is not None):
            raise PrivilegedError("service restart terminal outcome is incomplete")
        if self.service_readiness_evidence_sha256 is not None:
            _require_sha256(
                self.service_readiness_evidence_sha256,
                "service restart readiness evidence",
            )
        if service_terminal:
            if self.service_restart_outcome is BrokerServiceRestartOutcome.SERVICE_READY:
                if (
                    self.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_EFFECT
                    or self.service_readiness_evidence_sha256 is None
                ):
                    raise PrivilegedError("ready service restart lacks readiness evidence")
            elif self.service_restart_outcome is BrokerServiceRestartOutcome.FAILED:
                if (
                    self.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_EFFECT
                    or self.service_readiness_evidence_sha256 is None
                ):
                    raise PrivilegedError("failed service restart lacks verification evidence")
            elif self.service_restart_outcome is BrokerServiceRestartOutcome.NO_SUBEFFECT and (
                self.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
                or self.service_readiness_evidence_sha256 is not None
            ):
                raise PrivilegedError("no-subeffect service restart carries readiness evidence")
            elif self.service_restart_outcome is not BrokerServiceRestartOutcome.NO_SUBEFFECT:
                raise PrivilegedError("service restart terminal outcome is invalid")
        elif self.service_readiness_evidence_sha256 is not None:
            raise PrivilegedError("nonterminal service restart carries readiness evidence")
        restart_values = (
            self.restart_checkpoint_state,
            self.restart_outcome,
            self.candidate_slot_id,
            self.lkg_slot_id,
        )
        has_restart = self.restart_checkpoint_sha256 is not None
        if has_restart != all(value is not None for value in restart_values):
            raise PrivilegedError("broker restart checkpoint projection is incomplete")
        promotion_values = (
            self.lkg_promotion_audit_sha256,
            self.lkg_promotion_evidence_sha256,
            self.lkg_promoted_at,
        )
        if any(value is not None for value in promotion_values) != all(
            value is not None for value in promotion_values
        ):
            raise PrivilegedError("broker LKG promotion projection is incomplete")
        if not has_restart:
            if self.selected_runtime_slot_id is not None or any(
                value is not None for value in promotion_values
            ):
                raise PrivilegedError("broker binding selects a slot without a checkpoint")
            return
        restart_checkpoint_sha256 = self.restart_checkpoint_sha256
        restart_checkpoint_state = self.restart_checkpoint_state
        restart_outcome = self.restart_outcome
        candidate_slot_id = self.candidate_slot_id
        lkg_slot_id = self.lkg_slot_id
        if (
            restart_checkpoint_sha256 is None
            or restart_checkpoint_state is None
            or restart_outcome is None
            or candidate_slot_id is None
            or lkg_slot_id is None
        ):
            raise PrivilegedError("broker restart checkpoint projection is incomplete")
        _require_sha256(restart_checkpoint_sha256, "restart checkpoint")
        _require_ticket_id(candidate_slot_id, "candidate slot")
        _require_ticket_id(lkg_slot_id, "LKG slot")
        if self.identity.action is not PrivilegedAction.CONTROLLED_RESTART:
            raise PrivilegedError("non-controlled broker binding carries a restart checkpoint")
        if candidate_slot_id == lkg_slot_id:
            raise PrivilegedError("broker checkpoint candidate and LKG slots are identical")
        if self.selected_runtime_slot_id is not None:
            _require_ticket_id(self.selected_runtime_slot_id, "selected runtime slot")
            if self.selected_runtime_slot_id not in {
                candidate_slot_id,
                lkg_slot_id,
            }:
                raise PrivilegedError("broker checkpoint selected an unbound runtime slot")
        expected_outcome = {
            BrokerRestartCheckpointState.TERMINAL: {
                BrokerRestartOutcome.CANDIDATE_READY,
                BrokerRestartOutcome.ROLLBACK_READY,
                BrokerRestartOutcome.NO_SUBEFFECT,
                BrokerRestartOutcome.FAILED,
            },
            BrokerRestartCheckpointState.UNCERTAIN: {BrokerRestartOutcome.UNCERTAIN},
            BrokerRestartCheckpointState.RESTRICTED_RECOVERY: {
                BrokerRestartOutcome.RESTRICTED_RECOVERY
            },
        }.get(restart_checkpoint_state, {BrokerRestartOutcome.PENDING})
        if restart_outcome not in expected_outcome:
            raise PrivilegedError("broker restart state and outcome disagree")
        if restart_checkpoint_state is BrokerRestartCheckpointState.TERMINAL and (
            self.execution_state is not BrokerExecutionState.TERMINAL
        ):
            raise PrivilegedError("terminal restart checkpoint has an open broker binding")
        if restart_checkpoint_state is BrokerRestartCheckpointState.UNCERTAIN and (
            self.execution_state is not BrokerExecutionState.UNCERTAIN
        ):
            raise PrivilegedError("uncertain restart checkpoint has different broker truth")
        if restart_checkpoint_state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY and (
            self.execution_state is not BrokerExecutionState.RESTRICTED_RECOVERY
        ):
            raise PrivilegedError("restricted restart checkpoint has different broker truth")
        if restart_outcome is BrokerRestartOutcome.CANDIDATE_READY and (
            self.selected_runtime_slot_id != candidate_slot_id
        ):
            raise PrivilegedError("candidate-ready restart did not select the candidate slot")
        if restart_outcome is BrokerRestartOutcome.ROLLBACK_READY and (
            self.selected_runtime_slot_id != lkg_slot_id
        ):
            raise PrivilegedError("rollback-ready restart did not select the LKG slot")
        if restart_outcome is BrokerRestartOutcome.NO_SUBEFFECT and (
            self.selected_runtime_slot_id is not None
            or self.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
        ):
            raise PrivilegedError("no-subeffect restart carries contradictory effect truth")
        promotion_audit_sha256 = self.lkg_promotion_audit_sha256
        promotion_evidence_sha256 = self.lkg_promotion_evidence_sha256
        promoted_at = self.lkg_promoted_at
        if promotion_evidence_sha256 is not None:
            if promotion_audit_sha256 is None or promoted_at is None:
                raise PrivilegedError("broker LKG promotion projection is incomplete")
            _require_sha256(promotion_audit_sha256, "LKG promotion audit")
            _require_sha256(promotion_evidence_sha256, "LKG promotion evidence")
            if (
                restart_outcome is not BrokerRestartOutcome.CANDIDATE_READY
                or self.execution_state is not BrokerExecutionState.TERMINAL
                or self.closed_at is None
                or promoted_at < self.closed_at
            ):
                raise PrivilegedError("broker LKG promotion truth is contradictory")
        elif restart_outcome is not BrokerRestartOutcome.CANDIDATE_READY and any(
            value is not None for value in promotion_values
        ):
            raise PrivilegedError("non-candidate restart carries LKG promotion evidence")


@dataclass(frozen=True, slots=True)
class BrokerAcceptanceReceipt:
    operation_id: str
    ticket_id: str
    ticket_sha256: str
    disposition: BrokerAcceptanceDisposition
    evidence_generation: int
    effect_knowledge: PrivilegedEffectKnowledge
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_ticket_id(self.operation_id, "operation")
        _require_ticket_id(self.ticket_id, "ticket")
        _require_sha256(self.ticket_sha256, "ticket")
        _require_sha256(self.evidence_sha256, "broker acceptance evidence")
        if self.evidence_generation < 1:
            raise PrivilegedError("broker evidence generation must be positive")
        expected_knowledge = {
            BrokerAcceptanceDisposition.ACCEPTED: PrivilegedEffectKnowledge.KNOWN_EFFECT,
            BrokerAcceptanceDisposition.RETAINED_ACCEPTED: PrivilegedEffectKnowledge.KNOWN_EFFECT,
            BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN: (
                PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            ),
            BrokerAcceptanceDisposition.CONFLICT: PrivilegedEffectKnowledge.NONE,
        }
        if self.effect_knowledge is not expected_knowledge[self.disposition]:
            raise PrivilegedError("broker acceptance receipt effect truth is contradictory")

    @property
    def receipt_sha256(self) -> str:
        return canonical_sha256(asdict(self))


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_timestamp(value: datetime) -> str:
    _require_aware_utc(value, "canonical timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, tuple | list):
        return [_canonical(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    raise TypeError(f"unsupported canonical privileged value: {type(value)!r}")


def _require_id(value: str, name: str) -> None:
    if _ID_RE.fullmatch(value) is None:
        raise PrivilegedError(f"{name} identity is invalid")


def _require_ticket_id(value: str, name: str) -> None:
    if _TICKET_ID_RE.fullmatch(value) is None:
        raise PrivilegedError(f"{name} identity is invalid")


def _require_sha256(value: str, name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise PrivilegedError(f"{name} must be a lowercase SHA-256 digest")


def _require_absolute_path(value: str, name: str) -> None:
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "\0" in value
        or "\n" in value
    ):
        raise PrivilegedError(f"{name} must be canonical absolute POSIX form")


def _require_aware_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedError(f"{name} must be timezone-aware")


def _wire_text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise PrivilegedError(f"privileged ticket {name} must be text")
    return result


def _wire_integer(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise PrivilegedError(f"privileged ticket {name} must be an integer")
    return result


def _wire_timestamp(value: Mapping[str, object], name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_wire_text(value, name))
    except ValueError as exc:
        raise PrivilegedError(f"privileged ticket {name} must be a timestamp") from exc
    _require_aware_utc(result, f"privileged ticket {name}")
    return result


__all__ = [
    "MAX_PRIVILEGED_FRAME_BYTES",
    "PRIVILEGED_PROTOCOL_ID",
    "PRIVILEGED_PROTOCOL_VERSION",
    "BinnacleServiceProfile",
    "BrokerAcceptanceDisposition",
    "BrokerAcceptanceReceipt",
    "BrokerAcceptanceState",
    "BrokerBindingSnapshot",
    "BrokerExecutionState",
    "BrokerNoAcceptReason",
    "BrokerRestartCheckpointState",
    "BrokerRestartOutcome",
    "BrokerServiceRestartOutcome",
    "PackageProfile",
    "PrivilegedAction",
    "PrivilegedBrokerHello",
    "PrivilegedBrokerProfile",
    "PrivilegedEffectKnowledge",
    "PrivilegedError",
    "PrivilegedMaximumEffect",
    "PrivilegedTicket",
    "PrivilegedTicketRoutingIdentity",
    "canonical_sha256",
]

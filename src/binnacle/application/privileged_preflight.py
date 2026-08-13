"""Read-only Phase 9 runtime-identity and restart-preflight projection."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.privileged import canonical_sha256
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightReason,
    RestartPreflightResult,
    RuntimeIdentity,
    RuntimeSlotRole,
    RuntimeSlotState,
    ServiceInspectionResult,
    SourceDirtyState,
    VerifiedRuntimeSlot,
)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_OUTSTANDING: Final = 100_000


class PrivilegedPreflightError(RuntimeError):
    """Runtime or preflight evidence is malformed, stale, or contradictory."""


@dataclass(frozen=True, slots=True)
class RuntimeIdentityEvidence:
    source_git_oid: str
    source_dirty_state: SourceDirtyState
    source_state_sha256: str
    workspace_identity_sha256: str
    workspace_mount_identity_sha256: str
    python_executable: str
    python_version: str
    environment_root: str
    environment_sha256: str
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
    service_main_pid: int
    readiness_main_pid: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            not 1 <= self.service_main_pid <= 2_147_483_647
            or self.readiness_main_pid != self.service_main_pid
        ):
            raise PrivilegedPreflightError("runtime service and readiness PIDs disagree")
        _require_aware(self.process_started_at)
        _require_aware(self.observed_at)
        if self.process_started_at > self.observed_at:
            raise PrivilegedPreflightError("runtime process starts after its observation")


class RuntimeIdentityBuilder:
    """Build exact runtime identity and bind complete slot evidence when supplied."""

    def build(
        self,
        evidence: RuntimeIdentityEvidence,
        *,
        slot: VerifiedRuntimeSlot | None,
    ) -> RuntimeIdentity:
        if slot is not None:
            if slot.state not in {RuntimeSlotState.ACTIVE, RuntimeSlotState.LKG}:
                raise PrivilegedPreflightError("runtime slot is not active or LKG")
            if evidence.source_dirty_state is not SourceDirtyState.CLEAN:
                raise PrivilegedPreflightError("slot-backed runtime source is dirty")
            expected = (
                slot.source_sha256,
                slot.environment_sha256,
                slot.config_sha256,
                slot.policy_sha256,
                slot.manifest_sha256,
                slot.migration_heads_sha256,
                slot.layout_sha256,
                slot.deployed_peer_set_sha256,
            )
            observed = (
                evidence.source_state_sha256,
                evidence.environment_sha256,
                evidence.config_sha256,
                evidence.policy_sha256,
                evidence.manifest_sha256,
                evidence.schema_heads_sha256,
                evidence.runtime_layout_sha256,
                evidence.deployed_peer_set_sha256,
            )
            if observed != expected:
                raise PrivilegedPreflightError("runtime identity differs from its complete slot")
        try:
            return RuntimeIdentity(
                source_git_oid=evidence.source_git_oid,
                source_dirty_state=evidence.source_dirty_state,
                source_state_sha256=evidence.source_state_sha256,
                workspace_identity_sha256=evidence.workspace_identity_sha256,
                workspace_mount_identity_sha256=evidence.workspace_mount_identity_sha256,
                python_executable=evidence.python_executable,
                python_version=evidence.python_version,
                environment_root=evidence.environment_root,
                environment_sha256=evidence.environment_sha256,
                runtime_slot_identity_sha256=(None if slot is None else slot.slot_identity_sha256),
                lock_sha256=evidence.lock_sha256,
                build_sha256=evidence.build_sha256,
                config_sha256=evidence.config_sha256,
                policy_sha256=evidence.policy_sha256,
                manifest_sha256=evidence.manifest_sha256,
                service_profile_sha256=evidence.service_profile_sha256,
                device_id=evidence.device_id,
                device_epoch=evidence.device_epoch,
                runtime_instance_id=evidence.runtime_instance_id,
                process_started_at=evidence.process_started_at,
                readiness_generation=evidence.readiness_generation,
                schema_heads_sha256=evidence.schema_heads_sha256,
                runtime_layout_sha256=evidence.runtime_layout_sha256,
                deployed_peer_set_sha256=evidence.deployed_peer_set_sha256,
            )
        except ValueError as exc:
            raise PrivilegedPreflightError("runtime identity evidence is invalid") from exc


@dataclass(frozen=True, slots=True)
class RestartOutstandingFacts:
    operation_state_sha256: str
    command_state_sha256: str
    workspace_fence_sha256: str
    git_state_sha256: str
    credential_state_sha256: str
    privileged_state_sha256: str
    audit_state_sha256: str
    blocking_operation_count: int
    uncertain_operation_count: int
    open_command_count: int
    non_survivable_command_count: int
    source_changer_count: int
    open_git_effect_count: int
    open_credential_effect_count: int
    open_privileged_effect_count: int
    workspace_fence_held: bool
    package_mutation_open: bool
    prior_restart_unresolved: bool
    source_mutation_uncertain: bool
    audit_healthy: bool
    schema_heads_match: bool
    deployed_peer_set_matches: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        for value in (
            self.operation_state_sha256,
            self.command_state_sha256,
            self.workspace_fence_sha256,
            self.git_state_sha256,
            self.credential_state_sha256,
            self.privileged_state_sha256,
            self.audit_state_sha256,
        ):
            _require_sha256(value)
        counts = (
            self.blocking_operation_count,
            self.uncertain_operation_count,
            self.open_command_count,
            self.non_survivable_command_count,
            self.source_changer_count,
            self.open_git_effect_count,
            self.open_credential_effect_count,
            self.open_privileged_effect_count,
        )
        if any(not 0 <= value <= _MAX_OUTSTANDING for value in counts):
            raise PrivilegedPreflightError("restart outstanding count is outside the limit")
        if max(self.source_changer_count, self.non_survivable_command_count) > (
            self.open_command_count
        ):
            raise PrivilegedPreflightError("restart command counts are contradictory")
        _require_aware(self.observed_at)

    @property
    def outstanding_state_sha256(self) -> str:
        return canonical_sha256(asdict(self))


class RestartPreflightEvaluator:
    """Evaluate advisory point-in-time facts; this never reserves or authorizes restart."""

    def inspect(
        self,
        *,
        kind: RestartPreflightKind,
        facts: RestartOutstandingFacts,
        service: ServiceInspectionResult,
        runtime: RuntimeIdentity | None,
        lkg_slot: VerifiedRuntimeSlot | None = None,
        candidate_slot: VerifiedRuntimeSlot | None = None,
        candidate_verification_sha256: str | None = None,
        candidate_verification_fresh: bool = False,
        candidate_tested_state_matches: bool = False,
        observed_at: datetime,
    ) -> RestartPreflightResult:
        _require_aware(observed_at)
        if facts.observed_at > observed_at or service.observed_at > observed_at:
            raise PrivilegedPreflightError("restart preflight uses observations from the future")
        if candidate_verification_sha256 is not None:
            _require_sha256(candidate_verification_sha256)

        reasons: set[RestartPreflightReason] = set()
        if not facts.audit_healthy:
            reasons.add(RestartPreflightReason.AUDIT_UNAVAILABLE)
        _count_reason(
            facts.blocking_operation_count,
            RestartPreflightReason.BLOCKING_OPERATION,
            reasons,
        )
        _count_reason(
            facts.uncertain_operation_count,
            RestartPreflightReason.UNCERTAIN_OPERATION,
            reasons,
        )
        _count_reason(
            facts.non_survivable_command_count,
            RestartPreflightReason.COMMAND_EXECUTION_UNSAFE,
            reasons,
        )
        _count_reason(
            facts.source_changer_count,
            RestartPreflightReason.SOURCE_CHANGER_OPEN,
            reasons,
        )
        _count_reason(facts.open_git_effect_count, RestartPreflightReason.GIT_EFFECT_OPEN, reasons)
        _count_reason(
            facts.open_credential_effect_count,
            RestartPreflightReason.CREDENTIAL_EFFECT_OPEN,
            reasons,
        )
        _count_reason(
            facts.open_privileged_effect_count,
            RestartPreflightReason.PRIVILEGED_EFFECT_OPEN,
            reasons,
        )
        if facts.workspace_fence_held:
            reasons.add(RestartPreflightReason.WORKSPACE_FENCE_HELD)
        if facts.package_mutation_open:
            reasons.add(RestartPreflightReason.PACKAGE_MUTATION_OPEN)
        if facts.prior_restart_unresolved:
            reasons.add(RestartPreflightReason.PRIOR_RESTART_UNRESOLVED)
        if facts.source_mutation_uncertain:
            reasons.add(RestartPreflightReason.SOURCE_MUTATION_UNCERTAIN)
        if runtime is None:
            reasons.add(RestartPreflightReason.CURRENT_RUNTIME_UNAVAILABLE)
        if service.application_ready is not True or (
            runtime is not None
            and service.runtime_identity_sha256 != runtime.runtime_identity_sha256
        ):
            reasons.add(RestartPreflightReason.SERVICE_NOT_READY)
        if not facts.schema_heads_match:
            reasons.add(RestartPreflightReason.SCHEMA_HEAD_MISMATCH)
        if not facts.deployed_peer_set_matches:
            reasons.add(RestartPreflightReason.PEER_SET_MISMATCH)

        controlled = kind is RestartPreflightKind.CONTROLLED_SELF
        if controlled:
            if runtime is not None and runtime.runtime_slot_identity_sha256 is None:
                reasons.add(RestartPreflightReason.CURRENT_RUNTIME_UNAVAILABLE)
            if (
                lkg_slot is None
                or lkg_slot.role is not RuntimeSlotRole.LKG
                or lkg_slot.state is not RuntimeSlotState.LKG
            ):
                reasons.add(RestartPreflightReason.LKG_UNAVAILABLE)
            if candidate_verification_sha256 is None or candidate_slot is None:
                reasons.add(RestartPreflightReason.CANDIDATE_VERIFICATION_MISSING)
            elif (
                candidate_slot.role is not RuntimeSlotRole.CANDIDATE
                or candidate_slot.state is not RuntimeSlotState.COMPLETE
            ):
                reasons.add(RestartPreflightReason.CANDIDATE_TESTED_STATE_MISMATCH)
            if candidate_verification_sha256 is not None and not candidate_verification_fresh:
                reasons.add(RestartPreflightReason.CANDIDATE_VERIFICATION_STALE)
            if candidate_verification_sha256 is not None and not candidate_tested_state_matches:
                reasons.add(RestartPreflightReason.CANDIDATE_TESTED_STATE_MISMATCH)

        impacts = {
            RestartImpact.APPLICATION_PROCESS_REPLACED,
            RestartImpact.CONNECTION_INTERRUPTED,
        }
        if controlled:
            impacts.update({RestartImpact.RUNTIME_SELECTOR_CHANGED, RestartImpact.ROLLBACK_MAY_RUN})
        current_runtime_sha256 = None if runtime is None else runtime.runtime_identity_sha256
        lkg_sha256 = None if not controlled or lkg_slot is None else lkg_slot.slot_identity_sha256
        candidate_sha256 = (
            None
            if not controlled or candidate_slot is None
            else candidate_slot.slot_identity_sha256
        )
        verification_sha256 = candidate_verification_sha256 if controlled else None
        state_binding = canonical_sha256(
            {
                "candidate_slot_identity_sha256": candidate_sha256,
                "candidate_verification_sha256": verification_sha256,
                "current_runtime_identity_sha256": current_runtime_sha256,
                "current_service_observation_sha256": service.observation_sha256,
                "kind": kind,
                "lkg_slot_identity_sha256": lkg_sha256,
                "outstanding_state_sha256": facts.outstanding_state_sha256,
            }
        )
        try:
            return RestartPreflightResult(
                kind=kind,
                available=not reasons,
                reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
                predicted_impacts=tuple(sorted(impacts, key=lambda item: item.value)),
                current_runtime_identity_sha256=current_runtime_sha256,
                current_service_observation_sha256=service.observation_sha256,
                lkg_slot_identity_sha256=lkg_sha256,
                candidate_slot_identity_sha256=candidate_sha256,
                candidate_verification_sha256=verification_sha256,
                outstanding_state_sha256=facts.outstanding_state_sha256,
                state_binding_sha256=state_binding,
                observed_at=observed_at,
            )
        except ValueError as exc:
            raise PrivilegedPreflightError("restart preflight result is contradictory") from exc


def _count_reason(
    value: int,
    reason: RestartPreflightReason,
    reasons: set[RestartPreflightReason],
) -> None:
    if value:
        reasons.add(reason)


def _require_sha256(value: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise PrivilegedPreflightError("restart evidence digest is invalid")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedPreflightError("restart timestamp must be timezone-aware")


__all__ = [
    "PrivilegedPreflightError",
    "RestartOutstandingFacts",
    "RestartPreflightEvaluator",
    "RuntimeIdentityBuilder",
    "RuntimeIdentityEvidence",
]

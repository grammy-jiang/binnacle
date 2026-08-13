"""Application-side Phase 9 restart admission and retained evidence values."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from binnacle.domain.idempotency import owner_digest
from binnacle.domain.operation import OperationSnapshot, OperationState
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.privileged import (
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedMaximumEffect,
    PrivilegedTicket,
    canonical_sha256,
)
from binnacle.domain.privileged_observation import (
    RestartPreflightKind,
    RestartPreflightResult,
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE: Final = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
_PROFILE_RE: Final = re.compile(r"[a-z][a-z0-9._-]{0,95}\Z")


class PrivilegedRestartError(ValueError):
    """Restart admission evidence is malformed, stale, or contradictory."""


class PrivilegedPreparationState(StrEnum):
    AVAILABLE = "available"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class PrivilegedOperationState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    RECONCILING = "reconciling"
    TERMINAL = "terminal"
    UNCERTAIN = "uncertain"
    RESTRICTED_RECOVERY = "restricted_recovery"


class PrivilegedReservationState(StrEnum):
    HELD = "held"
    RELEASED = "released"
    UNCERTAIN = "uncertain"
    RESTRICTED_RECOVERY = "restricted_recovery"


_RESTART_EFFECT: Final = {
    PrivilegedAction.SERVICE_RESTART: PrivilegedMaximumEffect.SERVICE_RESTART,
    PrivilegedAction.CONTROLLED_RESTART: PrivilegedMaximumEffect.CONTROLLED_RESTART,
}
_RESTART_CONTRACT: Final = {
    PrivilegedAction.SERVICE_RESTART: "binnacle_service_restart",
    PrivilegedAction.CONTROLLED_RESTART: "binnacle_restart",
}


@dataclass(frozen=True, slots=True)
class PrivilegedRestartPreparation:
    prepare_operation_id: str
    session_id: str
    workspace_id: str
    action: PrivilegedAction
    target_profile_id: str
    target_profile_sha256: str
    maximum_effect: PrivilegedMaximumEffect
    normalized_request_sha256: str
    current_state_binding_sha256: str
    prepared_evidence_sha256: str
    execution_nonce_sha256: str
    service_profile_sha256: str
    candidate_verification_reference: str
    candidate_verification_sha256: str
    candidate_slot_id: str | None
    lkg_slot_id: str
    schema_heads_sha256: str
    runtime_layout_sha256: str
    deployed_peer_set_sha256: str
    state: PrivilegedPreparationState
    consumed_by_operation_id: str | None
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.prepare_operation_id, "prepare operation"),
            (self.session_id, "development session"),
            (self.workspace_id, "workspace"),
            (self.candidate_verification_reference, "candidate verification reference"),
            (self.lkg_slot_id, "LKG slot"),
        ):
            _require_identity(value, name)
        _require_profile(self.target_profile_id, "target profile")
        for value, name in (
            (self.target_profile_sha256, "target profile"),
            (self.normalized_request_sha256, "normalized restart request"),
            (self.current_state_binding_sha256, "restart current-state binding"),
            (self.prepared_evidence_sha256, "restart prepared evidence"),
            (self.execution_nonce_sha256, "restart execution nonce"),
            (self.service_profile_sha256, "restart service profile"),
            (self.candidate_verification_sha256, "candidate verification"),
            (self.schema_heads_sha256, "restart schema heads"),
            (self.runtime_layout_sha256, "restart runtime layout"),
            (self.deployed_peer_set_sha256, "restart deployed-peer set"),
        ):
            _require_sha256(value, name)
        if self.action not in _RESTART_EFFECT:
            raise PrivilegedRestartError("preparation is not a promoted restart action")
        if self.maximum_effect is not _RESTART_EFFECT[self.action]:
            raise PrivilegedRestartError("restart action and maximum effect disagree")
        controlled = self.action is PrivilegedAction.CONTROLLED_RESTART
        if controlled != (self.candidate_slot_id is not None):
            raise PrivilegedRestartError("restart candidate-slot shape differs from its action")
        if self.candidate_slot_id is not None:
            _require_identity(self.candidate_slot_id, "candidate slot")
            if self.candidate_slot_id == self.lkg_slot_id:
                raise PrivilegedRestartError("candidate and LKG slots must differ")
        for timestamp, name in (
            (self.created_at, "restart preparation creation"),
            (self.expires_at, "restart preparation expiry"),
            (self.updated_at, "restart preparation update"),
        ):
            _require_aware(timestamp, name)
        if not self.created_at < self.expires_at or self.updated_at < self.created_at:
            raise PrivilegedRestartError("restart preparation timestamps are contradictory")
        consumed = self.state is PrivilegedPreparationState.CONSUMED
        if consumed != (self.consumed_by_operation_id is not None and self.consumed_at is not None):
            raise PrivilegedRestartError("restart preparation consumption is contradictory")
        if self.consumed_by_operation_id is not None:
            _require_identity(self.consumed_by_operation_id, "restart consumer")
        if self.consumed_at is not None:
            _require_aware(self.consumed_at, "restart consumption")
            if self.consumed_at < self.created_at:
                raise PrivilegedRestartError("restart consumption precedes preparation")
        if self.state is not PrivilegedPreparationState.CONSUMED and (
            self.consumed_by_operation_id is not None or self.consumed_at is not None
        ):
            raise PrivilegedRestartError("unconsumed restart preparation has a consumer")


@dataclass(frozen=True, slots=True)
class PrivilegedRestartRecord:
    operation_id: str
    prepare_operation_id: str
    session_id: str
    workspace_id: str
    workspace_fence_version: int
    reservation_generation: int
    action: PrivilegedAction
    maximum_effect: PrivilegedMaximumEffect
    target_profile_id: str
    target_profile_sha256: str
    broker_profile_id: str
    broker_profile_sha256: str
    prepared_evidence_sha256: str
    current_state_binding_sha256: str
    policy_decision_id: str
    policy_evidence_sha256: str
    ticket_id: str
    ticket_sha256: str
    ticket_nonce_sha256: str
    ticket_issued_at: datetime
    ticket_expires_at: datetime
    broker_acceptance_state: BrokerAcceptanceState
    broker_evidence_generation: int
    broker_acceptance_evidence_sha256: str | None
    service_profile_sha256: str
    candidate_verification_reference: str
    candidate_verification_sha256: str
    candidate_slot_id: str | None
    lkg_slot_id: str
    schema_heads_sha256: str
    runtime_layout_sha256: str
    deployed_peer_set_sha256: str
    state: PrivilegedOperationState
    reservation_state: PrivilegedReservationState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "privileged operation"),
            (self.prepare_operation_id, "prepare operation"),
            (self.session_id, "development session"),
            (self.workspace_id, "workspace"),
            (self.policy_decision_id, "policy decision"),
            (self.ticket_id, "privileged ticket"),
            (self.candidate_verification_reference, "candidate verification reference"),
            (self.lkg_slot_id, "LKG slot"),
        ):
            _require_identity(value, name)
        _require_profile(self.target_profile_id, "target profile")
        _require_profile(self.broker_profile_id, "broker profile")
        for value, name in (
            (self.target_profile_sha256, "target profile"),
            (self.broker_profile_sha256, "broker profile"),
            (self.prepared_evidence_sha256, "prepared evidence"),
            (self.current_state_binding_sha256, "current-state binding"),
            (self.policy_evidence_sha256, "policy evidence"),
            (self.ticket_sha256, "privileged ticket"),
            (self.ticket_nonce_sha256, "privileged ticket nonce"),
            (self.service_profile_sha256, "service profile"),
            (self.candidate_verification_sha256, "candidate verification"),
            (self.schema_heads_sha256, "schema heads"),
            (self.runtime_layout_sha256, "runtime layout"),
            (self.deployed_peer_set_sha256, "deployed-peer set"),
        ):
            _require_sha256(value, name)
        if self.workspace_fence_version < 1 or self.reservation_generation < 1:
            raise PrivilegedRestartError("restart fence or reservation generation is invalid")
        if (
            self.action not in _RESTART_EFFECT
            or self.maximum_effect is not _RESTART_EFFECT[self.action]
        ):
            raise PrivilegedRestartError("retained restart action is invalid")
        if (self.action is PrivilegedAction.CONTROLLED_RESTART) != (
            self.candidate_slot_id is not None
        ):
            raise PrivilegedRestartError("retained restart candidate-slot shape differs")
        if self.candidate_slot_id is not None:
            _require_identity(self.candidate_slot_id, "candidate slot")
        for timestamp, name in (
            (self.ticket_issued_at, "ticket issue"),
            (self.ticket_expires_at, "ticket expiry"),
            (self.created_at, "restart creation"),
            (self.updated_at, "restart update"),
        ):
            _require_aware(timestamp, name)
        if not self.ticket_issued_at < self.ticket_expires_at:
            raise PrivilegedRestartError("retained restart ticket expiry is invalid")
        if self.broker_evidence_generation < 0:
            raise PrivilegedRestartError("broker evidence generation is invalid")
        unresolved = self.broker_acceptance_state is BrokerAcceptanceState.UNRESOLVED
        if unresolved != (
            self.broker_evidence_generation == 0 and self.broker_acceptance_evidence_sha256 is None
        ):
            raise PrivilegedRestartError("broker acceptance evidence is contradictory")
        if self.broker_acceptance_evidence_sha256 is not None:
            _require_sha256(
                self.broker_acceptance_evidence_sha256,
                "broker acceptance evidence",
            )
        expected_reservation = {
            PrivilegedOperationState.TERMINAL: PrivilegedReservationState.RELEASED,
            PrivilegedOperationState.UNCERTAIN: PrivilegedReservationState.UNCERTAIN,
            PrivilegedOperationState.RESTRICTED_RECOVERY: (
                PrivilegedReservationState.RESTRICTED_RECOVERY
            ),
        }.get(self.state, PrivilegedReservationState.HELD)
        if self.reservation_state is not expected_reservation:
            raise PrivilegedRestartError("restart reservation state differs from operation")


@dataclass(frozen=True, slots=True)
class PrivilegedRestartCheckpointIntent:
    """Exact application-signed inputs retained before a controlled root restart."""

    operation_id: str
    ticket_id: str
    ticket_sha256: str
    service_profile_sha256: str
    workspace_id: str
    workspace_fence_version: int
    preflight: RestartPreflightResult
    candidate_slot: VerifiedRuntimeSlot
    lkg_slot: VerifiedRuntimeSlot
    restart_deadline_seconds: int
    created_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "checkpoint operation"),
            (self.ticket_id, "checkpoint ticket"),
            (self.workspace_id, "checkpoint workspace"),
        ):
            _require_identity(value, name)
        for value, name in (
            (self.ticket_sha256, "checkpoint ticket"),
            (self.service_profile_sha256, "checkpoint service profile"),
        ):
            _require_sha256(value, name)
        _require_aware(self.created_at, "checkpoint creation")
        if self.workspace_fence_version < 1:
            raise PrivilegedRestartError("checkpoint workspace fence is invalid")
        if not 1 <= self.restart_deadline_seconds <= 900:
            raise PrivilegedRestartError("checkpoint restart deadline is invalid")
        if (
            self.preflight.kind is not RestartPreflightKind.CONTROLLED_SELF
            or not self.preflight.available
            or self.preflight.reason_codes
            or self.preflight.observed_at > self.created_at
        ):
            raise PrivilegedRestartError(
                "checkpoint preflight is not an available controlled restart"
            )
        if (
            self.candidate_slot.role is not RuntimeSlotRole.CANDIDATE
            or self.candidate_slot.state is not RuntimeSlotState.COMPLETE
            or self.lkg_slot.role is not RuntimeSlotRole.LKG
            or self.lkg_slot.state is not RuntimeSlotState.LKG
            or self.candidate_slot.slot_id == self.lkg_slot.slot_id
        ):
            raise PrivilegedRestartError("checkpoint candidate or LKG slot is ineligible")
        if (
            self.preflight.candidate_slot_identity_sha256
            != self.candidate_slot.slot_identity_sha256
            or self.preflight.lkg_slot_identity_sha256 != self.lkg_slot.slot_identity_sha256
            or self.preflight.candidate_verification_sha256
            != self.candidate_slot.candidate_verification_sha256
        ):
            raise PrivilegedRestartError("checkpoint slots differ from retained preflight")
        candidate_compatibility = (
            self.candidate_slot.config_sha256,
            self.candidate_slot.policy_sha256,
            self.candidate_slot.manifest_sha256,
            self.candidate_slot.service_definition_sha256,
            self.candidate_slot.deployed_peer_set_sha256,
            self.candidate_slot.migration_heads_sha256,
            self.candidate_slot.layout_sha256,
        )
        lkg_compatibility = (
            self.lkg_slot.config_sha256,
            self.lkg_slot.policy_sha256,
            self.lkg_slot.manifest_sha256,
            self.lkg_slot.service_definition_sha256,
            self.lkg_slot.deployed_peer_set_sha256,
            self.lkg_slot.migration_heads_sha256,
            self.lkg_slot.layout_sha256,
        )
        if candidate_compatibility != lkg_compatibility:
            raise PrivilegedRestartError(
                "checkpoint candidate and LKG generations are incompatible"
            )

    @property
    def intent_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class PrivilegedRestartCheckpointSnapshot:
    """Bounded root-owned checkpoint used for deterministic restart recovery."""

    intent: PrivilegedRestartCheckpointIntent
    checkpoint_sha256: str
    evidence_generation: int
    state: BrokerRestartCheckpointState
    outcome: BrokerRestartOutcome
    selected_slot_id: str | None
    result_evidence_sha256: str | None
    service_stopped_at: datetime | None
    closed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.checkpoint_sha256, "restart checkpoint")
        if self.evidence_generation < 1:
            raise PrivilegedRestartError("restart checkpoint generation is invalid")
        for timestamp, name in (
            (self.service_stopped_at, "restart service stop"),
            (self.closed_at, "restart checkpoint closure"),
        ):
            if timestamp is not None:
                _require_aware(timestamp, name)
        _require_aware(self.updated_at, "restart checkpoint update")
        if self.updated_at < self.intent.created_at:
            raise PrivilegedRestartError("restart checkpoint update time regressed")
        if self.result_evidence_sha256 is not None:
            _require_sha256(self.result_evidence_sha256, "restart result evidence")
        if self.selected_slot_id is not None:
            _require_identity(self.selected_slot_id, "selected restart slot")
            if self.selected_slot_id not in {
                self.intent.candidate_slot.slot_id,
                self.intent.lkg_slot.slot_id,
            }:
                raise PrivilegedRestartError("restart checkpoint selected a foreign slot")
        terminal = self.state is BrokerRestartCheckpointState.TERMINAL
        restricted = self.state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY
        if terminal != (self.closed_at is not None and self.result_evidence_sha256 is not None):
            raise PrivilegedRestartError("restart checkpoint terminal evidence is contradictory")
        if restricted and self.result_evidence_sha256 is None:
            raise PrivilegedRestartError("restricted restart checkpoint lacks result evidence")
        if not (terminal or restricted) and self.outcome is not BrokerRestartOutcome.PENDING:
            raise PrivilegedRestartError("open restart checkpoint carries a terminal outcome")
        if terminal and self.outcome not in {
            BrokerRestartOutcome.CANDIDATE_READY,
            BrokerRestartOutcome.ROLLBACK_READY,
            BrokerRestartOutcome.NO_SUBEFFECT,
            BrokerRestartOutcome.FAILED,
        }:
            raise PrivilegedRestartError("terminal restart checkpoint outcome is invalid")
        if restricted and self.outcome is not BrokerRestartOutcome.RESTRICTED_RECOVERY:
            raise PrivilegedRestartError("restricted restart checkpoint outcome is invalid")
        if self.outcome is BrokerRestartOutcome.CANDIDATE_READY and (
            self.selected_slot_id != self.intent.candidate_slot.slot_id
        ):
            raise PrivilegedRestartError("candidate-ready checkpoint did not select candidate")
        if self.outcome is BrokerRestartOutcome.ROLLBACK_READY and (
            self.selected_slot_id != self.intent.lkg_slot.slot_id
        ):
            raise PrivilegedRestartError("rollback-ready checkpoint did not select LKG")


@dataclass(frozen=True, slots=True)
class RestartAuthorisationRequest:
    operation: OperationSnapshot
    preparation: PrivilegedRestartPreparation
    decision: PolicyDecision
    ticket: PrivilegedTicket
    expected_fence_version: int
    required_scope_digest: str | None
    authorised_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.authorised_at, "restart authorisation")
        if self.required_scope_digest is not None:
            _require_sha256(self.required_scope_digest, "restart required scope")
        if self.expected_fence_version < 1:
            raise PrivilegedRestartError("expected workspace fence version is invalid")
        preparation = self.preparation
        ticket = self.ticket
        operation = self.operation
        expected_contract = _RESTART_CONTRACT[preparation.action]
        if (
            operation.state is not OperationState.RECEIVED
            or operation.operation_id != ticket.operation_id
            or operation.intent.operation_contract != expected_contract
            or operation.intent.tool_name != expected_contract
            or operation.intent.operation_contract_version != ticket.operation_contract_version
            or operation.intent.request_fingerprint_sha256 != ticket.request_fingerprint_sha256
            or operation.intent.target_identity_sha256 != preparation.target_profile_sha256
            or operation.intent.device_id != ticket.device_id
            or operation.intent.device_epoch != ticket.device_epoch
            or operation.intent.runtime_build_sha256 != ticket.application_build_sha256
            or operation.intent.runtime_config_sha256 != ticket.application_config_sha256
            or owner_digest(operation.owner) != ticket.controller_identity_sha256
        ):
            raise PrivilegedRestartError("restart operation and ticket identity differ")
        nonce_sha256 = hashlib.sha256(bytes.fromhex(ticket.nonce)).hexdigest()
        if (
            preparation.state is not PrivilegedPreparationState.AVAILABLE
            or preparation.consumed_by_operation_id is not None
            or preparation.consumed_at is not None
            or not preparation.created_at <= self.authorised_at < preparation.expires_at
            or ticket.issued_at != self.authorised_at
            or ticket.expires_at > preparation.expires_at
            or ticket.operation_contract != expected_contract
            or ticket.action is not preparation.action
            or ticket.maximum_effect is not preparation.maximum_effect
            or ticket.target_profile_id != preparation.target_profile_id
            or ticket.target_profile_sha256 != preparation.target_profile_sha256
            or ticket.current_state_binding_sha256 != preparation.current_state_binding_sha256
            or ticket.operation_specific_evidence_sha256 != preparation.prepared_evidence_sha256
            or nonce_sha256 != preparation.execution_nonce_sha256
        ):
            raise PrivilegedRestartError("restart ticket does not consume exact preparation")
        if (
            not self.decision.allowed
            or self.decision.operation_id != operation.operation_id
            or self.decision.decided_at > self.authorised_at
            or self.decision.runtime_policy_sha256 != ticket.policy_evidence_sha256
            or self.decision.runtime_policy_sha256 != ticket.application_policy_sha256
            or self.decision.policy_decision_id != ticket.policy_evidence_reference
        ):
            raise PrivilegedRestartError("restart policy evidence and ticket differ")


@dataclass(frozen=True, slots=True)
class RestartNoAcceptClosureRequest:
    snapshot: BrokerBindingSnapshot
    audit_closure_evidence_sha256: str
    closed_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(
            self.audit_closure_evidence_sha256,
            "restart no-accept audit closure",
        )
        _require_aware(self.closed_at, "restart no-accept closure")
        snapshot = self.snapshot
        if (
            snapshot.acceptance_state is not BrokerAcceptanceState.SEALED_NO_ACCEPT
            or snapshot.execution_state is not BrokerExecutionState.TERMINAL
            or snapshot.effect_knowledge is not PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            or snapshot.result_evidence_sha256 is None
            or snapshot.sealed_at is None
            or snapshot.closed_at is None
            or self.closed_at < snapshot.sealed_at
            or self.closed_at < snapshot.closed_at
        ):
            raise PrivilegedRestartError("restart no-accept closure evidence is contradictory")


@dataclass(frozen=True, slots=True)
class RestartAcceptedClosureRequest:
    """Application-side terminal closure for exact accepted broker effect truth."""

    snapshot: BrokerBindingSnapshot
    audit_closure_evidence_sha256: str
    closed_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(
            self.audit_closure_evidence_sha256,
            "restart accepted audit closure",
        )
        _require_aware(self.closed_at, "restart accepted closure")
        snapshot = self.snapshot
        if (
            snapshot.acceptance_state is not BrokerAcceptanceState.ACCEPTED
            or snapshot.execution_state is not BrokerExecutionState.TERMINAL
            or snapshot.result_evidence_sha256 is None
            or snapshot.accepted_at is None
            or snapshot.closed_at is None
            or snapshot.restart_checkpoint_sha256 is None
            or snapshot.restart_checkpoint_state is not BrokerRestartCheckpointState.TERMINAL
            or snapshot.restart_outcome
            not in {
                BrokerRestartOutcome.CANDIDATE_READY,
                BrokerRestartOutcome.ROLLBACK_READY,
                BrokerRestartOutcome.NO_SUBEFFECT,
                BrokerRestartOutcome.FAILED,
            }
            or self.closed_at < snapshot.accepted_at
            or self.closed_at < snapshot.closed_at
        ):
            raise PrivilegedRestartError("restart accepted closure evidence is contradictory")
        expected_knowledge = (
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            if snapshot.restart_outcome is BrokerRestartOutcome.NO_SUBEFFECT
            else PrivilegedEffectKnowledge.KNOWN_EFFECT
        )
        if snapshot.effect_knowledge is not expected_knowledge:
            raise PrivilegedRestartError("restart accepted effect knowledge is contradictory")


def _require_sha256(value: str, name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise PrivilegedRestartError(f"{name} must be a lowercase SHA-256 digest")


def _require_identity(value: str, name: str) -> None:
    if _IDENTITY_RE.fullmatch(value) is None or ".." in value:
        raise PrivilegedRestartError(f"{name} identity is invalid")


def _require_profile(value: str, name: str) -> None:
    if _PROFILE_RE.fullmatch(value) is None or ".." in value:
        raise PrivilegedRestartError(f"{name} identity is invalid")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedRestartError(f"{name} timestamp must be timezone-aware")


__all__ = [
    "PrivilegedOperationState",
    "PrivilegedPreparationState",
    "PrivilegedReservationState",
    "PrivilegedRestartCheckpointIntent",
    "PrivilegedRestartCheckpointSnapshot",
    "PrivilegedRestartError",
    "PrivilegedRestartPreparation",
    "PrivilegedRestartRecord",
    "RestartAcceptedClosureRequest",
    "RestartAuthorisationRequest",
    "RestartNoAcceptClosureRequest",
]

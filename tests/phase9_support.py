"""Shared exact Phase 9 authority fixtures."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from binnacle.domain.privileged import (
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedMaximumEffect,
    PrivilegedTicket,
)
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightResult,
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointIntent

NOW = datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
PROOF = "signed-proof-value-with-sufficient-length"


def privileged_ticket(*, now: datetime = NOW) -> PrivilegedTicket:
    return PrivilegedTicket(
        operation_id="operation:fixture",
        ticket_id="ticket:fixture",
        nonce="1" * 64,
        controller_identity_sha256=SHA_A,
        device_id="device:pi:1",
        device_epoch=1,
        operation_contract="package_install",
        operation_contract_version="v1",
        broker_profile_id="development-privileged",
        broker_profile_version="v1",
        broker_profile_sha256=SHA_C,
        action=PrivilegedAction.PACKAGE_INSTALL,
        target_profile_id="development-packages",
        target_profile_sha256=SHA_B,
        request_fingerprint_sha256=SHA_C,
        maximum_effect=PrivilegedMaximumEffect.PACKAGE_CHANGE,
        current_state_binding_sha256=SHA_A,
        policy_evidence_reference="policy:operation:1",
        policy_evidence_sha256=SHA_B,
        application_build_sha256=SHA_C,
        application_config_sha256=SHA_A,
        application_policy_sha256=SHA_B,
        operation_specific_evidence_sha256=SHA_C,
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=119),
        integrity_algorithm="ed25519",
        integrity_proof=PROOF,
    )


def acceptance_receipt() -> BrokerAcceptanceReceipt:
    ticket = privileged_ticket()
    return BrokerAcceptanceReceipt(
        operation_id=ticket.operation_id,
        ticket_id=ticket.ticket_id,
        ticket_sha256=ticket.ticket_sha256,
        disposition=BrokerAcceptanceDisposition.ACCEPTED,
        evidence_generation=1,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_EFFECT,
        evidence_sha256=SHA_B,
    )


def binding_snapshot() -> BrokerBindingSnapshot:
    ticket = privileged_ticket()
    return BrokerBindingSnapshot(
        identity=ticket.routing_identity,
        acceptance_state=BrokerAcceptanceState.ACCEPTED,
        evidence_generation=1,
        acceptance_evidence_sha256=SHA_B,
        execution_state=BrokerExecutionState.ACCEPTED_PRE_EFFECT,
        effect_knowledge=PrivilegedEffectKnowledge.NONE,
        result_evidence_sha256=None,
        accepted_at=NOW,
        sealed_at=None,
        closed_at=None,
        last_reconciled_at=None,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _runtime_slot(
    now: datetime,
    *,
    slot_id: str,
    generation: int,
    role: RuntimeSlotRole,
    state: RuntimeSlotState,
) -> VerifiedRuntimeSlot:
    return VerifiedRuntimeSlot(
        slot_id=slot_id,
        slot_generation=generation,
        slot_path=f"/srv/binnacle-runtime/slots/{slot_id}",
        role=role,
        state=state,
        source_sha256=_digest(f"source:{slot_id}"),
        environment_sha256=_digest(f"environment:{slot_id}"),
        config_sha256=_digest("config"),
        policy_sha256=_digest("policy"),
        manifest_sha256=_digest("manifest"),
        service_definition_sha256=_digest("service-definition"),
        deployed_peer_set_sha256=_digest("peers"),
        migration_heads_sha256=_digest("heads"),
        layout_sha256=_digest("layout"),
        candidate_verification_sha256=_digest(f"verification:{slot_id}"),
        complete_manifest_sha256=_digest(f"complete:{slot_id}"),
        byte_count=4096,
        inode_count=64,
        completed_at=now - timedelta(minutes=1),
    )


def controlled_restart_intent_and_ticket(
    now: datetime = NOW,
) -> tuple[PrivilegedRestartCheckpointIntent, PrivilegedTicket]:
    candidate = _runtime_slot(
        now,
        slot_id="candidate-slot",
        generation=2,
        role=RuntimeSlotRole.CANDIDATE,
        state=RuntimeSlotState.COMPLETE,
    )
    lkg = _runtime_slot(
        now,
        slot_id="lkg-slot",
        generation=1,
        role=RuntimeSlotRole.LKG,
        state=RuntimeSlotState.LKG,
    )
    preflight = RestartPreflightResult(
        kind=RestartPreflightKind.CONTROLLED_SELF,
        available=True,
        reason_codes=(),
        predicted_impacts=tuple(
            sorted(
                {
                    RestartImpact.APPLICATION_PROCESS_REPLACED,
                    RestartImpact.CONNECTION_INTERRUPTED,
                    RestartImpact.RUNTIME_SELECTOR_CHANGED,
                    RestartImpact.ROLLBACK_MAY_RUN,
                },
                key=lambda item: item.value,
            )
        ),
        current_runtime_identity_sha256=_digest("current-runtime"),
        current_service_observation_sha256=_digest("service-observation"),
        lkg_slot_identity_sha256=lkg.slot_identity_sha256,
        candidate_slot_identity_sha256=candidate.slot_identity_sha256,
        candidate_verification_sha256=candidate.candidate_verification_sha256,
        outstanding_state_sha256=_digest("outstanding"),
        state_binding_sha256=_digest("state-binding"),
        observed_at=now - timedelta(seconds=1),
    )
    issued_at = now - timedelta(milliseconds=100)
    ticket = PrivilegedTicket(
        operation_id="operation:restart",
        ticket_id="ticket:restart",
        nonce="1" * 64,
        controller_identity_sha256=_digest("controller"),
        device_id="device:pi:1",
        device_epoch=1,
        operation_contract="binnacle_restart",
        operation_contract_version="v1",
        broker_profile_id="development-privileged",
        broker_profile_version="v1",
        broker_profile_sha256=_digest("broker-profile"),
        action=PrivilegedAction.CONTROLLED_RESTART,
        target_profile_id="development-service",
        target_profile_sha256=_digest("service-profile"),
        request_fingerprint_sha256=_digest("request"),
        maximum_effect=PrivilegedMaximumEffect.CONTROLLED_RESTART,
        current_state_binding_sha256=preflight.state_binding_sha256,
        policy_evidence_reference="policy:restart",
        policy_evidence_sha256=_digest("policy-evidence"),
        application_build_sha256=_digest("application-build"),
        application_config_sha256=candidate.config_sha256,
        application_policy_sha256=candidate.policy_sha256,
        operation_specific_evidence_sha256=_digest("preparation"),
        issued_at=issued_at,
        expires_at=now + timedelta(minutes=2),
        integrity_algorithm="ed25519",
        integrity_proof=PROOF,
    )
    return (
        PrivilegedRestartCheckpointIntent(
            operation_id=ticket.operation_id,
            ticket_id=ticket.ticket_id,
            ticket_sha256=ticket.ticket_sha256,
            service_profile_sha256=ticket.target_profile_sha256,
            workspace_id="workspace:fixture",
            workspace_fence_version=7,
            preflight=preflight,
            candidate_slot=candidate,
            lkg_slot=lkg,
            restart_deadline_seconds=120,
            created_at=issued_at,
        ),
        ticket,
    )


__all__ = [
    "NOW",
    "PROOF",
    "SHA_A",
    "SHA_B",
    "SHA_C",
    "acceptance_receipt",
    "binding_snapshot",
    "controlled_restart_intent_and_ticket",
    "privileged_ticket",
]

"""Shared exact Phase 9 authority fixtures."""

from __future__ import annotations

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


__all__ = [
    "NOW",
    "PROOF",
    "SHA_A",
    "SHA_B",
    "SHA_C",
    "acceptance_receipt",
    "binding_snapshot",
    "privileged_ticket",
]

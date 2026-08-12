from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from binnacle.domain.privileged import (
    BinnacleServiceProfile,
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    PackageProfile,
    PrivilegedAction,
    PrivilegedBrokerProfile,
    PrivilegedEffectKnowledge,
    PrivilegedError,
    PrivilegedMaximumEffect,
    PrivilegedTicket,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _broker_profile() -> PrivilegedBrokerProfile:
    return PrivilegedBrokerProfile(
        profile_id="development-privileged",
        version="v1",
        protocol_version="v1",
        socket_path="/run/binnacle-privileged/broker.sock",
        broker_uid=0,
        broker_gid=0,
        application_peer_uid=1001,
        application_peer_gid=1001,
        allowed_actions=tuple(
            sorted(
                (
                    action
                    for action in PrivilegedAction
                    if action is not PrivilegedAction.HOST_REBOOT
                ),
                key=lambda value: value.value,
            )
        ),
        maximum_frame_bytes=65_536,
        request_deadline_seconds=30,
        maximum_requests_per_minute=60,
        evidence_root="/var/lib/binnacle-privileged",
        evidence_mount_identity_sha256=DIGEST_A,
        checkpoint_root="/var/lib/binnacle-privileged/checkpoints",
        checkpoint_mount_identity_sha256=DIGEST_B,
        executable_path="/opt/binnacle-privileged/bin/binnacle-privileged",
        executable_sha256=DIGEST_C,
        migration_head="0001_privileged_evidence",
        ticket_verification_key_reference_sha256=DIGEST_A,
        ticket_integrity_algorithm="ed25519",
        service_hardening_sha256=DIGEST_B,
        capability_evidence_sha256=DIGEST_C,
    )


def _service_profile() -> BinnacleServiceProfile:
    return BinnacleServiceProfile(
        profile_id="binnacle-development-service",
        version="v1",
        service_unit="binnacle-dev.service",
        workspace_root="/srv/binnacle-dev/repo",
        workspace_identity_sha256=DIGEST_A,
        workspace_mount_identity_sha256=DIGEST_B,
        runtime_root="/srv/binnacle-runtime",
        runtime_mount_identity_sha256=DIGEST_C,
        current_selector="/srv/binnacle-runtime/current",
        slot_layout_version="v1",
        maximum_slot_bytes=2_000_000_000,
        maximum_slot_inodes=100_000,
        maximum_retained_slots=3,
        service_uid=1001,
        service_gid=1001,
        config_sha256=DIGEST_A,
        policy_sha256=DIGEST_B,
        manifest_sha256=DIGEST_C,
        executable_path="/srv/binnacle-runtime/current/.venv/bin/binnacle",
        stable_unit_sha256=DIGEST_A,
        application_migration_head="0006_privileged_operations",
        executor_migration_head="0002_git_members",
        git_credential_migration_head="0001_credential_evidence",
        privileged_migration_head="0001_privileged_evidence",
        deployed_peer_set_sha256=DIGEST_B,
        readiness_contract_version="v1",
        restart_deadline_seconds=120,
        checkpoint_root="/var/lib/binnacle-privileged/checkpoints",
        local_recovery_marker="/var/lib/binnacle-privileged/checkpoints/recovery.json",
    )


def _package_profile() -> PackageProfile:
    return PackageProfile(
        profile_id="development-packages",
        version="v1",
        executable_path="/usr/bin/apt-get",
        executable_sha256=DIGEST_A,
        repository_profile_sha256=DIGEST_B,
        allowed_packages=("git", "ripgrep"),
        dependencies_allowed=True,
        version_pin_required=True,
        removals_allowed=False,
        repository_metadata_maximum_age_seconds=86_400,
        maximum_download_bytes=1_000_000_000,
        maximum_install_seconds=600,
        maximum_output_bytes=2_000_000,
        parser_version="apt-v1",
    )


def _ticket() -> PrivilegedTicket:
    issued = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    return PrivilegedTicket(
        operation_id="op:phase9:1",
        ticket_id="ticket:phase9:1",
        nonce="1" * 64,
        controller_identity_sha256=DIGEST_A,
        device_id="device:pi:1",
        device_epoch=1,
        operation_contract="package-install",
        operation_contract_version="v1",
        broker_profile_id="development-privileged",
        broker_profile_version="v1",
        action=PrivilegedAction.PACKAGE_INSTALL,
        target_profile_id="development-packages",
        target_profile_sha256=DIGEST_B,
        request_fingerprint_sha256=DIGEST_C,
        maximum_effect=PrivilegedMaximumEffect.PACKAGE_CHANGE,
        current_state_binding_sha256=DIGEST_A,
        policy_evidence_reference="policy:operation:1",
        policy_evidence_sha256=DIGEST_B,
        application_build_sha256=DIGEST_C,
        application_config_sha256=DIGEST_A,
        application_policy_sha256=DIGEST_B,
        operation_specific_evidence_sha256=DIGEST_C,
        issued_at=issued,
        expires_at=issued + timedelta(seconds=120),
        integrity_algorithm="ed25519",
        integrity_proof="signed-proof-value-with-sufficient-length",
    )


def test_protected_profiles_are_closed_and_digest_stable() -> None:
    broker = _broker_profile()
    service = _service_profile()
    package = _package_profile()

    assert broker.profile_sha256 == broker.profile_sha256
    assert service.profile_sha256 == service.profile_sha256
    assert package.profile_sha256 == package.profile_sha256
    assert not broker.active
    assert not service.active
    assert not package.active

    invalid: tuple[Callable[[], object], ...] = (
        lambda: replace(broker, broker_uid=1),
        lambda: replace(broker, allowed_actions=tuple(reversed(broker.allowed_actions))),
        lambda: replace(broker, migration_head="0002_unknown"),
        lambda: replace(
            broker,
            allowed_actions=tuple(
                sorted(
                    (*broker.allowed_actions, PrivilegedAction.HOST_REBOOT),
                    key=lambda value: value.value,
                )
            ),
        ),
        lambda: replace(service, service_unit="ssh.service"),
        lambda: replace(service, current_selector="/tmp/current"),
        lambda: replace(service, executor_migration_head="0001_executor_evidence"),
        lambda: replace(package, removals_allowed=True),
        lambda: replace(package, allowed_packages=("git", "git")),
        lambda: replace(package, executable_path="apt-get"),
    )
    for construct in invalid:
        with pytest.raises(PrivilegedError):
            construct()


def test_privileged_ticket_is_exact_consequential_and_time_bounded() -> None:
    ticket = _ticket()

    assert ticket.unsigned_payload_sha256 != ticket.ticket_sha256
    assert len(ticket.ticket_sha256) == 64
    assert ticket.action.consequential
    assert not PrivilegedAction.PACKAGE_INSPECT.consequential

    invalid: tuple[Callable[[], object], ...] = (
        lambda: replace(ticket, nonce="short"),
        lambda: replace(ticket, action=PrivilegedAction.PACKAGE_INSPECT),
        lambda: replace(
            ticket,
            action=PrivilegedAction.HOST_REBOOT,
            maximum_effect=PrivilegedMaximumEffect.HOST_REBOOT,
        ),
        lambda: replace(ticket, maximum_effect=PrivilegedMaximumEffect.SERVICE_RESTART),
        lambda: replace(ticket, device_epoch=0),
        lambda: replace(ticket, expires_at=ticket.issued_at),
        lambda: replace(ticket, expires_at=ticket.issued_at + timedelta(seconds=301)),
        lambda: replace(ticket, issued_at=ticket.issued_at.replace(tzinfo=None)),
        lambda: replace(ticket, integrity_algorithm="none"),
    )
    for construct in invalid:
        with pytest.raises(PrivilegedError):
            construct()


def test_acceptance_receipts_bind_effect_truth() -> None:
    ticket = _ticket()
    accepted = BrokerAcceptanceReceipt(
        operation_id=ticket.operation_id,
        ticket_id=ticket.ticket_id,
        ticket_sha256=ticket.ticket_sha256,
        disposition=BrokerAcceptanceDisposition.ACCEPTED,
        evidence_generation=1,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_EFFECT,
        evidence_sha256=DIGEST_A,
    )
    no_accept = replace(
        accepted,
        disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT,
    )
    conflict = replace(
        accepted,
        disposition=BrokerAcceptanceDisposition.CONFLICT,
        effect_knowledge=PrivilegedEffectKnowledge.NONE,
    )

    assert len(accepted.receipt_sha256) == 64
    assert len(no_accept.receipt_sha256) == 64
    assert len(conflict.receipt_sha256) == 64
    with pytest.raises(PrivilegedError, match="effect truth"):
        replace(accepted, effect_knowledge=PrivilegedEffectKnowledge.UNCERTAIN)

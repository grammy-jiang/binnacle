"""Broker accept-or-seal linearization and receiver-side validation."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from binnacle.domain.privileged import (
    BrokerAcceptanceDisposition,
    BrokerAcceptanceState,
    BrokerExecutionState,
    BrokerNoAcceptReason,
    PrivilegedAction,
    PrivilegedMaximumEffect,
    PrivilegedTicket,
)
from binnacle.privileged_broker import (
    PrivilegedStoreConflict,
    PrivilegedStoreError,
    PrivilegedStoreIdentity,
    PrivilegedStoreSettings,
    PrivilegedTicketRejected,
    PrivilegedTicketValidationProfile,
    PrivilegedTicketValidator,
    SqlitePrivilegedEvidenceStore,
    open_privileged_store,
    verify_privileged_broker_connection,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
PROOF = "signed-proof-value-with-sufficient-length"


def _ticket(now: datetime, *, suffix: str = "one") -> PrivilegedTicket:
    return PrivilegedTicket(
        operation_id=f"operation:{suffix}",
        ticket_id=f"ticket:{suffix}",
        nonce=("1" if suffix == "one" else "2") * 64,
        controller_identity_sha256=DIGEST_A,
        device_id="device:pi:1",
        device_epoch=1,
        operation_contract="package_install",
        operation_contract_version="v1",
        broker_profile_id="development-privileged",
        broker_profile_version="v1",
        broker_profile_sha256=DIGEST_C,
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
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=119),
        integrity_algorithm="ed25519",
        integrity_proof=PROOF,
    )


def _validator(now: datetime) -> PrivilegedTicketValidator:
    profile = PrivilegedTicketValidationProfile(
        broker_profile_id="development-privileged",
        broker_profile_version="v1",
        broker_profile_sha256=DIGEST_C,
        action_contract_versions={PrivilegedAction.PACKAGE_INSTALL: ("package_install", "v1")},
        target_profiles={PrivilegedAction.PACKAGE_INSTALL: ("development-packages", DIGEST_B)},
        application_build_sha256=DIGEST_C,
        application_config_sha256=DIGEST_A,
        application_policy_sha256=DIGEST_B,
        integrity_algorithm="ed25519",
    )
    return PrivilegedTicketValidator(
        profile,
        verify_integrity=lambda _payload, algorithm, proof: (
            algorithm == "ed25519" and proof == PROOF
        ),
        wall_clock=lambda: now,
    )


def _migrate(database: Path, repo_root: Path) -> None:
    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")


async def _open(
    tmp_path: Path,
    repo_root: Path,
    *,
    now: datetime,
    enabled: bool = True,
) -> tuple[Path, SqlitePrivilegedEvidenceStore]:
    database = tmp_path / "evidence.db"
    runtime = tmp_path / "run"
    runtime.mkdir()
    _migrate(database, repo_root)
    store = await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id="broker-instance-1",
            boot_id_sha256=DIGEST_A,
            protocol_version="v1",
            build_sha256=DIGEST_B,
            profile_sha256=DIGEST_C,
        ),
        ticket_verifier=_validator(now),
        acceptance_enabled=enabled,
    )
    return database, store


def test_receiver_validator_rejects_stale_wrong_profile_and_bad_proof() -> None:
    now = datetime.now(UTC)
    validator = _validator(now)
    ticket = _ticket(now)
    validator.validate(ticket)

    invalid = (
        replace(ticket, target_profile_sha256=DIGEST_A),
        replace(ticket, integrity_proof="bad-proof-value-that-is-long-enough-000"),
        replace(
            ticket,
            issued_at=now - timedelta(minutes=5),
            expires_at=now - timedelta(minutes=1),
        ),
    )
    for candidate in invalid:
        with pytest.raises(PrivilegedTicketRejected):
            validator.validate(candidate)


@pytest.mark.anyio
async def test_acceptance_is_stable_and_conflicting_ticket_is_rejected(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database, store = await _open(tmp_path, repo_root, now=now)
    ticket = _ticket(now)
    try:
        accepted = await store.accept_once(ticket)
        replay = await store.accept_once(ticket)
        after_accept_seal = await store.seal_no_accept(
            identity=ticket.routing_identity,
            reason=BrokerNoAcceptReason.REPLACEMENT_RECOVERY,
            trusted_time_at=now,
            retain_until=now + timedelta(days=1),
        )
        assert accepted.disposition is BrokerAcceptanceDisposition.ACCEPTED
        assert replay.disposition is BrokerAcceptanceDisposition.RETAINED_ACCEPTED
        assert after_accept_seal.disposition is BrokerAcceptanceDisposition.RETAINED_ACCEPTED
        assert {
            accepted.evidence_generation,
            replay.evidence_generation,
            after_accept_seal.evidence_generation,
        } == {1}
        assert {accepted.evidence_sha256, replay.evidence_sha256} == {accepted.evidence_sha256}
        snapshot = await store.get(ticket.operation_id)
        assert snapshot is not None
        assert snapshot.acceptance_state is BrokerAcceptanceState.ACCEPTED
        assert snapshot.execution_state is BrokerExecutionState.ACCEPTED_PRE_EFFECT

        with pytest.raises(PrivilegedStoreConflict, match="retains authority"):
            await store.accept_once(_ticket(now, suffix="two"))

        conflict = replace(ticket, ticket_id="ticket:alternate", nonce="3" * 64)
        with pytest.raises(PrivilegedStoreConflict):
            await store.accept_once(conflict)
    finally:
        await store.close()

    with closing(sqlite3.connect(database)) as connection:
        report = verify_privileged_broker_connection(connection)
        assert report.evidence_generation == 1
        assert report.accepted_bindings == 1
        assert report.outstanding_accepted_bindings == 1

    runtime = tmp_path / "run"
    restarted = await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id="broker-instance-2",
            boot_id_sha256=DIGEST_A,
            protocol_version="v1",
            build_sha256=DIGEST_B,
            profile_sha256=DIGEST_C,
        ),
        ticket_verifier=_validator(now),
        acceptance_enabled=True,
    )
    try:
        assert restarted.readiness == "restricted_recovery"
        retained = await restarted.accept_once(ticket)
        assert retained.disposition is BrokerAcceptanceDisposition.RETAINED_ACCEPTED
        with pytest.raises(PrivilegedStoreError, match="remains disabled"):
            await restarted.accept_once(_ticket(now, suffix="two"))
    finally:
        await restarted.close()


@pytest.mark.anyio
async def test_seal_wins_against_delayed_accept_and_survives_expiry(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database, store = await _open(tmp_path, repo_root, now=now)
    ticket = _ticket(now)
    try:
        seal, delayed_accept = await asyncio.gather(
            store.seal_no_accept(
                identity=ticket.routing_identity,
                reason=BrokerNoAcceptReason.PHASE4_NO_START,
                trusted_time_at=now,
                retain_until=now + timedelta(days=1),
            ),
            store.accept_once(ticket),
        )
        assert seal.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
        assert delayed_accept.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
        assert seal.evidence_sha256 == delayed_accept.evidence_sha256
        assert seal.evidence_generation == delayed_accept.evidence_generation == 1
        snapshot = await store.get(ticket.operation_id)
        assert snapshot is not None
        assert snapshot.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT
        assert snapshot.execution_state is BrokerExecutionState.TERMINAL

        expired_replay = replace(
            ticket,
            issued_at=now - timedelta(seconds=121),
            expires_at=now - timedelta(seconds=1),
        )
        with pytest.raises(PrivilegedStoreConflict):
            await store.accept_once(expired_replay)
        retained = await store.accept_once(ticket)
        assert retained.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
    finally:
        await store.close()

    with closing(sqlite3.connect(database)) as connection:
        report = verify_privileged_broker_connection(connection)
        assert report.evidence_generation == 1
        assert report.sealed_bindings == 1
        assert not report.outstanding_accepted_bindings


@pytest.mark.anyio
async def test_default_disabled_store_allows_sealing_but_not_new_acceptance(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    _database, store = await _open(tmp_path, repo_root, now=now, enabled=False)
    first = _ticket(now)
    second = _ticket(now, suffix="two")
    try:
        with pytest.raises(PrivilegedStoreError, match="remains disabled"):
            await store.accept_once(first)
        sealed = await store.seal_no_accept(
            identity=first.routing_identity,
            reason=BrokerNoAcceptReason.DISPATCH_CANCELLED,
            trusted_time_at=now,
            retain_until=now + timedelta(days=1),
        )
        assert sealed.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
        replay = await store.accept_once(first)
        assert replay.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
        with pytest.raises(PrivilegedStoreError, match="remains disabled"):
            await store.accept_once(second)
    finally:
        await store.close()


@pytest.mark.anyio
async def test_terminal_history_allows_broker_identity_upgrade(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database, store = await _open(tmp_path, repo_root, now=now)
    ticket = _ticket(now)
    await store.seal_no_accept(
        identity=ticket.routing_identity,
        reason=BrokerNoAcceptReason.DISPATCH_CANCELLED,
        trusted_time_at=now,
        retain_until=now + timedelta(days=1),
    )
    await store.close()

    upgraded = await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=database,
            runtime_directory=tmp_path / "run",
            verify_permissions=False,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id="broker-instance-upgraded",
            boot_id_sha256=DIGEST_B,
            protocol_version="v2",
            build_sha256=DIGEST_A,
            profile_sha256=DIGEST_B,
        ),
        ticket_verifier=_validator(now),
        acceptance_enabled=False,
    )
    try:
        assert upgraded.readiness == "disabled"
        retained = await upgraded.get(ticket.operation_id)
        assert retained is not None
        assert retained.acceptance_state is BrokerAcceptanceState.SEALED_NO_ACCEPT
    finally:
        await upgraded.close()


@pytest.mark.anyio
async def test_outstanding_authority_pins_exact_broker_identity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    now = datetime.now(UTC)
    database, store = await _open(tmp_path, repo_root, now=now)
    await store.accept_once(_ticket(now))
    await store.close()

    with pytest.raises(PrivilegedStoreError, match=r"outstanding.*exact identity"):
        await open_privileged_store(
            settings=PrivilegedStoreSettings(
                path=database,
                runtime_directory=tmp_path / "run",
                verify_permissions=False,
            ),
            identity=PrivilegedStoreIdentity(
                broker_instance_id="broker-instance-upgraded",
                boot_id_sha256=DIGEST_B,
                protocol_version="v2",
                build_sha256=DIGEST_A,
                profile_sha256=DIGEST_B,
            ),
            ticket_verifier=_validator(now),
            acceptance_enabled=True,
        )

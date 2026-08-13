"""Privileged-broker authority, checkpoint, and subeffect persistence.

The store retains facts and one-way transitions.  It never invokes systemd, changes the
runtime selector, or performs another root effect itself.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sqlite3
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import quote

import aiosqlite

from binnacle.domain.privileged import (
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerNoAcceptReason,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
    canonical_sha256,
    canonical_timestamp,
)
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightResult,
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import (
    PrivilegedRestartCheckpointIntent,
    PrivilegedRestartCheckpointSnapshot,
)
from binnacle.ports.privileged import PrivilegedTicketVerifier
from binnacle.privileged_broker.integrity import (
    PrivilegedBrokerIntegrityError,
    verify_privileged_broker_connection,
)
from binnacle.privileged_broker.runtime_publication import (
    RuntimeSelectorActivationRequest,
    runtime_selector_intent_sha256,
)

_ZERO_DIGEST: Final = "0" * 64


class PrivilegedStoreError(RuntimeError):
    """Privileged evidence is unavailable, unsafe, or contradictory."""


class PrivilegedStoreConflict(PrivilegedStoreError):
    """A replay differs from the one ticket retained for an operation."""


@dataclass(frozen=True, slots=True)
class PrivilegedStoreSettings:
    path: Path = Path("/var/lib/binnacle-privileged/evidence.db")
    runtime_directory: Path = Path("/run/binnacle-privileged")
    busy_timeout_ms: int = 5_000
    verify_permissions: bool = True
    runtime_group_gid: int | None = None


@dataclass(frozen=True, slots=True)
class PrivilegedStoreIdentity:
    broker_instance_id: str
    boot_id_sha256: str
    protocol_version: str
    build_sha256: str
    profile_sha256: str

    def __post_init__(self) -> None:
        if not self.broker_instance_id or len(self.broker_instance_id) > 160:
            raise PrivilegedStoreError("privileged broker instance identity is invalid")
        if not self.protocol_version or len(self.protocol_version) > 32:
            raise PrivilegedStoreError("privileged broker protocol identity is invalid")
        for value in (self.boot_id_sha256, self.build_sha256, self.profile_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise PrivilegedStoreError("privileged broker identity digest is invalid")


@dataclass(frozen=True, slots=True)
class RetainedRestartSubeffect:
    """Bounded replay fact for one restart phase intent."""

    subeffect_id: str
    state: str
    outcome: str
    effect_started: bool
    effect_reference: str | None
    boundary_receipt_sha256: str | None
    result_evidence_sha256: str | None
    updated_at: datetime

    @property
    def complete(self) -> bool:
        return self.state in {"terminal", "uncertain", "restricted_recovery"}

    @property
    def uncertain(self) -> bool:
        return self.state in {"uncertain", "restricted_recovery"}


@dataclass(frozen=True, slots=True)
class RetainedSelectorGeneration:
    """Exact persisted selector intent and its one-way publication state."""

    request: RuntimeSelectorActivationRequest
    state: str
    publication_receipt_sha256: str | None
    verification_evidence_sha256: str | None


@dataclass(slots=True)
class _StoreLock:
    descriptor: int

    def close(self) -> None:
        if self.descriptor < 0:
            return
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1


class SqlitePrivilegedEvidenceStore:
    """One serialized FULL transaction chooses acceptance or no-accept."""

    def __init__(
        self,
        *,
        connection: aiosqlite.Connection,
        settings: PrivilegedStoreSettings,
        identity: PrivilegedStoreIdentity,
        ticket_verifier: PrivilegedTicketVerifier,
        runtime_lock: _StoreLock,
        broker_generation: int,
        acceptance_enabled: bool,
        readiness: str,
    ) -> None:
        self._connection = connection
        self._settings = settings
        self._identity = identity
        self._ticket_verifier = ticket_verifier
        self._runtime_lock = runtime_lock
        self._broker_generation = broker_generation
        self._acceptance_enabled = acceptance_enabled
        self._readiness = readiness
        self._acceptance_gate = asyncio.Lock()
        self._closed = False

    @property
    def broker_generation(self) -> int:
        return self._broker_generation

    @property
    def readiness(self) -> str:
        return self._readiness

    async def accept_once(self, ticket: PrivilegedTicket) -> BrokerAcceptanceReceipt:
        identity = ticket.routing_identity
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._find_binding(identity)
                if retained is not None:
                    self._require_exact_identity(retained, identity)
                    state = BrokerAcceptanceState(str(retained["acceptance_state"]))
                    if state is BrokerAcceptanceState.ACCEPTED:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.RETAINED_ACCEPTED,
                        )
                        await self._connection.commit()
                        return result
                    if state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                        )
                        await self._connection.commit()
                        return result
                if not self._acceptance_enabled or self._readiness != "ready":
                    raise PrivilegedStoreError("privileged acceptance remains disabled")
                active = await self._fetchone(
                    "SELECT operation_id FROM privileged_operation_bindings "
                    "WHERE active_slot=1 AND operation_id!=? LIMIT 1",
                    (identity.operation_id,),
                )
                if active is not None:
                    raise PrivilegedStoreConflict("another privileged effect retains authority")
                self._ticket_verifier.validate(ticket)
                if retained is None:
                    await self._insert_unresolved(identity)

                now = datetime.now(UTC)
                if not identity.issued_at <= now < identity.expires_at:
                    raise PrivilegedStoreConflict("privileged ticket acceptance deadline elapsed")
                generation = await self._next_evidence_generation(now)
                evidence_sha256 = canonical_sha256(
                    {
                        "action": identity.action,
                        "disposition": "accepted",
                        "evidence_generation": generation,
                        "operation_id": identity.operation_id,
                        "target_profile_sha256": identity.target_profile_sha256,
                        "ticket_id": identity.ticket_id,
                        "ticket_sha256": identity.ticket_sha256,
                    }
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_operation_bindings
                    SET acceptance_state='accepted', evidence_generation=?,
                        acceptance_evidence_sha256=?, accepted_at=?,
                        execution_state='accepted_pre_effect',active_slot=1,updated_at=?
                    WHERE operation_id=? AND acceptance_state='unresolved'
                    """,
                    (
                        generation,
                        evidence_sha256,
                        canonical_timestamp(now),
                        canonical_timestamp(now),
                        identity.operation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("privileged acceptance winner changed")
                await cursor.close()
                await self._append_event(
                    generation=generation,
                    event_id=f"accept_{identity.ticket_sha256[:24]}",
                    operation_id=identity.operation_id,
                    event_type="ticket.accepted",
                    event_sha256=evidence_sha256,
                    recorded_at=now,
                )
                row = await self._required_binding(identity.operation_id)
                await self._connection.commit()
                return self._receipt(row, disposition=BrokerAcceptanceDisposition.ACCEPTED)
            except BaseException:
                await self._connection.rollback()
                raise

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt:
        _require_aware(trusted_time_at, "trusted seal time")
        _require_aware(retain_until, "seal retention time")
        if trusted_time_at < identity.issued_at or retain_until <= trusted_time_at:
            raise PrivilegedStoreError("privileged no-accept retention window is invalid")
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._find_binding(identity)
                if retained is not None:
                    self._require_exact_identity(retained, identity)
                    state = BrokerAcceptanceState(str(retained["acceptance_state"]))
                    if state is BrokerAcceptanceState.ACCEPTED:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.RETAINED_ACCEPTED,
                        )
                        await self._connection.commit()
                        return result
                    if state is BrokerAcceptanceState.SEALED_NO_ACCEPT:
                        result = self._receipt(
                            retained,
                            disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                        )
                        await self._connection.commit()
                        return result
                else:
                    await self._insert_unresolved(identity)

                generation = await self._next_evidence_generation(trusted_time_at)
                evidence_sha256 = canonical_sha256(
                    {
                        "boot_id_sha256": self._identity.boot_id_sha256,
                        "disposition": "sealed_no_accept",
                        "evidence_generation": generation,
                        "operation_id": identity.operation_id,
                        "reason": reason,
                        "retain_until": retain_until,
                        "ticket_id": identity.ticket_id,
                        "ticket_sha256": identity.ticket_sha256,
                        "trusted_time_at": trusted_time_at,
                    }
                )
                await self._connection.execute(
                    """
                    INSERT INTO privileged_no_accept_tombstones (
                      operation_id,ticket_id,ticket_sha256,reason,boot_id_sha256,
                      evidence_generation,evidence_sha256,trusted_time_at,retain_until,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        identity.operation_id,
                        identity.ticket_id,
                        identity.ticket_sha256,
                        reason.value,
                        self._identity.boot_id_sha256,
                        generation,
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        canonical_timestamp(retain_until),
                        canonical_timestamp(trusted_time_at),
                    ),
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_operation_bindings
                    SET acceptance_state='sealed_no_accept', evidence_generation=?,
                        acceptance_evidence_sha256=?, sealed_at=?,execution_state='terminal',
                        effect_knowledge='known_no_subeffect',result_evidence_sha256=?,
                        closed_at=?,updated_at=?
                    WHERE operation_id=? AND acceptance_state='unresolved'
                    """,
                    (
                        generation,
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        evidence_sha256,
                        canonical_timestamp(trusted_time_at),
                        canonical_timestamp(trusted_time_at),
                        identity.operation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("privileged no-accept winner changed")
                await cursor.close()
                await self._append_event(
                    generation=generation,
                    event_id=f"seal_{identity.ticket_sha256[:24]}",
                    operation_id=identity.operation_id,
                    event_type="ticket.sealed_no_accept",
                    event_sha256=evidence_sha256,
                    recorded_at=trusted_time_at,
                )
                row = await self._required_binding(identity.operation_id)
                await self._connection.commit()
                return self._receipt(
                    row,
                    disposition=BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None:
        row = await self._fetchone(
            "SELECT * FROM privileged_operation_bindings WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            return None
        checkpoint = await self._fetchone(
            "SELECT * FROM privileged_restart_checkpoints WHERE operation_id=?",
            (operation_id,),
        )
        return self._snapshot(row, checkpoint=checkpoint)

    async def create_restart_checkpoint(
        self,
        *,
        ticket: PrivilegedTicket,
        intent: PrivilegedRestartCheckpointIntent,
    ) -> PrivilegedRestartCheckpointSnapshot:
        """Retain exact complete candidate/LKG identities before any restart subeffect."""

        self._require_restart_ticket_intent(ticket, intent)
        async with self._acceptance_gate:
            await self._begin()
            try:
                binding = await self._required_binding(ticket.operation_id)
                self._require_exact_identity(binding, ticket.routing_identity)
                if (
                    BrokerAcceptanceState(str(binding["acceptance_state"]))
                    is not BrokerAcceptanceState.ACCEPTED
                ):
                    raise PrivilegedStoreConflict("restart checkpoint lacks accepted authority")
                retained = await self._fetchone(
                    "SELECT * FROM privileged_restart_checkpoints WHERE operation_id=?",
                    (ticket.operation_id,),
                )
                if retained is not None:
                    snapshot = await self._restart_snapshot(retained, binding=binding)
                    if snapshot.intent != intent:
                        raise PrivilegedStoreConflict("restart checkpoint intent changed")
                    await self._connection.commit()
                    return snapshot

                await self._retain_runtime_slot(intent.candidate_slot)
                await self._retain_runtime_slot(intent.lkg_slot)
                now = max(datetime.now(UTC), intent.created_at)
                generation = await self._next_evidence_generation(now)
                checkpoint_sha256 = canonical_sha256(
                    {
                        "acceptance_evidence_sha256": binding["acceptance_evidence_sha256"],
                        "broker_generation": self._broker_generation,
                        "candidate_slot_identity_sha256": (
                            intent.candidate_slot.slot_identity_sha256
                        ),
                        "evidence_generation": generation,
                        "intent_sha256": intent.intent_sha256,
                        "lkg_slot_identity_sha256": intent.lkg_slot.slot_identity_sha256,
                        "operation_id": ticket.operation_id,
                        "ticket_sha256": ticket.ticket_sha256,
                    }
                )
                await self._connection.execute(
                    """
                    INSERT INTO privileged_restart_checkpoints (
                      operation_id,service_profile_sha256,workspace_id,
                      workspace_fence_version,evidence_generation,candidate_slot_id,lkg_slot_id,
                      selected_slot_id,current_runtime_identity_sha256,
                      current_service_observation_sha256,outstanding_state_sha256,
                      preflight_state_binding_sha256,preflight_observed_at,
                      candidate_verification_sha256,
                      peer_set_sha256,schema_heads_sha256,restart_deadline_seconds,
                      checkpoint_sha256,state,outcome,result_evidence_sha256,created_at,
                      service_stopped_at,closed_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'checkpointed','pending',NULL,
                              ?,NULL,NULL,?)
                    """,
                    (
                        ticket.operation_id,
                        intent.service_profile_sha256,
                        intent.workspace_id,
                        intent.workspace_fence_version,
                        generation,
                        intent.candidate_slot.slot_id,
                        intent.lkg_slot.slot_id,
                        None,
                        intent.preflight.current_runtime_identity_sha256,
                        intent.preflight.current_service_observation_sha256,
                        intent.preflight.outstanding_state_sha256,
                        intent.preflight.state_binding_sha256,
                        canonical_timestamp(intent.preflight.observed_at),
                        intent.candidate_slot.candidate_verification_sha256,
                        intent.candidate_slot.deployed_peer_set_sha256,
                        intent.candidate_slot.migration_heads_sha256,
                        intent.restart_deadline_seconds,
                        checkpoint_sha256,
                        canonical_timestamp(intent.created_at),
                        canonical_timestamp(now),
                    ),
                )
                await self._append_event(
                    generation=generation,
                    event_id=f"checkpoint_{ticket.ticket_sha256[:24]}",
                    operation_id=ticket.operation_id,
                    event_type="restart.checkpointed",
                    event_sha256=checkpoint_sha256,
                    recorded_at=now,
                )
                retained = await self._required_restart_checkpoint(ticket.operation_id)
                await self._connection.commit()
                return await self._restart_snapshot(retained, binding=binding)
            except BaseException:
                await self._connection.rollback()
                raise

    async def get_restart_checkpoint(
        self,
        operation_id: str,
    ) -> PrivilegedRestartCheckpointSnapshot | None:
        row = await self._fetchone(
            "SELECT * FROM privileged_restart_checkpoints WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            return None
        binding = await self._required_binding(operation_id)
        return await self._restart_snapshot(row, binding=binding)

    async def record_initial_selector(
        self,
        *,
        slot: VerifiedRuntimeSlot,
        publication_receipt_sha256: str,
        verification_evidence_sha256: str,
        recorded_at: datetime,
    ) -> RetainedSelectorGeneration:
        """Retain owner-proven offline LKG selector bootstrap; perform no selector effect."""

        _require_aware(recorded_at, "initial selector evidence time")
        _require_digest(publication_receipt_sha256, "initial selector receipt")
        _require_digest(verification_evidence_sha256, "initial selector verification")
        if slot.role is not RuntimeSlotRole.LKG or slot.state is not RuntimeSlotState.LKG:
            raise PrivilegedStoreConflict("initial selector is not an exact LKG slot")
        request = RuntimeSelectorActivationRequest(
            selector_generation=1,
            operation_id=None,
            initial_bootstrap=True,
            expected_current_slot_id=None,
            target_slot_id=slot.slot_id,
            target_slot_identity_sha256=slot.slot_identity_sha256,
            retained_intent_sha256=runtime_selector_intent_sha256(
                selector_generation=1,
                operation_id=None,
                initial_bootstrap=True,
                expected_current_slot_id=None,
                target_slot_id=slot.slot_id,
                target_slot_identity_sha256=slot.slot_identity_sha256,
                requested_at=recorded_at,
            ),
            requested_at=recorded_at,
        )
        async with self._acceptance_gate:
            await self._begin()
            try:
                await self._retain_runtime_slot(slot)
                existing = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations WHERE selector_generation=1"
                )
                if existing is not None:
                    retained = await self._selector_generation(existing)
                    if (
                        retained.request != request
                        or retained.state != "verified"
                        or retained.publication_receipt_sha256 != publication_receipt_sha256
                        or retained.verification_evidence_sha256 != verification_evidence_sha256
                    ):
                        raise PrivilegedStoreConflict(
                            "initial selector conflicts with retained evidence"
                        )
                    await self._connection.commit()
                    return retained
                count = await self._fetchone(
                    "SELECT COUNT(*) AS count FROM privileged_selector_generations"
                )
                if count is None or _integer(count["count"]) != 0:
                    raise PrivilegedStoreConflict(
                        "initial selector must be the first retained generation"
                    )
                timestamp = canonical_timestamp(recorded_at)
                await self._connection.execute(
                    """
                    INSERT INTO privileged_selector_generations (
                      selector_generation,operation_id,initial_bootstrap,old_slot_id,
                      new_slot_id,intent_sha256,state,publication_receipt_sha256,
                      verification_evidence_sha256,created_at,published_at,verified_at,
                      updated_at
                    ) VALUES (1,NULL,1,NULL,?,?,'verified',?,?,?,?,?,?)
                    """,
                    (
                        slot.slot_id,
                        request.retained_intent_sha256,
                        publication_receipt_sha256,
                        verification_evidence_sha256,
                        timestamp,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                await self._connection.commit()
                return RetainedSelectorGeneration(
                    request=request,
                    state="verified",
                    publication_receipt_sha256=publication_receipt_sha256,
                    verification_evidence_sha256=verification_evidence_sha256,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def begin_selector_change(
        self,
        *,
        operation_id: str,
        expected_current_slot_id: str,
        target_slot_id: str,
        requested_at: datetime,
    ) -> RetainedSelectorGeneration:
        """Reserve one global selector generation and exact CAS intent before mutation."""

        _require_aware(requested_at, "selector intent time")
        async with self._acceptance_gate:
            await self._begin()
            try:
                checkpoint = await self._required_restart_checkpoint(operation_id)
                binding = await self._required_binding(operation_id)
                if (
                    binding["acceptance_state"] != BrokerAcceptanceState.ACCEPTED.value
                    or binding["action"] != PrivilegedAction.CONTROLLED_RESTART.value
                    or target_slot_id
                    not in {
                        str(checkpoint["candidate_slot_id"]),
                        str(checkpoint["lkg_slot_id"]),
                    }
                    or expected_current_slot_id
                    not in {
                        str(checkpoint["candidate_slot_id"]),
                        str(checkpoint["lkg_slot_id"]),
                    }
                ):
                    raise PrivilegedStoreConflict(
                        "selector intent lacks accepted checkpoint authority"
                    )
                existing = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations "
                    "WHERE operation_id=? AND new_slot_id=? "
                    "ORDER BY selector_generation DESC LIMIT 1",
                    (operation_id, target_slot_id),
                )
                if existing is not None:
                    retained = await self._selector_generation(existing)
                    if (
                        retained.request.expected_current_slot_id != expected_current_slot_id
                        or retained.request.requested_at != requested_at
                    ):
                        raise PrivilegedStoreConflict(
                            "selector replay differs from retained intent"
                        )
                    await self._connection.commit()
                    return retained
                effective = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations "
                    "WHERE state IN ('published','verified','restored','uncertain') "
                    "ORDER BY selector_generation DESC LIMIT 1"
                )
                if effective is None:
                    raise PrivilegedStoreConflict(
                        "controlled selector lacks an offline LKG bootstrap"
                    )
                if effective["state"] == "uncertain":
                    raise PrivilegedStoreConflict("prior selector publication remains uncertain")
                if str(effective["new_slot_id"]) != expected_current_slot_id:
                    raise PrivilegedStoreConflict(
                        "selector preimage differs from retained generation"
                    )
                maximum = await self._fetchone(
                    "SELECT MAX(selector_generation) AS generation "
                    "FROM privileged_selector_generations"
                )
                if maximum is None or maximum["generation"] is None:
                    raise PrivilegedStoreConflict("selector generation history is absent")
                selector_generation = _integer(maximum["generation"]) + 1
                slot_row = await self._fetchone(
                    "SELECT * FROM privileged_runtime_slots WHERE slot_id=?",
                    (target_slot_id,),
                )
                if slot_row is None:
                    raise PrivilegedStoreConflict("selector target slot is absent")
                slot = self._runtime_slot(slot_row)
                intent_sha256 = runtime_selector_intent_sha256(
                    selector_generation=selector_generation,
                    operation_id=operation_id,
                    initial_bootstrap=False,
                    expected_current_slot_id=expected_current_slot_id,
                    target_slot_id=target_slot_id,
                    target_slot_identity_sha256=slot.slot_identity_sha256,
                    requested_at=requested_at,
                )
                request = RuntimeSelectorActivationRequest(
                    selector_generation=selector_generation,
                    operation_id=operation_id,
                    initial_bootstrap=False,
                    expected_current_slot_id=expected_current_slot_id,
                    target_slot_id=target_slot_id,
                    target_slot_identity_sha256=slot.slot_identity_sha256,
                    retained_intent_sha256=intent_sha256,
                    requested_at=requested_at,
                )
                timestamp = canonical_timestamp(requested_at)
                await self._connection.execute(
                    """
                    INSERT INTO privileged_selector_generations (
                      selector_generation,operation_id,initial_bootstrap,old_slot_id,
                      new_slot_id,intent_sha256,state,publication_receipt_sha256,
                      verification_evidence_sha256,created_at,published_at,verified_at,
                      updated_at
                    ) VALUES (?,?,0,?,?,?,'intent_recorded',NULL,NULL,?,NULL,NULL,?)
                    """,
                    (
                        selector_generation,
                        operation_id,
                        expected_current_slot_id,
                        target_slot_id,
                        intent_sha256,
                        timestamp,
                        timestamp,
                    ),
                )
                await self._connection.commit()
                return RetainedSelectorGeneration(
                    request=request,
                    state="intent_recorded",
                    publication_receipt_sha256=None,
                    verification_evidence_sha256=None,
                )
            except BaseException:
                await self._connection.rollback()
                raise

    async def finish_selector_change(
        self,
        *,
        request: RuntimeSelectorActivationRequest,
        succeeded: bool,
        uncertain: bool,
        effect_started: bool,
        evidence_sha256: str,
        recorded_at: datetime,
    ) -> RetainedSelectorGeneration:
        """Retain selector publication/no-publication truth after its root boundary."""

        _require_aware(recorded_at, "selector publication time")
        _require_digest(evidence_sha256, "selector publication evidence")
        if succeeded and uncertain:
            raise PrivilegedStoreConflict("selector outcome is contradictory")
        state = (
            "published"
            if succeeded
            else ("uncertain" if uncertain or effect_started else "not_published")
        )
        publication = evidence_sha256 if succeeded else None
        verification = evidence_sha256 if state == "not_published" else None
        async with self._acceptance_gate:
            await self._begin()
            try:
                row = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations WHERE selector_generation=?",
                    (request.selector_generation,),
                )
                if row is None:
                    raise PrivilegedStoreConflict("selector intent is absent")
                retained = await self._selector_generation(row)
                if retained.request != request:
                    raise PrivilegedStoreConflict("selector publication intent changed")
                if retained.state != "intent_recorded":
                    if (
                        retained.state != state
                        or retained.publication_receipt_sha256 != publication
                        or retained.verification_evidence_sha256 != verification
                    ):
                        raise PrivilegedStoreConflict(
                            "selector publication conflicts with retained truth"
                        )
                    await self._connection.commit()
                    return retained
                timestamp = canonical_timestamp(recorded_at)
                await self._connection.execute(
                    """
                    UPDATE privileged_selector_generations
                    SET state=?,publication_receipt_sha256=?,
                        verification_evidence_sha256=?,published_at=?,verified_at=?,updated_at=?
                    WHERE selector_generation=? AND state='intent_recorded'
                    """,
                    (
                        state,
                        publication,
                        verification,
                        timestamp if state in {"published", "uncertain"} else None,
                        timestamp if state == "not_published" else None,
                        timestamp,
                        request.selector_generation,
                    ),
                )
                generation = await self._next_evidence_generation(recorded_at)
                await self._append_event(
                    generation=generation,
                    event_id=f"selector_{request.selector_generation}_{state}",
                    operation_id=request.operation_id or "offline-bootstrap",
                    event_type=f"selector.{state}",
                    event_sha256=evidence_sha256,
                    recorded_at=recorded_at,
                )
                await self._connection.commit()
                updated = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations WHERE selector_generation=?",
                    (request.selector_generation,),
                )
                if updated is None:
                    raise PrivilegedStoreError("selector publication evidence disappeared")
                return await self._selector_generation(updated)
            except BaseException:
                await self._connection.rollback()
                raise

    async def verify_selector_change(
        self,
        *,
        operation_id: str,
        target_slot_id: str,
        verification_evidence_sha256: str,
        restored: bool,
        recorded_at: datetime,
    ) -> RetainedSelectorGeneration:
        """Close exact runtime verification for the retained published selector."""

        _require_aware(recorded_at, "selector verification time")
        _require_digest(verification_evidence_sha256, "selector verification evidence")
        target_state = "restored" if restored else "verified"
        async with self._acceptance_gate:
            await self._begin()
            try:
                row = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations "
                    "WHERE operation_id=? AND new_slot_id=? "
                    "ORDER BY selector_generation DESC LIMIT 1",
                    (operation_id, target_slot_id),
                )
                if row is None:
                    raise PrivilegedStoreConflict("selector verification intent is absent")
                retained = await self._selector_generation(row)
                if retained.state in {"verified", "restored"}:
                    if (
                        retained.state != target_state
                        or retained.verification_evidence_sha256 != verification_evidence_sha256
                    ):
                        raise PrivilegedStoreConflict(
                            "selector verification conflicts with retained truth"
                        )
                    await self._connection.commit()
                    return retained
                if retained.state != "published":
                    raise PrivilegedStoreConflict(
                        "selector is not durably published for verification"
                    )
                timestamp = canonical_timestamp(recorded_at)
                await self._connection.execute(
                    """
                    UPDATE privileged_selector_generations
                    SET state=?,verification_evidence_sha256=?,verified_at=?,updated_at=?
                    WHERE selector_generation=? AND state='published'
                    """,
                    (
                        target_state,
                        verification_evidence_sha256,
                        timestamp,
                        timestamp,
                        retained.request.selector_generation,
                    ),
                )
                generation = await self._next_evidence_generation(recorded_at)
                await self._append_event(
                    generation=generation,
                    event_id=(f"selector_{retained.request.selector_generation}_{target_state}"),
                    operation_id=operation_id,
                    event_type=f"selector.{target_state}",
                    event_sha256=verification_evidence_sha256,
                    recorded_at=recorded_at,
                )
                await self._connection.commit()
                updated = await self._fetchone(
                    "SELECT * FROM privileged_selector_generations WHERE selector_generation=?",
                    (retained.request.selector_generation,),
                )
                if updated is None:
                    raise PrivilegedStoreError("selector verification evidence disappeared")
                return await self._selector_generation(updated)
            except BaseException:
                await self._connection.rollback()
                raise

    async def restart_recovery_operation_ids(self) -> tuple[str, ...]:
        cursor = await self._connection.execute(
            """
            SELECT operation_id FROM privileged_operation_bindings
            WHERE action='controlled_restart' AND acceptance_state='accepted'
              AND execution_state!='terminal'
            ORDER BY operation_id
            """
        )
        rows = tuple(await cursor.fetchall())
        await cursor.close()
        return tuple(str(row[0]) for row in rows)

    async def begin_restart_subeffect(
        self,
        *,
        operation_id: str,
        phase: str,
        kind: str,
        intent_sha256: str,
        recorded_at: datetime,
    ) -> RetainedRestartSubeffect:
        """Durably retain/reuse one exact phase intent before its root boundary call."""

        _require_aware(recorded_at, "restart subeffect intent time")
        if kind not in {
            "service_stop",
            "service_start",
            "selector_activate",
            "selector_restore",
            "runtime_verify",
        }:
            raise PrivilegedStoreError("restart subeffect kind is invalid")
        if (
            not phase
            or len(phase) > 64
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in phase)
        ):
            raise PrivilegedStoreError("restart subeffect phase is invalid")
        if len(intent_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in intent_sha256
        ):
            raise PrivilegedStoreError("restart subeffect intent digest is invalid")
        subeffect_id = f"restart_{phase}_{canonical_sha256(operation_id)[:32]}"
        async with self._acceptance_gate:
            await self._begin()
            try:
                checkpoint = await self._required_restart_checkpoint(operation_id)
                if str(checkpoint["state"]) in {"terminal", "restricted_recovery"}:
                    raise PrivilegedStoreConflict("restart checkpoint cannot start another effect")
                retained = await self._fetchone(
                    "SELECT * FROM privileged_subeffects WHERE subeffect_id=?",
                    (subeffect_id,),
                )
                if retained is not None:
                    if (
                        str(retained["operation_id"]) != operation_id
                        or str(retained["kind"]) != kind
                        or str(retained["intent_sha256"]) != intent_sha256
                    ):
                        raise PrivilegedStoreConflict("restart subeffect intent changed")
                    await self._connection.commit()
                    return self._retained_subeffect(retained)
                active = await self._fetchone(
                    "SELECT subeffect_id FROM privileged_subeffects "
                    "WHERE operation_id=? AND state IN "
                    "('intent_recorded','started','reconciling','uncertain','restricted_recovery')",
                    (operation_id,),
                )
                if active is not None:
                    raise PrivilegedStoreConflict("another restart subeffect remains active")
                row = await self._fetchone(
                    "SELECT COALESCE(MAX(subeffect_generation),0) FROM privileged_subeffects "
                    "WHERE operation_id=?",
                    (operation_id,),
                )
                if row is None:
                    raise PrivilegedStoreError("restart subeffect generation is unavailable")
                subeffect_generation = _integer(row[0]) + 1
                await self._connection.execute(
                    """
                    INSERT INTO privileged_subeffects (
                      operation_id,subeffect_generation,subeffect_id,kind,intent_sha256,state,
                      effect_knowledge,outcome,effect_reference,boundary_receipt_sha256,
                      result_evidence_sha256,created_at,started_at,closed_at,updated_at
                    ) VALUES (?,?,?,?,?,'intent_recorded','none','pending',NULL,NULL,NULL,
                              ?,NULL,NULL,?)
                    """,
                    (
                        operation_id,
                        subeffect_generation,
                        subeffect_id,
                        kind,
                        intent_sha256,
                        canonical_timestamp(recorded_at),
                        canonical_timestamp(recorded_at),
                    ),
                )
                generation = await self._next_evidence_generation(recorded_at)
                await self._append_event(
                    generation=generation,
                    event_id=f"intent_{canonical_sha256(subeffect_id)[:24]}",
                    operation_id=operation_id,
                    event_type=f"{kind}.intent_recorded",
                    event_sha256=intent_sha256,
                    recorded_at=recorded_at,
                )
                await self._connection.commit()
                retained = await self._fetchone(
                    "SELECT * FROM privileged_subeffects WHERE subeffect_id=?",
                    (subeffect_id,),
                )
                if retained is None:
                    raise PrivilegedStoreError("restart subeffect intent disappeared")
                return self._retained_subeffect(retained)
            except BaseException:
                await self._connection.rollback()
                raise

    async def finish_restart_subeffect(
        self,
        *,
        operation_id: str,
        subeffect_id: str,
        effect_started: bool,
        effect_reference: str | None,
        boundary_receipt_sha256: str | None,
        result_evidence_sha256: str,
        succeeded: bool,
        uncertain: bool,
        recorded_at: datetime,
    ) -> RetainedRestartSubeffect:
        """Close one retained intent with bounded known or uncertain effect truth."""

        _require_aware(recorded_at, "restart subeffect result time")
        for value, name in (
            (result_evidence_sha256, "restart subeffect result"),
            (boundary_receipt_sha256, "restart subeffect boundary receipt"),
        ):
            if value is not None and (
                len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            ):
                raise PrivilegedStoreError(f"{name} digest is invalid")
        if effect_reference is not None and (not effect_reference or len(effect_reference) > 160):
            raise PrivilegedStoreError("restart subeffect reference is invalid")
        if uncertain and not effect_started:
            raise PrivilegedStoreError("uncertain restart subeffect lacks a crossed boundary")
        if uncertain and succeeded:
            raise PrivilegedStoreError("uncertain restart subeffect claims success")
        async with self._acceptance_gate:
            await self._begin()
            try:
                retained = await self._fetchone(
                    "SELECT * FROM privileged_subeffects WHERE subeffect_id=?",
                    (subeffect_id,),
                )
                if retained is None or str(retained["operation_id"]) != operation_id:
                    raise PrivilegedStoreConflict("restart subeffect intent is absent")
                retained_result = _optional_text(retained["result_evidence_sha256"])
                if retained_result is not None:
                    if (
                        retained_result != result_evidence_sha256
                        or str(retained["outcome"])
                        != ("uncertain" if uncertain else ("succeeded" if succeeded else "failed"))
                        or bool(retained["started_at"] is not None) != effect_started
                        or _optional_text(retained["effect_reference"]) != effect_reference
                        or _optional_text(retained["boundary_receipt_sha256"])
                        != boundary_receipt_sha256
                    ):
                        raise PrivilegedStoreConflict("restart subeffect result changed")
                    await self._connection.commit()
                    return self._retained_subeffect(retained)
                state = "uncertain" if uncertain else "terminal"
                outcome = "uncertain" if uncertain else ("succeeded" if succeeded else "failed")
                knowledge = (
                    "uncertain"
                    if uncertain
                    else ("known_effect" if effect_started else "known_no_subeffect")
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_subeffects
                    SET state=?,effect_knowledge=?,outcome=?,effect_reference=?,
                        boundary_receipt_sha256=?,result_evidence_sha256=?,started_at=?,
                        closed_at=?,updated_at=?
                    WHERE subeffect_id=? AND state='intent_recorded'
                    """,
                    (
                        state,
                        knowledge,
                        outcome,
                        effect_reference,
                        boundary_receipt_sha256,
                        result_evidence_sha256,
                        canonical_timestamp(recorded_at) if effect_started else None,
                        None if uncertain else canonical_timestamp(recorded_at),
                        canonical_timestamp(recorded_at),
                        subeffect_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("restart subeffect result winner changed")
                await cursor.close()
                generation = await self._next_evidence_generation(recorded_at)
                await self._append_event(
                    generation=generation,
                    event_id=f"result_{canonical_sha256(subeffect_id)[:24]}",
                    operation_id=operation_id,
                    event_type=f"subeffect.{state}",
                    event_sha256=result_evidence_sha256,
                    recorded_at=recorded_at,
                )
                await self._connection.commit()
                retained = await self._fetchone(
                    "SELECT * FROM privileged_subeffects WHERE subeffect_id=?",
                    (subeffect_id,),
                )
                if retained is None:
                    raise PrivilegedStoreError("restart subeffect result disappeared")
                return self._retained_subeffect(retained)
            except BaseException:
                await self._connection.rollback()
                raise

    async def advance_restart_checkpoint(
        self,
        *,
        operation_id: str,
        expected_state: BrokerRestartCheckpointState,
        next_state: BrokerRestartCheckpointState,
        selected_slot_id: str | None,
        outcome: BrokerRestartOutcome = BrokerRestartOutcome.PENDING,
        result_evidence_sha256: str | None = None,
        service_stopped: bool = False,
        recorded_at: datetime,
    ) -> PrivilegedRestartCheckpointSnapshot:
        """Advance checkpoint and aggregate binding truth in one FULL transaction."""

        _require_aware(recorded_at, "restart checkpoint transition time")
        if result_evidence_sha256 is not None and (
            len(result_evidence_sha256) != 64
            or any(character not in "0123456789abcdef" for character in result_evidence_sha256)
        ):
            raise PrivilegedStoreError("restart result digest is invalid")
        async with self._acceptance_gate:
            await self._begin()
            try:
                checkpoint = await self._required_restart_checkpoint(operation_id)
                if BrokerRestartCheckpointState(str(checkpoint["state"])) is not expected_state:
                    if (
                        BrokerRestartCheckpointState(str(checkpoint["state"])) is next_state
                        and str(checkpoint["outcome"]) == outcome.value
                        and _optional_text(checkpoint["selected_slot_id"]) == selected_slot_id
                        and _optional_text(checkpoint["result_evidence_sha256"])
                        == result_evidence_sha256
                    ):
                        binding = await self._required_binding(operation_id)
                        await self._connection.commit()
                        return await self._restart_snapshot(checkpoint, binding=binding)
                    raise PrivilegedStoreConflict("restart checkpoint transition preimage changed")
                generation = await self._next_evidence_generation(recorded_at)
                terminal = next_state is BrokerRestartCheckpointState.TERMINAL
                restricted = next_state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY
                service_stopped_at = checkpoint["service_stopped_at"]
                if service_stopped and service_stopped_at is None:
                    service_stopped_at = canonical_timestamp(recorded_at)
                cursor = await self._connection.execute(
                    """
                    UPDATE privileged_restart_checkpoints
                    SET evidence_generation=?,state=?,outcome=?,selected_slot_id=?,
                        result_evidence_sha256=?,service_stopped_at=?,closed_at=?,updated_at=?
                    WHERE operation_id=? AND state=?
                    """,
                    (
                        generation,
                        next_state.value,
                        outcome.value,
                        selected_slot_id,
                        result_evidence_sha256,
                        service_stopped_at,
                        canonical_timestamp(recorded_at) if terminal else None,
                        canonical_timestamp(recorded_at),
                        operation_id,
                        expected_state.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PrivilegedStoreConflict("restart checkpoint transition winner changed")
                await cursor.close()
                if terminal or restricted:
                    knowledge = (
                        PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
                        if outcome is BrokerRestartOutcome.NO_SUBEFFECT
                        else (
                            PrivilegedEffectKnowledge.UNCERTAIN
                            if restricted
                            else PrivilegedEffectKnowledge.KNOWN_EFFECT
                        )
                    )
                    execution = (
                        BrokerExecutionState.RESTRICTED_RECOVERY
                        if restricted
                        else BrokerExecutionState.TERMINAL
                    )
                    await self._connection.execute(
                        """
                        UPDATE privileged_operation_bindings
                        SET execution_state=?,effect_knowledge=?,result_evidence_sha256=?,
                            active_slot=?,closed_at=?,last_reconciled_at=?,updated_at=?
                        WHERE operation_id=? AND acceptance_state='accepted'
                        """,
                        (
                            execution.value,
                            knowledge.value,
                            result_evidence_sha256,
                            None if terminal else 1,
                            canonical_timestamp(recorded_at) if terminal else None,
                            canonical_timestamp(recorded_at),
                            canonical_timestamp(recorded_at),
                            operation_id,
                        ),
                    )
                else:
                    await self._connection.execute(
                        """
                        UPDATE privileged_operation_bindings
                        SET execution_state='executing',effect_knowledge='known_effect',
                            last_reconciled_at=?,updated_at=?
                        WHERE operation_id=? AND acceptance_state='accepted'
                        """,
                        (
                            canonical_timestamp(recorded_at),
                            canonical_timestamp(recorded_at),
                            operation_id,
                        ),
                    )
                event_sha256 = result_evidence_sha256 or canonical_sha256(
                    {
                        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
                        "evidence_generation": generation,
                        "next_state": next_state,
                        "operation_id": operation_id,
                        "selected_slot_id": selected_slot_id,
                    }
                )
                await self._append_event(
                    generation=generation,
                    event_id=f"restart_{generation}_{operation_id[-24:]}",
                    operation_id=operation_id,
                    event_type=f"restart.{next_state.value}",
                    event_sha256=event_sha256,
                    recorded_at=recorded_at,
                )
                checkpoint = await self._required_restart_checkpoint(operation_id)
                binding = await self._required_binding(operation_id)
                await self._connection.commit()
                return await self._restart_snapshot(checkpoint, binding=binding)
            except BaseException:
                await self._connection.rollback()
                raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._connection.close()
        finally:
            self._runtime_lock.close()

    async def _begin(self) -> None:
        await self._connection.execute("BEGIN IMMEDIATE")

    async def _insert_unresolved(self, identity: PrivilegedTicketRoutingIdentity) -> None:
        try:
            await self._connection.execute(
                """
                INSERT INTO privileged_operation_bindings (
                  operation_id,ticket_id,ticket_sha256,ticket_nonce_sha256,action,
                  target_profile_id,target_profile_sha256,broker_profile_sha256,
                  request_fingerprint_sha256,current_state_binding_sha256,
                  policy_evidence_sha256,expires_at,acceptance_state,evidence_generation,
                  acceptance_evidence_sha256,execution_state,effect_knowledge,
                  active_slot,result_evidence_sha256,created_at,accepted_at,sealed_at,closed_at,
                  updated_at,last_reconciled_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'unresolved',0,NULL,'not_accepted','none',
                          NULL,NULL,?,NULL,NULL,NULL,?,NULL)
                """,
                (
                    identity.operation_id,
                    identity.ticket_id,
                    identity.ticket_sha256,
                    identity.ticket_nonce_sha256,
                    identity.action.value,
                    identity.target_profile_id,
                    identity.target_profile_sha256,
                    identity.broker_profile_sha256,
                    identity.request_fingerprint_sha256,
                    identity.current_state_binding_sha256,
                    identity.policy_evidence_sha256,
                    canonical_timestamp(identity.expires_at),
                    canonical_timestamp(identity.issued_at),
                    canonical_timestamp(identity.issued_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PrivilegedStoreConflict("privileged ticket identity is already bound") from exc

    async def _find_binding(
        self,
        identity: PrivilegedTicketRoutingIdentity,
    ) -> sqlite3.Row | None:
        cursor = await self._connection.execute(
            """
            SELECT * FROM privileged_operation_bindings
            WHERE operation_id=? OR ticket_id=? OR ticket_sha256=? OR ticket_nonce_sha256=?
            ORDER BY operation_id LIMIT 2
            """,
            (
                identity.operation_id,
                identity.ticket_id,
                identity.ticket_sha256,
                identity.ticket_nonce_sha256,
            ),
        )
        rows = tuple(await cursor.fetchall())
        await cursor.close()
        if len(rows) > 1:
            raise PrivilegedStoreConflict("privileged ticket identity crosses retained bindings")
        return None if not rows else rows[0]

    @staticmethod
    def _require_exact_identity(
        row: sqlite3.Row,
        identity: PrivilegedTicketRoutingIdentity,
    ) -> None:
        if (
            str(row["operation_id"]) != identity.operation_id
            or str(row["ticket_id"]) != identity.ticket_id
            or str(row["ticket_sha256"]) != identity.ticket_sha256
            or str(row["ticket_nonce_sha256"]) != identity.ticket_nonce_sha256
            or str(row["action"]) != identity.action.value
            or str(row["target_profile_id"]) != identity.target_profile_id
            or str(row["target_profile_sha256"]) != identity.target_profile_sha256
            or str(row["broker_profile_sha256"]) != identity.broker_profile_sha256
            or str(row["request_fingerprint_sha256"]) != identity.request_fingerprint_sha256
            or str(row["current_state_binding_sha256"]) != identity.current_state_binding_sha256
            or str(row["policy_evidence_sha256"]) != identity.policy_evidence_sha256
            or _timestamp(row["created_at"]) != identity.issued_at
            or _timestamp(row["expires_at"]) != identity.expires_at
        ):
            raise PrivilegedStoreConflict("privileged ticket conflicts with retained binding")

    @staticmethod
    def _require_restart_ticket_intent(
        ticket: PrivilegedTicket,
        intent: PrivilegedRestartCheckpointIntent,
    ) -> None:
        if (
            ticket.action is not PrivilegedAction.CONTROLLED_RESTART
            or ticket.operation_id != intent.operation_id
            or ticket.ticket_id != intent.ticket_id
            or ticket.ticket_sha256 != intent.ticket_sha256
            or ticket.target_profile_sha256 != intent.service_profile_sha256
            or ticket.current_state_binding_sha256 != intent.preflight.state_binding_sha256
            or ticket.issued_at != intent.created_at
            or ticket.application_config_sha256 != intent.candidate_slot.config_sha256
            or ticket.application_policy_sha256 != intent.candidate_slot.policy_sha256
        ):
            raise PrivilegedStoreConflict("controlled restart ticket and checkpoint intent differ")

    async def _retain_runtime_slot(self, slot: VerifiedRuntimeSlot) -> None:
        retained = await self._fetchone(
            "SELECT * FROM privileged_runtime_slots WHERE slot_id=? OR slot_generation=?",
            (slot.slot_id, slot.slot_generation),
        )
        if retained is not None:
            if self._runtime_slot(retained) != slot:
                raise PrivilegedStoreConflict("retained runtime slot identity changed")
            return
        try:
            await self._connection.execute(
                """
                INSERT INTO privileged_runtime_slots (
                  slot_id,slot_generation,slot_path,role,state,source_sha256,
                  environment_sha256,config_sha256,policy_sha256,manifest_sha256,
                  service_definition_sha256,deployed_peer_set_sha256,
                  migration_heads_sha256,layout_sha256,candidate_verification_sha256,
                  complete_manifest_sha256,byte_count,inode_count,created_at,completed_at,
                  updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    slot.slot_id,
                    slot.slot_generation,
                    slot.slot_path,
                    slot.role.value,
                    slot.state.value,
                    slot.source_sha256,
                    slot.environment_sha256,
                    slot.config_sha256,
                    slot.policy_sha256,
                    slot.manifest_sha256,
                    slot.service_definition_sha256,
                    slot.deployed_peer_set_sha256,
                    slot.migration_heads_sha256,
                    slot.layout_sha256,
                    slot.candidate_verification_sha256,
                    slot.complete_manifest_sha256,
                    slot.byte_count,
                    slot.inode_count,
                    canonical_timestamp(slot.completed_at),
                    canonical_timestamp(slot.completed_at),
                    canonical_timestamp(slot.completed_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PrivilegedStoreConflict("runtime slot generation is already retained") from exc

    async def _required_restart_checkpoint(self, operation_id: str) -> sqlite3.Row:
        row = await self._fetchone(
            "SELECT * FROM privileged_restart_checkpoints WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            raise PrivilegedStoreConflict("restart checkpoint is absent")
        return row

    async def _restart_snapshot(
        self,
        row: sqlite3.Row,
        *,
        binding: sqlite3.Row,
    ) -> PrivilegedRestartCheckpointSnapshot:
        candidate_row = await self._fetchone(
            "SELECT * FROM privileged_runtime_slots WHERE slot_id=?",
            (str(row["candidate_slot_id"]),),
        )
        lkg_row = await self._fetchone(
            "SELECT * FROM privileged_runtime_slots WHERE slot_id=?",
            (str(row["lkg_slot_id"]),),
        )
        if candidate_row is None or lkg_row is None:
            raise PrivilegedStoreError("restart checkpoint slot evidence is absent")
        candidate = self._runtime_slot(candidate_row)
        lkg = self._runtime_slot(lkg_row)
        created_at = _timestamp(row["created_at"])
        current_runtime = _optional_text(row["current_runtime_identity_sha256"])
        if current_runtime is None:
            raise PrivilegedStoreError("restart checkpoint current runtime is absent")
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
            current_runtime_identity_sha256=current_runtime,
            current_service_observation_sha256=str(row["current_service_observation_sha256"]),
            lkg_slot_identity_sha256=lkg.slot_identity_sha256,
            candidate_slot_identity_sha256=candidate.slot_identity_sha256,
            candidate_verification_sha256=str(row["candidate_verification_sha256"]),
            outstanding_state_sha256=str(row["outstanding_state_sha256"]),
            state_binding_sha256=str(row["preflight_state_binding_sha256"]),
            observed_at=_timestamp(row["preflight_observed_at"]),
        )
        intent = PrivilegedRestartCheckpointIntent(
            operation_id=str(row["operation_id"]),
            ticket_id=str(binding["ticket_id"]),
            ticket_sha256=str(binding["ticket_sha256"]),
            service_profile_sha256=str(row["service_profile_sha256"]),
            workspace_id=str(row["workspace_id"]),
            workspace_fence_version=_integer(row["workspace_fence_version"]),
            preflight=preflight,
            candidate_slot=candidate,
            lkg_slot=lkg,
            restart_deadline_seconds=_integer(row["restart_deadline_seconds"]),
            created_at=created_at,
        )
        return PrivilegedRestartCheckpointSnapshot(
            intent=intent,
            checkpoint_sha256=str(row["checkpoint_sha256"]),
            evidence_generation=_integer(row["evidence_generation"]),
            state=BrokerRestartCheckpointState(str(row["state"])),
            outcome=BrokerRestartOutcome(str(row["outcome"])),
            selected_slot_id=_optional_text(row["selected_slot_id"]),
            result_evidence_sha256=_optional_text(row["result_evidence_sha256"]),
            service_stopped_at=_optional_timestamp(row["service_stopped_at"]),
            closed_at=_optional_timestamp(row["closed_at"]),
            updated_at=_timestamp(row["updated_at"]),
        )

    async def _selector_generation(
        self,
        row: sqlite3.Row,
    ) -> RetainedSelectorGeneration:
        slot_row = await self._fetchone(
            "SELECT * FROM privileged_runtime_slots WHERE slot_id=?",
            (str(row["new_slot_id"]),),
        )
        if slot_row is None:
            raise PrivilegedStoreError("selector target slot evidence is absent")
        slot = self._runtime_slot(slot_row)
        initial = bool(row["initial_bootstrap"])
        operation_id = _optional_text(row["operation_id"])
        request = RuntimeSelectorActivationRequest(
            selector_generation=_integer(row["selector_generation"]),
            operation_id=operation_id,
            initial_bootstrap=initial,
            expected_current_slot_id=_optional_text(row["old_slot_id"]),
            target_slot_id=slot.slot_id,
            target_slot_identity_sha256=slot.slot_identity_sha256,
            retained_intent_sha256=str(row["intent_sha256"]),
            requested_at=_timestamp(row["created_at"]),
        )
        return RetainedSelectorGeneration(
            request=request,
            state=str(row["state"]),
            publication_receipt_sha256=_optional_text(row["publication_receipt_sha256"]),
            verification_evidence_sha256=_optional_text(row["verification_evidence_sha256"]),
        )

    @staticmethod
    def _runtime_slot(row: sqlite3.Row) -> VerifiedRuntimeSlot:
        completed_at = _optional_timestamp(row["completed_at"])
        manifest = _optional_text(row["complete_manifest_sha256"])
        if completed_at is None or manifest is None:
            raise PrivilegedStoreError("retained runtime slot is incomplete")
        return VerifiedRuntimeSlot(
            slot_id=str(row["slot_id"]),
            slot_generation=_integer(row["slot_generation"]),
            slot_path=str(row["slot_path"]),
            role=RuntimeSlotRole(str(row["role"])),
            state=RuntimeSlotState(str(row["state"])),
            source_sha256=str(row["source_sha256"]),
            environment_sha256=str(row["environment_sha256"]),
            config_sha256=str(row["config_sha256"]),
            policy_sha256=str(row["policy_sha256"]),
            manifest_sha256=str(row["manifest_sha256"]),
            service_definition_sha256=str(row["service_definition_sha256"]),
            deployed_peer_set_sha256=str(row["deployed_peer_set_sha256"]),
            migration_heads_sha256=str(row["migration_heads_sha256"]),
            layout_sha256=str(row["layout_sha256"]),
            candidate_verification_sha256=str(row["candidate_verification_sha256"]),
            complete_manifest_sha256=manifest,
            byte_count=_integer(row["byte_count"]),
            inode_count=_integer(row["inode_count"]),
            completed_at=completed_at,
        )

    @staticmethod
    def _retained_subeffect(row: sqlite3.Row) -> RetainedRestartSubeffect:
        return RetainedRestartSubeffect(
            subeffect_id=str(row["subeffect_id"]),
            state=str(row["state"]),
            outcome=str(row["outcome"]),
            effect_started=row["started_at"] is not None,
            effect_reference=_optional_text(row["effect_reference"]),
            boundary_receipt_sha256=_optional_text(row["boundary_receipt_sha256"]),
            result_evidence_sha256=_optional_text(row["result_evidence_sha256"]),
            updated_at=_timestamp(row["updated_at"]),
        )

    async def _next_evidence_generation(self, recorded_at: datetime) -> int:
        row = await self._fetchone(
            "SELECT evidence_generation_high_water,updated_at FROM privileged_meta WHERE id=1"
        )
        if row is None:
            raise PrivilegedStoreError("privileged metadata singleton is absent")
        generation = _integer(row["evidence_generation_high_water"]) + 1
        metadata_time = max(recorded_at, _timestamp(row["updated_at"]))
        await self._connection.execute(
            "UPDATE privileged_meta SET evidence_generation_high_water=?,updated_at=? WHERE id=1",
            (generation, canonical_timestamp(metadata_time)),
        )
        return generation

    async def _append_event(
        self,
        *,
        generation: int,
        event_id: str,
        operation_id: str,
        event_type: str,
        event_sha256: str,
        recorded_at: datetime,
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO privileged_evidence_events (
              evidence_generation,event_id,operation_id,event_type,event_sha256,recorded_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                generation,
                event_id,
                operation_id,
                event_type,
                event_sha256,
                canonical_timestamp(recorded_at),
            ),
        )

    async def _required_binding(self, operation_id: str) -> sqlite3.Row:
        row = await self._fetchone(
            "SELECT * FROM privileged_operation_bindings WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            raise PrivilegedStoreError("privileged binding disappeared")
        return row

    async def _fetchone(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> sqlite3.Row | None:
        cursor = await self._connection.execute(query, parameters)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    def _receipt(
        row: sqlite3.Row,
        *,
        disposition: BrokerAcceptanceDisposition,
    ) -> BrokerAcceptanceReceipt:
        evidence_sha256 = row["acceptance_evidence_sha256"]
        if evidence_sha256 is None:
            raise PrivilegedStoreError("privileged decision lacks retained evidence")
        knowledge = (
            PrivilegedEffectKnowledge.KNOWN_NO_SUBEFFECT
            if disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN
            else PrivilegedEffectKnowledge.KNOWN_EFFECT
        )
        return BrokerAcceptanceReceipt(
            operation_id=str(row["operation_id"]),
            ticket_id=str(row["ticket_id"]),
            ticket_sha256=str(row["ticket_sha256"]),
            disposition=disposition,
            evidence_generation=_integer(row["evidence_generation"]),
            effect_knowledge=knowledge,
            evidence_sha256=str(evidence_sha256),
        )

    @staticmethod
    def _snapshot(
        row: sqlite3.Row,
        *,
        checkpoint: sqlite3.Row | None,
    ) -> BrokerBindingSnapshot:
        return BrokerBindingSnapshot(
            identity=PrivilegedTicketRoutingIdentity(
                operation_id=str(row["operation_id"]),
                ticket_id=str(row["ticket_id"]),
                ticket_sha256=str(row["ticket_sha256"]),
                ticket_nonce_sha256=str(row["ticket_nonce_sha256"]),
                action=PrivilegedAction(str(row["action"])),
                target_profile_id=str(row["target_profile_id"]),
                target_profile_sha256=str(row["target_profile_sha256"]),
                broker_profile_sha256=str(row["broker_profile_sha256"]),
                request_fingerprint_sha256=str(row["request_fingerprint_sha256"]),
                current_state_binding_sha256=str(row["current_state_binding_sha256"]),
                policy_evidence_sha256=str(row["policy_evidence_sha256"]),
                issued_at=_timestamp(row["created_at"]),
                expires_at=_timestamp(row["expires_at"]),
            ),
            acceptance_state=BrokerAcceptanceState(str(row["acceptance_state"])),
            evidence_generation=_integer(row["evidence_generation"]),
            acceptance_evidence_sha256=_optional_text(row["acceptance_evidence_sha256"]),
            execution_state=BrokerExecutionState(str(row["execution_state"])),
            effect_knowledge=PrivilegedEffectKnowledge(str(row["effect_knowledge"])),
            result_evidence_sha256=_optional_text(row["result_evidence_sha256"]),
            accepted_at=_optional_timestamp(row["accepted_at"]),
            sealed_at=_optional_timestamp(row["sealed_at"]),
            closed_at=_optional_timestamp(row["closed_at"]),
            last_reconciled_at=_optional_timestamp(row["last_reconciled_at"]),
            restart_checkpoint_sha256=(
                None if checkpoint is None else str(checkpoint["checkpoint_sha256"])
            ),
            restart_checkpoint_state=(
                None
                if checkpoint is None
                else BrokerRestartCheckpointState(str(checkpoint["state"]))
            ),
            restart_outcome=(
                None if checkpoint is None else BrokerRestartOutcome(str(checkpoint["outcome"]))
            ),
            candidate_slot_id=(
                None if checkpoint is None else str(checkpoint["candidate_slot_id"])
            ),
            lkg_slot_id=None if checkpoint is None else str(checkpoint["lkg_slot_id"]),
            selected_runtime_slot_id=(
                None if checkpoint is None else _optional_text(checkpoint["selected_slot_id"])
            ),
        )


async def open_privileged_store(
    *,
    settings: PrivilegedStoreSettings,
    identity: PrivilegedStoreIdentity,
    ticket_verifier: PrivilegedTicketVerifier,
    acceptance_enabled: bool = False,
) -> SqlitePrivilegedEvidenceStore:
    _validate_settings(settings)
    _verify_state_path(settings)
    runtime_lock = _acquire_lock(settings)
    try:
        try:
            integrity_connection = sqlite3.connect(
                f"file:{quote(str(settings.path), safe='/')}?mode=ro",
                uri=True,
            )
            try:
                report = verify_privileged_broker_connection(integrity_connection)
            finally:
                integrity_connection.close()
        except (PrivilegedBrokerIntegrityError, sqlite3.Error) as exc:
            raise PrivilegedStoreError("privileged durable evidence verification failed") from exc

        connection = await aiosqlite.connect(settings.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA synchronous=FULL")
        await connection.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
        meta = await _fetchone(connection, "SELECT * FROM privileged_meta WHERE id=1")
        if meta is None or _integer(meta["schema_generation"]) != 1:
            raise PrivilegedStoreError("privileged metadata is absent or incompatible")
        initialized = str(meta["build_sha256"]) != _ZERO_DIGEST
        retained_bindings = (
            report.unresolved_bindings + report.accepted_bindings + report.sealed_bindings
        )
        if (
            initialized
            and retained_bindings
            and (
                str(meta["build_sha256"]) != identity.build_sha256
                or str(meta["profile_sha256"]) != identity.profile_sha256
                or str(meta["protocol_version"]) != identity.protocol_version
            )
        ):
            raise PrivilegedStoreError("retained privileged evidence requires exact identity")
        outstanding = await _single_integer(
            connection,
            "SELECT COUNT(*) FROM privileged_operation_bindings "
            "WHERE acceptance_state='accepted' AND execution_state!='terminal'",
        )
        readiness = (
            "restricted_recovery"
            if outstanding
            else ("ready" if acceptance_enabled else "disabled")
        )
        now = datetime.now(UTC)
        await connection.execute("BEGIN IMMEDIATE")
        await connection.execute(
            """
            UPDATE privileged_meta
            SET broker_instance_id=?,broker_generation=broker_generation+1,
                protocol_version=?,build_sha256=?,profile_sha256=?,readiness=?,
                failure_reason=NULL,updated_at=? WHERE id=1
            """,
            (
                identity.broker_instance_id,
                identity.protocol_version,
                identity.build_sha256,
                identity.profile_sha256,
                readiness,
                canonical_timestamp(now),
            ),
        )
        generation_row = await _fetchone(
            connection,
            "SELECT broker_generation FROM privileged_meta WHERE id=1",
        )
        if generation_row is None:
            raise PrivilegedStoreError("privileged broker generation is absent")
        await connection.commit()
        return SqlitePrivilegedEvidenceStore(
            connection=connection,
            settings=settings,
            identity=identity,
            ticket_verifier=ticket_verifier,
            runtime_lock=runtime_lock,
            broker_generation=_integer(generation_row["broker_generation"]),
            acceptance_enabled=acceptance_enabled,
            readiness=readiness,
        )
    except BaseException:
        runtime_lock.close()
        if "connection" in locals():
            await connection.close()
        raise


def _validate_settings(settings: PrivilegedStoreSettings) -> None:
    if settings.path != Path("/var/lib/binnacle-privileged/evidence.db") and (
        settings.verify_permissions
    ):
        raise PrivilegedStoreError("privileged evidence path is fixed")
    if settings.runtime_directory != Path("/run/binnacle-privileged") and (
        settings.verify_permissions
    ):
        raise PrivilegedStoreError("privileged runtime path is fixed")
    if not 100 <= settings.busy_timeout_ms <= 60_000:
        raise PrivilegedStoreError("privileged busy timeout is outside the safe range")


def _verify_state_path(settings: PrivilegedStoreSettings) -> None:
    path = settings.path
    try:
        parent = path.parent.lstat()
        database = path.lstat()
    except OSError as exc:
        raise PrivilegedStoreError("privileged evidence path is unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISREG(database.st_mode)
        or stat.S_ISLNK(database.st_mode)
    ):
        raise PrivilegedStoreError("privileged evidence path is unsafe")
    if settings.verify_permissions and (
        parent.st_uid != 0
        or parent.st_gid != 0
        or stat.S_IMODE(parent.st_mode) != 0o700
        or database.st_uid != 0
        or database.st_gid != 0
        or stat.S_IMODE(database.st_mode) != 0o600
    ):
        raise PrivilegedStoreError("privileged evidence ownership or mode is invalid")


def _acquire_lock(settings: PrivilegedStoreSettings) -> _StoreLock:
    try:
        metadata = settings.runtime_directory.lstat()
    except OSError as exc:
        raise PrivilegedStoreError("privileged runtime directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise PrivilegedStoreError("privileged runtime directory is unsafe")
    if settings.verify_permissions and (
        metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o750
        or settings.runtime_group_gid is None
        or metadata.st_gid != settings.runtime_group_gid
    ):
        raise PrivilegedStoreError("privileged runtime ownership or mode is invalid")
    descriptor = os.open(
        settings.runtime_directory / "broker-writer.lock",
        os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        lock_metadata = os.fstat(descriptor)
        if settings.verify_permissions and (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != 0
            or lock_metadata.st_gid != 0
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
        ):
            raise PrivilegedStoreError("privileged writer lock ownership or mode is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except PrivilegedStoreError:
        os.close(descriptor)
        raise
    except BlockingIOError as exc:
        os.close(descriptor)
        raise PrivilegedStoreError("privileged writer or maintenance process is active") from exc
    except OSError as exc:
        os.close(descriptor)
        raise PrivilegedStoreError("privileged writer lock is unavailable") from exc
    return _StoreLock(descriptor)


async def _fetchone(
    connection: aiosqlite.Connection,
    query: str,
    parameters: Sequence[object] = (),
) -> sqlite3.Row | None:
    cursor = await connection.execute(query, parameters)
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def _single_integer(connection: aiosqlite.Connection, query: str) -> int:
    row = await _fetchone(connection, query)
    if row is None:
        raise PrivilegedStoreError("privileged database query returned no row")
    return _integer(row[0])


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PrivilegedStoreError("privileged timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_timestamp(value: object) -> datetime | None:
    return None if value is None else _timestamp(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrivilegedStoreError("privileged evidence integer is invalid")
    return value


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivilegedStoreError(f"{name} is not timezone-aware")


def _require_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PrivilegedStoreError(f"{name} digest is invalid")


__all__ = [
    "PrivilegedStoreConflict",
    "PrivilegedStoreError",
    "PrivilegedStoreIdentity",
    "PrivilegedStoreSettings",
    "RetainedRestartSubeffect",
    "RetainedSelectorGeneration",
    "SqlitePrivilegedEvidenceStore",
    "open_privileged_store",
]

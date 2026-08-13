"""Evidence-driven controlled restart and exact LKG recovery composition.

This module is intentionally absent from production composition until the configured
systemd/readiness mechanism and candidate-Pi evidence are promoted.  Its state machine,
ports, persistence order, and recovery behavior are evidence-independent and testable.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Protocol

from binnacle.domain.privileged import (
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedTicket,
    canonical_sha256,
)
from binnacle.domain.privileged_restart import (
    PrivilegedRestartCheckpointIntent,
    PrivilegedRestartCheckpointSnapshot,
)
from binnacle.privileged_broker.runtime_publication import RuntimeSelectorActivationRequest
from binnacle.privileged_broker.state import (
    RetainedRestartSubeffect,
    SqlitePrivilegedEvidenceStore,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE_RE = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")


class PrivilegedRestartExecutionError(RuntimeError):
    """Controlled restart composition or retained recovery is contradictory."""


class RestartDriverOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class RestartDriverResult:
    """Sanitized receiver-owned fact returned by one fixed root adapter call."""

    outcome: RestartDriverOutcome
    effect_started: bool
    effect_reference: str | None
    boundary_receipt_sha256: str | None
    result_evidence_sha256: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.result_evidence_sha256) is None:
            raise PrivilegedRestartExecutionError("restart driver result digest is invalid")
        if self.boundary_receipt_sha256 is not None and (
            _SHA256_RE.fullmatch(self.boundary_receipt_sha256) is None
        ):
            raise PrivilegedRestartExecutionError(
                "restart driver boundary receipt digest is invalid"
            )
        if self.effect_reference is not None and (
            _REFERENCE_RE.fullmatch(self.effect_reference) is None
        ):
            raise PrivilegedRestartExecutionError("restart driver reference is invalid")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise PrivilegedRestartExecutionError("restart driver observation is naive")
        if self.outcome is RestartDriverOutcome.UNCERTAIN and not self.effect_started:
            raise PrivilegedRestartExecutionError(
                "uncertain restart driver result lacks a crossed boundary"
            )
        if self.effect_started != (self.boundary_receipt_sha256 is not None):
            raise PrivilegedRestartExecutionError(
                "restart driver boundary receipt and effect truth disagree"
            )


class ControlledRestartDriver(Protocol):
    """Closed adapter surface; every target comes only from the retained checkpoint."""

    async def stop_service(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...

    async def stop_service_for_rollback(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...

    async def activate_candidate(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        request: RuntimeSelectorActivationRequest,
    ) -> RestartDriverResult: ...

    async def start_candidate(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...

    async def verify_candidate(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...

    async def restore_lkg(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        request: RuntimeSelectorActivationRequest,
    ) -> RestartDriverResult: ...

    async def start_lkg(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...

    async def verify_lkg(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult: ...


DriverCall = Callable[[PrivilegedRestartCheckpointSnapshot], Awaitable[RestartDriverResult]]


class PrivilegedRestartCoordinator:
    """Accept once, checkpoint first, then resume exact candidate/LKG phases."""

    def __init__(
        self,
        *,
        store: SqlitePrivilegedEvidenceStore,
        driver: ControlledRestartDriver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._driver = driver
        self._clock = clock or (lambda: datetime.now(UTC))
        self._operation_locks: dict[str, asyncio.Lock] = {}

    async def start(
        self,
        ticket: PrivilegedTicket,
        intent: PrivilegedRestartCheckpointIntent,
    ) -> BrokerAcceptanceReceipt:
        """Retain authority/checkpoint, then run independently of the application process."""

        if ticket.action is not PrivilegedAction.CONTROLLED_RESTART:
            raise PrivilegedRestartExecutionError(
                "controlled restart coordinator received another action"
            )
        receipt = await self._store.accept_once(ticket)
        if receipt.disposition is BrokerAcceptanceDisposition.NO_ACCEPT_PROVEN:
            return receipt
        await self._store.create_restart_checkpoint(ticket=ticket, intent=intent)
        await self.resume(ticket.operation_id)
        return receipt

    async def recover_all(self) -> tuple[PrivilegedRestartCheckpointSnapshot, ...]:
        """Resume every retained checkpoint; accepted/no-checkpoint gaps remain closed."""

        results: list[PrivilegedRestartCheckpointSnapshot] = []
        for operation_id in await self._store.restart_recovery_operation_ids():
            checkpoint = await self._store.get_restart_checkpoint(operation_id)
            if checkpoint is None:
                # Acceptance crossed but no exact checkpoint inputs survived.  The broker
                # must retain exclusive authority until the exact signed request is replayed.
                continue
            results.append(await self.resume(operation_id))
        return tuple(results)

    async def resume(self, operation_id: str) -> PrivilegedRestartCheckpointSnapshot:
        lock = self._operation_locks.setdefault(operation_id, asyncio.Lock())
        async with lock:
            for _ in range(16):
                checkpoint = await self._store.get_restart_checkpoint(operation_id)
                if checkpoint is None:
                    raise PrivilegedRestartExecutionError("accepted restart checkpoint is absent")
                if checkpoint.state in {
                    BrokerRestartCheckpointState.TERMINAL,
                    BrokerRestartCheckpointState.RESTRICTED_RECOVERY,
                }:
                    return checkpoint
                if checkpoint.state is BrokerRestartCheckpointState.CHECKPOINTED:
                    result = await self._run_phase(
                        checkpoint,
                        phase="service_stop",
                        kind="service_stop",
                        call=self._driver.stop_service,
                    )
                    if result.outcome is RestartDriverOutcome.UNCERTAIN or (
                        result.outcome is RestartDriverOutcome.FAILED and result.effect_started
                    ):
                        return await self._restrict(checkpoint, result)
                    if result.outcome is RestartDriverOutcome.FAILED:
                        return await self._terminal(
                            checkpoint,
                            BrokerRestartOutcome.NO_SUBEFFECT,
                            selected_slot_id=None,
                            result=result,
                        )
                    await self._store.advance_restart_checkpoint(
                        operation_id=operation_id,
                        expected_state=checkpoint.state,
                        next_state=BrokerRestartCheckpointState.SERVICE_STOPPED,
                        selected_slot_id=None,
                        service_stopped=True,
                        recorded_at=self._transition_time(checkpoint, result),
                    )
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.SERVICE_STOPPED:
                    selector = await self._store.begin_selector_change(
                        operation_id=operation_id,
                        expected_current_slot_id=checkpoint.intent.lkg_slot.slot_id,
                        target_slot_id=checkpoint.intent.candidate_slot.slot_id,
                        requested_at=checkpoint.updated_at,
                    )
                    result = await self._run_phase(
                        checkpoint,
                        phase="candidate_select",
                        kind="selector_activate",
                        call=partial(
                            self._driver.activate_candidate,
                            request=selector.request,
                        ),
                    )
                    await self._store.finish_selector_change(
                        request=selector.request,
                        succeeded=result.outcome is RestartDriverOutcome.SUCCEEDED,
                        uncertain=result.outcome is RestartDriverOutcome.UNCERTAIN,
                        effect_started=result.effect_started,
                        evidence_sha256=result.result_evidence_sha256,
                        recorded_at=result.observed_at,
                    )
                    if result.outcome is RestartDriverOutcome.SUCCEEDED:
                        await self._store.advance_restart_checkpoint(
                            operation_id=operation_id,
                            expected_state=checkpoint.state,
                            next_state=BrokerRestartCheckpointState.CANDIDATE_SELECTED,
                            selected_slot_id=checkpoint.intent.candidate_slot.slot_id,
                            recorded_at=self._transition_time(checkpoint, result),
                        )
                        continue
                    if result.outcome is RestartDriverOutcome.UNCERTAIN or (
                        result.outcome is RestartDriverOutcome.FAILED and result.effect_started
                    ):
                        return await self._restrict(checkpoint, result)
                    await self._require_rollback(checkpoint, result=result)
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.CANDIDATE_SELECTED:
                    result = await self._run_phase(
                        checkpoint,
                        phase="candidate_start",
                        kind="service_start",
                        call=self._driver.start_candidate,
                    )
                    if result.outcome is RestartDriverOutcome.SUCCEEDED:
                        await self._store.advance_restart_checkpoint(
                            operation_id=operation_id,
                            expected_state=checkpoint.state,
                            next_state=BrokerRestartCheckpointState.CANDIDATE_STARTED,
                            selected_slot_id=checkpoint.intent.candidate_slot.slot_id,
                            recorded_at=self._transition_time(checkpoint, result),
                        )
                        continue
                    if result.outcome is RestartDriverOutcome.UNCERTAIN:
                        return await self._restrict(checkpoint, result)
                    await self._require_rollback(checkpoint, result=result)
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.CANDIDATE_STARTED:
                    await self._store.advance_restart_checkpoint(
                        operation_id=operation_id,
                        expected_state=checkpoint.state,
                        next_state=BrokerRestartCheckpointState.VERIFYING,
                        selected_slot_id=checkpoint.intent.candidate_slot.slot_id,
                        recorded_at=self._transition_time(checkpoint),
                    )
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.VERIFYING:
                    result = await self._run_phase(
                        checkpoint,
                        phase="candidate_verify",
                        kind="runtime_verify",
                        call=self._driver.verify_candidate,
                    )
                    if result.outcome is RestartDriverOutcome.SUCCEEDED:
                        await self._store.verify_selector_change(
                            operation_id=operation_id,
                            target_slot_id=checkpoint.intent.candidate_slot.slot_id,
                            verification_evidence_sha256=(result.result_evidence_sha256),
                            restored=False,
                            recorded_at=result.observed_at,
                        )
                        return await self._terminal(
                            checkpoint,
                            BrokerRestartOutcome.CANDIDATE_READY,
                            selected_slot_id=checkpoint.intent.candidate_slot.slot_id,
                            result=result,
                        )
                    if result.outcome is RestartDriverOutcome.UNCERTAIN:
                        return await self._restrict(checkpoint, result)
                    await self._require_rollback(checkpoint, result=result)
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.ROLLBACK_REQUIRED:
                    result = await self._run_phase(
                        checkpoint,
                        phase="rollback_service_stop",
                        kind="service_stop",
                        call=self._driver.stop_service_for_rollback,
                    )
                    if result.outcome is not RestartDriverOutcome.SUCCEEDED:
                        return await self._restrict(checkpoint, result)
                    await self._store.advance_restart_checkpoint(
                        operation_id=operation_id,
                        expected_state=checkpoint.state,
                        next_state=(BrokerRestartCheckpointState.ROLLBACK_SERVICE_STOPPED),
                        selected_slot_id=checkpoint.selected_slot_id,
                        recorded_at=self._transition_time(checkpoint, result),
                    )
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.ROLLBACK_SERVICE_STOPPED:
                    rollback = await self._select_rollback(checkpoint)
                    if rollback.state is BrokerRestartCheckpointState.RESTRICTED_RECOVERY:
                        return rollback
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.ROLLBACK_SELECTED:
                    result = await self._run_phase(
                        checkpoint,
                        phase="lkg_start",
                        kind="service_start",
                        call=self._driver.start_lkg,
                    )
                    if result.outcome is not RestartDriverOutcome.SUCCEEDED:
                        return await self._restrict(checkpoint, result)
                    await self._store.advance_restart_checkpoint(
                        operation_id=operation_id,
                        expected_state=checkpoint.state,
                        next_state=BrokerRestartCheckpointState.ROLLBACK_STARTED,
                        selected_slot_id=checkpoint.intent.lkg_slot.slot_id,
                        recorded_at=self._transition_time(checkpoint, result),
                    )
                    continue
                if checkpoint.state is BrokerRestartCheckpointState.ROLLBACK_STARTED:
                    result = await self._run_phase(
                        checkpoint,
                        phase="lkg_verify",
                        kind="runtime_verify",
                        call=self._driver.verify_lkg,
                    )
                    if result.outcome is not RestartDriverOutcome.SUCCEEDED:
                        return await self._restrict(checkpoint, result)
                    await self._store.verify_selector_change(
                        operation_id=operation_id,
                        target_slot_id=checkpoint.intent.lkg_slot.slot_id,
                        verification_evidence_sha256=result.result_evidence_sha256,
                        restored=True,
                        recorded_at=result.observed_at,
                    )
                    return await self._terminal(
                        checkpoint,
                        BrokerRestartOutcome.ROLLBACK_READY,
                        selected_slot_id=checkpoint.intent.lkg_slot.slot_id,
                        result=result,
                    )
                raise PrivilegedRestartExecutionError(
                    f"unsupported retained restart state: {checkpoint.state.value}"
                )
        raise PrivilegedRestartExecutionError("restart recovery exceeded its state bound")

    async def _select_rollback(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
    ) -> PrivilegedRestartCheckpointSnapshot:
        expected_current_slot_id = (
            checkpoint.intent.lkg_slot.slot_id
            if checkpoint.selected_slot_id is None
            else checkpoint.intent.candidate_slot.slot_id
        )
        selector = await self._store.begin_selector_change(
            operation_id=checkpoint.intent.operation_id,
            expected_current_slot_id=expected_current_slot_id,
            target_slot_id=checkpoint.intent.lkg_slot.slot_id,
            requested_at=checkpoint.updated_at,
        )
        result = await self._run_phase(
            checkpoint,
            phase="lkg_select",
            kind="selector_restore",
            call=partial(self._driver.restore_lkg, request=selector.request),
        )
        await self._store.finish_selector_change(
            request=selector.request,
            succeeded=result.outcome is RestartDriverOutcome.SUCCEEDED,
            uncertain=result.outcome is RestartDriverOutcome.UNCERTAIN,
            effect_started=result.effect_started,
            evidence_sha256=result.result_evidence_sha256,
            recorded_at=result.observed_at,
        )
        if result.outcome is not RestartDriverOutcome.SUCCEEDED:
            return await self._restrict(checkpoint, result)
        return await self._store.advance_restart_checkpoint(
            operation_id=checkpoint.intent.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.ROLLBACK_SELECTED,
            selected_slot_id=checkpoint.intent.lkg_slot.slot_id,
            recorded_at=self._transition_time(checkpoint, result),
        )

    async def _require_rollback(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        *,
        result: RestartDriverResult,
    ) -> PrivilegedRestartCheckpointSnapshot:
        return await self._store.advance_restart_checkpoint(
            operation_id=checkpoint.intent.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.ROLLBACK_REQUIRED,
            selected_slot_id=checkpoint.selected_slot_id,
            recorded_at=self._transition_time(checkpoint, result),
        )

    async def _run_phase(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        *,
        phase: str,
        kind: str,
        call: DriverCall,
    ) -> RestartDriverResult:
        intent_sha256 = canonical_sha256(
            {
                "checkpoint_sha256": checkpoint.checkpoint_sha256,
                "expected_state": checkpoint.state,
                "phase": phase,
                "selected_slot_id": checkpoint.selected_slot_id,
            }
        )
        retained = await self._store.begin_restart_subeffect(
            operation_id=checkpoint.intent.operation_id,
            phase=phase,
            kind=kind,
            intent_sha256=intent_sha256,
            recorded_at=self._transition_time(checkpoint),
        )
        if retained.complete:
            return self._retained_result(retained)
        try:
            result = await call(checkpoint)
        except Exception as exc:  # noqa: BLE001 - unknown boundary outcome is retained.
            observed_at = self._transition_time(checkpoint)
            result = RestartDriverResult(
                outcome=RestartDriverOutcome.UNCERTAIN,
                effect_started=True,
                effect_reference=f"driver_exception:{type(exc).__name__}",
                boundary_receipt_sha256=canonical_sha256(
                    {"exception_type": type(exc).__name__, "phase": phase}
                ),
                result_evidence_sha256=canonical_sha256(
                    {
                        "checkpoint_sha256": checkpoint.checkpoint_sha256,
                        "exception_type": type(exc).__name__,
                        "phase": phase,
                        "truth": "uncertain",
                    }
                ),
                observed_at=observed_at,
            )
        if result.observed_at < checkpoint.updated_at:
            raise PrivilegedRestartExecutionError("restart driver result time regressed")
        retained = await self._store.finish_restart_subeffect(
            operation_id=checkpoint.intent.operation_id,
            subeffect_id=retained.subeffect_id,
            effect_started=result.effect_started,
            effect_reference=result.effect_reference,
            boundary_receipt_sha256=result.boundary_receipt_sha256,
            result_evidence_sha256=result.result_evidence_sha256,
            succeeded=result.outcome is RestartDriverOutcome.SUCCEEDED,
            uncertain=result.outcome is RestartDriverOutcome.UNCERTAIN,
            recorded_at=result.observed_at,
        )
        return self._retained_result(retained)

    async def _terminal(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        outcome: BrokerRestartOutcome,
        *,
        selected_slot_id: str | None,
        result: RestartDriverResult,
    ) -> PrivilegedRestartCheckpointSnapshot:
        evidence = canonical_sha256(
            {
                "checkpoint_sha256": checkpoint.checkpoint_sha256,
                "driver_result_sha256": result.result_evidence_sha256,
                "outcome": outcome,
                "selected_slot_id": selected_slot_id,
            }
        )
        return await self._store.advance_restart_checkpoint(
            operation_id=checkpoint.intent.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.TERMINAL,
            selected_slot_id=selected_slot_id,
            outcome=outcome,
            result_evidence_sha256=evidence,
            recorded_at=self._transition_time(checkpoint, result),
        )

    async def _restrict(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        result: RestartDriverResult,
    ) -> PrivilegedRestartCheckpointSnapshot:
        evidence = canonical_sha256(
            {
                "checkpoint_sha256": checkpoint.checkpoint_sha256,
                "driver_outcome": result.outcome,
                "driver_result_sha256": result.result_evidence_sha256,
                "state": checkpoint.state,
            }
        )
        return await self._store.advance_restart_checkpoint(
            operation_id=checkpoint.intent.operation_id,
            expected_state=checkpoint.state,
            next_state=BrokerRestartCheckpointState.RESTRICTED_RECOVERY,
            selected_slot_id=checkpoint.selected_slot_id,
            outcome=BrokerRestartOutcome.RESTRICTED_RECOVERY,
            result_evidence_sha256=evidence,
            recorded_at=self._transition_time(checkpoint, result),
        )

    def _transition_time(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        result: RestartDriverResult | None = None,
    ) -> datetime:
        candidates = [checkpoint.updated_at, self._clock()]
        if result is not None:
            candidates.append(result.observed_at)
        if any(value.tzinfo is None or value.utcoffset() is None for value in candidates):
            raise PrivilegedRestartExecutionError("restart transition clock is naive")
        return max(candidates)

    @staticmethod
    def _retained_result(retained: RetainedRestartSubeffect) -> RestartDriverResult:
        if not retained.complete or retained.result_evidence_sha256 is None:
            raise PrivilegedRestartExecutionError("restart subeffect is not terminal")
        try:
            outcome = RestartDriverOutcome(retained.outcome)
        except ValueError as exc:
            raise PrivilegedRestartExecutionError(
                "retained restart subeffect outcome is invalid"
            ) from exc
        return RestartDriverResult(
            outcome=outcome,
            effect_started=retained.effect_started,
            effect_reference=retained.effect_reference,
            boundary_receipt_sha256=retained.boundary_receipt_sha256,
            result_evidence_sha256=retained.result_evidence_sha256,
            observed_at=retained.updated_at,
        )


__all__ = [
    "ControlledRestartDriver",
    "PrivilegedRestartCoordinator",
    "PrivilegedRestartExecutionError",
    "RestartDriverOutcome",
    "RestartDriverResult",
]

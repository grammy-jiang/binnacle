"""Fixed, default-uncomposed Linux driver for controlled runtime-slot restart.

The production broker intentionally does not instantiate these classes until promotion
evidence exists.  The implementation itself is closed: one systemd unit, one protected
selector publisher, exact retained slots, bounded output, and exact readiness matching.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from binnacle.domain.privileged import canonical_sha256
from binnacle.domain.privileged_observation import (
    RuntimeIdentity,
    ServiceInspectionResult,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointSnapshot
from binnacle.privileged_broker.restart import (
    ControlledRestartDriver,
    RestartDriverOutcome,
    RestartDriverResult,
)
from binnacle.privileged_broker.runtime_publication import (
    FilesystemRuntimeSlotPublisher,
    RuntimeSelectorActivationRequest,
    RuntimeSelectorConflict,
    RuntimeSelectorPublicationUncertain,
    RuntimeSlotPublicationError,
)

_SERVICE_UNIT: Final = "binnacle-dev.service"
_SYSTEMCTL: Final = Path("/usr/bin/systemctl")


class RestartDriverAdapterError(RuntimeError):
    """The fixed service/selector/readiness adapter is invalid or contradictory."""


class SystemdAction(StrEnum):
    START = "start"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class FixedSystemdSettings:
    systemctl_path: Path = _SYSTEMCTL
    timeout_seconds: int = 120
    require_fixed_path: bool = True

    def __post_init__(self) -> None:
        if self.require_fixed_path and self.systemctl_path != _SYSTEMCTL:
            raise RestartDriverAdapterError("systemctl path is outside the fixed profile")
        if (
            not self.systemctl_path.is_absolute()
            or self.systemctl_path != Path(os.path.normpath(str(self.systemctl_path)))
            or not 1 <= self.timeout_seconds <= 900
        ):
            raise RestartDriverAdapterError("systemd adapter settings are invalid")


class FixedSystemdServiceManager:
    """Invoke only start/stop for the one reviewed Binnacle development unit."""

    def __init__(
        self,
        settings: FixedSystemdSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or FixedSystemdSettings()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def stop(self) -> RestartDriverResult:
        return await self._run(SystemdAction.STOP)

    async def start(self) -> RestartDriverResult:
        return await self._run(SystemdAction.START)

    async def _run(self, action: SystemdAction) -> RestartDriverResult:
        command_sha256 = canonical_sha256(
            {
                "action": action,
                "service_unit": _SERVICE_UNIT,
                "systemctl_path": str(self._settings.systemctl_path),
            }
        )
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._settings.systemctl_path),
                "--no-ask-password",
                action.value,
                _SERVICE_UNIT,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            observed_at = self._aware_now()
            return RestartDriverResult(
                outcome=RestartDriverOutcome.FAILED,
                effect_started=False,
                effect_reference=None,
                boundary_receipt_sha256=None,
                result_evidence_sha256=canonical_sha256(
                    {
                        "command_sha256": command_sha256,
                        "error_type": type(exc).__name__,
                        "outcome": "not_started",
                        "observed_at": observed_at,
                    }
                ),
                observed_at=observed_at,
            )

        boundary_sha256 = canonical_sha256(
            {
                "command_sha256": command_sha256,
                "effect_reference": f"systemd:{action.value}:{process.pid}",
                "state": "command_started",
            }
        )
        try:
            return_code = await asyncio.wait_for(
                process.wait(),
                timeout=self._settings.timeout_seconds,
            )
            outcome = (
                RestartDriverOutcome.SUCCEEDED if return_code == 0 else RestartDriverOutcome.FAILED
            )
        except (TimeoutError, asyncio.CancelledError):
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(Exception):
                await process.wait()
            return_code = None
            outcome = RestartDriverOutcome.UNCERTAIN
        observed_at = self._aware_now()
        return RestartDriverResult(
            outcome=outcome,
            effect_started=True,
            effect_reference=f"systemd:{action.value}:{process.pid}",
            boundary_receipt_sha256=boundary_sha256,
            result_evidence_sha256=canonical_sha256(
                {
                    "boundary_receipt_sha256": boundary_sha256,
                    "command_sha256": command_sha256,
                    "outcome": outcome,
                    "return_code": return_code,
                    "observed_at": observed_at,
                }
            ),
            observed_at=observed_at,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RestartDriverAdapterError("systemd adapter clock is naive")
        return value


@dataclass(frozen=True, slots=True)
class RestartRuntimeObservation:
    """One receiver-owned correlated view of service, readiness, and selector truth."""

    service: ServiceInspectionResult
    runtime: RuntimeIdentity | None
    current_slot: VerifiedRuntimeSlot | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise RestartDriverAdapterError("restart runtime observation is naive")
        if self.service.observed_at > self.observed_at:
            raise RestartDriverAdapterError("service observation is from the future")
        if self.runtime is None and self.service.runtime_identity_sha256 is not None:
            raise RestartDriverAdapterError("service readiness has no correlated runtime identity")


class RestartRuntimeProbe(Protocol):
    async def observe(self) -> RestartRuntimeObservation: ...


@dataclass(frozen=True, slots=True)
class ExactRestartVerifierSettings:
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not 0.01 <= self.poll_interval_seconds <= 5.0:
            raise RestartDriverAdapterError("restart verifier poll interval is invalid")


class ExactRestartRuntimeVerifier:
    """Require exact selected-slot, service, and application readiness identities."""

    def __init__(
        self,
        *,
        probe: RestartRuntimeProbe,
        settings: ExactRestartVerifierSettings | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._probe = probe
        self._settings = settings or ExactRestartVerifierSettings()
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or asyncio.sleep

    async def verify(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        *,
        expected_slot: VerifiedRuntimeSlot,
    ) -> RestartDriverResult:
        deadline = self._monotonic() + checkpoint.intent.restart_deadline_seconds
        last: RestartRuntimeObservation | None = None
        while True:
            try:
                last = await self._probe.observe()
            except Exception as exc:  # noqa: BLE001 - readiness truth is unavailable.
                observed_at = datetime.now(UTC)
                return self._uncertain(checkpoint, expected_slot, type(exc).__name__, observed_at)
            disposition = self._classify(
                checkpoint,
                expected_slot=expected_slot,
                observation=last,
            )
            observed_monotonic = self._monotonic()
            if disposition is not None:
                if (
                    disposition.outcome is not RestartDriverOutcome.SUCCEEDED
                    or observed_monotonic < deadline
                ):
                    return disposition
                return self._failure(
                    checkpoint,
                    expected_slot,
                    last,
                    reason="readiness_deadline_elapsed",
                )
            remaining = deadline - observed_monotonic
            if remaining <= 0:
                return self._failure(
                    checkpoint,
                    expected_slot,
                    last,
                    reason="readiness_deadline_elapsed",
                )
            await self._sleep(min(self._settings.poll_interval_seconds, remaining))

    @staticmethod
    def _classify(
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        *,
        expected_slot: VerifiedRuntimeSlot,
        observation: RestartRuntimeObservation,
    ) -> RestartDriverResult | None:
        service = observation.service
        runtime = observation.runtime
        selected = observation.current_slot
        if selected is not None and selected != expected_slot:
            return ExactRestartRuntimeVerifier._failure(
                checkpoint,
                expected_slot,
                observation,
                reason="selected_slot_identity_mismatch",
            )
        if service.active_state == "active" and service.sub_state == "running":
            if runtime is not None and not ExactRestartRuntimeVerifier._matches(
                checkpoint,
                slot=expected_slot,
                service=service,
                runtime=runtime,
            ):
                return ExactRestartRuntimeVerifier._failure(
                    checkpoint,
                    expected_slot,
                    observation,
                    reason="runtime_identity_mismatch",
                )
            if selected is None or runtime is None or service.application_ready is not True:
                return None
            return RestartDriverResult(
                outcome=RestartDriverOutcome.SUCCEEDED,
                effect_started=False,
                effect_reference=None,
                boundary_receipt_sha256=None,
                result_evidence_sha256=canonical_sha256(
                    {
                        "checkpoint_sha256": checkpoint.checkpoint_sha256,
                        "expected_slot_sha256": expected_slot.slot_identity_sha256,
                        "observation": asdict(observation),
                        "outcome": "ready",
                    }
                ),
                observed_at=observation.observed_at,
            )
        if service.active_state in {"failed"} or service.sub_state == "failed":
            return ExactRestartRuntimeVerifier._failure(
                checkpoint,
                expected_slot,
                observation,
                reason="service_failed",
            )
        return None

    @staticmethod
    def _matches(
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        *,
        slot: VerifiedRuntimeSlot,
        service: ServiceInspectionResult,
        runtime: RuntimeIdentity,
    ) -> bool:
        stopped_at = checkpoint.service_stopped_at
        return (
            service.service_unit == _SERVICE_UNIT
            and service.service_profile_sha256 == checkpoint.intent.service_profile_sha256
            and service.runtime_identity_sha256 == runtime.runtime_identity_sha256
            and runtime.runtime_slot_identity_sha256 == slot.slot_identity_sha256
            and (stopped_at is None or runtime.process_started_at >= stopped_at)
            and (
                runtime.source_state_sha256,
                runtime.environment_sha256,
                runtime.config_sha256,
                runtime.policy_sha256,
                runtime.manifest_sha256,
                runtime.schema_heads_sha256,
                runtime.runtime_layout_sha256,
                runtime.deployed_peer_set_sha256,
            )
            == (
                slot.source_sha256,
                slot.environment_sha256,
                slot.config_sha256,
                slot.policy_sha256,
                slot.manifest_sha256,
                slot.migration_heads_sha256,
                slot.layout_sha256,
                slot.deployed_peer_set_sha256,
            )
        )

    @staticmethod
    def _failure(
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        expected_slot: VerifiedRuntimeSlot,
        observation: RestartRuntimeObservation,
        *,
        reason: str,
    ) -> RestartDriverResult:
        return RestartDriverResult(
            outcome=RestartDriverOutcome.FAILED,
            effect_started=False,
            effect_reference=None,
            boundary_receipt_sha256=None,
            result_evidence_sha256=canonical_sha256(
                {
                    "checkpoint_sha256": checkpoint.checkpoint_sha256,
                    "expected_slot_sha256": expected_slot.slot_identity_sha256,
                    "observation": asdict(observation),
                    "outcome": "failed",
                    "reason": reason,
                }
            ),
            observed_at=observation.observed_at,
        )

    @staticmethod
    def _uncertain(
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        expected_slot: VerifiedRuntimeSlot,
        error_type: str,
        observed_at: datetime,
    ) -> RestartDriverResult:
        boundary = canonical_sha256(
            {
                "checkpoint_sha256": checkpoint.checkpoint_sha256,
                "prior_effect": "service_start",
                "selected_slot_sha256": expected_slot.slot_identity_sha256,
            }
        )
        return RestartDriverResult(
            outcome=RestartDriverOutcome.UNCERTAIN,
            effect_started=True,
            effect_reference="readiness:unavailable",
            boundary_receipt_sha256=boundary,
            result_evidence_sha256=canonical_sha256(
                {
                    "boundary_receipt_sha256": boundary,
                    "checkpoint_sha256": checkpoint.checkpoint_sha256,
                    "error_type": error_type,
                    "outcome": "uncertain",
                }
            ),
            observed_at=observed_at,
        )


class FixedControlledRestartDriver(ControlledRestartDriver):
    """Compose fixed systemd, crash-safe selector CAS, and exact runtime verification."""

    def __init__(
        self,
        *,
        service: FixedSystemdServiceManager,
        publisher: FilesystemRuntimeSlotPublisher,
        verifier: ExactRestartRuntimeVerifier,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._publisher = publisher
        self._verifier = verifier
        self._clock = clock or (lambda: datetime.now(UTC))

    async def stop_service(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        del checkpoint
        return await self._service.stop()

    async def stop_service_for_rollback(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        del checkpoint
        return await self._service.stop()

    async def activate_candidate(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        request: RuntimeSelectorActivationRequest,
    ) -> RestartDriverResult:
        if request.target_slot_id != checkpoint.intent.candidate_slot.slot_id:
            raise RestartDriverAdapterError("candidate selector target differs")
        return await self._select(request)

    async def start_candidate(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        del checkpoint
        return await self._service.start()

    async def verify_candidate(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        return await self._verifier.verify(
            checkpoint,
            expected_slot=checkpoint.intent.candidate_slot,
        )

    async def restore_lkg(
        self,
        checkpoint: PrivilegedRestartCheckpointSnapshot,
        request: RuntimeSelectorActivationRequest,
    ) -> RestartDriverResult:
        if request.target_slot_id != checkpoint.intent.lkg_slot.slot_id:
            raise RestartDriverAdapterError("LKG selector target differs")
        return await self._select(request)

    async def start_lkg(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        del checkpoint
        return await self._service.start()

    async def verify_lkg(
        self, checkpoint: PrivilegedRestartCheckpointSnapshot
    ) -> RestartDriverResult:
        return await self._verifier.verify(
            checkpoint,
            expected_slot=checkpoint.intent.lkg_slot,
        )

    async def _select(
        self,
        request: RuntimeSelectorActivationRequest,
    ) -> RestartDriverResult:
        observed_at = self._aware_now()
        try:
            receipt = await asyncio.to_thread(
                self._publisher.activate_complete_slot,
                request,
                observed_at=observed_at,
            )
        except RuntimeSelectorPublicationUncertain as exc:
            evidence = canonical_sha256(
                {
                    "error_type": type(exc).__name__,
                    "intent_sha256": request.retained_intent_sha256,
                    "outcome": "uncertain",
                }
            )
            return RestartDriverResult(
                outcome=RestartDriverOutcome.UNCERTAIN,
                effect_started=True,
                effect_reference=f"selector:{request.selector_generation}",
                boundary_receipt_sha256=evidence,
                result_evidence_sha256=evidence,
                observed_at=observed_at,
            )
        except (RuntimeSelectorConflict, RuntimeSlotPublicationError) as exc:
            return RestartDriverResult(
                outcome=RestartDriverOutcome.FAILED,
                effect_started=False,
                effect_reference=None,
                boundary_receipt_sha256=None,
                result_evidence_sha256=canonical_sha256(
                    {
                        "error_type": type(exc).__name__,
                        "intent_sha256": request.retained_intent_sha256,
                        "outcome": "not_published",
                    }
                ),
                observed_at=observed_at,
            )
        return RestartDriverResult(
            outcome=RestartDriverOutcome.SUCCEEDED,
            effect_started=receipt.selector_changed,
            effect_reference=(
                f"selector:{request.selector_generation}" if receipt.selector_changed else None
            ),
            boundary_receipt_sha256=(receipt.receipt_sha256 if receipt.selector_changed else None),
            result_evidence_sha256=receipt.receipt_sha256,
            observed_at=receipt.observed_at,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RestartDriverAdapterError("restart driver clock is naive")
        return value


__all__ = [
    "ExactRestartRuntimeVerifier",
    "ExactRestartVerifierSettings",
    "FixedControlledRestartDriver",
    "FixedSystemdServiceManager",
    "FixedSystemdSettings",
    "RestartDriverAdapterError",
    "RestartRuntimeObservation",
    "RestartRuntimeProbe",
    "SystemdAction",
]

"""Strict normalization of read-only systemd and application readiness facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.privileged import BinnacleServiceProfile
from binnacle.domain.privileged_observation import (
    PrivilegedObservationError,
    ServiceInspectionResult,
)

_TOKEN_RE: Final = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_LOAD_STATES: Final = frozenset({"loaded", "not-found", "masked", "error"})
_ALLOWED_ACTIVE_STATES: Final = frozenset(
    {"active", "reloading", "inactive", "failed", "activating", "deactivating"}
)
_ALLOWED_SUB_STATES: Final = frozenset(
    {"running", "start", "stop", "dead", "failed", "exited", "auto-restart"}
)
_ALLOWED_RESULTS: Final = frozenset(
    {
        "success",
        "exit-code",
        "signal",
        "core-dump",
        "timeout",
        "watchdog",
        "start-limit-hit",
        "resources",
        "protocol",
    }
)


class ServiceInspectionError(RuntimeError):
    """Service-manager or readiness evidence is ambiguous or outside the profile."""


@dataclass(frozen=True, slots=True)
class ServiceManagerSnapshot:
    """Exact bounded systemd property projection from the fixed service unit."""

    service_unit: str
    load_state: str
    active_state: str
    sub_state: str
    result: str | None
    main_pid: int
    main_process_started_at: datetime | None
    unit_definition_sha256: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.service_unit != "binnacle-dev.service":
            raise ServiceInspectionError("service manager snapshot targets another unit")
        if self.load_state not in _ALLOWED_LOAD_STATES:
            raise ServiceInspectionError("service load state is unsupported")
        if self.active_state not in _ALLOWED_ACTIVE_STATES:
            raise ServiceInspectionError("service active state is unsupported")
        if self.sub_state not in _ALLOWED_SUB_STATES:
            raise ServiceInspectionError("service sub-state is unsupported")
        if self.result is not None and self.result not in _ALLOWED_RESULTS:
            raise ServiceInspectionError("service result is unsupported")
        if not 0 <= self.main_pid <= 2_147_483_647:
            raise ServiceInspectionError("service main PID is invalid")
        if (self.main_pid == 0) != (self.main_process_started_at is None):
            raise ServiceInspectionError("service PID and start time disagree")
        if self.main_process_started_at is not None:
            _require_aware(self.main_process_started_at)
        _require_aware(self.observed_at)
        if (
            self.main_process_started_at is not None
            and self.main_process_started_at > self.observed_at
        ):
            raise ServiceInspectionError("service process starts after its observation")
        if _SHA256_RE.fullmatch(self.unit_definition_sha256) is None:
            raise ServiceInspectionError("service unit definition digest is invalid")


@dataclass(frozen=True, slots=True)
class ApplicationReadinessSnapshot:
    """Bounded application-generated readiness receipt, never inferred from systemd active."""

    service_unit: str
    main_pid: int
    runtime_instance_id: str
    runtime_identity_sha256: str
    ready: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.service_unit != "binnacle-dev.service":
            raise ServiceInspectionError("readiness snapshot targets another unit")
        if not 1 <= self.main_pid <= 2_147_483_647:
            raise ServiceInspectionError("readiness PID is invalid")
        if _TOKEN_RE.fullmatch(self.runtime_instance_id) is None:
            raise ServiceInspectionError("readiness runtime instance is invalid")
        if _SHA256_RE.fullmatch(self.runtime_identity_sha256) is None:
            raise ServiceInspectionError("readiness runtime identity digest is invalid")
        _require_aware(self.observed_at)


class FixedServiceInspectionNormalizer:
    """Bind systemd state and optional readiness to one protected service profile."""

    def __init__(self, profile: BinnacleServiceProfile) -> None:
        self._profile = profile

    def normalize(
        self,
        manager: ServiceManagerSnapshot,
        readiness: ApplicationReadinessSnapshot | None,
    ) -> ServiceInspectionResult:
        if not self._profile.active:
            raise ServiceInspectionError("service profile is not active")
        if manager.service_unit != self._profile.service_unit:
            raise ServiceInspectionError("service manager snapshot conflicts with the profile")
        if manager.unit_definition_sha256 != self._profile.stable_unit_sha256:
            raise ServiceInspectionError("effective service definition differs")
        runtime_identity_sha256: str | None = None
        application_ready: bool | None = None
        if readiness is not None:
            if (
                manager.main_pid == 0
                or readiness.service_unit != manager.service_unit
                or readiness.main_pid != manager.main_pid
                or readiness.observed_at > manager.observed_at
            ):
                raise ServiceInspectionError("application readiness is stale or uncorrelated")
            runtime_identity_sha256 = readiness.runtime_identity_sha256
            application_ready = readiness.ready
        try:
            return ServiceInspectionResult(
                service_profile_sha256=self._profile.profile_sha256,
                service_unit=manager.service_unit,
                load_state=manager.load_state,
                active_state=manager.active_state,
                sub_state=manager.sub_state,
                result=manager.result,
                main_pid=manager.main_pid,
                main_process_started_at=manager.main_process_started_at,
                application_ready=application_ready,
                runtime_identity_sha256=runtime_identity_sha256,
                observed_at=manager.observed_at,
            )
        except PrivilegedObservationError as exc:
            raise ServiceInspectionError("service inspection facts are contradictory") from exc


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ServiceInspectionError("service timestamp must be timezone-aware")


__all__ = [
    "ApplicationReadinessSnapshot",
    "FixedServiceInspectionNormalizer",
    "ServiceInspectionError",
    "ServiceManagerSnapshot",
]

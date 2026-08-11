"""Durable Phase 6 development-session values and state invariants."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

DEFAULT_SESSION_SECONDS: Final = 3_600
MAX_SESSION_SECONDS: Final = 14_400
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DevelopmentSessionError(ValueError):
    """A session value or transition violates the frozen Phase 6 contract."""


class DevelopmentSessionState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ENDED = "ended"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ActivationClosure(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


class SessionIneffectiveReason(StrEnum):
    NOT_ACTIVE = "development_session_not_active"
    ACTIVATION_INCOMPLETE = "development_session_activation_incomplete"
    TRUSTED_TIME_UNAVAILABLE = "trusted_time_unavailable"
    EXPIRED = "development_session_expired"
    CONTROLLER_MISMATCH = "controller_identity_mismatch"
    DEVICE_MISMATCH = "device_identity_mismatch"
    WORKSPACE_MISMATCH = "workspace_profile_mismatch"
    ROOT_MISMATCH = "workspace_root_identity_mismatch"
    MOUNT_MISMATCH = "workspace_mount_identity_mismatch"
    POLICY_MISMATCH = "policy_identity_mismatch"
    CONTRACT_MISMATCH = "contract_profile_mismatch"
    KERNEL_UNAVAILABLE = "kernel_unavailable"


@dataclass(frozen=True, slots=True)
class DevelopmentSessionSnapshot:
    session_id: str
    begin_operation_id: str
    state: DevelopmentSessionState
    state_version: int
    activation_closure: ActivationClosure
    activation_closure_version: int
    controller_id: str
    controller_epoch: int
    device_id: str
    device_epoch: int
    workspace_id: str
    workspace_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    policy_version: str
    contract_profile_sha256: str
    objective_sha256: str
    created_at: datetime
    expires_at: datetime
    trusted_time_generation: int
    activation_boot_id_digest: str
    monotonic_deadline_ns: int
    started_at: datetime | None = None
    terminal_at: datetime | None = None
    terminal_reason: str | None = None
    activation_effect_reference: str | None = None
    activation_effect_reference_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_session_snapshot(self)


@dataclass(frozen=True, slots=True)
class SessionAuthorityFacts:
    controller_id: str
    controller_epoch: int
    device_id: str
    device_epoch: int
    workspace_id: str
    workspace_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    policy_version: str
    contract_profile_sha256: str
    wall_time: datetime
    wall_time_trusted: bool
    boot_id_digest: str
    monotonic_ns: int
    kernel_consequential_ready: bool


@dataclass(frozen=True, slots=True)
class SessionEffectiveness:
    effective: bool
    reason: SessionIneffectiveReason | None


def new_session_id() -> str:
    """Return an opaque non-authoritative identifier with 128 random bits."""

    return f"dev_{secrets.token_hex(16)}"


def new_pending_session(
    *,
    begin_operation_id: str,
    controller_id: str,
    controller_epoch: int,
    device_id: str,
    device_epoch: int,
    workspace_id: str,
    workspace_profile_sha256: str,
    workspace_root_identity_sha256: str,
    workspace_mount_identity_sha256: str,
    policy_version: str,
    contract_profile_sha256: str,
    objective_sha256: str,
    expires_at: datetime,
    trusted_time_generation: int,
    activation_boot_id_digest: str,
    monotonic_deadline_ns: int,
    now: datetime | None = None,
    session_id: str | None = None,
) -> DevelopmentSessionSnapshot:
    created_at = now or datetime.now(UTC)
    if expires_at <= created_at:
        raise DevelopmentSessionError("session deadline must be after creation")
    if (expires_at - created_at).total_seconds() > MAX_SESSION_SECONDS:
        raise DevelopmentSessionError("session deadline exceeds the reviewed maximum")
    return DevelopmentSessionSnapshot(
        session_id=session_id or new_session_id(),
        begin_operation_id=begin_operation_id,
        state=DevelopmentSessionState.PENDING,
        state_version=1,
        activation_closure=ActivationClosure.PENDING,
        activation_closure_version=1,
        controller_id=controller_id,
        controller_epoch=controller_epoch,
        device_id=device_id,
        device_epoch=device_epoch,
        workspace_id=workspace_id,
        workspace_profile_sha256=workspace_profile_sha256,
        workspace_root_identity_sha256=workspace_root_identity_sha256,
        workspace_mount_identity_sha256=workspace_mount_identity_sha256,
        policy_version=policy_version,
        contract_profile_sha256=contract_profile_sha256,
        objective_sha256=objective_sha256,
        created_at=created_at,
        expires_at=expires_at,
        trusted_time_generation=trusted_time_generation,
        activation_boot_id_digest=activation_boot_id_digest,
        monotonic_deadline_ns=monotonic_deadline_ns,
    )


def activate_session(
    snapshot: DevelopmentSessionSnapshot,
    *,
    expected_state_version: int,
    effect_reference: str,
    effect_reference_sha256: str,
    now: datetime,
) -> DevelopmentSessionSnapshot:
    """Apply only the gate-owned PENDING -> ACTIVE activation effect."""

    if snapshot.state is not DevelopmentSessionState.PENDING:
        raise DevelopmentSessionError("only a pending session can activate")
    if snapshot.state_version != expected_state_version:
        raise DevelopmentSessionError("session activation state version is stale")
    _identifier(effect_reference, "activation_effect_reference")
    _sha256(effect_reference_sha256, "activation_effect_reference_sha256")
    if not snapshot.created_at <= now < snapshot.expires_at:
        raise DevelopmentSessionError("session activation time is outside its lifetime")
    return replace(
        snapshot,
        state=DevelopmentSessionState.ACTIVE,
        state_version=snapshot.state_version + 1,
        started_at=now,
        activation_effect_reference=effect_reference,
        activation_effect_reference_sha256=effect_reference_sha256,
    )


def complete_activation(
    snapshot: DevelopmentSessionSnapshot,
    *,
    expected_state_version: int,
) -> DevelopmentSessionSnapshot:
    """Close activation only after the application proves audit/obligation truth."""

    if snapshot.state is not DevelopmentSessionState.ACTIVE:
        raise DevelopmentSessionError("only an active session can close activation")
    if snapshot.activation_closure is not ActivationClosure.PENDING:
        raise DevelopmentSessionError("session activation is already closed")
    if snapshot.state_version != expected_state_version:
        raise DevelopmentSessionError("activation closure state version is stale")
    if snapshot.activation_effect_reference is None:
        raise DevelopmentSessionError("activation closure requires retained effect evidence")
    return replace(
        snapshot,
        state_version=snapshot.state_version + 1,
        activation_closure=ActivationClosure.COMPLETE,
        activation_closure_version=snapshot.activation_closure_version + 1,
    )


def reduce_session(
    snapshot: DevelopmentSessionSnapshot,
    *,
    expected_state_version: int,
    target: DevelopmentSessionState,
    reason: str,
    now: datetime,
) -> DevelopmentSessionSnapshot:
    """Durably reduce authority; reduction never reactivates a terminal session."""

    if target not in {
        DevelopmentSessionState.ENDED,
        DevelopmentSessionState.EXPIRED,
        DevelopmentSessionState.REVOKED,
    }:
        raise DevelopmentSessionError("session reduction target is not terminal")
    if snapshot.state not in {
        DevelopmentSessionState.PENDING,
        DevelopmentSessionState.ACTIVE,
    }:
        raise DevelopmentSessionError("terminal session authority cannot be reduced again")
    if snapshot.state_version != expected_state_version:
        raise DevelopmentSessionError("session reduction state version is stale")
    _identifier(reason, "terminal_reason")
    if now < snapshot.created_at:
        raise DevelopmentSessionError("session terminal time predates creation")
    return replace(
        snapshot,
        state=target,
        state_version=snapshot.state_version + 1,
        terminal_at=now,
        terminal_reason=reason,
    )


def evaluate_session_authority(
    snapshot: DevelopmentSessionSnapshot,
    facts: SessionAuthorityFacts,
) -> SessionEffectiveness:
    """Evaluate exact current authority without mutating or extending the session."""

    if snapshot.state is not DevelopmentSessionState.ACTIVE:
        return SessionEffectiveness(False, SessionIneffectiveReason.NOT_ACTIVE)
    if snapshot.activation_closure is not ActivationClosure.COMPLETE:
        return SessionEffectiveness(False, SessionIneffectiveReason.ACTIVATION_INCOMPLETE)
    if not facts.kernel_consequential_ready:
        return SessionEffectiveness(False, SessionIneffectiveReason.KERNEL_UNAVAILABLE)
    if (
        facts.controller_id != snapshot.controller_id
        or facts.controller_epoch != snapshot.controller_epoch
    ):
        return SessionEffectiveness(False, SessionIneffectiveReason.CONTROLLER_MISMATCH)
    if facts.device_id != snapshot.device_id or facts.device_epoch != snapshot.device_epoch:
        return SessionEffectiveness(False, SessionIneffectiveReason.DEVICE_MISMATCH)
    if facts.workspace_id != snapshot.workspace_id or (
        facts.workspace_profile_sha256 != snapshot.workspace_profile_sha256
    ):
        return SessionEffectiveness(False, SessionIneffectiveReason.WORKSPACE_MISMATCH)
    if facts.workspace_root_identity_sha256 != snapshot.workspace_root_identity_sha256:
        return SessionEffectiveness(False, SessionIneffectiveReason.ROOT_MISMATCH)
    if facts.workspace_mount_identity_sha256 != snapshot.workspace_mount_identity_sha256:
        return SessionEffectiveness(False, SessionIneffectiveReason.MOUNT_MISMATCH)
    if facts.policy_version != snapshot.policy_version:
        return SessionEffectiveness(False, SessionIneffectiveReason.POLICY_MISMATCH)
    if facts.contract_profile_sha256 != snapshot.contract_profile_sha256:
        return SessionEffectiveness(False, SessionIneffectiveReason.CONTRACT_MISMATCH)
    same_boot = facts.boot_id_digest == snapshot.activation_boot_id_digest
    if same_boot:
        if facts.monotonic_ns < 0:
            return SessionEffectiveness(False, SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE)
        if facts.monotonic_ns >= snapshot.monotonic_deadline_ns:
            return SessionEffectiveness(False, SessionIneffectiveReason.EXPIRED)
    elif not facts.wall_time_trusted:
        return SessionEffectiveness(False, SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE)
    if not facts.wall_time_trusted:
        return SessionEffectiveness(False, SessionIneffectiveReason.TRUSTED_TIME_UNAVAILABLE)
    if facts.wall_time >= snapshot.expires_at:
        return SessionEffectiveness(False, SessionIneffectiveReason.EXPIRED)
    return SessionEffectiveness(True, None)


def objective_sha256(objective: str) -> str:
    """Digest a bounded NFC objective label; it never becomes executable policy."""

    if not isinstance(objective, str) or not 1 <= len(objective.encode("utf-8")) <= 4_096:
        raise DevelopmentSessionError("development objective is outside the bounded contract")
    return hashlib.sha256(
        json.dumps(objective, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_session_snapshot(snapshot: DevelopmentSessionSnapshot) -> None:
    for field, value in (
        ("session_id", snapshot.session_id),
        ("begin_operation_id", snapshot.begin_operation_id),
        ("controller_id", snapshot.controller_id),
        ("device_id", snapshot.device_id),
        ("workspace_id", snapshot.workspace_id),
        ("policy_version", snapshot.policy_version),
    ):
        _identifier(value, field)
    for field, value in (
        ("workspace_profile_sha256", snapshot.workspace_profile_sha256),
        ("workspace_root_identity_sha256", snapshot.workspace_root_identity_sha256),
        ("workspace_mount_identity_sha256", snapshot.workspace_mount_identity_sha256),
        ("contract_profile_sha256", snapshot.contract_profile_sha256),
        ("objective_sha256", snapshot.objective_sha256),
        ("activation_boot_id_digest", snapshot.activation_boot_id_digest),
    ):
        _sha256(value, field)
    if snapshot.activation_effect_reference_sha256 is not None:
        _sha256(
            snapshot.activation_effect_reference_sha256,
            "activation_effect_reference_sha256",
        )
    if snapshot.activation_effect_reference is not None:
        _identifier(snapshot.activation_effect_reference, "activation_effect_reference")
    if snapshot.controller_epoch < 1 or snapshot.device_epoch < 1:
        raise DevelopmentSessionError("session owner/device epoch is invalid")
    if snapshot.state_version < 1 or snapshot.activation_closure_version < 1:
        raise DevelopmentSessionError("session version is invalid")
    if snapshot.trusted_time_generation < 1 or snapshot.monotonic_deadline_ns < 0:
        raise DevelopmentSessionError("session trusted-time binding is invalid")
    if snapshot.expires_at <= snapshot.created_at:
        raise DevelopmentSessionError("session time range is invalid")
    if snapshot.started_at is not None and not (
        snapshot.created_at <= snapshot.started_at < snapshot.expires_at
    ):
        raise DevelopmentSessionError("session start time is invalid")
    terminal = snapshot.state in {
        DevelopmentSessionState.ENDED,
        DevelopmentSessionState.EXPIRED,
        DevelopmentSessionState.REVOKED,
    }
    if terminal != (snapshot.terminal_at is not None and snapshot.terminal_reason is not None):
        raise DevelopmentSessionError("session terminal fields do not match state")
    if snapshot.terminal_at is not None and snapshot.terminal_at < snapshot.created_at:
        raise DevelopmentSessionError("session terminal time is invalid")
    if snapshot.state is DevelopmentSessionState.PENDING and snapshot.started_at is not None:
        raise DevelopmentSessionError("pending session cannot have started")
    if snapshot.state is DevelopmentSessionState.ACTIVE and snapshot.started_at is None:
        raise DevelopmentSessionError("active session lacks start evidence")
    if snapshot.activation_closure is ActivationClosure.COMPLETE and (
        snapshot.activation_effect_reference is None
        or snapshot.activation_effect_reference_sha256 is None
    ):
        raise DevelopmentSessionError("closed activation lacks effect evidence")


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DevelopmentSessionError(f"{name} is not a bounded identifier")
    return value


def _sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentSessionError(f"{name} is not lowercase SHA-256")
    return value


__all__ = [
    "DEFAULT_SESSION_SECONDS",
    "MAX_SESSION_SECONDS",
    "ActivationClosure",
    "DevelopmentSessionError",
    "DevelopmentSessionSnapshot",
    "DevelopmentSessionState",
    "SessionAuthorityFacts",
    "SessionEffectiveness",
    "SessionIneffectiveReason",
    "activate_session",
    "complete_activation",
    "evaluate_session_authority",
    "new_pending_session",
    "new_session_id",
    "objective_sha256",
    "reduce_session",
    "validate_session_snapshot",
]

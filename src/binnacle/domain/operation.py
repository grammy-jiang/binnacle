"""Contract-exact durable operation lifecycle domain model."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class OperationState(StrEnum):
    RECEIVED = "received"
    REJECTED = "rejected"
    AUTHORISED = "authorised"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class EffectKnowledge(StrEnum):
    NONE = "none"
    KNOWN_NO_EFFECT = "known_no_effect"
    KNOWN_EFFECT = "known_effect"
    PARTIAL = "partial"
    UNCERTAIN = "uncertain"


class Terminality(StrEnum):
    NON_TERMINAL = "non_terminal"
    EFFECT_TERMINAL_RECONCILABLE = "effect_terminal_reconcilable"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class OperationError:
    code: str
    summary: str
    retry_action: str = "none"


@dataclass(frozen=True, slots=True)
class OperationOwner:
    controller_id: str
    controller_epoch: int
    controller_profile_id: str
    controller_profile_version: str

    def __post_init__(self) -> None:
        if not self.controller_id or self.controller_epoch < 1:
            raise ValueError("invalid operation owner")


@dataclass(frozen=True, slots=True)
class OperationIntent:
    operation_contract: str
    operation_contract_version: str
    request_fingerprint_sha256: str
    device_id: str
    device_epoch: int
    runtime_build_sha256: str
    runtime_config_sha256: str
    tool_name: str | None = None
    tool_contract_version: str | None = None
    target_identity_sha256: str | None = None
    maximum_effect_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: str
    owner: OperationOwner
    intent: OperationIntent
    state: OperationState
    state_version: int
    effect_knowledge: EffectKnowledge
    terminality: Terminality
    automatic_retry_allowed: bool
    created_at: datetime
    updated_at: datetime
    authorised_at: datetime | None = None
    started_at: datetime | None = None
    terminal_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    effect_boundary_crossed_at: datetime | None = None
    effect_reference: str | None = None
    effect_reference_digest: str | None = None
    error: OperationError | None = None


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    expected_state_version: int
    to_state: OperationState
    effect_knowledge: EffectKnowledge
    reason_code: str
    error: OperationError | None = None
    effect_reference: str | None = None
    effect_reference_digest: str | None = None
    occurred_at: datetime | None = None


class OperationTransitionError(ValueError):
    """A requested lifecycle edge or cross-field combination is invalid."""


_ALLOWED_TRANSITIONS: Final = MappingProxyType(
    {
        OperationState.RECEIVED: frozenset({OperationState.REJECTED, OperationState.AUTHORISED}),
        OperationState.REJECTED: frozenset(),
        OperationState.AUTHORISED: frozenset(
            {
                OperationState.RUNNING,
                OperationState.CANCELLING,
                OperationState.CANCELLED,
                OperationState.FAILED,
            }
        ),
        OperationState.RUNNING: frozenset(
            {
                OperationState.PAUSED,
                OperationState.CANCELLING,
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.UNCERTAIN,
            }
        ),
        OperationState.PAUSED: frozenset(
            {
                OperationState.RUNNING,
                OperationState.CANCELLING,
                OperationState.FAILED,
                OperationState.UNCERTAIN,
            }
        ),
        OperationState.CANCELLING: frozenset(
            {
                OperationState.CANCELLED,
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.UNCERTAIN,
            }
        ),
        OperationState.CANCELLED: frozenset(),
        OperationState.SUCCEEDED: frozenset(),
        OperationState.FAILED: frozenset(),
        OperationState.UNCERTAIN: frozenset(
            {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.CANCELLED}
        ),
    }
)

_STATE_KNOWLEDGE: Final = MappingProxyType(
    {
        OperationState.RECEIVED: frozenset({EffectKnowledge.NONE, EffectKnowledge.KNOWN_NO_EFFECT}),
        OperationState.REJECTED: frozenset({EffectKnowledge.NONE, EffectKnowledge.KNOWN_NO_EFFECT}),
        OperationState.AUTHORISED: frozenset(
            {EffectKnowledge.NONE, EffectKnowledge.KNOWN_NO_EFFECT}
        ),
        OperationState.RUNNING: frozenset(
            {
                EffectKnowledge.NONE,
                EffectKnowledge.KNOWN_NO_EFFECT,
                EffectKnowledge.KNOWN_EFFECT,
                EffectKnowledge.PARTIAL,
            }
        ),
        OperationState.PAUSED: frozenset(
            {
                EffectKnowledge.NONE,
                EffectKnowledge.KNOWN_NO_EFFECT,
                EffectKnowledge.KNOWN_EFFECT,
                EffectKnowledge.PARTIAL,
            }
        ),
        OperationState.CANCELLING: frozenset(
            {
                EffectKnowledge.NONE,
                EffectKnowledge.KNOWN_NO_EFFECT,
                EffectKnowledge.KNOWN_EFFECT,
                EffectKnowledge.PARTIAL,
            }
        ),
        OperationState.CANCELLED: frozenset(
            {
                EffectKnowledge.KNOWN_NO_EFFECT,
                EffectKnowledge.KNOWN_EFFECT,
                EffectKnowledge.PARTIAL,
            }
        ),
        OperationState.SUCCEEDED: frozenset({EffectKnowledge.KNOWN_EFFECT}),
        OperationState.FAILED: frozenset(
            {
                EffectKnowledge.KNOWN_NO_EFFECT,
                EffectKnowledge.KNOWN_EFFECT,
                EffectKnowledge.PARTIAL,
            }
        ),
        OperationState.UNCERTAIN: frozenset({EffectKnowledge.UNCERTAIN}),
    }
)

_ERROR_REQUIRED: Final = frozenset(
    {OperationState.REJECTED, OperationState.FAILED, OperationState.UNCERTAIN}
)


def terminality_for(state: OperationState) -> Terminality:
    if state is OperationState.UNCERTAIN:
        return Terminality.EFFECT_TERMINAL_RECONCILABLE
    if state in {
        OperationState.REJECTED,
        OperationState.CANCELLED,
        OperationState.SUCCEEDED,
        OperationState.FAILED,
    }:
        return Terminality.TERMINAL
    return Terminality.NON_TERMINAL


def validate_state_combination(
    state: OperationState,
    effect_knowledge: EffectKnowledge,
    terminality: Terminality,
    error: OperationError | None,
) -> None:
    if effect_knowledge not in _STATE_KNOWLEDGE[state]:
        raise OperationTransitionError("effect knowledge is invalid for operation state")
    if terminality is not terminality_for(state):
        raise OperationTransitionError("terminality is invalid for operation state")
    if (state in _ERROR_REQUIRED) != (error is not None):
        raise OperationTransitionError("operation error presence is invalid for state")


def new_operation_id() -> str:
    return f"op_{secrets.token_hex(16)}"


def new_received_operation(
    *,
    owner: OperationOwner,
    intent: OperationIntent,
    operation_id: str | None = None,
    now: datetime | None = None,
) -> OperationSnapshot:
    timestamp = now or datetime.now(UTC)
    snapshot = OperationSnapshot(
        operation_id=operation_id or new_operation_id(),
        owner=owner,
        intent=intent,
        state=OperationState.RECEIVED,
        state_version=1,
        effect_knowledge=EffectKnowledge.NONE,
        terminality=Terminality.NON_TERMINAL,
        automatic_retry_allowed=False,
        created_at=timestamp,
        updated_at=timestamp,
    )
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: OperationSnapshot) -> None:
    if snapshot.state_version < 1:
        raise OperationTransitionError("state version must be positive")
    if snapshot.automatic_retry_allowed:
        raise OperationTransitionError("automatic retry is forbidden")
    validate_state_combination(
        snapshot.state,
        snapshot.effect_knowledge,
        snapshot.terminality,
        snapshot.error,
    )


def transition(snapshot: OperationSnapshot, request: TransitionRequest) -> OperationSnapshot:
    if request.expected_state_version != snapshot.state_version:
        raise OperationTransitionError("operation state version conflict")
    if request.to_state not in _ALLOWED_TRANSITIONS[snapshot.state]:
        raise OperationTransitionError("operation lifecycle transition is not declared")
    terminality = terminality_for(request.to_state)
    validate_state_combination(
        request.to_state,
        request.effect_knowledge,
        terminality,
        request.error,
    )
    timestamp = request.occurred_at or datetime.now(UTC)
    return replace(
        snapshot,
        state=request.to_state,
        state_version=snapshot.state_version + 1,
        effect_knowledge=request.effect_knowledge,
        terminality=terminality,
        updated_at=timestamp,
        authorised_at=(
            timestamp if request.to_state is OperationState.AUTHORISED else snapshot.authorised_at
        ),
        started_at=(
            timestamp if request.to_state is OperationState.RUNNING else snapshot.started_at
        ),
        terminal_at=(timestamp if terminality is Terminality.TERMINAL else None),
        last_reconciled_at=(
            timestamp
            if snapshot.state is OperationState.UNCERTAIN
            and request.to_state
            in {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.CANCELLED}
            else snapshot.last_reconciled_at
        ),
        effect_boundary_crossed_at=(
            timestamp
            if request.effect_knowledge in {EffectKnowledge.KNOWN_EFFECT, EffectKnowledge.PARTIAL}
            and snapshot.effect_boundary_crossed_at is None
            else snapshot.effect_boundary_crossed_at
        ),
        effect_reference=request.effect_reference or snapshot.effect_reference,
        effect_reference_digest=(
            request.effect_reference_digest or snapshot.effect_reference_digest
        ),
        error=request.error,
    )


def allowed_transitions(state: OperationState) -> frozenset[OperationState]:
    return _ALLOWED_TRANSITIONS[state]

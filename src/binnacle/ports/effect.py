"""Synthetic/future consequential effect and reconciliation ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from binnacle.domain.operation import EffectKnowledge, OperationState


@dataclass(frozen=True, slots=True)
class EffectRequest:
    operation_id: str
    running_state_version: int
    effect_type: str
    protected_arguments: Mapping[str, object]


class BoundaryCrossing(StrEnum):
    DEFINITELY_NOT_CROSSED = "definitely_not_crossed"
    CROSSED = "crossed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EffectStartReceipt:
    crossing: BoundaryCrossing
    effect_knowledge: EffectKnowledge
    reference: str | None = None
    reference_digest: str | None = None
    terminal_state: OperationState | None = None
    reason_code: str = "effect_start_classified"


@dataclass(frozen=True, slots=True)
class EffectReference:
    operation_id: str
    reference: str
    reference_digest: str


@dataclass(frozen=True, slots=True)
class EffectObservation:
    state: OperationState
    effect_knowledge: EffectKnowledge
    reason_code: str


class EffectBoundary(Protocol):
    async def start(self, request: EffectRequest) -> EffectStartReceipt: ...


class EffectReconciler(Protocol):
    async def reconcile(self, reference: EffectReference) -> EffectObservation: ...


class UnavailableEffectBoundary:
    """Production-safe boundary: Phase 4 has no effect-capable adapter."""

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        del request
        return EffectStartReceipt(
            crossing=BoundaryCrossing.DEFINITELY_NOT_CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
            terminal_state=OperationState.FAILED,
            reason_code="effect_boundary_unavailable",
        )

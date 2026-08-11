"""Synthetic/future consequential effect and reconciliation ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

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


class EffectReceiptError(ValueError):
    """The adapter receipt cannot support one authoritative effect classification."""


_VALID_EFFECT_RECEIPT_MATRIX: Final[
    frozenset[tuple[BoundaryCrossing, EffectKnowledge, OperationState | None]]
] = frozenset(
    {
        (
            BoundaryCrossing.DEFINITELY_NOT_CROSSED,
            EffectKnowledge.KNOWN_NO_EFFECT,
            OperationState.FAILED,
        ),
        (BoundaryCrossing.CROSSED, EffectKnowledge.KNOWN_EFFECT, None),
        (BoundaryCrossing.CROSSED, EffectKnowledge.PARTIAL, None),
        (
            BoundaryCrossing.CROSSED,
            EffectKnowledge.KNOWN_EFFECT,
            OperationState.SUCCEEDED,
        ),
        (
            BoundaryCrossing.CROSSED,
            EffectKnowledge.KNOWN_EFFECT,
            OperationState.FAILED,
        ),
        (
            BoundaryCrossing.CROSSED,
            EffectKnowledge.PARTIAL,
            OperationState.FAILED,
        ),
        (
            BoundaryCrossing.UNCERTAIN,
            EffectKnowledge.UNCERTAIN,
            OperationState.UNCERTAIN,
        ),
    }
)


def validate_effect_start_receipt(receipt: EffectStartReceipt) -> None:
    """Reject contradictory adapter claims before any durable state is changed."""

    shape = (receipt.crossing, receipt.effect_knowledge, receipt.terminal_state)
    if shape not in _VALID_EFFECT_RECEIPT_MATRIX:
        raise EffectReceiptError("effect receipt crossing/knowledge/outcome is outside the matrix")
    if receipt.reference is not None and (not receipt.reference or len(receipt.reference) > 512):
        raise EffectReceiptError("effect receipt reference is empty or exceeds its bound")
    if receipt.crossing is BoundaryCrossing.CROSSED and receipt.reference is None:
        raise EffectReceiptError("a crossed effect receipt requires a stable reference")
    if receipt.crossing is BoundaryCrossing.DEFINITELY_NOT_CROSSED and (
        receipt.reference is not None or receipt.reference_digest is not None
    ):
        raise EffectReceiptError("a definitely-not-crossed receipt cannot carry a reference")
    if receipt.reference_digest is not None:
        if receipt.reference is None:
            raise EffectReceiptError("an effect reference digest requires its reference")
        if (
            len(receipt.reference_digest) != 64
            or receipt.reference_digest != receipt.reference_digest.casefold()
            or any(character not in "0123456789abcdef" for character in receipt.reference_digest)
        ):
            raise EffectReceiptError("effect receipt reference digest is not lowercase SHA-256")


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

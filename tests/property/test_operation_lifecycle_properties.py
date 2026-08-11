"""Generated lifecycle state-version and cross-field invariants."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.phase4_support import NOW, intent, owner

from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationState,
    OperationTransitionError,
    TransitionRequest,
    allowed_transitions,
    new_received_operation,
    terminality_for,
    transition,
)


@given(st.sampled_from(tuple(OperationState)), st.sampled_from(tuple(OperationState)))
def test_generated_edges_never_bypass_declared_map(
    source: OperationState, target: OperationState
) -> None:
    operation = new_received_operation(owner=owner(), intent=intent(), now=NOW)
    object.__setattr__(operation, "state", source)
    object.__setattr__(operation, "effect_knowledge", _knowledge(target=source))
    object.__setattr__(operation, "terminality", terminality_for(source))
    object.__setattr__(
        operation,
        "error",
        OperationError("prior", "prior")
        if source in {OperationState.REJECTED, OperationState.FAILED, OperationState.UNCERTAIN}
        else None,
    )
    request = TransitionRequest(
        1,
        target,
        _knowledge(target=target),
        "property",
        OperationError("next", "next")
        if target in {OperationState.REJECTED, OperationState.FAILED, OperationState.UNCERTAIN}
        else None,
        occurred_at=NOW,
    )
    if target in allowed_transitions(source):
        assert transition(operation, request).state_version == 2
    else:
        with pytest.raises(OperationTransitionError):
            transition(operation, request)


def _knowledge(*, target: OperationState) -> EffectKnowledge:
    if target is OperationState.UNCERTAIN:
        return EffectKnowledge.UNCERTAIN
    if target is OperationState.SUCCEEDED:
        return EffectKnowledge.KNOWN_EFFECT
    if target in {OperationState.REJECTED, OperationState.CANCELLED, OperationState.FAILED}:
        return EffectKnowledge.KNOWN_NO_EFFECT
    return EffectKnowledge.NONE

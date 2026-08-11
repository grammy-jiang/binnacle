"""Contract parity and cross-field tests for operation lifecycle."""

from __future__ import annotations

from itertools import product

import pytest
from tests.phase4_support import NOW, intent, owner

from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationState,
    OperationTransitionError,
    Terminality,
    TransitionRequest,
    allowed_transitions,
    new_operation_id,
    new_received_operation,
    terminality_for,
    transition,
    validate_snapshot,
    validate_state_combination,
)


def test_new_received_operation_has_version_one_and_safe_defaults() -> None:
    operation = new_received_operation(
        owner=owner(), intent=intent(), operation_id="op_fixture", now=NOW
    )
    assert operation.operation_id == "op_fixture"
    assert operation.state is OperationState.RECEIVED
    assert operation.state_version == 1
    assert operation.effect_knowledge is EffectKnowledge.NONE
    assert not operation.automatic_retry_allowed
    validate_snapshot(operation)
    assert new_operation_id().startswith("op_")
    assert len(new_operation_id()) == 35


@pytest.mark.parametrize("state", tuple(OperationState))
def test_terminality_is_contract_exact(state: OperationState) -> None:
    expected = (
        Terminality.EFFECT_TERMINAL_RECONCILABLE
        if state is OperationState.UNCERTAIN
        else Terminality.TERMINAL
        if state
        in {
            OperationState.REJECTED,
            OperationState.CANCELLED,
            OperationState.SUCCEEDED,
            OperationState.FAILED,
        }
        else Terminality.NON_TERMINAL
    )
    assert terminality_for(state) is expected


@pytest.mark.parametrize(
    ("state", "knowledge", "error"),
    [
        (OperationState.RECEIVED, EffectKnowledge.NONE, None),
        (OperationState.REJECTED, EffectKnowledge.KNOWN_NO_EFFECT, OperationError("x", "x")),
        (OperationState.RUNNING, EffectKnowledge.PARTIAL, None),
        (OperationState.CANCELLED, EffectKnowledge.KNOWN_EFFECT, None),
        (OperationState.SUCCEEDED, EffectKnowledge.KNOWN_EFFECT, None),
        (OperationState.FAILED, EffectKnowledge.KNOWN_NO_EFFECT, OperationError("x", "x")),
        (OperationState.UNCERTAIN, EffectKnowledge.UNCERTAIN, OperationError("x", "x")),
    ],
)
def test_valid_state_combinations(
    state: OperationState, knowledge: EffectKnowledge, error: OperationError | None
) -> None:
    validate_state_combination(state, knowledge, terminality_for(state), error)


@pytest.mark.parametrize(
    ("state", "knowledge", "terminality", "error"),
    [
        (OperationState.SUCCEEDED, EffectKnowledge.NONE, Terminality.TERMINAL, None),
        (OperationState.RUNNING, EffectKnowledge.NONE, Terminality.TERMINAL, None),
        (OperationState.FAILED, EffectKnowledge.KNOWN_NO_EFFECT, Terminality.TERMINAL, None),
        (
            OperationState.RECEIVED,
            EffectKnowledge.NONE,
            Terminality.NON_TERMINAL,
            OperationError("x", "x"),
        ),
    ],
)
def test_invalid_state_combinations_fail_closed(
    state: OperationState,
    knowledge: EffectKnowledge,
    terminality: Terminality,
    error: OperationError | None,
) -> None:
    with pytest.raises(OperationTransitionError):
        validate_state_combination(state, knowledge, terminality, error)


def test_every_declared_edge_and_forbidden_edge() -> None:
    declared_count = 0
    for source, target in product(OperationState, repeat=2):
        operation = new_received_operation(
            owner=owner(), intent=intent(), operation_id="op_fixture", now=NOW
        )
        object.__setattr__(operation, "state", source)
        object.__setattr__(operation, "effect_knowledge", _knowledge_for(source))
        object.__setattr__(operation, "terminality", terminality_for(source))
        object.__setattr__(
            operation,
            "error",
            OperationError("prior", "prior")
            if source in {OperationState.REJECTED, OperationState.FAILED, OperationState.UNCERTAIN}
            else None,
        )
        request = TransitionRequest(
            expected_state_version=1,
            to_state=target,
            effect_knowledge=_knowledge_for(target),
            reason_code="test_transition",
            error=OperationError("next", "next")
            if target in {OperationState.REJECTED, OperationState.FAILED, OperationState.UNCERTAIN}
            else None,
            occurred_at=NOW,
        )
        if target in allowed_transitions(source):
            declared_count += 1
            updated = transition(operation, request)
            assert updated.state is target
            assert updated.state_version == 2
        else:
            with pytest.raises(OperationTransitionError):
                transition(operation, request)
    assert declared_count == 22


def test_stale_transition_is_rejected() -> None:
    operation = new_received_operation(owner=owner(), intent=intent(), now=NOW)
    with pytest.raises(OperationTransitionError, match="version conflict"):
        transition(
            operation,
            TransitionRequest(
                expected_state_version=2,
                to_state=OperationState.AUTHORISED,
                effect_knowledge=EffectKnowledge.NONE,
                reason_code="stale",
            ),
        )


def _knowledge_for(state: OperationState) -> EffectKnowledge:
    if state is OperationState.UNCERTAIN:
        return EffectKnowledge.UNCERTAIN
    if state is OperationState.SUCCEEDED:
        return EffectKnowledge.KNOWN_EFFECT
    if state in {OperationState.REJECTED, OperationState.CANCELLED, OperationState.FAILED}:
        return EffectKnowledge.KNOWN_NO_EFFECT
    return EffectKnowledge.NONE

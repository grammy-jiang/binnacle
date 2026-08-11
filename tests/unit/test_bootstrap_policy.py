"""Fail-closed Bootstrap policy tests."""

from __future__ import annotations

import pytest
from tests.phase4_support import intent, owner

from binnacle.adapters.policy.bootstrap import BootstrapPolicyEngine
from binnacle.domain.policy import PolicyDecisionValue, PolicyRequest


@pytest.mark.anyio
async def test_production_default_denies_every_consequential_contract() -> None:
    engine = BootstrapPolicyEngine()
    decision = await engine.evaluate(
        PolicyRequest("op", owner(), intent(), normalized_target_digest="d" * 64)
    )
    assert decision.decision is PolicyDecisionValue.DENY
    assert decision.reason_codes == ("operation_contract_unknown",)


@pytest.mark.anyio
async def test_explicit_test_fixture_contract_is_allowed_only_with_bounded_facts() -> None:
    engine = BootstrapPolicyEngine(
        allowed_contracts=frozenset({("synthetic.effect", "1.0.0")}),
        allowed_scope_digests=frozenset({"f" * 64}),
    )
    decision = await engine.evaluate(
        PolicyRequest(
            "op",
            owner(),
            intent(),
            required_scope_digest="f" * 64,
            normalized_target_digest="d" * 64,
        )
    )
    assert decision.allowed
    assert decision.reason_codes == ("bootstrap_rule_allowed",)
    assert len(decision.runtime_policy_sha256) == 64


@pytest.mark.anyio
async def test_missing_target_and_unknown_scope_are_denied() -> None:
    engine = BootstrapPolicyEngine(allowed_contracts=frozenset({("synthetic.effect", "1.0.0")}))
    decision = await engine.evaluate(
        PolicyRequest("op", owner(), intent(), required_scope_digest="f" * 64)
    )
    assert decision.decision is PolicyDecisionValue.DENY
    assert decision.reason_codes == (
        "required_scope_not_allowed",
        "normalized_target_missing",
    )

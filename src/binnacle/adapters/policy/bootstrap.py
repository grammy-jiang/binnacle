"""Fail-closed finite Bootstrap policy implementation."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from binnacle.adapters.audit.canonical import canonicalize
from binnacle.domain.policy import PolicyDecision, PolicyDecisionValue, PolicyRequest


class BootstrapPolicyEngine:
    def __init__(
        self,
        *,
        allowed_contracts: frozenset[tuple[str, str]] = frozenset(),
        allowed_scope_digests: frozenset[str] = frozenset(),
        policy_id: str = "bootstrap-policy",
        policy_version: str = "1.0.0",
    ) -> None:
        self._allowed_contracts = allowed_contracts
        self._allowed_scope_digests = allowed_scope_digests
        self._policy_id = policy_id
        self._policy_version = policy_version
        policy_projection = {
            "allowed_contracts": sorted([list(item) for item in allowed_contracts]),
            "allowed_scope_digests": sorted(allowed_scope_digests),
            "policy_id": policy_id,
            "policy_version": policy_version,
        }
        self._policy_digest = hashlib.sha256(canonicalize(policy_projection)).hexdigest()

    async def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        reasons: list[str] = []
        contract = (
            request.intent.operation_contract,
            request.intent.operation_contract_version,
        )
        if not request.owner.controller_id:
            reasons.append("controller_missing")
        if contract not in self._allowed_contracts:
            reasons.append("operation_contract_unknown")
        if request.required_scope_digest is not None and (
            request.required_scope_digest not in self._allowed_scope_digests
        ):
            reasons.append("required_scope_not_allowed")
        if request.normalized_target_digest is None:
            reasons.append("normalized_target_missing")
        decision = PolicyDecisionValue.DENY if reasons else PolicyDecisionValue.ALLOW
        if not reasons:
            reasons.append("bootstrap_rule_allowed")
        input_facts = {
            "controller_id": request.owner.controller_id,
            "controller_epoch": request.owner.controller_epoch,
            "operation_contract": request.intent.operation_contract,
            "operation_contract_version": request.intent.operation_contract_version,
            "required_scope_digest": request.required_scope_digest,
            "normalized_target_digest": request.normalized_target_digest,
        }
        return PolicyDecision(
            policy_decision_id=f"policy_{secrets.token_hex(16)}",
            operation_id=request.operation_id,
            policy_id=self._policy_id,
            policy_version=self._policy_version,
            decision=decision,
            reason_codes=tuple(reasons),
            input_facts_sha256=hashlib.sha256(canonicalize(input_facts)).hexdigest(),
            runtime_policy_sha256=self._policy_digest,
            decided_at=datetime.now(UTC),
        )

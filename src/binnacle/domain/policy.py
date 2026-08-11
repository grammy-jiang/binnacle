"""Minimal deterministic Bootstrap policy domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from binnacle.domain.operation import OperationIntent, OperationOwner


class PolicyDecisionValue(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    operation_id: str
    owner: OperationOwner
    intent: OperationIntent
    required_scope_digest: str | None = None
    normalized_target_digest: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    policy_decision_id: str
    operation_id: str
    policy_id: str
    policy_version: str
    decision: PolicyDecisionValue
    reason_codes: tuple[str, ...]
    input_facts_sha256: str
    runtime_policy_sha256: str
    decided_at: datetime

    @property
    def allowed(self) -> bool:
        return self.decision is PolicyDecisionValue.ALLOW

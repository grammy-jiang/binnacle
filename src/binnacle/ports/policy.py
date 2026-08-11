"""Policy decision boundary."""

from __future__ import annotations

from typing import Protocol

from binnacle.domain.policy import PolicyDecision, PolicyRequest


class PolicyEngine(Protocol):
    async def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...

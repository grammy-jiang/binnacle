"""Compatibility facade for Commands execution-policy telemetry."""

from binnacle.features.commands.run_command_telemetry import (
    AUTO_BACKGROUND_SEMANTICS_VERSION,
    DispatchPlan,
    auto_background_behavior_hash,
    auto_background_policy_hash,
    auto_background_rule_hash,
)

__all__ = [
    "AUTO_BACKGROUND_SEMANTICS_VERSION",
    "DispatchPlan",
    "auto_background_behavior_hash",
    "auto_background_policy_hash",
    "auto_background_rule_hash",
]

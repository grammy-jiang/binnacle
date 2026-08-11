"""Validated access to the single frozen MCP evaluation case manifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from binnacle.evaluation.profile import (
    EvaluationSourceError,
    FrozenEvaluationProfile,
    load_evaluation_profile,
)


@dataclass(frozen=True, slots=True)
class FrozenEvaluationCase:
    """Identity and oracle shape that result recording may not rewrite."""

    case_id: str
    axis: str
    risk_class: str
    oracle_keys: frozenset[str]
    not_applicable_when: frozenset[str]
    target_revision_required: str | None

    def allows_status(self, status: str) -> bool:
        """Apply this case's frozen oracle plus Phase 3 probe-missing rules."""

        if status in {
            "observed-supported",
            "observed-limited",
            "test-failed",
            "not-tested",
            "unstable",
            "expired",
        }:
            return True
        if status == "host-policy-blocked":
            return "blocked_when" in self.oracle_keys
        if status == "not-applicable":
            return "not_applicable_when" in self.oracle_keys
        if status in {"declared-unexercised", "not-declared"}:
            return "not_applicable_when" in self.oracle_keys
        if status in {"server-not-implemented", "unsupported-by-design"}:
            return self.axis in {"write_entitlement", "host_confirmation"} or self.risk_class in {
                "write_cancellation_retry_cache_confirmation",
                "concurrency_race_reconnect_instability",
            }
        return False

    def status_matches_profile(
        self,
        status: str,
        *,
        negotiated_revision: str | None,
        intended_revision_set: frozenset[str],
    ) -> bool:
        """Enforce oracle predicates that are decidable from the profile snapshot."""

        if not self.allows_status(status):
            return False
        if status != "not-applicable":
            return True
        if "negotiated_revision_is_legacy" not in self.not_applicable_when:
            return True
        return (
            self.target_revision_required is not None
            and negotiated_revision is not None
            and negotiated_revision in intended_revision_set
            and negotiated_revision != self.target_revision_required
        )


@dataclass(frozen=True, slots=True)
class FrozenCaseSet:
    """Immutable indexed view of all frozen cases."""

    manifest_id: str
    version: str
    cases: Mapping[str, FrozenEvaluationCase]

    def require(self, case_id: str) -> FrozenEvaluationCase:
        """Return a frozen case or reject a caller-invented identifier."""

        try:
            return self.cases[case_id]
        except KeyError as exc:
            raise EvaluationSourceError(f"unknown evaluation case: {case_id}") from exc


def load_evaluation_cases(
    repo_root: Path,
    *,
    profile: FrozenEvaluationProfile | None = None,
) -> FrozenCaseSet:
    """Load exact cases and cross-check every risk class against the profile."""

    selected_profile = profile or load_evaluation_profile(repo_root)
    values = _mapping(
        yaml.safe_load((repo_root.resolve() / selected_profile.case_manifest.path).read_bytes()),
        "case manifest",
    )
    if _string(values, "schema_version") != selected_profile.schema_version:
        raise EvaluationSourceError("case manifest schema_version does not match profile")
    if _string(values, "case_manifest_version") != selected_profile.case_manifest.version:
        raise EvaluationSourceError("case manifest version does not match profile")

    source_risks = _mapping(values.get("risk_classes"), "case risk_classes")
    if set(source_risks) != set(selected_profile.risk_classes):
        raise EvaluationSourceError("case/profile risk class sets differ")
    for name, profile_risk in selected_profile.risk_classes.items():
        case_risk = _mapping(source_risks[name], f"case risk class {name}")
        if case_risk.get("minimum_attempts") != profile_risk.minimum_attempts:
            raise EvaluationSourceError(f"minimum attempts differ for risk class {name}")

    raw_cases = values.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationSourceError("case manifest cases must be a non-empty array")
    cases: dict[str, FrozenEvaluationCase] = {}
    for raw_case in raw_cases:
        case_values = _mapping(raw_case, "evaluation case")
        case_id = _string(case_values, "case_id")
        axis = _string(case_values, "axis")
        risk_class = _string(case_values, "risk_class")
        if risk_class not in selected_profile.risk_classes:
            raise EvaluationSourceError(f"unknown case risk class: {risk_class}")
        oracle = _mapping(case_values.get("oracle"), f"oracle for {case_id}")
        if not oracle:
            raise EvaluationSourceError(f"evaluation case {case_id} has no oracle")
        setup = _mapping(case_values.get("setup"), f"setup for {case_id}")
        target_revision = setup.get("target_revision_required")
        if target_revision is not None and (
            not isinstance(target_revision, str) or not target_revision
        ):
            raise EvaluationSourceError(
                f"target_revision_required for {case_id} must be a non-empty string"
            )
        if case_id in cases:
            raise EvaluationSourceError(f"duplicate evaluation case: {case_id}")
        cases[case_id] = FrozenEvaluationCase(
            case_id=case_id,
            axis=axis,
            risk_class=risk_class,
            oracle_keys=frozenset(oracle),
            not_applicable_when=_condition_set(
                oracle.get("not_applicable_when"),
                f"not_applicable_when for {case_id}",
            ),
            target_revision_required=target_revision,
        )
    return FrozenCaseSet(
        manifest_id=_string(values, "case_manifest_id"),
        version=_string(values, "case_manifest_version"),
        cases=MappingProxyType(cases),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationSourceError(f"{name} must be an object")
    return cast(Mapping[str, Any], value)


def _string(values: Mapping[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value or len(value) > 160:
        raise EvaluationSourceError(f"{name} must be a bounded non-empty string")
    return value


def _condition_set(value: object, name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or len(item) > 160 for item in value
    ):
        raise EvaluationSourceError(f"{name} must be an array of bounded identifiers")
    return frozenset(cast(list[str], value))


__all__ = ["FrozenCaseSet", "FrozenEvaluationCase", "load_evaluation_cases"]

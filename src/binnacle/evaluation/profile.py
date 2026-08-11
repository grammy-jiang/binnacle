"""Load and validate the exact frozen Phase 3 evaluation profile."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

EVALUATION_PROFILE_PATH = Path("spec/mcp/evaluation-profile.yaml")


class EvaluationSourceError(ValueError):
    """A frozen evaluation source is malformed or its digest does not match."""


@dataclass(frozen=True, slots=True)
class RiskClass:
    """Attempt floor and target pass rate for one frozen risk class."""

    minimum_attempts: int
    target_pass_rate: float


@dataclass(frozen=True, slots=True)
class FrozenCaseManifestReference:
    """Expected path, version, and exact digest of the frozen case source."""

    path: Path
    version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class FrozenEvaluationProfile:
    """Validated immutable projection of ``evaluation-profile.yaml``."""

    schema_version: str
    profile_id: str
    profile_version: str
    manifest_schema: Path
    case_manifest: FrozenCaseManifestReference
    canonical_statuses: tuple[str, ...]
    risk_classes: Mapping[str, RiskClass]
    maximum_validity_days: int
    rerun_triggers: tuple[str, ...]
    sha256: str

    def requires_status(self, status: str) -> None:
        """Reject any status outside the single frozen vocabulary."""

        if status not in self.canonical_statuses:
            raise EvaluationSourceError(f"unknown evaluation status: {status}")


def load_evaluation_profile(repo_root: Path) -> FrozenEvaluationProfile:
    """Load the frozen profile and prove its referenced case digest before use."""

    root = repo_root.resolve()
    profile_path = root / EVALUATION_PROFILE_PATH
    raw = profile_path.read_bytes()
    values = _mapping(yaml.safe_load(raw), "evaluation profile")
    if _string(values, "schema_version") != "1.1":
        raise EvaluationSourceError("unsupported evaluation profile schema_version")

    case_values = _mapping(values.get("case_manifest"), "case_manifest")
    case_path = _safe_repo_path(_string(case_values, "path"))
    expected_case_digest = _digest(case_values, "sha256")
    actual_case_digest = hashlib.sha256((root / case_path).read_bytes()).hexdigest()
    if actual_case_digest != expected_case_digest:
        raise EvaluationSourceError("evaluation case-manifest digest does not match profile")

    statuses = _string_tuple(values.get("canonical_statuses"), "canonical_statuses")
    if len(set(statuses)) != len(statuses):
        raise EvaluationSourceError("canonical_statuses contains duplicates")

    raw_risk_classes = _mapping(values.get("risk_classes"), "risk_classes")
    risk_classes: dict[str, RiskClass] = {}
    for name, raw_risk in raw_risk_classes.items():
        if not isinstance(name, str):
            raise EvaluationSourceError("risk class name must be a string")
        risk = _mapping(raw_risk, f"risk class {name}")
        minimum = _integer(risk, "minimum_attempts", minimum=1, maximum=1000)
        target = risk.get("target_pass_rate")
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise EvaluationSourceError(f"risk class {name} target_pass_rate is invalid")
        target_float = float(target)
        if not 0 <= target_float <= 1:
            raise EvaluationSourceError(f"risk class {name} target_pass_rate is invalid")
        risk_classes[name] = RiskClass(minimum, target_float)

    validity = _mapping(values.get("validity"), "validity")
    rerun_triggers = _string_tuple(validity.get("rerun_triggers"), "rerun_triggers")
    if len(set(rerun_triggers)) != len(rerun_triggers):
        raise EvaluationSourceError("rerun_triggers contains duplicates")

    return FrozenEvaluationProfile(
        schema_version="1.1",
        profile_id=_string(values, "profile_id"),
        profile_version=_string(values, "profile_version"),
        manifest_schema=_safe_repo_path(_string(values, "manifest_schema")),
        case_manifest=FrozenCaseManifestReference(
            path=case_path,
            version=_string(case_values, "version"),
            sha256=expected_case_digest,
        ),
        canonical_statuses=statuses,
        risk_classes=MappingProxyType(risk_classes),
        maximum_validity_days=_integer(validity, "maximum_days", minimum=1, maximum=365),
        rerun_triggers=rerun_triggers,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationSourceError(f"{name} must be an object")
    return cast(Mapping[str, Any], value)


def _string(values: Mapping[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise EvaluationSourceError(f"{name} must be a bounded non-empty string")
    return value


def _digest(values: Mapping[str, Any], name: str) -> str:
    value = _string(values, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise EvaluationSourceError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _integer(
    values: Mapping[str, Any],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EvaluationSourceError(f"{name} is outside the reviewed range")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise EvaluationSourceError(f"{name} must be a non-empty array")
    if any(not isinstance(item, str) or not item or len(item) > 160 for item in value):
        raise EvaluationSourceError(f"{name} contains an invalid identifier")
    return tuple(cast(list[str], value))


def _safe_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise EvaluationSourceError("evaluation source path escapes the repository")
    return path


__all__ = [
    "EVALUATION_PROFILE_PATH",
    "EvaluationSourceError",
    "FrozenCaseManifestReference",
    "FrozenEvaluationProfile",
    "RiskClass",
    "load_evaluation_profile",
]

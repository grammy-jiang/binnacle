"""Frozen policy identity for the Phase 10 self-hosting acceptance evaluator."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from binnacle.evaluation.digests import canonical_json_sha256

PHASE10_POLICY_PATH = Path("spec/acceptance/phase10-policy.json")
PHASE10_SCHEMA_PATH = Path("schemas/acceptance/phase10-run.schema.json")
CI_ATTESTATION_SCHEMA_PATH = Path("schemas/acceptance/ci-checkout-attestation.schema.json")
_EXPECTED_POLICY_KEYS = frozenset(
    {
        "acceptance_schema_sha256",
        "allowed_merge_methods",
        "ci_attestation_schema_sha256",
        "limits",
        "plan_version",
        "policy_id",
        "protected_branch_ref",
        "repository",
        "required_ci_jobs",
        "required_security_checks",
        "required_workflows",
        "schema_version",
    }
)
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_BRANCH_REF_RE = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXPECTED_LIMIT_KEYS = frozenset(
    {
        "candidate_generations_max",
        "ci_evidence_per_integration_max",
        "evidence_reference_id_bytes_max",
        "integration_generations_max",
        "manifest_bytes_max",
        "security_checks_max",
    }
)


class Phase10PolicyError(ValueError):
    """The reviewed Phase 10 policy source is missing or contradictory."""


@dataclass(frozen=True, slots=True)
class Phase10Policy:
    """Exact repository-owned rules used to evaluate one acceptance run."""

    policy_id: str
    schema_version: str
    plan_version: str
    acceptance_schema_sha256: str
    ci_attestation_schema_sha256: str
    repository: str
    protected_branch_ref: str
    allowed_merge_methods: tuple[str, ...]
    required_workflows: tuple[str, ...]
    required_ci_jobs: Mapping[str, tuple[str, ...]]
    required_security_checks: tuple[str, ...]
    limits: Mapping[str, int]
    sha256: str


def load_phase10_policy(repo_root: Path) -> Phase10Policy:
    """Load and validate the checked-in policy without accepting caller overrides."""

    path = repo_root.resolve() / PHASE10_POLICY_PATH
    if path.is_symlink() or not path.is_file():
        raise Phase10PolicyError("Phase 10 policy source is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise Phase10PolicyError("Phase 10 policy source is invalid") from exc
    if not isinstance(value, dict) or set(value) != _EXPECTED_POLICY_KEYS:
        raise Phase10PolicyError("Phase 10 policy fields are not exact")
    policy = cast(dict[str, Any], value)
    if policy.get("schema_version") != "1.0":
        raise Phase10PolicyError("Phase 10 policy schema version is unsupported")
    if policy.get("plan_version") != "phase10-self-hosting-acceptance-v1":
        raise Phase10PolicyError("Phase 10 plan version is unsupported")

    policy_id = _bounded_string(policy, "policy_id", maximum=160)
    repository = _bounded_string(policy, "repository", maximum=256)
    if _REPOSITORY_RE.fullmatch(repository) is None:
        raise Phase10PolicyError("Phase 10 repository identity is invalid")
    protected_branch_ref = _bounded_string(policy, "protected_branch_ref", maximum=256)
    if _BRANCH_REF_RE.fullmatch(protected_branch_ref) is None:
        raise Phase10PolicyError("Phase 10 protected branch identity is invalid")
    acceptance_schema_sha256 = _bounded_string(
        policy,
        "acceptance_schema_sha256",
        maximum=64,
    )
    ci_attestation_schema_sha256 = _bounded_string(
        policy,
        "ci_attestation_schema_sha256",
        maximum=64,
    )
    if _DIGEST_RE.fullmatch(acceptance_schema_sha256) is None:
        raise Phase10PolicyError("Phase 10 acceptance schema identity is invalid")
    if _DIGEST_RE.fullmatch(ci_attestation_schema_sha256) is None:
        raise Phase10PolicyError("Phase 10 CI attestation schema identity is invalid")
    allowed_merge_methods = _unique_strings(policy, "allowed_merge_methods", maximum=8)
    if not allowed_merge_methods or set(allowed_merge_methods) - {"merge", "squash", "rebase"}:
        raise Phase10PolicyError("Phase 10 merge policy is unsupported")
    workflows = _unique_strings(policy, "required_workflows", maximum=32)
    raw_jobs = policy.get("required_ci_jobs")
    if not isinstance(raw_jobs, dict) or set(raw_jobs) != set(workflows):
        raise Phase10PolicyError("Phase 10 required CI jobs do not match workflows")
    jobs: dict[str, tuple[str, ...]] = {}
    for workflow in workflows:
        jobs[workflow] = _canonical_string_list(
            raw_jobs[workflow],
            context=f"required_ci_jobs.{workflow}",
            maximum=32,
        )
    security_checks = _unique_strings(policy, "required_security_checks", maximum=32)
    if not workflows or not security_checks:
        raise Phase10PolicyError("Phase 10 required evidence sets may not be empty")

    raw_limits = policy.get("limits")
    if not isinstance(raw_limits, dict) or set(raw_limits) != _EXPECTED_LIMIT_KEYS:
        raise Phase10PolicyError("Phase 10 policy limits are not exact")
    limits: dict[str, int] = {}
    for name, raw in raw_limits.items():
        if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 16_777_216:
            raise Phase10PolicyError(f"Phase 10 policy limit is invalid: {name}")
        limits[name] = raw
    if limits["manifest_bytes_max"] > 1_048_576:
        raise Phase10PolicyError("Phase 10 manifest limit exceeds the reviewed ceiling")

    actual_acceptance_schema = _load_schema_sha256(repo_root, PHASE10_SCHEMA_PATH)
    if actual_acceptance_schema != acceptance_schema_sha256:
        raise Phase10PolicyError("Phase 10 acceptance schema identity is stale")
    actual_ci_schema = _load_schema_sha256(repo_root, CI_ATTESTATION_SCHEMA_PATH)
    if actual_ci_schema != ci_attestation_schema_sha256:
        raise Phase10PolicyError("Phase 10 CI attestation schema identity is stale")

    return Phase10Policy(
        policy_id=policy_id,
        schema_version="1.0",
        plan_version="phase10-self-hosting-acceptance-v1",
        acceptance_schema_sha256=acceptance_schema_sha256,
        ci_attestation_schema_sha256=ci_attestation_schema_sha256,
        repository=repository,
        protected_branch_ref=protected_branch_ref,
        allowed_merge_methods=allowed_merge_methods,
        required_workflows=workflows,
        required_ci_jobs=jobs,
        required_security_checks=security_checks,
        limits=limits,
        sha256=canonical_json_sha256(policy),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate Phase 10 policy field")
        value[key] = item
    return value


def _load_schema_sha256(repo_root: Path, relative_path: Path) -> str:
    path = repo_root.resolve() / relative_path
    if path.is_symlink() or not path.is_file():
        raise Phase10PolicyError(f"Phase 10 schema source is missing or unsafe: {relative_path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise Phase10PolicyError(f"Phase 10 schema source is invalid: {relative_path}") from exc
    if not isinstance(value, dict):
        raise Phase10PolicyError(f"Phase 10 schema source is invalid: {relative_path}")
    return canonical_json_sha256(value)


def _bounded_string(value: Mapping[str, Any], name: str, *, maximum: int) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result or len(result.encode("utf-8")) > maximum:
        raise Phase10PolicyError(f"Phase 10 policy {name} is invalid")
    return result


def _unique_strings(
    value: Mapping[str, Any],
    name: str,
    *,
    maximum: int,
) -> tuple[str, ...]:
    return _canonical_string_list(value.get(name), context=name, maximum=maximum)


def _canonical_string_list(
    raw: object,
    *,
    context: str,
    maximum: int,
) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not 1 <= len(raw) <= maximum
        or not all(isinstance(item, str) and item for item in raw)
    ):
        raise Phase10PolicyError(f"Phase 10 policy {context} is invalid")
    result = tuple(cast(list[str], raw))
    if result != tuple(sorted(set(result))):
        raise Phase10PolicyError(f"Phase 10 policy {context} is not canonical")
    return result


__all__ = [
    "CI_ATTESTATION_SCHEMA_PATH",
    "PHASE10_POLICY_PATH",
    "PHASE10_SCHEMA_PATH",
    "Phase10Policy",
    "Phase10PolicyError",
    "load_phase10_policy",
]

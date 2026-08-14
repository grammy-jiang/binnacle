"""Deterministic, authority-free evaluation of Phase 10 acceptance evidence."""

from __future__ import annotations

import base64
import binascii
import io
import json
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from binnacle.evaluation.digests import canonical_json_bytes, canonical_json_sha256, sha256_bytes
from binnacle.evaluation.phase10_policy import (
    PHASE10_SCHEMA_PATH,
    Phase10CiWorkflowProfile,
    Phase10Policy,
    load_phase10_policy,
)


class AcceptanceManifestError(ValueError):
    """The supplied evidence document is not a closed Phase 10 manifest."""


class ArtifactApiLookupUnavailable(RuntimeError):
    """The authenticated, non-manifest GitHub artifact lookup could not complete."""


ArtifactApiLookup = Callable[[str, int], Mapping[str, Any] | None]


class CiApiLookupUnavailable(RuntimeError):
    """The authenticated GitHub job/run/workflow lookup could not complete."""


CiApiLookup = Callable[[str, int, int, str, str], Mapping[str, Any] | None]


class AcceptanceVerdict(StrEnum):
    """Only terminal evaluator outcomes permitted by the Phase 10 plan."""

    # This is a public evaluator verdict label, never a credential.
    PASS = "PASS"  # nosec B105
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class AcceptanceFinding:
    """One bounded reason preventing PASS."""

    disposition: AcceptanceVerdict
    code: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {
            "disposition": self.disposition.value,
            "code": self.code,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    """Deterministic safe summary of one evaluated evidence manifest."""

    acceptance_run_id: str
    verdict: AcceptanceVerdict
    manifest_sha256: str
    policy_sha256: str
    findings: tuple[AcceptanceFinding, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "acceptance_run_id": self.acceptance_run_id,
            "verdict": self.verdict.value,
            "manifest_sha256": self.manifest_sha256,
            "policy_sha256": self.policy_sha256,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(slots=True)
class _Findings:
    values: list[AcceptanceFinding] = field(default_factory=list)
    _seen: set[tuple[AcceptanceVerdict, str, str]] = field(default_factory=set)

    def fail(self, code: str, path: str) -> None:
        self._add(AcceptanceVerdict.FAIL, code, path)

    def incomplete(self, code: str, path: str) -> None:
        self._add(AcceptanceVerdict.INCOMPLETE, code, path)

    def _add(self, disposition: AcceptanceVerdict, code: str, path: str) -> None:
        key = disposition, code, path
        if key not in self._seen:
            self._seen.add(key)
            self.values.append(AcceptanceFinding(disposition=disposition, code=code, path=path))

    def verdict(self) -> AcceptanceVerdict:
        if any(item.disposition is AcceptanceVerdict.FAIL for item in self.values):
            return AcceptanceVerdict.FAIL
        if self.values:
            return AcceptanceVerdict.INCOMPLETE
        return AcceptanceVerdict.PASS

    def frozen(self) -> tuple[AcceptanceFinding, ...]:
        rank = {AcceptanceVerdict.FAIL: 0, AcceptanceVerdict.INCOMPLETE: 1}
        return tuple(
            sorted(
                self.values,
                key=lambda item: (rank[item.disposition], item.code, item.path),
            )
        )


def create_phase10_skeleton(*, acceptance_run_id: str, repo_root: Path) -> dict[str, Any]:
    """Create a schema-valid planned run without claiming any external evidence."""

    policy = load_phase10_policy(repo_root)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "acceptance_run_id": acceptance_run_id,
        "plan_version": policy.plan_version,
        "policy_sha256": policy.sha256,
        "state": "planned",
        "readiness": {
            "evidence_ref": None,
            "real_chatgpt_connection": "unavailable",
            "real_development_pi": "unavailable",
            "predecessor_promotions": "unavailable",
            "baseline_coherence": "unavailable",
        },
        "baseline": None,
        "branch": None,
        "candidate_generations": [],
        "final_candidate_generation": None,
        "integration_generations": [],
        "final_integration_generation": None,
        "failure_exercise": None,
        "github_pr": None,
        "github_merge": None,
        "local_update": None,
        "post_merge_local_checks": [],
        "restart": None,
        "post_restart_runtime": None,
        "behaviour_probe": None,
        "security_checks": [],
        "unresolved_refs": [],
        "owner_review": None,
    }
    _validate_manifest_schema(manifest, repo_root)
    return manifest


def evaluate_phase10_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    authenticated_artifact_api_lookup: ArtifactApiLookup | None = None,
    authenticated_ci_api_lookup: CiApiLookup | None = None,
) -> AcceptanceReport:
    """Evaluate evidence without device effects, using a trusted live API reader when supplied."""

    _validate_manifest_schema(manifest, repo_root)
    policy = load_phase10_policy(repo_root)
    value = dict(manifest)
    findings = _Findings()

    if value["policy_sha256"] != policy.sha256:
        findings.incomplete("policy_identity_stale", "/policy_sha256")

    _evaluate_readiness(_object(value["readiness"]), findings)
    baseline = _optional_object(value["baseline"])
    branch = _optional_object(value["branch"])
    _evaluate_baseline_and_branch(baseline, branch, policy, findings)

    candidates = _object_list(value["candidate_generations"])
    final_candidate = _select_final_generation(
        candidates,
        value["final_candidate_generation"],
        kind="candidate",
        findings=findings,
    )
    for candidate in candidates:
        _evaluate_candidate(candidate, baseline, branch, policy, findings)
    _reject_reused_candidate_evidence(candidates, findings)

    integrations = _object_list(value["integration_generations"])
    final_integration = _select_final_generation(
        integrations,
        value["final_integration_generation"],
        kind="integration",
        findings=findings,
    )
    if final_integration is not None:
        _evaluate_integration(
            final_integration,
            final_candidate,
            candidates,
            baseline,
            policy,
            findings,
            authenticated_artifact_api_lookup,
            authenticated_ci_api_lookup,
        )
        _reject_reused_integration_evidence(integrations, final_integration, findings)

    _evaluate_failure_exercise(_optional_object(value["failure_exercise"]), findings)
    github_merge = _optional_object(value["github_merge"])
    restart_evidence = _optional_object(value["restart"])
    runtime_evidence = _optional_object(value["post_restart_runtime"])
    _evaluate_hosted_and_local_chain(
        github_pr=_optional_object(value["github_pr"]),
        github_merge=github_merge,
        local_update=_optional_object(value["local_update"]),
        post_merge_checks=_object_list(value["post_merge_local_checks"]),
        candidates=candidates,
        final_candidate=final_candidate,
        final_integration=final_integration,
        policy=policy,
        findings=findings,
    )
    runtime = _evaluate_restart_and_runtime(
        restart=restart_evidence,
        runtime=runtime_evidence,
        github_merge=github_merge,
        baseline=baseline,
        findings=findings,
    )
    _evaluate_behaviour_probe(_optional_object(value["behaviour_probe"]), runtime, findings)
    _evaluate_security(
        _object_list(value["security_checks"]),
        acceptance_run_id=cast(str, value["acceptance_run_id"]),
        policy=policy,
        github_merge=github_merge,
        restart=restart_evidence,
        runtime=runtime,
        findings=findings,
    )
    if cast(list[object], value["unresolved_refs"]):
        findings.incomplete("unresolved_evidence_remains", "/unresolved_refs")
    _evaluate_owner_review(
        _optional_object(value["owner_review"]),
        acceptance_run_id=cast(str, value["acceptance_run_id"]),
        policy_sha256=policy.sha256,
        reviewed_evidence_sha256=phase10_reviewed_evidence_sha256(value),
        findings=findings,
    )

    state = cast(str, value["state"])
    if state == "failed":
        findings.fail("run_declared_failed", "/state")
    elif state == "incomplete":
        findings.incomplete("run_declared_incomplete", "/state")
    elif state != "passed" and findings.verdict() is AcceptanceVerdict.PASS:
        findings.incomplete("run_not_terminally_closed", "/state")

    return AcceptanceReport(
        acceptance_run_id=cast(str, value["acceptance_run_id"]),
        verdict=findings.verdict(),
        manifest_sha256=canonical_json_sha256(value),
        policy_sha256=policy.sha256,
        findings=findings.frozen(),
    )


def _validate_manifest_schema(manifest: Mapping[str, Any], repo_root: Path) -> None:
    path = repo_root.resolve() / PHASE10_SCHEMA_PATH
    if path.is_symlink() or not path.is_file():
        raise AcceptanceManifestError("Phase 10 acceptance schema is missing or unsafe")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceManifestError("Phase 10 acceptance schema is invalid") from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(dict(manifest)), key=lambda item: list(item.path))
    error = next(iter(errors), None)
    if error is not None:
        location = "/" + "/".join(str(item) for item in error.absolute_path)
        raise AcceptanceManifestError(f"Phase 10 manifest violates its schema at {location}")


def _evaluate_readiness(value: dict[str, Any], findings: _Findings) -> None:
    for name in (
        "real_chatgpt_connection",
        "real_development_pi",
        "predecessor_promotions",
        "baseline_coherence",
    ):
        status = value[name]
        path = f"/readiness/{name}"
        if status in {"unavailable", "stale"}:
            findings.incomplete("readiness_not_current", path)
        elif status == "failed":
            findings.fail("readiness_verification_failed", path)
    if value["evidence_ref"] is None:
        findings.incomplete("readiness_evidence_missing", "/readiness/evidence_ref")


def _evaluate_baseline_and_branch(
    baseline: dict[str, Any] | None,
    branch: dict[str, Any] | None,
    policy: Phase10Policy,
    findings: _Findings,
) -> None:
    if baseline is None:
        findings.incomplete("baseline_missing", "/baseline")
    else:
        if not baseline["repository_clean"]:
            findings.fail("baseline_repository_dirty", "/baseline/repository_clean")
        if baseline["repository_head_oid"] != baseline["protected_base_oid"]:
            findings.fail(
                "baseline_protected_base_mismatch",
                "/baseline/protected_base_oid",
            )
    if branch is None:
        findings.incomplete("feature_branch_missing", "/branch")
        return
    if branch["protected_branch_mutated"]:
        findings.fail("protected_branch_mutated", "/branch/protected_branch_mutated")
    if branch["ref"] == policy.protected_branch_ref:
        findings.fail("feature_branch_is_protected_branch", "/branch/ref")
    if branch["created_from_oid"] != branch["observed_oid"]:
        findings.fail("feature_branch_oid_mismatch", "/branch/observed_oid")
    if baseline is not None and branch["created_from_oid"] != baseline["repository_head_oid"]:
        findings.fail("feature_branch_not_from_baseline", "/branch/created_from_oid")


def _select_final_generation(
    generations: list[dict[str, Any]],
    selected: object,
    *,
    kind: str,
    findings: _Findings,
) -> dict[str, Any] | None:
    plural = f"{kind}_generations"
    selected_path = f"/final_{kind}_generation"
    if not generations:
        findings.incomplete(f"{kind}_generation_missing", f"/{plural}")
        if selected is not None:
            findings.fail(f"{kind}_selection_without_generation", selected_path)
        return None
    numbers = [cast(int, item["generation"]) for item in generations]
    if numbers != list(range(1, len(generations) + 1)):
        findings.fail(f"{kind}_generation_sequence_invalid", f"/{plural}")
    if selected is None:
        findings.incomplete(f"final_{kind}_generation_missing", selected_path)
        return None
    selected_number = cast(int, selected)
    indexed = {cast(int, item["generation"]): item for item in generations}
    current = indexed.get(selected_number)
    if current is None:
        findings.fail(f"final_{kind}_generation_unknown", selected_path)
        return None
    if selected_number != max(numbers):
        findings.fail(f"final_{kind}_generation_not_latest", selected_path)
    for item in generations:
        number = cast(int, item["generation"])
        superseded = item["superseded_reason_ref"]
        if number == selected_number and superseded is not None:
            findings.fail(f"final_{kind}_generation_superseded", f"/{plural}/{number - 1}")
        elif number != selected_number and superseded is None:
            findings.incomplete(
                f"prior_{kind}_generation_not_superseded",
                f"/{plural}/{number - 1}/superseded_reason_ref",
            )
    return current


def _evaluate_candidate(
    candidate: dict[str, Any],
    baseline: dict[str, Any] | None,
    branch: dict[str, Any] | None,
    policy: Phase10Policy,
    findings: _Findings,
) -> None:
    generation = cast(int, candidate["generation"])
    prefix = f"/candidate_generations/{generation - 1}"
    source_digest = candidate["source_content_sha256"]
    checks = _object_list(candidate["local_checks"])
    _evaluate_local_check_profile(
        checks,
        policy=policy,
        prefix=f"{prefix}/local_checks",
        findings=findings,
    )
    _evaluate_local_check_evidence_set(
        checks,
        stage="candidate",
        prefix=f"{prefix}/local_checks",
        findings=findings,
    )
    for index, check in enumerate(checks):
        check_path = f"{prefix}/local_checks/{index}"
        if check["source_content_sha256"] != source_digest:
            findings.fail("candidate_check_source_mismatch", check_path)
        _evaluate_check_truth(check, check_path, findings)

    status = _object(candidate["status_diff"])
    commit = _object(candidate["signed_commit"])
    push = _object(candidate["push"])
    if status["unexpected_paths"]:
        findings.fail("candidate_contains_unexpected_paths", f"{prefix}/status_diff")
    if status["parent_oid"] != commit["parent_oid"]:
        findings.fail("candidate_parent_evidence_mismatch", f"{prefix}/signed_commit/parent_oid")
    if branch is not None and status["branch_ref"] != branch["ref"]:
        findings.fail("candidate_branch_mismatch", f"{prefix}/status_diff/branch_ref")
    if (
        generation == 1
        and baseline is not None
        and commit["parent_oid"] != baseline["repository_head_oid"]
    ):
        findings.fail("first_candidate_parent_not_baseline", f"{prefix}/signed_commit/parent_oid")
    if commit["source_content_sha256"] != source_digest:
        findings.fail("signed_commit_source_mismatch", f"{prefix}/signed_commit")
    if not commit["signature_verified"]:
        findings.fail("candidate_signature_unverified", f"{prefix}/signed_commit")
    if baseline is not None and commit["signer_sha256"] != baseline["commit_signer_sha256"]:
        findings.fail("candidate_signer_mismatch", f"{prefix}/signed_commit/signer_sha256")
    commit_oid = commit["oid"]
    if push["conclusion"] == "failure":
        findings.fail("candidate_push_failed", f"{prefix}/push")
    elif push["conclusion"] == "uncertain":
        findings.incomplete("candidate_push_uncertain", f"{prefix}/push")
    if push["target_oid"] != commit_oid or push["remote_observed_oid"] != commit_oid:
        findings.fail("candidate_push_oid_mismatch", f"{prefix}/push")
    if branch is not None and push["remote_ref"] != branch["ref"]:
        findings.fail("candidate_push_ref_mismatch", f"{prefix}/push/remote_ref")
    if baseline is not None and push["remote_profile_sha256"] != baseline["remote_profile_sha256"]:
        findings.fail(
            "candidate_remote_profile_mismatch",
            f"{prefix}/push/remote_profile_sha256",
        )
    if candidate["hosted_head_oid"] != commit_oid:
        findings.fail("hosted_head_not_signed_candidate", f"{prefix}/hosted_head_oid")


def _evaluate_check_truth(check: dict[str, Any], path: str, findings: _Findings) -> None:
    conclusion = check["conclusion"]
    if conclusion == "failure":
        findings.fail("required_check_failed", f"{path}/conclusion")
    elif conclusion == "uncertain":
        findings.incomplete("required_check_uncertain", f"{path}/conclusion")
    if not check["terminal"]:
        findings.incomplete("required_check_nonterminal", f"{path}/terminal")
    if not check["descendants_closed"]:
        findings.incomplete("required_check_descendants_open", f"{path}/descendants_closed")
    if not check["workspace_fence_closed"]:
        findings.incomplete("required_check_fence_open", f"{path}/workspace_fence_closed")


def _reject_reused_candidate_evidence(
    candidates: list[dict[str, Any]],
    findings: _Findings,
) -> None:
    prior_identities: set[tuple[str, str]] = set()
    for index, candidate in enumerate(candidates):
        identities = _candidate_evidence_identities(candidate)
        if identities & prior_identities:
            findings.incomplete(
                "candidate_generation_reuses_stale_evidence",
                f"/candidate_generations/{index}",
            )
        prior_identities.update(identities)


def _candidate_evidence_identities(candidate: dict[str, Any]) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for evidence_ref in (
        _object(candidate["status_diff"])["evidence_ref"],
        _object(candidate["signed_commit"])["evidence_ref"],
        _object(candidate["push"])["evidence_ref"],
    ):
        values.update(_evidence_ref_identities(evidence_ref))
    for check in _object_list(candidate["local_checks"]):
        values.update(_evidence_ref_identities(check["evidence_ref"]))
    return values


def _evaluate_integration(
    integration: dict[str, Any],
    candidate: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    policy: Phase10Policy,
    findings: _Findings,
    authenticated_artifact_api_lookup: ArtifactApiLookup | None,
    authenticated_ci_api_lookup: CiApiLookup | None,
) -> None:
    generation = cast(int, integration["generation"])
    prefix = f"/integration_generations/{generation - 1}"
    if candidate is None:
        findings.incomplete("integration_has_no_final_candidate", prefix)
        return
    candidate_generation = cast(int, candidate["generation"])
    candidate_oid = _object(candidate["signed_commit"])["oid"]
    if integration["candidate_generation"] != candidate_generation:
        findings.incomplete("integration_uses_stale_candidate_generation", prefix)
    if integration["candidate_oid"] != candidate_oid:
        findings.incomplete("integration_uses_stale_candidate_oid", f"{prefix}/candidate_oid")
    if integration["merge_policy_sha256"] != policy.sha256:
        findings.incomplete("integration_merge_policy_stale", f"{prefix}/merge_policy_sha256")

    reviews = _object_list(integration["reviews"])
    for index, review in enumerate(reviews):
        path = f"{prefix}/reviews/{index}"
        if (
            review["candidate_oid"] != integration["candidate_oid"]
            or review["protected_base_oid"] != integration["protected_base_oid"]
        ):
            findings.incomplete("review_bound_to_stale_integration", path)
        if not review["substantive"]:
            findings.incomplete("review_not_substantive", f"{path}/substantive")
        if not review["clean"]:
            findings.fail("review_rejected_integration", f"{path}/clean")
        if review["unresolved_actionable_count"] != 0:
            findings.incomplete("review_findings_unresolved", f"{path}/unresolved_actionable_count")

    observed_jobs: dict[str, set[str]] = {}
    observed_attestations: set[str] = set()
    observed_artifact_ids: set[int] = set()
    observed_artifact_archives: set[str] = set()
    observed_artifact_api_ref_ids: set[str] = set()
    observed_artifact_api_ref_digests: set[str] = set()
    observed_job_ids: set[int] = set()
    observed_ci_api_ref_ids: set[str] = set()
    observed_ci_api_ref_digests: set[str] = set()
    expected_tree = integration["expected_integration_tree_oid"]
    commit = _object(candidate["signed_commit"])
    integration_base_oid = cast(str, integration["protected_base_oid"])
    lineage_base_oid = _candidate_lineage_base(candidates, candidate, findings)
    recognized_lineage_bases = {integration_base_oid}
    if baseline is not None:
        recognized_lineage_bases.add(cast(str, baseline["repository_head_oid"]))
    if lineage_base_oid is not None and lineage_base_oid not in recognized_lineage_bases:
        findings.fail(
            "candidate_lineage_disconnected",
            f"/candidate_generations/{candidate_generation - 1}/signed_commit/parent_oid",
        )
    if lineage_base_oid == integration_base_oid and commit["tree_oid"] != expected_tree:
        findings.fail("same_base_signed_tree_mismatch", f"{prefix}/expected_integration_tree_oid")
    ci_evidence = _object_list(integration["ci_evidence"])
    for index, evidence in enumerate(ci_evidence):
        path = f"{prefix}/ci_evidence/{index}"
        workflow = cast(str, evidence["workflow_name"])
        attestation = _object(evidence["attestation"])
        attestation_sha256 = cast(str, evidence["attestation_sha256"])
        artifact_name = cast(str, evidence["github_artifact_name"])
        artifact_id = cast(int, evidence["github_artifact_id"])
        artifact_archive_sha256 = cast(str, evidence["github_artifact_archive_sha256"])
        artifact_api_ref = _object(evidence["github_artifact_api_ref"])
        artifact_api_observation = _object(evidence["github_artifact_api_observation"])
        job_id = cast(int, evidence["github_job_id"])
        ci_api_ref = _object(evidence["github_ci_api_ref"])
        ci_api_observation = _object(evidence["github_ci_api_observation"])
        ci_api_identity = (_ref_id(ci_api_ref), cast(str, ci_api_ref["sha256"]))
        if job_id in observed_job_ids:
            findings.fail("ci_job_reused", f"{path}/github_job_id")
        observed_job_ids.add(job_id)
        if (
            ci_api_identity[0] in observed_ci_api_ref_ids
            or ci_api_identity[1] in observed_ci_api_ref_digests
        ):
            findings.fail("ci_job_reused", f"{path}/github_ci_api_ref")
        observed_ci_api_ref_ids.add(ci_api_identity[0])
        observed_ci_api_ref_digests.add(ci_api_identity[1])
        if canonical_json_sha256(ci_api_observation) != ci_api_identity[1]:
            findings.fail(
                "ci_api_observation_digest_mismatch",
                f"{path}/github_ci_api_ref/sha256",
            )
        workflow_profile = policy.required_ci_workflow_profiles.get(workflow)
        if workflow_profile is not None:
            _authenticate_ci_api_observation(
                lookup=authenticated_ci_api_lookup,
                repository=policy.repository,
                job_id=job_id,
                run_id=cast(int, evidence["run_id"]),
                workflow_path=workflow_profile.path,
                checkout_oid=cast(str, evidence["checkout_oid"]),
                embedded=ci_api_observation,
                path=path,
                findings=findings,
            )
            _evaluate_ci_api_observation(
                evidence=evidence,
                observation=ci_api_observation,
                workflow_profile=workflow_profile,
                path=path,
                findings=findings,
            )
        artifact_api_identity = (
            _ref_id(artifact_api_ref),
            cast(str, artifact_api_ref["sha256"]),
        )
        if (
            artifact_api_identity[0] in observed_artifact_api_ref_ids
            or artifact_api_identity[1] in observed_artifact_api_ref_digests
        ):
            findings.fail("ci_artifact_reused", f"{path}/github_artifact_api_ref")
        observed_artifact_api_ref_ids.add(artifact_api_identity[0])
        observed_artifact_api_ref_digests.add(artifact_api_identity[1])
        if canonical_json_sha256(artifact_api_observation) != artifact_api_identity[1]:
            findings.fail(
                "ci_artifact_api_observation_digest_mismatch",
                f"{path}/github_artifact_api_ref/sha256",
            )
        _authenticate_artifact_api_observation(
            lookup=authenticated_artifact_api_lookup,
            repository=policy.repository,
            artifact_id=artifact_id,
            embedded=artifact_api_observation,
            path=path,
            findings=findings,
        )
        if artifact_api_observation["repository"] != evidence["repository"]:
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/repository",
            )
        if artifact_api_observation["id"] != artifact_id:
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/id",
            )
        if artifact_api_observation["name"] != artifact_name:
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/name",
            )
        if artifact_api_observation["expired"]:
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/expired",
            )
        if artifact_api_observation["digest"] != f"sha256:{artifact_archive_sha256}":
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/digest",
            )
        workflow_run = _object(artifact_api_observation["workflow_run"])
        if (
            workflow_run["id"] != evidence["run_id"]
            or workflow_run["head_sha"] != evidence["candidate_oid"]
        ):
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/workflow_run",
            )
        expected_api_url = (
            f"https://api.github.com/repos/{evidence['repository']}/actions/artifacts/{artifact_id}"
        )
        if (
            artifact_api_observation["url"] != expected_api_url
            or artifact_api_observation["archive_download_url"] != f"{expected_api_url}/zip"
        ):
            findings.fail(
                "ci_artifact_api_metadata_mismatch",
                f"{path}/github_artifact_api_observation/url",
            )
        if artifact_id in observed_artifact_ids:
            findings.fail("ci_artifact_reused", f"{path}/github_artifact_id")
        observed_artifact_ids.add(artifact_id)
        if artifact_archive_sha256 in observed_artifact_archives:
            findings.fail("ci_artifact_reused", f"{path}/github_artifact_archive_sha256")
        observed_artifact_archives.add(artifact_archive_sha256)
        expected_artifact_name = _expected_artifact_name(evidence)
        if artifact_name != expected_artifact_name:
            findings.fail("ci_artifact_name_mismatch", f"{path}/github_artifact_name")
        archive_payload = _decode_artifact_archive(evidence, path, findings)
        if archive_payload is not None:
            if artifact_api_observation["size_in_bytes"] != len(archive_payload):
                findings.fail(
                    "ci_artifact_api_metadata_mismatch",
                    f"{path}/github_artifact_api_observation/size_in_bytes",
                )
            artifact_attestation = _attestation_from_archive(archive_payload, path, findings)
            if artifact_attestation is not None and artifact_attestation != attestation:
                findings.fail("ci_artifact_attestation_mismatch", f"{path}/attestation")
        if attestation_sha256 in observed_attestations:
            findings.fail("ci_attestation_reused", f"{path}/attestation_sha256")
        observed_attestations.add(attestation_sha256)
        if sha256_bytes(canonical_json_bytes(attestation) + b"\n") != attestation_sha256:
            findings.fail("ci_attestation_digest_mismatch", f"{path}/attestation_sha256")
        attestation_bindings = (
            ("workflow_name", "workflow_name"),
            ("job_name", "job_name"),
            ("run_id", "run_id"),
            ("run_attempt", "run_attempt"),
            ("repository", "repository"),
            ("event_name", "event_name"),
            ("collector_commit_oid", "collector_commit_oid"),
            ("collector_sha256", "collector_sha256"),
            ("candidate_oid", "event_candidate_oid"),
            ("protected_base_oid", "event_base_oid"),
            ("github_sha", "github_sha"),
            ("checkout_oid", "checkout_oid"),
            ("checkout_tree_oid", "checkout_tree_oid"),
            ("checkout_parent_oids", "checkout_parent_oids"),
            ("checkout_kind", "checkout_kind"),
        )
        if attestation["event_after_oid"] is not None or any(
            evidence[evidence_name] != attestation[attestation_name]
            for evidence_name, attestation_name in attestation_bindings
        ):
            findings.fail("ci_attestation_identity_mismatch", f"{path}/attestation")
        if evidence["required"]:
            observed_jobs.setdefault(workflow, set()).add(cast(str, evidence["job_name"]))
            if workflow not in policy.required_ci_jobs:
                findings.incomplete("unexpected_required_ci_evidence", path)
        if evidence["repository"] != policy.repository:
            findings.fail("ci_repository_mismatch", f"{path}/repository")
        if evidence["collector_commit_oid"] != policy.ci_attestation_collector_commit_oid:
            findings.fail("ci_collector_commit_mismatch", f"{path}/collector_commit_oid")
        if evidence["collector_sha256"] != policy.ci_attestation_collector_sha256:
            findings.fail("ci_collector_bundle_mismatch", f"{path}/collector_sha256")
        if evidence["github_sha"] != evidence["checkout_oid"]:
            findings.incomplete("ci_github_sha_unbound", f"{path}/github_sha")
        if evidence["conclusion"] == "failure":
            findings.fail("required_ci_failed", f"{path}/conclusion")
        elif evidence["conclusion"] == "uncertain":
            findings.incomplete("required_ci_uncertain", f"{path}/conclusion")
        if (
            evidence["candidate_oid"] != integration["candidate_oid"]
            or evidence["protected_base_oid"] != integration["protected_base_oid"]
        ):
            findings.incomplete("ci_bound_to_stale_integration", path)
        if evidence["checkout_kind"] != "pull_request_integration":
            findings.incomplete("ci_checkout_integration_unbound", f"{path}/checkout_kind")
        parents = cast(list[str], evidence["checkout_parent_oids"])
        if parents != [integration["protected_base_oid"], integration["candidate_oid"]]:
            findings.incomplete("ci_checkout_parents_unbound", f"{path}/checkout_parent_oids")
        if evidence["checkout_tree_oid"] != expected_tree:
            findings.fail("ci_checkout_tree_mismatch", f"{path}/checkout_tree_oid")

    for workflow in policy.required_workflows:
        required_jobs = set(policy.required_ci_jobs[workflow])
        if observed_jobs.get(workflow, set()) != required_jobs:
            findings.incomplete("required_ci_job_evidence_missing", f"{prefix}/ci_evidence")


def _authenticate_ci_api_observation(
    *,
    lookup: CiApiLookup | None,
    repository: str,
    job_id: int,
    run_id: int,
    workflow_path: str,
    checkout_oid: str,
    embedded: dict[str, Any],
    path: str,
    findings: _Findings,
) -> None:
    """Compare retained CI facts with live job, run, and exact-workflow sources."""

    if lookup is None:
        findings.incomplete(
            "ci_api_authentication_missing",
            f"{path}/github_ci_api_observation",
        )
        return
    try:
        authenticated = lookup(repository, job_id, run_id, workflow_path, checkout_oid)
    except CiApiLookupUnavailable:
        findings.incomplete(
            "ci_api_lookup_unavailable",
            f"{path}/github_ci_api_observation",
        )
        return
    if authenticated is None:
        findings.fail("ci_api_record_not_found", f"{path}/github_ci_api_observation")
        return
    try:
        authenticated_value = dict(authenticated)
        canonical_json_sha256(authenticated_value)
    except (TypeError, ValueError, RecursionError):
        findings.fail(
            "ci_api_authentication_invalid",
            f"{path}/github_ci_api_observation",
        )
        return
    if authenticated_value != embedded:
        findings.fail(
            "ci_api_authentication_mismatch",
            f"{path}/github_ci_api_observation",
        )


def _evaluate_ci_api_observation(
    *,
    evidence: dict[str, Any],
    observation: dict[str, Any],
    workflow_profile: Phase10CiWorkflowProfile,
    path: str,
    findings: _Findings,
) -> None:
    """Bind authoritative CI state to the reviewed workflow source and manifest record."""

    repository = cast(str, evidence["repository"])
    job_id = cast(int, evidence["github_job_id"])
    run_id = cast(int, evidence["run_id"])
    job_attempt = cast(int, evidence["run_attempt"])
    workflow_run_attempt = cast(int, evidence["workflow_run_attempt"])
    workflow_name = cast(str, evidence["workflow_name"])
    candidate_oid = cast(str, evidence["candidate_oid"])
    checkout_oid = cast(str, evidence["checkout_oid"])
    job = _object(observation["job"])
    workflow_run = _object(observation["workflow_run"])
    workflow_source = _object(observation["workflow_source"])
    if observation["repository"] != repository:
        findings.fail("ci_api_metadata_mismatch", f"{path}/github_ci_api_observation/repository")
    job_bindings = {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": job_attempt,
        "workflow_name": workflow_name,
        "name": evidence["job_name"],
        "head_sha": candidate_oid,
        "url": f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}",
        "check_run_url": f"https://api.github.com/repos/{repository}/check-runs/{job_id}",
    }
    if any(job[name] != expected for name, expected in job_bindings.items()):
        findings.fail("ci_job_api_metadata_mismatch", f"{path}/github_ci_api_observation/job")
    if observation["latest_job_id"] != job_id:
        findings.fail(
            "ci_job_superseded_by_later_attempt",
            f"{path}/github_ci_api_observation/latest_job_id",
        )
    if job["status"] != "completed":
        findings.incomplete(
            "ci_job_api_nonterminal", f"{path}/github_ci_api_observation/job/status"
        )
    elif job["conclusion"] != "success":
        findings.fail(
            "ci_job_api_not_successful",
            f"{path}/github_ci_api_observation/job/conclusion",
        )
    expected_manifest_conclusion = (
        "success"
        if job["status"] == "completed" and job["conclusion"] == "success"
        else "failure"
        if job["status"] == "completed" and job["conclusion"] is not None
        else "uncertain"
    )
    if evidence["conclusion"] != expected_manifest_conclusion:
        findings.fail("ci_job_conclusion_mismatch", f"{path}/conclusion")

    run_bindings = {
        "id": run_id,
        "run_attempt": workflow_run_attempt,
        "workflow_id": workflow_profile.workflow_id,
        "name": workflow_name,
        "path": workflow_profile.path,
        "event": evidence["event_name"],
        "head_sha": candidate_oid,
        "url": f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        "jobs_url": f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs",
    }
    if any(workflow_run[name] != expected for name, expected in run_bindings.items()):
        findings.fail(
            "ci_workflow_run_api_metadata_mismatch",
            f"{path}/github_ci_api_observation/workflow_run",
        )
    if workflow_run_attempt < job_attempt:
        findings.fail(
            "ci_workflow_run_attempt_precedes_job_attempt",
            f"{path}/workflow_run_attempt",
        )
    if workflow_run["status"] != "completed":
        findings.incomplete(
            "ci_workflow_run_api_nonterminal",
            f"{path}/github_ci_api_observation/workflow_run/status",
        )
    elif workflow_run["conclusion"] != "success":
        findings.fail(
            "ci_workflow_run_api_not_successful",
            f"{path}/github_ci_api_observation/workflow_run/conclusion",
        )

    source_bindings = {
        "path": workflow_profile.path,
        "ref": checkout_oid,
        "sha256": workflow_profile.source_sha256,
    }
    if any(workflow_source[name] != expected for name, expected in source_bindings.items()):
        findings.fail(
            "ci_workflow_source_identity_mismatch",
            f"{path}/github_ci_api_observation/workflow_source",
        )


def _authenticate_artifact_api_observation(
    *,
    lookup: ArtifactApiLookup | None,
    repository: str,
    artifact_id: int,
    embedded: dict[str, Any],
    path: str,
    findings: _Findings,
) -> None:
    """Compare manifest metadata with an authenticated source outside the manifest."""

    if lookup is None:
        findings.incomplete(
            "ci_artifact_api_authentication_missing",
            f"{path}/github_artifact_api_observation",
        )
        return
    try:
        authenticated = lookup(repository, artifact_id)
    except ArtifactApiLookupUnavailable:
        findings.incomplete(
            "ci_artifact_api_lookup_unavailable",
            f"{path}/github_artifact_api_observation",
        )
        return
    if authenticated is None:
        findings.fail(
            "ci_artifact_api_not_found",
            f"{path}/github_artifact_api_observation/id",
        )
        return
    try:
        authenticated_value = dict(authenticated)
        canonical_json_sha256(authenticated_value)
    except (TypeError, ValueError, RecursionError):
        findings.fail(
            "ci_artifact_api_authentication_invalid",
            f"{path}/github_artifact_api_observation",
        )
        return
    if authenticated_value != embedded:
        findings.fail(
            "ci_artifact_api_authentication_mismatch",
            f"{path}/github_artifact_api_observation",
        )


def _candidate_lineage_base(
    candidates: list[dict[str, Any]],
    final_candidate: dict[str, Any],
    findings: _Findings,
) -> str | None:
    """Require the final candidate to consume every immediately preceding generation."""

    commit_oids = [
        cast(str, _object(candidate["signed_commit"])["oid"]) for candidate in candidates
    ]
    if len(commit_oids) != len(set(commit_oids)):
        findings.fail("candidate_lineage_duplicate_oid", "/candidate_generations")
        return None

    current_index = cast(int, final_candidate["generation"]) - 1
    if current_index >= len(candidates) or candidates[current_index] is not final_candidate:
        findings.fail("candidate_lineage_disconnected", "/candidate_generations")
        return None
    for index in range(current_index, 0, -1):
        actual_parent = _object(candidates[index]["signed_commit"])["parent_oid"]
        expected_parent = _object(candidates[index - 1]["signed_commit"])["oid"]
        if actual_parent != expected_parent:
            findings.fail(
                "candidate_lineage_disconnected",
                f"/candidate_generations/{index}/signed_commit/parent_oid",
            )
            return None
    return cast(str, _object(candidates[0]["signed_commit"])["parent_oid"])


def _reject_reused_integration_evidence(
    integrations: list[dict[str, Any]],
    final_integration: dict[str, Any],
    findings: _Findings,
) -> None:
    final_number = cast(int, final_integration["generation"])
    final_identities = _integration_evidence_identities(final_integration)
    old_identities: set[tuple[str, str]] = set()
    for integration in integrations:
        if integration is not final_integration:
            old_identities.update(_integration_evidence_identities(integration))
    if final_identities & old_identities:
        findings.incomplete(
            "integration_generation_reuses_stale_evidence",
            f"/integration_generations/{final_number - 1}",
        )


def _integration_evidence_identities(integration: dict[str, Any]) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for review in _object_list(integration["reviews"]):
        values.update(_evidence_ref_identities(review["evidence_ref"]))
    for evidence in _object_list(integration["ci_evidence"]):
        values.update(_evidence_ref_identities(evidence["evidence_ref"]))
        values.update(_evidence_ref_identities(evidence["github_artifact_api_ref"]))
        values.add(("attestation_sha256", cast(str, evidence["attestation_sha256"])))
        values.add(("github_artifact_id", str(evidence["github_artifact_id"])))
        values.add(
            (
                "github_artifact_archive_sha256",
                cast(str, evidence["github_artifact_archive_sha256"]),
            )
        )
    return values


def _evaluate_failure_exercise(value: dict[str, Any] | None, findings: _Findings) -> None:
    if value is None:
        findings.incomplete("recoverable_failure_exercise_missing", "/failure_exercise")
        return
    if value["outcome"] == "uncertain":
        findings.incomplete("failure_exercise_uncertain", "/failure_exercise/outcome")
    elif value["outcome"] == "unsafe":
        findings.fail("failure_exercise_unsafe", "/failure_exercise/outcome")
    if not value["descendants_closed"]:
        findings.incomplete("failure_exercise_descendants_open", "/failure_exercise")
    if not value["workspace_fence_closed"]:
        findings.incomplete("failure_exercise_fence_open", "/failure_exercise")


def _evaluate_hosted_and_local_chain(
    *,
    github_pr: dict[str, Any] | None,
    github_merge: dict[str, Any] | None,
    local_update: dict[str, Any] | None,
    post_merge_checks: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    final_candidate: dict[str, Any] | None,
    final_integration: dict[str, Any] | None,
    policy: Phase10Policy,
    findings: _Findings,
) -> None:
    if github_pr is None:
        findings.incomplete("github_pr_evidence_missing", "/github_pr")
    if final_candidate is not None and github_pr is not None:
        candidate_oid = _object(final_candidate["signed_commit"])["oid"]
        if github_pr["head_oid"] != candidate_oid:
            findings.fail("github_pr_head_mismatch", "/github_pr/head_oid")
        if github_pr["head_ref"] != _object(final_candidate["push"])["remote_ref"]:
            findings.fail("github_pr_head_ref_mismatch", "/github_pr/head_ref")
    if github_pr is not None:
        if github_pr["repository"] != policy.repository:
            findings.fail("github_pr_repository_mismatch", "/github_pr/repository")
        if github_pr["base_ref"] != policy.protected_branch_ref:
            findings.fail("github_pr_base_ref_mismatch", "/github_pr/base_ref")
    if (
        final_integration is not None
        and github_pr is not None
        and github_pr["base_oid"] != final_integration["protected_base_oid"]
    ):
        findings.incomplete("github_pr_base_stale", "/github_pr/base_oid")

    if github_merge is None:
        findings.incomplete("github_merge_evidence_missing", "/github_merge")
        expected_tree = None
        result_oid = None
        result_tree = None
    else:
        expected_tree = github_merge["expected_integration_tree_oid"]
        result_oid = github_merge["result_oid"]
        result_tree = github_merge["result_tree_oid"]
        method = cast(str, github_merge["method"])
        if method not in policy.allowed_merge_methods:
            findings.incomplete("merge_method_not_accepted", "/github_merge/method")
        if not github_merge["provenance_verified"]:
            findings.incomplete("merge_provenance_unverified", "/github_merge/provenance_verified")
        if result_tree != expected_tree:
            findings.fail("hosted_merge_tree_mismatch", "/github_merge/result_tree_oid")
        if final_candidate is not None:
            candidate_oid = _object(final_candidate["signed_commit"])["oid"]
            if github_merge["candidate_oid"] != candidate_oid:
                findings.fail("hosted_merge_candidate_mismatch", "/github_merge/candidate_oid")
        if final_integration is not None:
            if github_merge["accepted_base_oid"] != final_integration["protected_base_oid"]:
                findings.fail("hosted_merge_base_mismatch", "/github_merge/accepted_base_oid")
            if expected_tree != final_integration["expected_integration_tree_oid"]:
                findings.fail(
                    "hosted_merge_expected_tree_mismatch",
                    "/github_merge/expected_integration_tree_oid",
                )
        parents = cast(list[str], github_merge["parent_oids"])
        if method == "squash" and parents != [github_merge["accepted_base_oid"]]:
            findings.fail("squash_merge_parent_mismatch", "/github_merge/parent_oids")
        elif method == "merge" and parents != [
            github_merge["accepted_base_oid"],
            github_merge["candidate_oid"],
        ]:
            findings.fail("merge_commit_parents_mismatch", "/github_merge/parent_oids")

    if local_update is None:
        findings.incomplete("local_update_evidence_missing", "/local_update")
    elif github_merge is not None:
        if local_update["head_oid"] != result_oid or local_update["tree_oid"] != result_tree:
            findings.fail("local_update_identity_mismatch", "/local_update")
        if not local_update["repository_clean"]:
            findings.fail("local_update_repository_dirty", "/local_update/repository_clean")
        if not local_update["through_phase8_semantics"]:
            findings.fail("local_update_bypassed_phase8", "/local_update/through_phase8_semantics")
        if local_update["branch_ref"] != policy.protected_branch_ref:
            findings.fail("local_update_branch_mismatch", "/local_update/branch_ref")

    if not post_merge_checks:
        findings.incomplete("post_merge_local_checks_missing", "/post_merge_local_checks")
    _evaluate_local_check_profile(
        post_merge_checks,
        policy=policy,
        prefix="/post_merge_local_checks",
        findings=findings,
    )
    _evaluate_local_check_evidence_set(
        post_merge_checks,
        stage="post_merge",
        prefix="/post_merge_local_checks",
        findings=findings,
    )
    candidate_check_identities = {
        identity
        for candidate in candidates
        for check in _object_list(candidate["local_checks"])
        for identity in _evidence_ref_identities(check["evidence_ref"])
    }
    for index, check in enumerate(post_merge_checks):
        path = f"/post_merge_local_checks/{index}"
        if _evidence_ref_identities(check["evidence_ref"]) & candidate_check_identities:
            findings.fail("post_merge_check_reuses_candidate_evidence", f"{path}/evidence_ref")
        _evaluate_check_truth(check, path, findings)
        if github_merge is not None and (
            check["commit_oid"] != result_oid or check["tree_oid"] != result_tree
        ):
            findings.fail("post_merge_check_identity_mismatch", path)


def _evaluate_local_check_profile(
    checks: list[dict[str, Any]],
    *,
    policy: Phase10Policy,
    prefix: str,
    findings: _Findings,
) -> None:
    observed: dict[str, str] = {}
    for index, check in enumerate(checks):
        check_id = cast(str, check["check_id"])
        if check_id in observed:
            findings.fail("duplicate_local_check", f"{prefix}/{index}/check_id")
        observed[check_id] = cast(str, check["check_profile_sha256"])
    required = dict(policy.required_local_check_profiles)
    if set(observed) != set(required):
        findings.incomplete("required_local_check_profile_incomplete", prefix)
    for check_id in set(observed) & set(required):
        if observed[check_id] != required[check_id]:
            findings.fail("local_check_profile_mismatch", prefix)


def _evaluate_local_check_evidence_set(
    checks: list[dict[str, Any]],
    *,
    stage: str,
    prefix: str,
    findings: _Findings,
) -> None:
    observed_ids: set[str] = set()
    observed_digests: set[str] = set()
    for index, check in enumerate(checks):
        path = f"{prefix}/{index}/evidence_ref"
        evidence_ref = _object(check["evidence_ref"])
        evidence_id = _ref_id(evidence_ref)
        evidence_sha256 = cast(str, evidence_ref["sha256"])
        if evidence_id in observed_ids or evidence_sha256 in observed_digests:
            findings.fail("local_check_evidence_reused", path)
        observed_ids.add(evidence_id)
        observed_digests.add(evidence_sha256)
        if check["evidence_binding_sha256"] != phase10_local_check_evidence_sha256(
            check,
            stage=stage,
        ):
            findings.fail("local_check_evidence_binding_mismatch", path)


def phase10_local_check_evidence_sha256(check: Mapping[str, Any], *, stage: str) -> str:
    """Hash the closed retained-evidence projection for one local check."""

    projection: dict[str, Any] = {
        "schema_version": "1.0",
        "stage": stage,
        "check_id": check["check_id"],
        "check_profile_sha256": check["check_profile_sha256"],
        "evidence_ref": check["evidence_ref"],
        "conclusion": check["conclusion"],
        "terminal": check["terminal"],
        "descendants_closed": check["descendants_closed"],
        "workspace_fence_closed": check["workspace_fence_closed"],
    }
    if stage == "candidate":
        projection["source_content_sha256"] = check["source_content_sha256"]
    elif stage == "post_merge":
        projection["commit_oid"] = check["commit_oid"]
        projection["tree_oid"] = check["tree_oid"]
    else:
        raise AssertionError("unsupported local-check evidence stage")
    return canonical_json_sha256(projection)


def _expected_artifact_name(evidence: dict[str, Any]) -> str:
    run_id = evidence["run_id"]
    attempt = evidence["run_attempt"]
    job_name = evidence["job_name"]
    suffixes = {
        "validate-contracts": "contracts",
        "Code, contract, dependency, and document quality": "python-quality",
        "Test Python 3.11": "test-python-3.11",
        "Test Python 3.12": "test-python-3.12",
        "Test Python 3.13": "test-python-3.13",
    }
    suffix = suffixes.get(cast(str, job_name), "invalid-required-job")
    return f"phase10-checkout-{run_id}-{suffix}-{attempt}"


def _decode_artifact_archive(
    evidence: dict[str, Any],
    path: str,
    findings: _Findings,
) -> bytes | None:
    encoded = cast(str, evidence["github_artifact_archive_base64"])
    try:
        archive = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        findings.fail("ci_artifact_archive_invalid", f"{path}/github_artifact_archive_base64")
        return None
    if sha256_bytes(archive) != evidence["github_artifact_archive_sha256"]:
        findings.fail(
            "ci_artifact_archive_digest_mismatch",
            f"{path}/github_artifact_archive_sha256",
        )
        return None
    return archive


def _attestation_from_archive(
    archive: bytes,
    path: str,
    findings: _Findings,
) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if (
                len(members) != 1
                or members[0].filename != "phase10-ci-checkout.json"
                or members[0].is_dir()
                or members[0].file_size > 16_384
            ):
                raise ValueError("artifact member inventory is not exact")
            raw = bundle.read(members[0])
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except Exception:  # noqa: BLE001 - untrusted bounded ZIP/JSON must fail closed
        findings.fail("ci_artifact_archive_invalid", f"{path}/github_artifact_archive_base64")
        return None
    if not isinstance(value, dict) or canonical_json_bytes(value) + b"\n" != raw:
        findings.fail("ci_artifact_archive_invalid", f"{path}/github_artifact_archive_base64")
        return None
    return cast(dict[str, Any], value)


def _evaluate_restart_and_runtime(
    *,
    restart: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    github_merge: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    findings: _Findings,
) -> dict[str, Any] | None:
    if restart is None:
        findings.incomplete("controlled_restart_evidence_missing", "/restart")
    else:
        if restart["preflight_status"] == "blocked":
            findings.fail("restart_preflight_blocked", "/restart/preflight_status")
        elif restart["preflight_status"] == "uncertain":
            findings.incomplete("restart_preflight_uncertain", "/restart/preflight_status")
        outcome = restart["outcome"]
        if outcome in {"rolled_back", "failed"}:
            findings.fail("restart_candidate_not_running", "/restart/outcome")
        elif outcome in {"restricted_recovery", "uncertain"}:
            findings.incomplete("restart_outcome_unresolved", "/restart/outcome")
        if not restart["same_operation_reconciled"]:
            findings.fail("restart_operation_not_reconciled", "/restart/same_operation_reconciled")
        if restart["second_restart_issued"]:
            findings.fail("duplicate_restart_issued", "/restart/second_restart_issued")
        if not restart["audit_closed"]:
            findings.incomplete("restart_audit_open", "/restart/audit_closed")
        if not restart["workspace_fence_closed"]:
            findings.incomplete("restart_fence_open", "/restart/workspace_fence_closed")
        if github_merge is not None and (
            restart["candidate_oid"] != github_merge["result_oid"]
            or restart["candidate_tree_oid"] != github_merge["result_tree_oid"]
        ):
            findings.fail("restart_candidate_identity_mismatch", "/restart")

    if runtime is None:
        findings.incomplete("post_restart_runtime_missing", "/post_restart_runtime")
        return None
    if restart is not None and (
        runtime["restart_operation_ref"] != restart["operation_ref"]
        or runtime["restart_checkpoint_ref"] != restart["checkpoint_ref"]
        or runtime["readiness_generation"] != restart["readiness_generation"]
    ):
        findings.fail("post_restart_runtime_restart_mismatch", "/post_restart_runtime")
    if runtime["readiness"] == "restricted":
        findings.fail("post_restart_runtime_restricted", "/post_restart_runtime/readiness")
    elif runtime["readiness"] == "unavailable":
        findings.incomplete("post_restart_runtime_unavailable", "/post_restart_runtime/readiness")
    if not runtime["clean_source_state"]:
        findings.fail("post_restart_runtime_dirty", "/post_restart_runtime/clean_source_state")
    if github_merge is not None and (
        runtime["runtime_oid"] != github_merge["result_oid"]
        or runtime["runtime_tree_oid"] != github_merge["result_tree_oid"]
    ):
        findings.fail("post_restart_runtime_identity_mismatch", "/post_restart_runtime")
    if (
        baseline is not None
        and runtime["runtime_profile_sha256"] != baseline["runtime_profile_sha256"]
    ):
        findings.fail(
            "post_restart_runtime_profile_mismatch",
            "/post_restart_runtime/runtime_profile_sha256",
        )
    if baseline is not None:
        for field_name, finding_code in (
            ("controller_sha256", "post_restart_controller_mismatch"),
            ("device_sha256", "post_restart_device_mismatch"),
            ("workspace_sha256", "post_restart_workspace_mismatch"),
        ):
            if runtime[field_name] != baseline[field_name]:
                findings.fail(finding_code, f"/post_restart_runtime/{field_name}")
    if (
        baseline is not None
        and runtime["runtime_instance_sha256"] == baseline["runtime_instance_sha256"]
    ):
        findings.fail(
            "runtime_instance_not_replaced",
            "/post_restart_runtime/runtime_instance_sha256",
        )
    return runtime


def _evaluate_behaviour_probe(
    probe: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    findings: _Findings,
) -> None:
    if probe is None:
        findings.incomplete("behaviour_probe_missing", "/behaviour_probe")
        return
    if probe["outcome"] == "observed_old":
        findings.fail("changed_behaviour_absent", "/behaviour_probe/outcome")
    elif probe["outcome"] == "unavailable":
        findings.incomplete("changed_behaviour_unavailable", "/behaviour_probe/outcome")
    if not probe["post_restart"]:
        findings.fail("behaviour_probe_not_post_restart", "/behaviour_probe/post_restart")
    if (
        runtime is not None
        and probe["runtime_instance_sha256"] != runtime["runtime_instance_sha256"]
    ):
        findings.fail(
            "behaviour_probe_runtime_mismatch",
            "/behaviour_probe/runtime_instance_sha256",
        )


def _evaluate_security(
    checks: list[dict[str, Any]],
    *,
    acceptance_run_id: str,
    policy: Phase10Policy,
    github_merge: dict[str, Any] | None,
    restart: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    findings: _Findings,
) -> None:
    indexed: dict[str, dict[str, Any]] = {}
    observed_evidence_ids: set[str] = set()
    observed_evidence_digests: set[str] = set()
    for index, check in enumerate(checks):
        path = f"/security_checks/{index}"
        check_id = cast(str, check["check_id"])
        if check_id in indexed:
            findings.fail("duplicate_security_check", f"{path}/check_id")
        indexed[check_id] = check
        evidence_ref = _object(check["evidence_ref"])
        evidence_id = _ref_id(evidence_ref)
        evidence_digest = cast(str, evidence_ref["sha256"])
        if evidence_id in observed_evidence_ids or evidence_digest in observed_evidence_digests:
            findings.fail("security_evidence_reused", f"{path}/evidence_ref")
        observed_evidence_ids.add(evidence_id)
        observed_evidence_digests.add(evidence_digest)
        if check["evidence_binding_sha256"] != phase10_security_evidence_sha256(check):
            findings.fail("security_evidence_binding_mismatch", f"{path}/evidence_binding_sha256")
        if check["acceptance_run_id"] != acceptance_run_id:
            findings.fail("security_acceptance_run_mismatch", f"{path}/acceptance_run_id")
        if check["policy_sha256"] != policy.sha256:
            findings.fail("security_policy_mismatch", f"{path}/policy_sha256")
        if github_merge is not None and (
            check["merged_oid"] != github_merge["result_oid"]
            or check["merged_tree_oid"] != github_merge["result_tree_oid"]
        ):
            findings.fail("security_merge_identity_mismatch", path)
        if restart is not None and (
            check["restart_operation_ref"] != restart["operation_ref"]
            or check["restart_checkpoint_ref"] != restart["checkpoint_ref"]
            or check["readiness_generation"] != restart["readiness_generation"]
        ):
            findings.fail("security_restart_identity_mismatch", path)
        if runtime is not None and (
            check["runtime_instance_sha256"] != runtime["runtime_instance_sha256"]
            or check["runtime_profile_sha256"] != runtime["runtime_profile_sha256"]
        ):
            findings.fail("security_runtime_identity_mismatch", path)
        if runtime is not None and any(
            check[field_name] != runtime[field_name]
            for field_name in ("controller_sha256", "device_sha256", "workspace_sha256")
        ):
            findings.fail("security_environment_identity_mismatch", path)
        if check["conclusion"] == "fail":
            findings.fail("security_invariant_failed", f"{path}/conclusion")
        elif check["conclusion"] == "unavailable":
            findings.incomplete(
                "security_evidence_unavailable",
                f"{path}/conclusion",
            )
    actual = set(indexed)
    required = set(policy.required_security_checks)
    if actual != required:
        findings.incomplete("required_security_checks_incomplete", "/security_checks")


def phase10_security_evidence_sha256(check: Mapping[str, Any]) -> str:
    """Hash one security result and every current execution identity it asserts."""

    return canonical_json_sha256(
        {
            "schema_version": "1.0",
            "stage": "security",
            "check_id": check["check_id"],
            "evidence_ref": check["evidence_ref"],
            "acceptance_run_id": check["acceptance_run_id"],
            "policy_sha256": check["policy_sha256"],
            "merged_oid": check["merged_oid"],
            "merged_tree_oid": check["merged_tree_oid"],
            "restart_operation_ref": check["restart_operation_ref"],
            "restart_checkpoint_ref": check["restart_checkpoint_ref"],
            "readiness_generation": check["readiness_generation"],
            "runtime_instance_sha256": check["runtime_instance_sha256"],
            "runtime_profile_sha256": check["runtime_profile_sha256"],
            "controller_sha256": check["controller_sha256"],
            "device_sha256": check["device_sha256"],
            "workspace_sha256": check["workspace_sha256"],
            "conclusion": check["conclusion"],
        }
    )


def phase10_reviewed_evidence_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the prospective run evidence while excluding the approval record itself."""

    projection = dict(manifest)
    projection["owner_review"] = None
    return canonical_json_sha256(projection)


def _evaluate_owner_review(
    value: dict[str, Any] | None,
    *,
    acceptance_run_id: str,
    policy_sha256: str,
    reviewed_evidence_sha256: str,
    findings: _Findings,
) -> None:
    if value is None:
        findings.incomplete("owner_review_missing", "/owner_review")
        return
    if value["acceptance_run_id"] != acceptance_run_id:
        findings.incomplete("owner_review_run_mismatch", "/owner_review/acceptance_run_id")
    if value["policy_sha256"] != policy_sha256:
        findings.incomplete("owner_review_policy_mismatch", "/owner_review/policy_sha256")
    if value["reviewed_evidence_sha256"] != reviewed_evidence_sha256:
        findings.incomplete(
            "owner_review_evidence_mismatch",
            "/owner_review/reviewed_evidence_sha256",
        )
    if value["outcome"] == "rejected":
        findings.fail("owner_review_rejected", "/owner_review/outcome")
    elif value["outcome"] == "pending":
        findings.incomplete("owner_review_pending", "/owner_review/outcome")
    if not value["evidence_complete"]:
        findings.incomplete("owner_review_evidence_incomplete", "/owner_review/evidence_complete")


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError("schema-validated object is not a mapping")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate artifact attestation field")
        value[key] = item
    return value


def _optional_object(value: object) -> dict[str, Any] | None:
    return None if value is None else _object(value)


def _object_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AssertionError("schema-validated array is not a list")
    return [_object(item) for item in value]


def _ref_id(value: object) -> str:
    return cast(str, _object(value)["id"])


def _evidence_ref_identities(value: object) -> set[tuple[str, str]]:
    evidence_ref = _object(value)
    return {
        ("evidence_id", _ref_id(evidence_ref)),
        ("evidence_sha256", cast(str, evidence_ref["sha256"])),
    }


__all__ = [
    "AcceptanceFinding",
    "AcceptanceManifestError",
    "AcceptanceReport",
    "AcceptanceVerdict",
    "ArtifactApiLookup",
    "ArtifactApiLookupUnavailable",
    "CiApiLookup",
    "CiApiLookupUnavailable",
    "create_phase10_skeleton",
    "evaluate_phase10_manifest",
    "phase10_local_check_evidence_sha256",
    "phase10_reviewed_evidence_sha256",
    "phase10_security_evidence_sha256",
]

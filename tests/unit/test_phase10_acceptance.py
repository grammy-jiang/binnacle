"""Deterministic Phase 10 policy and acceptance-evaluator tests."""

from __future__ import annotations

import base64
import copy
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

import binnacle.evaluation as evaluation_package
from binnacle.evaluation.ci_attestation import CI_ATTESTATION_COLLECTOR_PATHS
from binnacle.evaluation.digests import canonical_json_bytes, canonical_json_sha256, sha256_bytes
from binnacle.evaluation.phase10_acceptance import (
    AcceptanceManifestError,
    AcceptanceReport,
    AcceptanceVerdict,
    ArtifactApiLookup,
    CiApiLookup,
    create_phase10_skeleton,
    phase10_local_check_evidence_sha256,
    phase10_reviewed_evidence_sha256,
)
from binnacle.evaluation.phase10_acceptance import (
    evaluate_phase10_manifest as _evaluate_phase10_manifest,
)
from binnacle.evaluation.phase10_policy import Phase10PolicyError, load_phase10_policy


def test_evaluation_package_preserves_lazy_public_api() -> None:
    assert "AcceptanceVerdict" in dir(evaluation_package)
    assert evaluation_package.AcceptanceVerdict is AcceptanceVerdict
    missing = "not_a_public_export"
    with pytest.raises(AttributeError, match="no attribute"):
        getattr(evaluation_package, missing)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _pass_manifest(repo_root: Path) -> dict[str, Any]:
    return _load_json(repo_root / "tests/fixtures/acceptance/phase10-pass.json")


def _artifact_api_lookup_from(manifest: dict[str, Any]) -> ArtifactApiLookup:
    observations: dict[tuple[str, int], dict[str, Any]] = {}
    for integration in manifest.get("integration_generations", []):
        if not isinstance(integration, dict):
            continue
        for evidence in integration.get("ci_evidence", []):
            if not isinstance(evidence, dict):
                continue
            repository = evidence.get("repository")
            artifact_id = evidence.get("github_artifact_id")
            observation = evidence.get("github_artifact_api_observation")
            if (
                isinstance(repository, str)
                and isinstance(artifact_id, int)
                and not isinstance(artifact_id, bool)
                and isinstance(observation, dict)
            ):
                observations[(repository, artifact_id)] = copy.deepcopy(observation)

    def lookup(repository: str, artifact_id: int) -> dict[str, Any] | None:
        observation = observations.get((repository, artifact_id))
        return copy.deepcopy(observation) if observation is not None else None

    return lookup


def _ci_api_lookup_from(manifest: dict[str, Any]) -> CiApiLookup:
    observations: dict[tuple[str, int, int, str, str], dict[str, Any]] = {}
    for integration in manifest.get("integration_generations", []):
        if not isinstance(integration, dict):
            continue
        for evidence in integration.get("ci_evidence", []):
            if not isinstance(evidence, dict):
                continue
            observation = evidence.get("github_ci_api_observation")
            workflow_source = (
                observation.get("workflow_source") if isinstance(observation, dict) else None
            )
            key = (
                evidence.get("repository"),
                evidence.get("github_job_id"),
                evidence.get("run_id"),
                workflow_source.get("path") if isinstance(workflow_source, dict) else None,
                evidence.get("checkout_oid"),
            )
            if (
                isinstance(key[0], str)
                and isinstance(key[1], int)
                and not isinstance(key[1], bool)
                and isinstance(key[2], int)
                and not isinstance(key[2], bool)
                and isinstance(key[3], str)
                and isinstance(key[4], str)
                and isinstance(observation, dict)
            ):
                observations[cast(tuple[str, int, int, str, str], key)] = copy.deepcopy(observation)

    def lookup(
        repository: str,
        job_id: int,
        run_id: int,
        workflow_path: str,
        checkout_oid: str,
    ) -> dict[str, Any] | None:
        observation = observations.get((repository, job_id, run_id, workflow_path, checkout_oid))
        return copy.deepcopy(observation) if observation is not None else None

    return lookup


def evaluate_phase10_manifest(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
) -> AcceptanceReport:
    """Evaluate with a test-controlled stand-in for the external authenticated API source."""

    return _evaluate_phase10_manifest(
        manifest,
        repo_root=repo_root,
        authenticated_artifact_api_lookup=_artifact_api_lookup_from(manifest),
        authenticated_ci_api_lookup=_ci_api_lookup_from(manifest),
    )


def _append_candidate_generation(
    manifest: dict[str, Any],
    *,
    parent_oid: str,
    tree_oid: str,
) -> None:
    first = manifest["candidate_generations"][0]
    first["superseded_reason_ref"] = {"id": "candidate-1-superseded", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 2
    second["superseded_reason_ref"] = None
    second["status_diff"]["parent_oid"] = parent_oid
    second["signed_commit"]["oid"] = "6" * 40
    second["signed_commit"]["tree_oid"] = tree_oid
    second["signed_commit"]["parent_oid"] = parent_oid
    second["push"]["target_oid"] = "6" * 40
    second["push"]["remote_observed_oid"] = "6" * 40
    second["hosted_head_oid"] = "6" * 40
    references = [
        second["status_diff"]["evidence_ref"],
        second["signed_commit"]["evidence_ref"],
        second["push"]["evidence_ref"],
    ]
    for index, reference in enumerate(references, start=1):
        reference["id"] = f"candidate-2-evidence-{index}"
        reference["sha256"] = f"{index:064x}"
    for index, check in enumerate(second["local_checks"], start=1):
        check["evidence_ref"]["id"] = f"candidate-2-local-check-{index}"
        check["evidence_ref"]["sha256"] = f"{index + 32:064x}"
        check["evidence_binding_sha256"] = phase10_local_check_evidence_sha256(
            check,
            stage="candidate",
        )
    manifest["candidate_generations"].append(second)
    manifest["final_candidate_generation"] = 2
    manifest["integration_generations"][0]["candidate_generation"] = 2
    manifest["integration_generations"][0]["candidate_oid"] = "6" * 40


def _append_third_candidate_generation(
    manifest: dict[str, Any],
    *,
    parent_oid: str,
) -> None:
    second = manifest["candidate_generations"][1]
    second["superseded_reason_ref"] = {"id": "candidate-2-superseded", "sha256": "d" * 64}
    third = copy.deepcopy(second)
    third["generation"] = 3
    third["superseded_reason_ref"] = None
    third["source_content_sha256"] = "13" * 32
    third["status_diff"]["parent_oid"] = parent_oid
    third["signed_commit"]["oid"] = "9" * 40
    third["signed_commit"]["parent_oid"] = parent_oid
    third["signed_commit"]["source_content_sha256"] = "13" * 32
    third["push"]["target_oid"] = "9" * 40
    third["push"]["remote_observed_oid"] = "9" * 40
    third["hosted_head_oid"] = "9" * 40
    for index, reference in enumerate(
        (
            third["status_diff"]["evidence_ref"],
            third["signed_commit"]["evidence_ref"],
            third["push"]["evidence_ref"],
        ),
        start=1,
    ):
        reference["id"] = f"candidate-3-evidence-{index}"
        reference["sha256"] = f"{index + 16:064x}"
    for index, check in enumerate(third["local_checks"], start=1):
        check["source_content_sha256"] = "13" * 32
        check["evidence_ref"]["id"] = f"candidate-3-local-check-{index}"
        check["evidence_ref"]["sha256"] = f"{index + 48:064x}"
        check["evidence_binding_sha256"] = phase10_local_check_evidence_sha256(
            check,
            stage="candidate",
        )
    manifest["candidate_generations"].append(third)
    manifest["final_candidate_generation"] = 3
    manifest["integration_generations"][0]["candidate_generation"] = 3
    manifest["integration_generations"][0]["candidate_oid"] = "9" * 40


def _cases(repo_root: Path) -> list[dict[str, Any]]:
    value = _load_json(repo_root / "tests/fixtures/acceptance/phase10-evaluator-cases.json")
    cases = value["cases"]
    assert isinstance(cases, list)
    return [cast(dict[str, Any], case) for case in cases]


def _pointer_parent(document: object, pointer: str) -> tuple[object, str]:
    tokens = pointer.lstrip("/").split("/")
    current = document
    for token in tokens[:-1]:
        decoded = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(decoded)]
        else:
            assert isinstance(current, dict)
            current = current[decoded]
    return current, tokens[-1].replace("~1", "/").replace("~0", "~")


def _apply_case(document: dict[str, Any], case: dict[str, Any]) -> None:
    operation = case["operation"]
    if operation == "none":
        return
    if operation == "batch":
        for nested_case in cast(list[dict[str, Any]], case["operations"]):
            _apply_case(document, nested_case)
        return
    parent, token = _pointer_parent(document, cast(str, case["path"]))
    if isinstance(parent, list):
        index = int(token)
        if operation == "remove":
            parent.pop(index)
        else:
            parent[index] = copy.deepcopy(case["value"])
        return
    assert isinstance(parent, dict)
    if operation == "remove":
        del parent[token]
    else:
        parent[token] = copy.deepcopy(case["value"])


def test_phase10_policy_is_frozen_and_canonical(repo_root: Path) -> None:
    policy = load_phase10_policy(repo_root)

    assert policy.policy_id == "binnacle-phase10-acceptance-v1"
    assert policy.sha256 == "2b7719d8fa95009c99649f4ade972eeaaf91849db59c0cbeceb77874689474d3"
    assert policy.acceptance_schema_sha256 == (
        "dddb73dabc2d1f23f9a6356982c5b6b51f83cf96cf702101e77f47bdff4f5423"
    )
    assert policy.ci_attestation_schema_sha256 == (
        "6b7d2c6dff03870790dfb3e4ee6be5c93399e61d1bc7c67afea2969ea91e2760"
    )
    assert policy.ci_attestation_collector_commit_oid == (
        "668a3b69af386894a6eedcd740634589b6bb1ccc"
    )
    assert policy.ci_attestation_collector_sha256 == (
        "96dc2225a3a12e18341656b2cd5ea05b9458a52a9cb7fa77f98d84ce844f8ec7"
    )
    assert policy.repository == "grammy-jiang/binnacle"
    assert policy.protected_branch_ref == "refs/heads/master"
    assert policy.artifact_api_authentication == "live-bearer-github-rest-v2022-11-28"
    assert policy.ci_api_authentication == "live-bearer-github-rest-v2022-11-28"
    assert policy.limits["github_api_response_bytes_max"] == 65_536
    assert policy.limits["github_api_token_bytes_max"] == 4_096
    assert policy.limits["github_api_timeout_seconds"] == 15
    assert policy.limits["workflow_source_bytes_max"] == 32_768
    assert policy.allowed_merge_methods == ("squash",)
    assert policy.required_ci_jobs["Python CI"] == (
        "Code, contract, dependency, and document quality",
        "Test Python 3.11",
        "Test Python 3.12",
        "Test Python 3.13",
    )
    assert policy.required_ci_workflow_profiles["Contract validation"].workflow_id == 330240211
    assert policy.required_ci_workflow_profiles["Contract validation"].path == (
        ".github/workflows/contracts.yml"
    )
    assert policy.required_ci_workflow_profiles["Contract validation"].source_sha256 == (
        "b074c669e4b72c7b97523b41d9bc6cb6fa68feb787d4f3e7fcc5251912cf0105"
    )
    assert policy.required_ci_workflow_profiles["Python CI"].workflow_id == 331525151
    assert policy.required_ci_workflow_profiles["Python CI"].path == (
        ".github/workflows/python.yml"
    )
    assert policy.required_ci_workflow_profiles["Python CI"].source_sha256 == (
        "3e432f34918e7ce168b445bde62eb4deeeb296eabca14c34ef2e6dbd928a085d"
    )
    assert tuple(policy.required_local_check_profiles) == (
        "pre-commit-all-files",
        "tox-py311",
        "tox-py312",
        "tox-py313",
        "tox-quality",
    )
    assert policy.required_local_check_profiles["tox-quality"] == (
        "bbe4fcf9b38b448b92e469a811cb7c5ac0ee09cb396e1df5ecc9d5fb75c5bcd4"
    )


def test_phase10_skeleton_claims_no_live_evidence(repo_root: Path) -> None:
    manifest = create_phase10_skeleton(
        acceptance_run_id="acceptance-planned-test",
        repo_root=repo_root,
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert manifest["state"] == "planned"
    assert manifest["candidate_generations"] == []
    assert manifest["restart"] is None
    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert {finding.code for finding in report.findings} >= {
        "readiness_not_current",
        "candidate_generation_missing",
        "controlled_restart_evidence_missing",
    }


def test_pass_manifest_requires_authenticated_artifact_api_source(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)

    report = _evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "ci_artifact_api_authentication_missing" in {finding.code for finding in report.findings}


def test_pass_manifest_requires_authenticated_ci_api_source(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)

    report = _evaluate_phase10_manifest(
        manifest,
        repo_root=repo_root,
        authenticated_artifact_api_lookup=_artifact_api_lookup_from(manifest),
    )

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "ci_api_authentication_missing" in {finding.code for finding in report.findings}


def test_manifest_success_claim_cannot_override_authenticated_failed_job(
    repo_root: Path,
) -> None:
    manifest = _pass_manifest(repo_root)
    evidence = manifest["integration_generations"][0]["ci_evidence"][0]
    observation = evidence["github_ci_api_observation"]
    observation["job"]["conclusion"] = "failure"
    observation["workflow_run"]["conclusion"] = "failure"
    evidence["github_ci_api_ref"]["sha256"] = canonical_json_sha256(observation)
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert {finding.code for finding in report.findings} >= {
        "ci_job_api_not_successful",
        "ci_job_conclusion_mismatch",
        "ci_workflow_run_api_not_successful",
    }


def test_successful_job_from_earlier_attempt_can_satisfy_latest_successful_run(
    repo_root: Path,
) -> None:
    manifest = _pass_manifest(repo_root)
    evidence = manifest["integration_generations"][0]["ci_evidence"]
    python_evidence = [item for item in evidence if item["workflow_name"] == "Python CI"]
    for item in python_evidence:
        item["workflow_run_attempt"] = 2
        item["github_ci_api_observation"]["workflow_run"]["run_attempt"] = 2
        item["github_ci_api_ref"]["sha256"] = canonical_json_sha256(
            item["github_ci_api_observation"]
        )

    retried = python_evidence[-1]
    retried["run_attempt"] = 2
    retried["attestation"]["run_attempt"] = 2
    retried["attestation_sha256"] = sha256_bytes(
        canonical_json_bytes(retried["attestation"]) + b"\n"
    )
    retried["github_artifact_name"] = "phase10-checkout-1002-test-python-3.13-2"
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "phase10-ci-checkout.json",
            canonical_json_bytes(retried["attestation"]) + b"\n",
        )
    archive_bytes = archive_buffer.getvalue()
    archive_sha256 = sha256_bytes(archive_bytes)
    retried["github_artifact_archive_base64"] = base64.b64encode(archive_bytes).decode("ascii")
    retried["github_artifact_archive_sha256"] = archive_sha256
    artifact_observation = retried["github_artifact_api_observation"]
    artifact_observation["name"] = retried["github_artifact_name"]
    artifact_observation["size_in_bytes"] = len(archive_bytes)
    artifact_observation["digest"] = f"sha256:{archive_sha256}"
    retried["github_artifact_api_ref"]["sha256"] = canonical_json_sha256(artifact_observation)
    retried["github_ci_api_observation"]["job"]["run_attempt"] = 2
    retried["github_ci_api_ref"]["sha256"] = canonical_json_sha256(
        retried["github_ci_api_observation"]
    )
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert [item["run_attempt"] for item in python_evidence] == [1, 1, 1, 2]
    assert {item["workflow_run_attempt"] for item in python_evidence} == {2}
    assert report.verdict is AcceptanceVerdict.PASS


def test_workflow_run_attempt_cannot_precede_retained_job_attempt(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    evidence = manifest["integration_generations"][0]["ci_evidence"][0]
    observation = evidence["github_ci_api_observation"]
    evidence["run_attempt"] = 2
    evidence["attestation"]["run_attempt"] = 2
    evidence["attestation_sha256"] = sha256_bytes(
        canonical_json_bytes(evidence["attestation"]) + b"\n"
    )
    observation["job"]["run_attempt"] = 2
    evidence["github_ci_api_ref"]["sha256"] = canonical_json_sha256(observation)
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_workflow_run_attempt_precedes_job_attempt" in {
        finding.code for finding in report.findings
    }


def test_authenticated_workflow_source_must_match_frozen_profile(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    evidence = manifest["integration_generations"][0]["ci_evidence"][0]
    observation = evidence["github_ci_api_observation"]
    observation["workflow_source"]["sha256"] = "8" * 64
    evidence["github_ci_api_ref"]["sha256"] = canonical_json_sha256(observation)
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_workflow_source_identity_mismatch" in {finding.code for finding in report.findings}


def test_fabricated_artifact_tuple_cannot_replace_authenticated_api_truth(
    repo_root: Path,
) -> None:
    trusted_manifest = _pass_manifest(repo_root)
    manifest = copy.deepcopy(trusted_manifest)
    evidence = manifest["integration_generations"][0]["ci_evidence"][0]
    observation = evidence["github_artifact_api_observation"]
    evidence["github_artifact_id"] = 9999
    observation["id"] = 9999
    observation["url"] = "https://api.github.com/repos/grammy-jiang/binnacle/actions/artifacts/9999"
    observation["archive_download_url"] = f"{observation['url']}/zip"
    evidence["github_artifact_api_ref"]["sha256"] = canonical_json_sha256(observation)
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = _evaluate_phase10_manifest(
        manifest,
        repo_root=repo_root,
        authenticated_artifact_api_lookup=_artifact_api_lookup_from(trusted_manifest),
        authenticated_ci_api_lookup=_ci_api_lookup_from(trusted_manifest),
    )

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_artifact_api_not_found" in {finding.code for finding in report.findings}


@pytest.mark.parametrize("case_index", range(44))
def test_phase10_evaluator_fixture(case_index: int, repo_root: Path) -> None:
    cases = _cases(repo_root)
    assert len(cases) == 44
    case = cases[case_index]
    manifest = _pass_manifest(repo_root)
    _apply_case(manifest, case)

    if case["expected"] == "ERROR":
        with pytest.raises(AcceptanceManifestError):
            evaluate_phase10_manifest(manifest, repo_root=repo_root)
        return

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict.value == case["expected"], case["id"]
    expected_code = case["code"]
    if expected_code is not None:
        assert expected_code in {finding.code for finding in report.findings}, case["id"]


def test_report_is_deterministic_and_does_not_echo_evidence(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    secret_marker = "never-render-this-evidence-value"
    manifest["owner_review"]["evidence_ref"]["id"] = secret_marker
    manifest["owner_review"]["outcome"] = "pending"

    first = evaluate_phase10_manifest(manifest, repo_root=repo_root)
    second = evaluate_phase10_manifest(copy.deepcopy(manifest), repo_root=repo_root)

    assert first.as_dict() == second.as_dict()
    assert secret_marker not in json.dumps(first.as_dict())


def test_duplicate_security_check_cannot_replace_required_check(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    manifest["security_checks"][0]["check_id"] = manifest["security_checks"][1]["check_id"]

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert {finding.code for finding in report.findings} >= {
        "duplicate_security_check",
        "required_security_checks_incomplete",
    }


_EVALUATOR_BRANCH_CASES: tuple[tuple[str, object, str], ...] = (
    ("/state", "failed", "run_declared_failed"),
    ("/state", "incomplete", "run_declared_incomplete"),
    ("/state", "hosted_merged", "run_not_terminally_closed"),
    ("/readiness/real_development_pi", "failed", "readiness_verification_failed"),
    ("/baseline/repository_clean", False, "baseline_repository_dirty"),
    (
        "/baseline/protected_base_oid",
        "8" * 40,
        "baseline_protected_base_mismatch",
    ),
    ("/branch/protected_branch_mutated", True, "protected_branch_mutated"),
    ("/branch/ref", "refs/heads/master", "feature_branch_is_protected_branch"),
    ("/branch/observed_oid", "8" * 40, "feature_branch_oid_mismatch"),
    ("/branch/created_from_oid", "8" * 40, "feature_branch_not_from_baseline"),
    (
        "/candidate_generations/0/local_checks/0/source_content_sha256",
        "8" * 64,
        "candidate_check_source_mismatch",
    ),
    ("/candidate_generations/0/local_checks/0/conclusion", "failure", "required_check_failed"),
    (
        "/candidate_generations/0/local_checks/0/conclusion",
        "uncertain",
        "required_check_uncertain",
    ),
    ("/candidate_generations/0/local_checks/0/terminal", False, "required_check_nonterminal"),
    (
        "/candidate_generations/0/local_checks/0/descendants_closed",
        False,
        "required_check_descendants_open",
    ),
    (
        "/candidate_generations/0/local_checks/0/workspace_fence_closed",
        False,
        "required_check_fence_open",
    ),
    (
        "/candidate_generations/0/local_checks/0/check_profile_sha256",
        "8" * 64,
        "local_check_profile_mismatch",
    ),
    (
        "/candidate_generations/0/status_diff/unexpected_paths",
        True,
        "candidate_contains_unexpected_paths",
    ),
    (
        "/candidate_generations/0/status_diff/parent_oid",
        "8" * 40,
        "candidate_parent_evidence_mismatch",
    ),
    (
        "/candidate_generations/0/status_diff/branch_ref",
        "refs/heads/wrong",
        "candidate_branch_mismatch",
    ),
    (
        "/candidate_generations/0/signed_commit/parent_oid",
        "8" * 40,
        "first_candidate_parent_not_baseline",
    ),
    (
        "/candidate_generations/0/signed_commit/source_content_sha256",
        "8" * 64,
        "signed_commit_source_mismatch",
    ),
    (
        "/candidate_generations/0/signed_commit/signature_verified",
        False,
        "candidate_signature_unverified",
    ),
    (
        "/candidate_generations/0/signed_commit/tree_oid",
        "8" * 40,
        "same_base_signed_tree_mismatch",
    ),
    ("/candidate_generations/0/push/conclusion", "failure", "candidate_push_failed"),
    ("/candidate_generations/0/push/conclusion", "uncertain", "candidate_push_uncertain"),
    (
        "/candidate_generations/0/push/remote_ref",
        "refs/heads/wrong",
        "candidate_push_ref_mismatch",
    ),
    (
        "/candidate_generations/0/push/remote_profile_sha256",
        "8" * 64,
        "candidate_remote_profile_mismatch",
    ),
    (
        "/integration_generations/0/candidate_generation",
        2,
        "integration_uses_stale_candidate_generation",
    ),
    (
        "/integration_generations/0/merge_policy_sha256",
        "8" * 64,
        "integration_merge_policy_stale",
    ),
    (
        "/integration_generations/0/reviews/0/substantive",
        False,
        "review_not_substantive",
    ),
    ("/integration_generations/0/reviews/0/clean", False, "review_rejected_integration"),
    (
        "/integration_generations/0/reviews/0/unresolved_actionable_count",
        1,
        "review_findings_unresolved",
    ),
    (
        "/integration_generations/0/ci_evidence/0/conclusion",
        "failure",
        "required_ci_failed",
    ),
    (
        "/integration_generations/0/ci_evidence/0/conclusion",
        "uncertain",
        "required_ci_uncertain",
    ),
    (
        "/integration_generations/0/ci_evidence/0/repository",
        "attacker/other",
        "ci_repository_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/collector_commit_oid",
        "8" * 40,
        "ci_collector_commit_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/collector_sha256",
        "8" * 64,
        "ci_collector_bundle_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/github_sha",
        "8" * 40,
        "ci_github_sha_unbound",
    ),
    (
        "/integration_generations/0/ci_evidence/0/workflow_name",
        "Unreviewed CI",
        "unexpected_required_ci_evidence",
    ),
    (
        "/integration_generations/0/ci_evidence/0/attestation_sha256",
        "8" * 64,
        "ci_attestation_digest_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/attestation/workflow_name",
        "Python CI",
        "ci_attestation_identity_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/github_artifact_api_ref/sha256",
        "8" * 64,
        "ci_artifact_api_observation_digest_mismatch",
    ),
    (
        "/integration_generations/0/ci_evidence/0/github_artifact_archive_sha256",
        "8" * 64,
        "ci_artifact_archive_digest_mismatch",
    ),
    ("/failure_exercise/outcome", "unsafe", "failure_exercise_unsafe"),
    (
        "/failure_exercise/descendants_closed",
        False,
        "failure_exercise_descendants_open",
    ),
    (
        "/failure_exercise/workspace_fence_closed",
        False,
        "failure_exercise_fence_open",
    ),
    ("/github_pr/head_ref", "refs/heads/wrong", "github_pr_head_ref_mismatch"),
    ("/github_pr/repository", "attacker/other", "github_pr_repository_mismatch"),
    ("/github_pr/base_ref", "refs/heads/other", "github_pr_base_ref_mismatch"),
    ("/github_pr/base_oid", "8" * 40, "github_pr_base_stale"),
    ("/github_merge/method", "merge", "merge_method_not_accepted"),
    ("/github_merge/provenance_verified", False, "merge_provenance_unverified"),
    ("/github_merge/candidate_oid", "8" * 40, "hosted_merge_candidate_mismatch"),
    ("/github_merge/accepted_base_oid", "8" * 40, "hosted_merge_base_mismatch"),
    (
        "/github_merge/expected_integration_tree_oid",
        "8" * 40,
        "hosted_merge_expected_tree_mismatch",
    ),
    ("/local_update/repository_clean", False, "local_update_repository_dirty"),
    ("/local_update/through_phase8_semantics", False, "local_update_bypassed_phase8"),
    ("/local_update/branch_ref", "refs/heads/other", "local_update_branch_mismatch"),
    (
        "/post_merge_local_checks/0/check_profile_sha256",
        "8" * 64,
        "local_check_profile_mismatch",
    ),
    ("/restart/preflight_status", "blocked", "restart_preflight_blocked"),
    ("/restart/preflight_status", "uncertain", "restart_preflight_uncertain"),
    ("/restart/outcome", "restricted_recovery", "restart_outcome_unresolved"),
    ("/restart/same_operation_reconciled", False, "restart_operation_not_reconciled"),
    ("/restart/audit_closed", False, "restart_audit_open"),
    ("/restart/workspace_fence_closed", False, "restart_fence_open"),
    ("/post_restart_runtime/readiness", "restricted", "post_restart_runtime_restricted"),
    ("/post_restart_runtime/readiness", "unavailable", "post_restart_runtime_unavailable"),
    ("/post_restart_runtime/clean_source_state", False, "post_restart_runtime_dirty"),
    (
        "/post_restart_runtime/runtime_instance_sha256",
        "0" * 64,
        "runtime_instance_not_replaced",
    ),
    (
        "/post_restart_runtime/runtime_profile_sha256",
        "8" * 64,
        "post_restart_runtime_profile_mismatch",
    ),
    (
        "/post_restart_runtime/restart_operation_ref/id",
        "other-restart-operation",
        "post_restart_runtime_restart_mismatch",
    ),
    (
        "/post_restart_runtime/restart_checkpoint_ref/id",
        "other-restart-checkpoint",
        "post_restart_runtime_restart_mismatch",
    ),
    (
        "/post_restart_runtime/readiness_generation",
        43,
        "post_restart_runtime_restart_mismatch",
    ),
    ("/behaviour_probe/outcome", "unavailable", "changed_behaviour_unavailable"),
    ("/behaviour_probe/post_restart", False, "behaviour_probe_not_post_restart"),
    (
        "/behaviour_probe/runtime_instance_sha256",
        "8" * 64,
        "behaviour_probe_runtime_mismatch",
    ),
    ("/security_checks/0/conclusion", "unavailable", "security_evidence_unavailable"),
    ("/owner_review/outcome", "rejected", "owner_review_rejected"),
    ("/owner_review/evidence_complete", False, "owner_review_evidence_incomplete"),
    ("/owner_review/acceptance_run_id", "old-run", "owner_review_run_mismatch"),
    ("/owner_review/policy_sha256", "8" * 64, "owner_review_policy_mismatch"),
    (
        "/owner_review/reviewed_evidence_sha256",
        "8" * 64,
        "owner_review_evidence_mismatch",
    ),
)


@pytest.mark.parametrize(("path", "value", "expected_code"), _EVALUATOR_BRANCH_CASES)
def test_phase10_evaluator_rejects_each_nonpassing_branch(
    path: str,
    value: object,
    expected_code: str,
    repo_root: Path,
) -> None:
    manifest = _pass_manifest(repo_root)
    _apply_case(manifest, {"operation": "replace", "path": path, "value": value})
    if path != "/owner_review/reviewed_evidence_sha256":
        manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
            manifest
        )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is not AcceptanceVerdict.PASS
    assert expected_code in {finding.code for finding in report.findings}


@pytest.mark.parametrize(
    ("field", "expected_code"),
    (
        ("baseline", "baseline_missing"),
        ("branch", "feature_branch_missing"),
        ("failure_exercise", "recoverable_failure_exercise_missing"),
        ("github_pr", "github_pr_evidence_missing"),
        ("github_merge", "github_merge_evidence_missing"),
        ("local_update", "local_update_evidence_missing"),
        ("restart", "controlled_restart_evidence_missing"),
        ("post_restart_runtime", "post_restart_runtime_missing"),
        ("behaviour_probe", "behaviour_probe_missing"),
        ("owner_review", "owner_review_missing"),
    ),
)
def test_phase10_evaluator_treats_nullable_evidence_as_incomplete(
    field: str,
    expected_code: str,
    repo_root: Path,
) -> None:
    manifest = _pass_manifest(repo_root)
    manifest[field] = None

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert expected_code in {finding.code for finding in report.findings}


def test_generation_selection_requires_exact_consecutive_latest_generation(repo_root: Path) -> None:
    base = _pass_manifest(repo_root)

    no_candidates = copy.deepcopy(base)
    no_candidates["candidate_generations"] = []
    no_candidates_report = evaluate_phase10_manifest(no_candidates, repo_root=repo_root)
    assert {finding.code for finding in no_candidates_report.findings} >= {
        "candidate_generation_missing",
        "candidate_selection_without_generation",
    }

    no_selection = copy.deepcopy(base)
    no_selection["final_candidate_generation"] = None
    no_selection_report = evaluate_phase10_manifest(no_selection, repo_root=repo_root)
    assert "final_candidate_generation_missing" in {
        finding.code for finding in no_selection_report.findings
    }

    unknown = copy.deepcopy(base)
    unknown["final_candidate_generation"] = 2
    unknown_report = evaluate_phase10_manifest(unknown, repo_root=repo_root)
    assert "final_candidate_generation_unknown" in {
        finding.code for finding in unknown_report.findings
    }

    stale = copy.deepcopy(base)
    first = stale["candidate_generations"][0]
    first["superseded_reason_ref"] = {"id": "superseded", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 3
    second["superseded_reason_ref"] = None
    second["status_diff"]["evidence_ref"]["id"] = "candidate-3-status"
    second["signed_commit"]["evidence_ref"]["id"] = "candidate-3-commit"
    second["push"]["evidence_ref"]["id"] = "candidate-3-push"
    second["local_checks"][0]["evidence_ref"]["id"] = "candidate-3-check"
    stale["candidate_generations"].append(second)
    stale["final_candidate_generation"] = 1
    stale_report = evaluate_phase10_manifest(stale, repo_root=repo_root)
    assert {finding.code for finding in stale_report.findings} >= {
        "candidate_generation_sequence_invalid",
        "final_candidate_generation_not_latest",
        "final_candidate_generation_superseded",
        "prior_candidate_generation_not_superseded",
    }


def test_later_candidate_must_reach_integration_base_through_prior_generations(
    repo_root: Path,
) -> None:
    disconnected = _pass_manifest(repo_root)
    _append_candidate_generation(disconnected, parent_oid="7" * 40, tree_oid="4" * 40)

    disconnected_report = evaluate_phase10_manifest(disconnected, repo_root=repo_root)

    assert disconnected_report.verdict is AcceptanceVerdict.FAIL
    assert "candidate_lineage_disconnected" in {
        finding.code for finding in disconnected_report.findings
    }

    connected_wrong_tree = _pass_manifest(repo_root)
    first_oid = connected_wrong_tree["candidate_generations"][0]["signed_commit"]["oid"]
    _append_candidate_generation(
        connected_wrong_tree,
        parent_oid=first_oid,
        tree_oid="8" * 40,
    )

    connected_report = evaluate_phase10_manifest(connected_wrong_tree, repo_root=repo_root)

    codes = {finding.code for finding in connected_report.findings}
    assert "candidate_lineage_disconnected" not in codes
    assert "same_base_signed_tree_mismatch" in codes


def test_candidate_lineage_cannot_skip_an_intervening_generation(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    first_oid = manifest["candidate_generations"][0]["signed_commit"]["oid"]
    _append_candidate_generation(manifest, parent_oid=first_oid, tree_oid="4" * 40)
    _append_third_candidate_generation(manifest, parent_oid=first_oid)

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "candidate_lineage_disconnected" in {finding.code for finding in report.findings}


def test_every_candidate_in_the_consumed_lineage_is_fully_validated(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    first_oid = manifest["candidate_generations"][0]["signed_commit"]["oid"]
    _append_candidate_generation(manifest, parent_oid=first_oid, tree_oid="4" * 40)
    manifest["candidate_generations"][0]["signed_commit"]["signature_verified"] = False

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "candidate_signature_unverified" in {finding.code for finding in report.findings}


def test_post_merge_checks_cannot_reuse_candidate_evidence(repo_root: Path) -> None:
    manifest = _pass_manifest(repo_root)
    candidate_checks = manifest["candidate_generations"][0]["local_checks"]
    for candidate_check, post_merge_check in zip(
        candidate_checks,
        manifest["post_merge_local_checks"],
        strict=True,
    ):
        post_merge_check["evidence_ref"] = copy.deepcopy(candidate_check["evidence_ref"])
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=repo_root)

    codes = {finding.code for finding in report.findings}
    assert report.verdict is AcceptanceVerdict.FAIL
    assert "post_merge_check_reuses_candidate_evidence" in codes
    assert "local_check_evidence_binding_mismatch" in codes


def test_phase10_policy_rejects_missing_duplicate_and_contradictory_sources(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    with pytest.raises(Phase10PolicyError, match="missing or unsafe"):
        load_phase10_policy(tmp_path)

    policy_path = tmp_path / "spec/acceptance/phase10-policy.json"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text('{"schema_version":"1.0","schema_version":"1.0"}\n', encoding="utf-8")
    with pytest.raises(Phase10PolicyError, match="invalid"):
        load_phase10_policy(tmp_path)

    policy = _load_json(repo_root / "spec/acceptance/phase10-policy.json")
    invalid_values = (
        {**policy, "schema_version": "2.0"},
        {**policy, "plan_version": "unknown"},
        {**policy, "allowed_merge_methods": ["octopus"]},
        {**policy, "ci_api_authentication": "manifest-asserted"},
        {**policy, "required_workflows": ["Python CI"]},
        {**policy, "required_security_checks": []},
        {**policy, "required_local_check_profiles": {}},
        {**policy, "required_local_check_profiles": {"tox-invalid": {"argv": [], "covers": []}}},
        {**policy, "limits": {**policy["limits"], "manifest_bytes_max": 1_048_577}},
        {
            **policy,
            "limits": {**policy["limits"], "workflow_source_bytes_max": 32_769},
        },
        {**policy, "required_ci_workflow_profiles": {}},
        {**policy, "policy_id": ""},
        {**policy, "repository": "not-a-repository"},
        {**policy, "protected_branch_ref": "master"},
        {**policy, "required_workflows": ["Python CI", "Contract validation"]},
    )
    for value in invalid_values:
        policy_path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(Phase10PolicyError):
            load_phase10_policy(tmp_path)

    acceptance_schema = tmp_path / "schemas/acceptance/phase10-run.schema.json"
    ci_schema = tmp_path / "schemas/acceptance/ci-checkout-attestation.schema.json"
    acceptance_schema.parent.mkdir(parents=True)
    acceptance_schema.write_bytes(
        (repo_root / "schemas/acceptance/phase10-run.schema.json").read_bytes()
    )
    ci_schema.write_bytes(
        (repo_root / "schemas/acceptance/ci-checkout-attestation.schema.json").read_bytes()
    )
    for relative in CI_ATTESTATION_COLLECTOR_PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_root / relative, target)
    for workflow_profile in load_phase10_policy(repo_root).required_ci_workflow_profiles.values():
        target = tmp_path / workflow_profile.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_root / workflow_profile.path, target)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    assert load_phase10_policy(tmp_path).sha256 == load_phase10_policy(repo_root).sha256

    stale_schema = _load_json(acceptance_schema)
    stale_schema["title"] = "stale schema"
    acceptance_schema.write_text(json.dumps(stale_schema), encoding="utf-8")
    with pytest.raises(Phase10PolicyError, match="schema identity is stale"):
        load_phase10_policy(tmp_path)

"""Deterministic Phase 10 policy and acceptance-evaluator tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

import binnacle.evaluation as evaluation_package
from binnacle.evaluation.phase10_acceptance import (
    AcceptanceManifestError,
    AcceptanceVerdict,
    create_phase10_skeleton,
    evaluate_phase10_manifest,
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
    assert policy.sha256 == "af8b9509a6c95c241e58e61edff77caa763e4a42287a33f5e0e75113d53fd568"
    assert policy.acceptance_schema_sha256 == (
        "a6246ea78375851789d62929bd6c3650b991cc765c1f52d9bea2bfa6157c2c58"
    )
    assert policy.ci_attestation_schema_sha256 == (
        "a3ae8f5c5c7973fa948fab3b78cb75e91d9cbc045fe28229dd5a543e210d716d"
    )
    assert policy.repository == "grammy-jiang/binnacle"
    assert policy.protected_branch_ref == "refs/heads/master"
    assert policy.allowed_merge_methods == ("squash",)
    assert policy.required_ci_jobs["Python CI"] == (
        "Code, contract, dependency, and document quality",
        "Test Python 3.11",
        "Test Python 3.12",
        "Test Python 3.13",
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


@pytest.mark.parametrize("case_index", range(25))
def test_phase10_evaluator_fixture(case_index: int, repo_root: Path) -> None:
    cases = _cases(repo_root)
    assert len(cases) == 25
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
    ("/candidate_generations/0/push/conclusion", "failure", "candidate_push_failed"),
    ("/candidate_generations/0/push/conclusion", "uncertain", "candidate_push_uncertain"),
    (
        "/candidate_generations/0/push/remote_ref",
        "refs/heads/wrong",
        "candidate_push_ref_mismatch",
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
        "/integration_generations/0/ci_evidence/0/github_sha",
        "8" * 40,
        "ci_github_sha_unbound",
    ),
    (
        "/integration_generations/0/ci_evidence/0/workflow_name",
        "Unreviewed CI",
        "unexpected_required_ci_evidence",
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
        {**policy, "required_workflows": ["Python CI"]},
        {**policy, "required_security_checks": []},
        {**policy, "limits": {**policy["limits"], "manifest_bytes_max": 1_048_577}},
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
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    assert load_phase10_policy(tmp_path).sha256 == load_phase10_policy(repo_root).sha256

    stale_schema = _load_json(acceptance_schema)
    stale_schema["title"] = "stale schema"
    acceptance_schema.write_text(json.dumps(stale_schema), encoding="utf-8")
    with pytest.raises(Phase10PolicyError, match="schema identity is stale"):
        load_phase10_policy(tmp_path)

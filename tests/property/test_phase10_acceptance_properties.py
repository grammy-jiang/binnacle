"""Property checks preventing stale or similarly named evidence from satisfying Phase 10."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

from hypothesis import given
from hypothesis import strategies as st

from binnacle.evaluation.digests import canonical_json_bytes, canonical_json_sha256, sha256_bytes
from binnacle.evaluation.phase10_acceptance import (
    AcceptanceVerdict,
    evaluate_phase10_manifest,
    phase10_reviewed_evidence_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_DISTINCT_CI_PAIRS = tuple(
    (source, target) for source in range(5) for target in range(5) if source != target
)


def _pass_manifest(repo_root: Path) -> dict[str, Any]:
    value = json.loads(
        (repo_root / "tests/fixtures/acceptance/phase10-pass.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


@given(index=st.integers(min_value=0, max_value=6))
def test_omitting_any_required_security_check_never_passes(
    index: int,
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    del manifest["security_checks"][index]

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "required_security_checks_incomplete" in {finding.code for finding in report.findings}


@given(order=st.permutations((0, 1, 2, 3, 4)))
def test_ci_evidence_order_does_not_change_exact_pass(
    order: list[int],
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    original = manifest["integration_generations"][0]["ci_evidence"]
    manifest["integration_generations"][0]["ci_evidence"] = [
        copy.deepcopy(original[index]) for index in order
    ]
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.PASS


@given(index=st.integers(min_value=0, max_value=4))
def test_similarly_named_duplicate_ci_job_cannot_replace_required_job(
    index: int,
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    evidence = manifest["integration_generations"][0]["ci_evidence"]
    replacement = copy.deepcopy(evidence[index])
    replacement["evidence_ref"]["id"] = f"duplicate-job-{index}"
    evidence[index] = replacement
    duplicate_source = evidence[(index + 1) % len(evidence)]
    evidence[index]["job_name"] = duplicate_source["job_name"]
    evidence[index]["workflow_name"] = duplicate_source["workflow_name"]
    evidence[index]["attestation"]["job_name"] = duplicate_source["job_name"]
    evidence[index]["attestation"]["workflow_name"] = duplicate_source["workflow_name"]
    evidence[index]["attestation_sha256"] = sha256_bytes(
        canonical_json_bytes(evidence[index]["attestation"]) + b"\n"
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is not AcceptanceVerdict.PASS
    assert "required_ci_job_evidence_missing" in {finding.code for finding in report.findings}


@given(pair=st.sampled_from(_DISTINCT_CI_PAIRS))
def test_one_ci_attestation_cannot_be_relabelled_as_another_required_job(
    pair: tuple[int, int],
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    source_index, target_index = pair
    evidence = manifest["integration_generations"][0]["ci_evidence"]
    evidence[target_index]["attestation"] = copy.deepcopy(evidence[source_index]["attestation"])
    evidence[target_index]["attestation_sha256"] = evidence[source_index]["attestation_sha256"]
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert {finding.code for finding in report.findings} >= {
        "ci_attestation_reused",
        "ci_attestation_identity_mismatch",
    }


@given(pair=st.sampled_from(_DISTINCT_CI_PAIRS))
def test_one_uploaded_artifact_cannot_be_relabelled_as_another_job(
    pair: tuple[int, int],
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    source_index, target_index = pair
    evidence = manifest["integration_generations"][0]["ci_evidence"]
    for field in (
        "github_artifact_api_ref",
        "github_artifact_api_observation",
        "github_artifact_id",
        "github_artifact_archive_sha256",
        "github_artifact_archive_base64",
    ):
        evidence[target_index][field] = copy.deepcopy(evidence[source_index][field])
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_artifact_reused" in {finding.code for finding in report.findings}


@given(index=st.integers(min_value=0, max_value=4))
def test_manifest_cannot_replace_attestation_from_uploaded_artifact(index: int) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    evidence = manifest["integration_generations"][0]["ci_evidence"][index]
    evidence["attestation"]["created_at"] = "2030-12-31T23:59:59Z"
    evidence["attestation_sha256"] = sha256_bytes(
        canonical_json_bytes(evidence["attestation"]) + b"\n"
    )
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_artifact_attestation_mismatch" in {finding.code for finding in report.findings}


@given(
    field=st.sampled_from(
        (
            "repository",
            "id",
            "name",
            "size_in_bytes",
            "url",
            "archive_download_url",
            "expired",
            "digest",
            "workflow_run.id",
            "workflow_run.head_sha",
        )
    )
)
def test_artifact_api_observation_must_bind_downloaded_archive_metadata(field: str) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    evidence = manifest["integration_generations"][0]["ci_evidence"][0]
    observation = evidence["github_artifact_api_observation"]
    replacements: dict[str, object] = {
        "repository": "attacker/other",
        "id": 9999,
        "name": "wrong-artifact",
        "size_in_bytes": 1,
        "url": "https://api.github.com/repos/grammy-jiang/binnacle/actions/artifacts/9999",
        "archive_download_url": (
            "https://api.github.com/repos/grammy-jiang/binnacle/actions/artifacts/9999/zip"
        ),
        "expired": True,
        "digest": f"sha256:{'8' * 64}",
        "workflow_run.id": 9999,
        "workflow_run.head_sha": "8" * 40,
    }
    if "." in field:
        parent, child = field.split(".", 1)
        observation[parent][child] = replacements[field]
    else:
        observation[field] = replacements[field]
    evidence["github_artifact_api_ref"]["sha256"] = canonical_json_sha256(observation)
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "ci_artifact_api_metadata_mismatch" in {finding.code for finding in report.findings}


@given(
    collection=st.sampled_from(("candidate", "post_merge")),
    index=st.integers(min_value=0, max_value=4),
)
def test_omitting_any_required_local_check_never_passes(
    collection: str,
    index: int,
) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    if collection == "candidate":
        checks = manifest["candidate_generations"][0]["local_checks"]
    else:
        checks = manifest["post_merge_local_checks"]
    del checks[index]
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "required_local_check_profile_incomplete" in {
        finding.code for finding in report.findings
    }


@given(
    field=st.sampled_from(
        (
            "hosted_head_oid",
            "push.target_oid",
            "push.remote_observed_oid",
            "signed_commit.parent_oid",
        )
    )
)
def test_candidate_identity_permutation_never_passes(field: str) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    candidate = manifest["candidate_generations"][0]
    if "." in field:
        parent, child = field.split(".", 1)
        candidate[parent][child] = "8" * 40
    else:
        candidate[field] = "8" * 40

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is not AcceptanceVerdict.PASS


@given(field=st.sampled_from(("repository_head_oid", "protected_base_oid")))
def test_incoherent_baseline_head_and_protected_base_never_passes(field: str) -> None:
    manifest = _pass_manifest(REPO_ROOT)
    manifest["baseline"][field] = "8" * 40
    manifest["owner_review"]["reviewed_evidence_sha256"] = phase10_reviewed_evidence_sha256(
        manifest
    )

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "baseline_protected_base_mismatch" in {finding.code for finding in report.findings}


def test_new_candidate_generation_cannot_reuse_prior_local_evidence() -> None:
    manifest = _pass_manifest(REPO_ROOT)
    first = manifest["candidate_generations"][0]
    first["superseded_reason_ref"] = {"id": "head-moved", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 2
    second["superseded_reason_ref"] = None
    prior_oid = first["signed_commit"]["oid"]
    second["status_diff"]["parent_oid"] = prior_oid
    second["signed_commit"]["oid"] = "6" * 40
    second["signed_commit"]["parent_oid"] = prior_oid
    second["push"]["target_oid"] = "6" * 40
    second["push"]["remote_observed_oid"] = "6" * 40
    second["hosted_head_oid"] = "6" * 40
    candidate_refs = [
        second["status_diff"]["evidence_ref"],
        second["signed_commit"]["evidence_ref"],
        second["push"]["evidence_ref"],
        *(check["evidence_ref"] for check in second["local_checks"]),
    ]
    for index, evidence_ref in enumerate(candidate_refs):
        evidence_ref["id"] = f"renamed-candidate-2-evidence-{index}"
    manifest["candidate_generations"].append(second)
    manifest["final_candidate_generation"] = 2
    manifest["integration_generations"][0]["candidate_generation"] = 2
    manifest["integration_generations"][0]["candidate_oid"] = "6" * 40
    manifest["github_pr"]["head_oid"] = "6" * 40
    manifest["github_merge"]["candidate_oid"] = "6" * 40

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "candidate_generation_reuses_stale_evidence" in {
        finding.code for finding in report.findings
    }


def test_new_integration_generation_cannot_reuse_old_review_or_ci() -> None:
    manifest = _pass_manifest(REPO_ROOT)
    first = manifest["integration_generations"][0]
    first["superseded_reason_ref"] = {"id": "base-moved", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 2
    second["superseded_reason_ref"] = None
    integration_refs = [
        *(review["evidence_ref"] for review in second["reviews"]),
        *(evidence["evidence_ref"] for evidence in second["ci_evidence"]),
    ]
    for index, evidence_ref in enumerate(integration_refs):
        evidence_ref["id"] = f"renamed-integration-2-evidence-{index}"
    manifest["integration_generations"].append(second)
    manifest["final_integration_generation"] = 2

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "integration_generation_reuses_stale_evidence" in {
        finding.code for finding in report.findings
    }


def test_new_integration_generation_cannot_relabel_old_checkout_attestations() -> None:
    manifest = _pass_manifest(REPO_ROOT)
    first = manifest["integration_generations"][0]
    first["superseded_reason_ref"] = {"id": "base-moved", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 2
    second["superseded_reason_ref"] = None
    integration_refs = [
        *(review["evidence_ref"] for review in second["reviews"]),
        *(evidence["evidence_ref"] for evidence in second["ci_evidence"]),
    ]
    for index, evidence_ref in enumerate(integration_refs, start=1):
        evidence_ref["id"] = f"replacement-integration-2-evidence-{index}"
        evidence_ref["sha256"] = f"{index:064x}"
    manifest["integration_generations"].append(second)
    manifest["final_integration_generation"] = 2

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "integration_generation_reuses_stale_evidence" in {
        finding.code for finding in report.findings
    }

"""Property checks preventing stale or similarly named evidence from satisfying Phase 10."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

from hypothesis import given
from hypothesis import strategies as st

from binnacle.evaluation.phase10_acceptance import (
    AcceptanceVerdict,
    evaluate_phase10_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "required_ci_job_evidence_missing" in {finding.code for finding in report.findings}


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


def test_new_candidate_generation_cannot_reuse_prior_local_evidence() -> None:
    manifest = _pass_manifest(REPO_ROOT)
    first = manifest["candidate_generations"][0]
    first["superseded_reason_ref"] = {"id": "head-moved", "sha256": "e" * 64}
    second = copy.deepcopy(first)
    second["generation"] = 2
    second["superseded_reason_ref"] = None
    manifest["candidate_generations"].append(second)
    manifest["final_candidate_generation"] = 2

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
    manifest["integration_generations"].append(second)
    manifest["final_integration_generation"] = 2

    report = evaluate_phase10_manifest(manifest, repo_root=REPO_ROOT)

    assert report.verdict is AcceptanceVerdict.INCOMPLETE
    assert "integration_generation_reuses_stale_evidence" in {
        finding.code for finding in report.findings
    }

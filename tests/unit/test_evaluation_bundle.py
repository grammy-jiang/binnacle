"""Final manifest verification and deterministic bundle tests."""

from __future__ import annotations

import copy
import gzip
import json
import tarfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from binnacle.evaluation.bundle import (
    BUNDLE_NAME,
    FINAL_MANIFEST_NAME,
    RECEIPT_NAME,
    WORKING_MANIFEST_NAME,
    EvaluationVerificationError,
    build_deterministic_archive,
    finalize_evaluation,
    verify_evaluation_manifest,
)
from binnacle.evaluation.cases import load_evaluation_cases
from binnacle.evaluation.evidence import EvidenceFile, EvidenceStore
from binnacle.evaluation.profile import load_evaluation_profile


def _complete_manifest(repo_root: Path, workspace: Path) -> dict[str, Any]:
    profile = load_evaluation_profile(repo_root)
    cases = load_evaluation_cases(repo_root, profile=profile)
    store = EvidenceStore(workspace)
    evidence = store.add_bytes(
        evidence_id="phase3-capability-scope",
        relative_path="phase3-capability-scope.json",
        data=(
            b'{"catalogue_phase":"compatibility-core","scope":"fixture-only-unexercised-cases"}\n'
        ),
        media_type="application/json",
        information_class="normal-result",
    )
    started = "2026-08-11T00:00:00Z"
    case_results: list[dict[str, Any]] = []
    axes: dict[str, list[str]] = defaultdict(list)
    for frozen in cases.cases.values():
        axes[frozen.axis].append(frozen.case_id)
        case_results.append(
            {
                "case_id": frozen.case_id,
                "axis": frozen.axis,
                "risk_class": frozen.risk_class,
                "attempts_required": profile.risk_classes[frozen.risk_class].minimum_attempts,
                "attempts_completed": 0,
                "passes": 0,
                "failures": 0,
                "blocked": 0,
                "status": "not-tested",
                "failure_details": [],
                "evidence_refs": [evidence.evidence_id],
                "started_at": started,
                "completed_at": started,
                "latency_ms": {"p50": None, "p95": None, "p99": None},
            }
        )
    digest = "a" * 64
    return {
        "schema_version": "1.1",
        "evaluation_id": "eval_20260811T000000Z_012345abcdef",
        "profile": {
            "profile_id": profile.profile_id,
            "chatgpt_product": "ChatGPT fixture",
            "chatgpt_surface": "web fixture",
            "account_plan": "fixture plan",
            "workspace_type": "fixture workspace",
            "workspace_policy_sha256": None,
            "connection_method": "fixture authenticated transport",
            "authentication_profile": "fixture-only",
            "binnacle_build_sha256": digest,
            "binnacle_config_sha256": digest,
            "mcp_sdk_name": "mcp",
            "mcp_sdk_version": "fixture",
            "mcp_sdk_artifact_sha256": digest,
            "tunnel_or_gateway_identity": None,
            "tunnel_or_gateway_artifact_sha256": None,
            "tool_manifest_sha256": digest,
            "schema_registry_sha256": digest,
            "policy_bundle_sha256": digest,
            "evaluation_profile_sha256": profile.sha256,
            "evaluation_cases_sha256": profile.case_manifest.sha256,
            "device_model": "Raspberry Pi fixture",
            "device_os": "fixture OS",
            "device_kernel": "fixture kernel",
            "device_architecture": "aarch64",
            "device_profile": "fixture-device-profile",
            "intended_revision_set": [
                "2026-07-28",
                "2025-11-25",
                "2025-06-18",
                "2025-03-26",
            ],
            "requested_revision": None,
            "negotiated_revision": None,
            "observed_client_capabilities_sha256": None,
        },
        "probe": {
            "probe_release": "phase3-readonly-evaluation-v1",
            "dispatcher_version": "mcp-revision-dispatch-v1",
            "oracle_version": f"evaluation-cases/{cases.version}",
            "runner_version": "binnacle-mcp-evaluation/1.0.0",
            "started_at": started,
            "completed_at": started,
        },
        "case_manifest": {
            "path": profile.case_manifest.path.as_posix(),
            "version": profile.case_manifest.version,
            "sha256": profile.case_manifest.sha256,
        },
        "case_results": case_results,
        "conclusions": [
            {
                "axis": axis,
                "status": "not-tested",
                "case_ids": case_ids,
                "summary": "Fixture case remains unexercised.",
                "limits": ["No live ChatGPT observation in this fixture."],
            }
            for axis, case_ids in axes.items()
        ],
        "evidence_files": [evidence.as_manifest_value()],
        "redaction": {
            "policy_version": "phase3-redaction-v1",
            "credentials_removed": True,
            "cookies_removed": True,
            "raw_auth_headers_removed": True,
            "owner_private_data_reviewed": True,
        },
        "review": {
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-08-11T01:00:00Z",
            "profile_match_verified": True,
            "case_manifest_match_verified": True,
            "evidence_complete": True,
            "approved_for_promotion": False,
        },
        "validity": {
            "valid_from": started,
            "valid_until": "2026-09-10T00:00:00Z",
            "rerun_triggers": list(profile.rerun_triggers),
        },
        "created_at": started,
    }


def test_complete_unpromoted_manifest_verifies(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(repo_root, tmp_path)

    report = verify_evaluation_manifest(
        manifest,
        workspace=tmp_path,
        repo_root=repo_root,
    )

    assert report.case_count == 21
    assert report.evidence_count == 1
    assert report.reviewed is True
    assert report.approved_for_promotion is False


def test_promoted_case_must_meet_frozen_attempt_threshold(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(repo_root, tmp_path)
    manifest["case_results"][0]["status"] = "observed-supported"

    with pytest.raises(EvaluationVerificationError, match="minimum attempts"):
        verify_evaluation_manifest(manifest, workspace=tmp_path, repo_root=repo_root)


def test_every_frozen_case_and_exact_evidence_digest_are_required(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(repo_root, tmp_path)
    missing_case = copy.deepcopy(manifest)
    missing_case["case_results"].pop()
    with pytest.raises(EvaluationVerificationError, match="every frozen case"):
        verify_evaluation_manifest(missing_case, workspace=tmp_path, repo_root=repo_root)

    (tmp_path / "evidence/phase3-capability-scope.json").write_bytes(b"{}\n")
    with pytest.raises(EvaluationVerificationError, match="digest mismatch"):
        verify_evaluation_manifest(manifest, workspace=tmp_path, repo_root=repo_root)


def test_deterministic_archive_has_no_receipt_or_self_inventory(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(repo_root, tmp_path)
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    raw_evidence = manifest["evidence_files"][0]
    evidence = (
        EvidenceFile(
            evidence_id=raw_evidence["evidence_id"],
            path=raw_evidence["path"],
            sha256=raw_evidence["sha256"],
            media_type=raw_evidence["media_type"],
            information_class=raw_evidence["information_class"],
        ),
    )

    first = build_deterministic_archive(
        manifest_bytes=manifest_bytes,
        workspace=tmp_path,
        evidence=evidence,
    )
    second = build_deterministic_archive(
        manifest_bytes=manifest_bytes,
        workspace=tmp_path,
        evidence=evidence,
    )

    assert first == second
    with tarfile.open(fileobj=gzip.GzipFile(fileobj=__import__("io").BytesIO(first))) as archive:
        names = archive.getnames()
    assert names == [FINAL_MANIFEST_NAME, "evidence/phase3-capability-scope.json"]
    assert RECEIPT_NAME not in names

    (tmp_path / evidence[0].path).write_bytes(b'{"changed":true}\n')
    with pytest.raises(EvaluationVerificationError, match="changed while building"):
        build_deterministic_archive(
            manifest_bytes=manifest_bytes,
            workspace=tmp_path,
            evidence=evidence,
        )


def test_finalize_writes_schema_valid_manifest_bundle_and_detached_receipt(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(repo_root, tmp_path)
    (tmp_path / WORKING_MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    completion = datetime(2026, 8, 11, 2, tzinfo=UTC)

    finalized = finalize_evaluation(
        tmp_path,
        repo_root=repo_root,
        completed_at=completion,
    )

    assert finalized.manifest_path.name == FINAL_MANIFEST_NAME
    assert finalized.bundle_path.name == BUNDLE_NAME
    assert finalized.receipt_path.name == RECEIPT_NAME
    receipt = json.loads(finalized.receipt_path.read_bytes())
    assert receipt["manifest_sha256"] == finalized.manifest_sha256
    assert receipt["bundle_sha256"] == finalized.bundle_sha256
    with tarfile.open(finalized.bundle_path, mode="r:gz") as archive:
        assert archive.getnames() == [
            FINAL_MANIFEST_NAME,
            "evidence/phase3-capability-scope.json",
        ]
    with pytest.raises(EvaluationVerificationError, match="already contains"):
        finalize_evaluation(
            tmp_path,
            repo_root=repo_root,
            completed_at=completion + timedelta(seconds=1),
        )


def test_semantic_verifier_rejects_cross_field_contradictions(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    base = _complete_manifest(repo_root, tmp_path)

    def rejected(candidate: dict[str, Any], message: str) -> None:
        with pytest.raises(EvaluationVerificationError, match=message):
            verify_evaluation_manifest(
                candidate,
                workspace=tmp_path,
                repo_root=repo_root,
                validate_schema=False,
            )

    candidate = copy.deepcopy(base)
    candidate["profile"]["profile_id"] = "other-profile"
    rejected(candidate, "profile_id")

    candidate = copy.deepcopy(base)
    candidate["profile"]["evaluation_profile_sha256"] = "b" * 64
    rejected(candidate, "profile digest")

    candidate = copy.deepcopy(base)
    candidate["profile"]["evaluation_cases_sha256"] = "b" * 64
    rejected(candidate, "cases digest")

    candidate = copy.deepcopy(base)
    candidate["case_manifest"]["version"] = "other"
    rejected(candidate, "case_manifest identity")

    candidate = copy.deepcopy(base)
    candidate["review"]["reviewer"] = "pending"
    rejected(candidate, "human review")

    candidate = copy.deepcopy(base)
    candidate["redaction"]["credentials_removed"] = False
    rejected(candidate, "redaction declaration")

    candidate = copy.deepcopy(base)
    candidate["case_results"].append(copy.deepcopy(candidate["case_results"][0]))
    rejected(candidate, "duplicate case_id")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["axis"] = "other-axis"
    rejected(candidate, "case axis")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["risk_class"] = "latency_and_context_cost"
    rejected(candidate, "risk_class")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["attempts_completed"] = 1
    rejected(candidate, "attempt totals")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["evidence_refs"] = []
    rejected(candidate, "no evidence references")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["evidence_refs"] = ["missing-evidence"]
    rejected(candidate, "does not resolve")

    candidate = copy.deepcopy(base)
    candidate["case_results"][0]["status"] = "server-not-implemented"
    rejected(candidate, "frozen oracle")

    candidate = copy.deepcopy(base)
    candidate["conclusions"].append(copy.deepcopy(candidate["conclusions"][0]))
    rejected(candidate, "duplicate axis")

    candidate = copy.deepcopy(base)
    candidate["conclusions"][0]["case_ids"] = []
    rejected(candidate, "exact cases")

    candidate = copy.deepcopy(base)
    candidate["conclusions"][0]["status"] = "observed-limited"
    rejected(candidate, "contradicts")

    candidate = copy.deepcopy(base)
    candidate["validity"]["valid_until"] = "2027-08-11T00:00:00Z"
    rejected(candidate, "exceeds frozen")

    candidate = copy.deepcopy(base)
    candidate["validity"]["rerun_triggers"] = ["invented-trigger"]
    rejected(candidate, "rerun_triggers")

    candidate = copy.deepcopy(base)
    candidate["review"]["approved_for_promotion"] = True
    rejected(candidate, "required live evidence")

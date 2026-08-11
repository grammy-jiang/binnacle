"""End-to-end evaluator CLI tests without real ChatGPT or Pi credentials."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from binnacle.evaluation.bundle import (
    BUNDLE_NAME,
    FINAL_MANIFEST_NAME,
    RECEIPT_NAME,
    WORKING_MANIFEST_NAME,
)
from binnacle.evaluation.profile import load_evaluation_profile


def _profile_snapshot(repo_root: Path) -> dict[str, object]:
    frozen = load_evaluation_profile(repo_root)
    digest = "a" * 64
    return {
        "profile_id": frozen.profile_id,
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
        "evaluation_profile_sha256": frozen.sha256,
        "evaluation_cases_sha256": frozen.case_manifest.sha256,
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
    }


def _run(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo_root / "src")
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts/mcp_evaluation.py"), *arguments],
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _initialize(repo_root: Path, tmp_path: Path) -> Path:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_profile_snapshot(repo_root)), encoding="utf-8")
    capability_path = tmp_path / "scope.json"
    capability_path.write_text(
        json.dumps(
            {
                "catalogue_phase": "compatibility-core",
                "implemented_tools": 5,
                "write_tools": 0,
                "durable_operations": False,
                "second_binnacle_server": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "evaluation"
    result = _run(
        repo_root,
        "init",
        "--output",
        str(output),
        "--profile-json",
        str(profile_path),
        "--capability-scope-json",
        str(capability_path),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "initialized"
    return output


def test_rejected_review_can_finalize_a_truthful_complete_bundle(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    output = _initialize(repo_root, tmp_path)

    draft = _run(repo_root, "verify", "--output", str(output))
    assert draft.returncode == 0, draft.stderr
    assert json.loads(draft.stdout)["reviewed"] is False

    review = _run(
        repo_root,
        "review",
        "--output",
        str(output),
        "--reviewer",
        "fixture-reviewer",
        "--reject-promotion",
        "--owner-private-data-reviewed",
    )
    assert review.returncode == 0, review.stderr
    assert json.loads(review.stdout)["approved_for_promotion"] is False

    finalized = _run(repo_root, "finalize", "--output", str(output))
    assert finalized.returncode == 0, finalized.stderr
    assert (output / WORKING_MANIFEST_NAME).is_file()
    assert (output / FINAL_MANIFEST_NAME).is_file()
    assert (output / BUNDLE_NAME).is_file()
    assert (output / RECEIPT_NAME).is_file()
    with tarfile.open(output / BUNDLE_NAME, mode="r:gz") as archive:
        assert RECEIPT_NAME not in archive.getnames()
        assert archive.getnames()[0] == FINAL_MANIFEST_NAME

    repeated = _run(repo_root, "finalize", "--output", str(output))
    assert repeated.returncode == 2
    assert "already contains finalized output" in repeated.stderr


def test_record_rejects_invented_case_before_retaining_payload(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    output = _initialize(repo_root, tmp_path)
    observation = tmp_path / "observation.json"
    observation.write_text('{"classification":"absent"}', encoding="utf-8")

    result = _run(
        repo_root,
        "record",
        "--output",
        str(output),
        "--case-id",
        "invented-case",
        "--outcome",
        "classification",
        "--status",
        "server-not-implemented",
        "--evidence",
        str(observation),
        "--evidence-id",
        "invented-observation",
        "--media-type",
        "application/json",
        "--information-class",
        "normal-result",
    )

    assert result.returncode == 2
    assert "unknown evaluation case" in result.stderr
    assert not (output / "evidence/invented-observation.json").exists()


def test_status_only_classification_keeps_attempt_totals_truthful(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    output = _initialize(repo_root, tmp_path)
    observation = tmp_path / "write-scope.json"
    observation.write_text(
        '{"write_tools":0,"classification":"server-not-implemented"}',
        encoding="utf-8",
    )

    recorded = _run(
        repo_root,
        "record",
        "--output",
        str(output),
        "--case-id",
        "write-entitlement-and-confirmation",
        "--outcome",
        "classification",
        "--status",
        "server-not-implemented",
        "--evidence",
        str(observation),
        "--evidence-id",
        "write-scope-observation",
        "--media-type",
        "application/json",
        "--information-class",
        "normal-result",
    )
    assert recorded.returncode == 0, recorded.stderr
    verified = _run(repo_root, "verify", "--output", str(output))
    assert verified.returncode == 0, verified.stderr
    working = json.loads((output / WORKING_MANIFEST_NAME).read_bytes())
    result = next(
        item
        for item in working["case_results"]
        if item["case_id"] == "write-entitlement-and-confirmation"
    )
    assert result["status"] == "server-not-implemented"
    assert result["attempts_completed"] == 0
    assert "write-scope-observation" in result["evidence_refs"]

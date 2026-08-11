#!/usr/bin/env python3
"""Create, record, verify, review, and finalize Phase 3 MCP evidence."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from binnacle.evaluation.bundle import (
    FINAL_MANIFEST_NAME,
    WORKING_MANIFEST_NAME,
    EvaluationVerificationError,
    finalize_evaluation,
    verify_evaluation_manifest,
)
from binnacle.evaluation.cases import load_evaluation_cases
from binnacle.evaluation.digests import canonical_json_bytes
from binnacle.evaluation.evidence import EvidenceStore
from binnacle.evaluation.profile import EvaluationSourceError, load_evaluation_profile

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MAX_JSON_INPUT_BYTES = 1_048_576
_TEXT_EVIDENCE_MEDIA_TYPES = frozenset(
    {"application/json", "application/x-ndjson", "text/plain", "text/markdown"}
)
_FAILURE_CATEGORIES = frozenset(
    {
        "protocol",
        "authentication",
        "authorization",
        "schema",
        "host-policy",
        "host-ui",
        "selection",
        "timeout",
        "latency",
        "retry",
        "cancellation",
        "reconnect",
        "race",
        "privacy",
        "server",
        "unknown",
    }
)
_CLASSIFICATION_STATUSES = frozenset(
    {
        "declared-unexercised",
        "not-declared",
        "server-not-implemented",
        "not-tested",
        "unsupported-by-design",
        "not-applicable",
        "expired",
    }
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _evaluation_id(now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    compact = current.strftime("%Y%m%dT%H%M%SZ")
    return f"eval_{compact}_{secrets.token_hex(6)}"


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_bounded_payload(path))
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("JSON input is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return cast(dict[str, Any], value)


def _read_bounded_payload(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        path_metadata = path.stat(follow_symlinks=False)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 <= metadata.st_size <= _MAX_JSON_INPUT_BYTES
        ):
            raise ValueError("input must be a bounded regular non-symlink file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            data = source.read(_MAX_JSON_INPUT_BYTES + 1)
        if len(data) > _MAX_JSON_INPUT_BYTES:
            raise ValueError("input exceeds the evaluation size bound")
        return data
    except OSError as exc:
        raise ValueError("input must be a bounded regular non-symlink file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_profile_snapshot(profile_value: Mapping[str, Any]) -> None:
    frozen = load_evaluation_profile(_REPO_ROOT)
    schema = _read_json_object(_REPO_ROOT / frozen.manifest_schema)
    selected = {"$ref": "#/$defs/profile", "$defs": schema.get("$defs", {})}
    if next(Draft202012Validator(selected).iter_errors(profile_value), None) is not None:
        raise ValueError("profile snapshot does not satisfy the frozen profile schema")
    if profile_value.get("profile_id") != frozen.profile_id:
        raise ValueError("profile snapshot profile_id does not match the frozen profile")
    if profile_value.get("evaluation_profile_sha256") != frozen.sha256:
        raise ValueError("profile snapshot evaluation_profile_sha256 does not match")
    if profile_value.get("evaluation_cases_sha256") != frozen.case_manifest.sha256:
        raise ValueError("profile snapshot evaluation_cases_sha256 does not match")


def initialize_workspace(
    *,
    output: Path,
    profile_json: Path,
    capability_scope_json: Path,
) -> dict[str, Any]:
    """Create a write-once draft covering every frozen case with initial evidence."""

    if output.exists() and any(output.iterdir()):
        raise FileExistsError("evaluation output directory is not empty")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.is_symlink():
        raise ValueError("evaluation output may not be a symbolic link")
    profile_value = _read_json_object(profile_json)
    _validate_profile_snapshot(profile_value)
    frozen = load_evaluation_profile(_REPO_ROOT)
    cases = load_evaluation_cases(_REPO_ROOT, profile=frozen)
    capability_bytes = _read_bounded_payload(capability_scope_json)
    evidence = EvidenceStore(output).add_bytes(
        evidence_id="phase3-capability-scope",
        relative_path="phase3-capability-scope.json",
        data=capability_bytes,
        media_type="application/json",
        information_class="normal-result",
    )
    current = datetime.now(UTC)
    now = current.isoformat().replace("+00:00", "Z")
    axes: dict[str, list[str]] = defaultdict(list)
    case_results: list[dict[str, Any]] = []
    for case in cases.cases.values():
        axes[case.axis].append(case.case_id)
        case_results.append(
            {
                "case_id": case.case_id,
                "axis": case.axis,
                "risk_class": case.risk_class,
                "attempts_required": frozen.risk_classes[case.risk_class].minimum_attempts,
                "attempts_completed": 0,
                "passes": 0,
                "failures": 0,
                "blocked": 0,
                "status": "not-tested",
                "failure_details": [],
                "evidence_refs": [evidence.evidence_id],
                "started_at": now,
                "completed_at": now,
                "latency_ms": {"p50": None, "p95": None, "p99": None},
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "1.1",
        "evaluation_id": _evaluation_id(current),
        "profile": profile_value,
        "probe": {
            "probe_release": "phase3-readonly-evaluation-v1",
            "dispatcher_version": "mcp-revision-dispatch-v1",
            "oracle_version": f"evaluation-cases/{cases.version}",
            "runner_version": "binnacle-mcp-evaluation/1.0.0",
            "started_at": now,
            "completed_at": now,
        },
        "case_manifest": {
            "path": frozen.case_manifest.path.as_posix(),
            "version": frozen.case_manifest.version,
            "sha256": frozen.case_manifest.sha256,
        },
        "case_results": case_results,
        "conclusions": [
            {
                "axis": axis,
                "status": "not-tested",
                "case_ids": case_ids,
                "summary": "Pending live evaluation.",
                "limits": ["No retained live attempt has yet changed this classification."],
            }
            for axis, case_ids in axes.items()
        ],
        "evidence_files": [evidence.as_manifest_value()],
        "redaction": {
            "policy_version": "phase3-redaction-v1",
            "credentials_removed": True,
            "cookies_removed": True,
            "raw_auth_headers_removed": True,
            "owner_private_data_reviewed": False,
        },
        "review": {
            "reviewer": "pending",
            "reviewed_at": now,
            "profile_match_verified": False,
            "case_manifest_match_verified": False,
            "evidence_complete": False,
            "approved_for_promotion": False,
        },
        "validity": {
            "valid_from": now,
            "valid_until": (current + timedelta(days=frozen.maximum_validity_days))
            .isoformat()
            .replace("+00:00", "Z"),
            "rerun_triggers": list(frozen.rerun_triggers),
        },
        "created_at": now,
    }
    verify_evaluation_manifest(
        manifest,
        workspace=output,
        repo_root=_REPO_ROOT,
        require_review=False,
        validate_schema=False,
    )
    _write_working(output, manifest)
    return manifest


def record_evidence(
    *,
    output: Path,
    case_id: str,
    outcome: str,
    status: str,
    evidence_path: Path,
    evidence_id: str,
    media_type: str,
    information_class: str,
    failure_category: str | None,
    failure_code: str | None,
    failure_summary: str | None,
    latency: tuple[float | None, float | None, float | None],
    conclusion_status: str | None,
    conclusion_summary: str | None,
    binary_human_reviewed: bool,
) -> dict[str, Any]:
    """Add one sanitized attempt or classification to an existing frozen case."""

    manifest = _load_working(output)
    _require_unreviewed(manifest)
    frozen = load_evaluation_profile(_REPO_ROOT)
    frozen.requires_status(status)
    cases = load_evaluation_cases(_REPO_ROOT, profile=frozen)
    frozen_case = cases.require(case_id)
    if not frozen_case.allows_status(status):
        raise ValueError("status is not permitted by the frozen case oracle")
    if outcome not in {"pass", "failure", "blocked", "classification"}:
        raise ValueError("unknown evaluation outcome")
    if outcome == "classification" and status not in _CLASSIFICATION_STATUSES:
        raise ValueError("classification outcome requires a non-observational status")
    if outcome != "classification" and status in _CLASSIFICATION_STATUSES:
        raise ValueError("attempt outcome cannot use a status-only classification")
    if outcome == "failure":
        if failure_category not in _FAILURE_CATEGORIES or not failure_code or not failure_summary:
            raise ValueError("failed outcome requires bounded category, code, and summary")
    elif any(value is not None for value in (failure_category, failure_code, failure_summary)):
        raise ValueError("failure details are accepted only for a failed outcome")
    if any(value is not None for value in latency) and any(
        value is None or value < 0 for value in latency
    ):
        raise ValueError("latency percentiles must be supplied together and non-negative")
    if conclusion_status is not None:
        frozen.requires_status(conclusion_status)
        if conclusion_status != status:
            raise ValueError("single-case conclusion must match the recorded case status")
        if not conclusion_summary or len(conclusion_summary) > 4000:
            raise ValueError("conclusion status requires a bounded conclusion summary")
    elif conclusion_summary is not None:
        raise ValueError("conclusion summary requires conclusion status")

    suffix = evidence_path.suffix.casefold()
    if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
        suffix = ".evidence"
    evidence_values = cast(list[dict[str, Any]], manifest["evidence_files"])
    if any(item.get("evidence_id") == evidence_id for item in evidence_values):
        raise ValueError("evidence_id already exists in the working manifest")
    payload = _read_bounded_payload(evidence_path)
    binary_media_type = media_type not in _TEXT_EVIDENCE_MEDIA_TYPES
    if binary_media_type and not binary_human_reviewed:
        raise ValueError("binary evidence requires explicit pre-retention human review")
    evidence = EvidenceStore(output).add_bytes(
        evidence_id=evidence_id,
        relative_path=f"{evidence_id}{suffix}",
        data=payload,
        media_type=media_type,
        information_class=information_class,
        human_reviewed=binary_human_reviewed,
    )
    evidence_values.append(evidence.as_manifest_value())
    result = _case_result(manifest, case_id)
    references = cast(list[str], result["evidence_refs"])
    if evidence_id not in references:
        references.append(evidence_id)
    now = _timestamp()
    if outcome != "classification":
        if result["attempts_completed"] == 0:
            result["started_at"] = now
        result["attempts_completed"] += 1
        counter = {"pass": "passes", "failure": "failures", "blocked": "blocked"}[outcome]
        result[counter] += 1
    if outcome == "failure":
        failure_details = cast(list[dict[str, str]], result["failure_details"])
        failure_details.append(
            {
                "category": cast(str, failure_category),
                "code": cast(str, failure_code),
                "summary": cast(str, failure_summary),
            }
        )
    result["status"] = status
    result["completed_at"] = now
    if any(value is not None for value in latency):
        result["latency_ms"] = dict(zip(("p50", "p95", "p99"), latency, strict=True))
    if conclusion_status is not None:
        conclusion = _axis_conclusion(manifest, frozen_case.axis)
        conclusion["status"] = conclusion_status
        conclusion["summary"] = conclusion_summary
    _write_working(output, manifest)
    return manifest


def review_workspace(
    *,
    output: Path,
    reviewer: str,
    approved_for_promotion: bool,
    owner_private_data_reviewed: bool,
) -> dict[str, Any]:
    """Record one human decision only after all final verification requirements hold."""

    if not reviewer.strip() or reviewer.casefold() in {"pending", "unknown", "tbd"}:
        raise ValueError("reviewer identity is invalid")
    if not owner_private_data_reviewed:
        raise ValueError("review requires an explicit owner-private-data redaction decision")
    manifest = _load_working(output)
    _require_unreviewed(manifest)
    candidate = cast(dict[str, Any], json.loads(json.dumps(manifest)))
    candidate["redaction"]["owner_private_data_reviewed"] = True
    candidate["review"] = {
        "reviewer": reviewer.strip(),
        "reviewed_at": _timestamp(),
        "profile_match_verified": True,
        "case_manifest_match_verified": True,
        "evidence_complete": True,
        "approved_for_promotion": approved_for_promotion,
    }
    verify_evaluation_manifest(
        candidate,
        workspace=output,
        repo_root=_REPO_ROOT,
        require_review=True,
        validate_schema=True,
    )
    _write_working(output, candidate)
    return candidate


def _case_result(manifest: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    results = manifest.get("case_results")
    if not isinstance(results, list):
        raise ValueError("working manifest case_results is invalid")
    matches = [
        item for item in results if isinstance(item, dict) and item.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError("working manifest does not contain exactly one frozen case result")
    return cast(dict[str, Any], matches[0])


def _axis_conclusion(manifest: Mapping[str, Any], axis: str) -> dict[str, Any]:
    conclusions = manifest.get("conclusions")
    if not isinstance(conclusions, list):
        raise ValueError("working manifest conclusions is invalid")
    matches = [item for item in conclusions if isinstance(item, dict) and item.get("axis") == axis]
    if len(matches) != 1:
        raise ValueError("working manifest does not contain exactly one axis conclusion")
    return cast(dict[str, Any], matches[0])


def _load_working(output: Path) -> dict[str, Any]:
    path = output.resolve() / WORKING_MANIFEST_NAME
    if (output.resolve() / FINAL_MANIFEST_NAME).exists():
        raise ValueError("finalized workspace is immutable")
    return _read_json_object(path)


def _require_unreviewed(manifest: Mapping[str, Any]) -> None:
    review = manifest.get("review")
    if not isinstance(review, Mapping) or review.get("reviewer") != "pending":
        raise ValueError("reviewed workspace is immutable; start a new evaluation run")


def _write_working(output: Path, manifest: Mapping[str, Any]) -> None:
    path = output.resolve() / WORKING_MANIFEST_NAME
    data = canonical_json_bytes(manifest) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".evaluation-working-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="initialize an evidence workspace")
    initialize.add_argument("--output", type=Path, required=True)
    initialize.add_argument("--profile-json", type=Path, required=True)
    initialize.add_argument("--capability-scope-json", type=Path, required=True)

    record = commands.add_parser("record", help="record one frozen-case observation")
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--case-id", required=True)
    record.add_argument(
        "--outcome",
        choices=("pass", "failure", "blocked", "classification"),
        required=True,
    )
    record.add_argument("--status", required=True)
    record.add_argument("--evidence", type=Path, required=True)
    record.add_argument("--evidence-id", required=True)
    record.add_argument("--media-type", required=True)
    record.add_argument(
        "--information-class",
        choices=("normal-result", "restricted-result"),
        required=True,
    )
    record.add_argument("--failure-category")
    record.add_argument("--failure-code")
    record.add_argument("--failure-summary")
    record.add_argument("--latency-p50", type=float)
    record.add_argument("--latency-p95", type=float)
    record.add_argument("--latency-p99", type=float)
    record.add_argument("--conclusion-status")
    record.add_argument("--conclusion-summary")
    record.add_argument(
        "--binary-human-reviewed",
        action="store_true",
        help="attest that a non-text payload was sanitized before retention",
    )

    verify = commands.add_parser("verify", help="verify draft or reviewed evidence")
    verify.add_argument("--output", type=Path, required=True)

    review = commands.add_parser("review", help="record the human review decision")
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve-promotion", action="store_true")
    decision.add_argument("--reject-promotion", action="store_true")
    review.add_argument("--owner-private-data-reviewed", action="store_true", required=True)

    finalize = commands.add_parser("finalize", help="freeze bundle and detached receipt")
    finalize.add_argument("--output", type=Path, required=True)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    command = cast(str, arguments.command)
    if command == "init":
        manifest = initialize_workspace(
            output=arguments.output,
            profile_json=arguments.profile_json,
            capability_scope_json=arguments.capability_scope_json,
        )
        return {"evaluation_id": manifest["evaluation_id"], "status": "initialized"}
    if command == "record":
        manifest = record_evidence(
            output=arguments.output,
            case_id=arguments.case_id,
            outcome=arguments.outcome,
            status=arguments.status,
            evidence_path=arguments.evidence,
            evidence_id=arguments.evidence_id,
            media_type=arguments.media_type,
            information_class=arguments.information_class,
            failure_category=arguments.failure_category,
            failure_code=arguments.failure_code,
            failure_summary=arguments.failure_summary,
            latency=(arguments.latency_p50, arguments.latency_p95, arguments.latency_p99),
            conclusion_status=arguments.conclusion_status,
            conclusion_summary=arguments.conclusion_summary,
            binary_human_reviewed=arguments.binary_human_reviewed,
        )
        return {"evaluation_id": manifest["evaluation_id"], "status": "recorded"}
    if command == "verify":
        manifest = _load_working(arguments.output)
        review = cast(Mapping[str, Any], manifest.get("review", {}))
        reviewed = review.get("reviewer") != "pending"
        report = verify_evaluation_manifest(
            manifest,
            workspace=arguments.output,
            repo_root=_REPO_ROOT,
            require_review=reviewed,
            validate_schema=reviewed,
        )
        return {
            "evaluation_id": report.evaluation_id,
            "status": "verified",
            "reviewed": report.reviewed,
            "case_count": report.case_count,
            "evidence_count": report.evidence_count,
        }
    if command == "review":
        manifest = review_workspace(
            output=arguments.output,
            reviewer=arguments.reviewer,
            approved_for_promotion=arguments.approve_promotion,
            owner_private_data_reviewed=arguments.owner_private_data_reviewed,
        )
        return {
            "evaluation_id": manifest["evaluation_id"],
            "status": "reviewed",
            "approved_for_promotion": arguments.approve_promotion,
        }
    if command == "finalize":
        finalized = finalize_evaluation(arguments.output, repo_root=_REPO_ROOT)
        return {
            "status": "finalized",
            "manifest_sha256": finalized.manifest_sha256,
            "bundle_sha256": finalized.bundle_sha256,
            "manifest": str(finalized.manifest_path),
            "bundle": str(finalized.bundle_path),
            "receipt": str(finalized.receipt_path),
        }
    raise ValueError("unknown command")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded evaluator CLI without ever printing retained payloads."""

    parser = _parser()
    try:
        result = _run(parser.parse_args(argv))
    except (
        EvaluationSourceError,
        EvaluationVerificationError,
        FileExistsError,
        OSError,
        ValueError,
    ) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Initialize and evaluate bounded Phase 10 self-hosting acceptance evidence."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from binnacle.evaluation.digests import canonical_json_bytes  # noqa: E402
from binnacle.evaluation.phase10_acceptance import (  # noqa: E402
    AcceptanceManifestError,
    AcceptanceVerdict,
    create_phase10_skeleton,
    evaluate_phase10_manifest,
    phase10_reviewed_evidence_sha256,
)
from binnacle.evaluation.phase10_policy import (  # noqa: E402
    Phase10PolicyError,
    load_phase10_policy,
)


def _read_manifest(path: Path, *, maximum: int) -> dict[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= maximum:
            raise AcceptanceManifestError("acceptance manifest is not a bounded regular file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            raw = source.read(maximum + 1)
    except OSError as exc:
        raise AcceptanceManifestError("acceptance manifest is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > maximum:
        raise AcceptanceManifestError("acceptance manifest exceeds the reviewed limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise AcceptanceManifestError("acceptance manifest is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceManifestError("acceptance manifest must be a JSON object")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate acceptance manifest field")
        value[key] = item
    return value


def _write_new(path: Path, value: object) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("acceptance write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise AcceptanceManifestError("acceptance output could not be created safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    policy = subparsers.add_parser("policy", help="Report the frozen evaluator policy identity.")
    policy.add_argument("--output", choices=("human", "json"), default="human")

    initialize = subparsers.add_parser(
        "initialize",
        help="Create a planned manifest without claiming unavailable live evidence.",
    )
    initialize.add_argument("--manifest", type=Path, required=True)
    initialize.add_argument("--run-id", required=True)

    review_digest = subparsers.add_parser(
        "review-digest",
        help="Hash the exact evidence projection an owner approval must bind.",
    )
    review_digest.add_argument("--manifest", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate one closed evidence manifest.")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, default=None)
    evaluate.add_argument("--output", choices=("human", "json"), default="human")
    evaluate.add_argument("--require-pass", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_phase10_policy(args.repo_root)
        if args.command == "policy":
            value = {
                "policy_id": policy.policy_id,
                "policy_sha256": policy.sha256,
                "plan_version": policy.plan_version,
                "schema_version": policy.schema_version,
                "acceptance_schema_sha256": policy.acceptance_schema_sha256,
                "ci_attestation_schema_sha256": policy.ci_attestation_schema_sha256,
                "ci_attestation_collector_commit_oid": (policy.ci_attestation_collector_commit_oid),
                "ci_attestation_collector_sha256": policy.ci_attestation_collector_sha256,
                "repository": policy.repository,
                "protected_branch_ref": policy.protected_branch_ref,
                "allowed_merge_methods": list(policy.allowed_merge_methods),
                "required_ci_jobs": {
                    workflow: list(jobs) for workflow, jobs in policy.required_ci_jobs.items()
                },
                "required_security_checks": list(policy.required_security_checks),
                "required_workflows": list(policy.required_workflows),
                "limits": dict(policy.limits),
            }
            if args.output == "json":
                print(canonical_json_bytes(value).decode("utf-8"))
            else:
                print(f"{policy.policy_id} {policy.sha256}")
            return 0
        if args.command == "initialize":
            manifest = create_phase10_skeleton(
                acceptance_run_id=args.run_id,
                repo_root=args.repo_root,
            )
            _write_new(args.manifest, manifest)
            print(f"Created planned acceptance manifest: {args.manifest}")
            return 0

        manifest = _read_manifest(
            args.manifest,
            maximum=policy.limits["manifest_bytes_max"],
        )
        if args.command == "review-digest":
            evaluate_phase10_manifest(manifest, repo_root=args.repo_root)
            print(phase10_reviewed_evidence_sha256(manifest))
            return 0
        report = evaluate_phase10_manifest(manifest, repo_root=args.repo_root)
        report_value = report.as_dict()
        if args.report is not None:
            _write_new(args.report, report_value)
        if args.output == "json":
            print(canonical_json_bytes(report_value).decode("utf-8"))
        else:
            print(
                f"{report.acceptance_run_id}: {report.verdict.value}; "
                f"findings={len(report.findings)}; manifest={report.manifest_sha256}"
            )
            for finding in report.findings:
                print(f"- {finding.disposition.value}: {finding.code} at {finding.path}")
        if args.require_pass and report.verdict is not AcceptanceVerdict.PASS:
            return 1
        return 0
    except (AcceptanceManifestError, Phase10PolicyError) as exc:
        print(f"Phase 10 acceptance error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

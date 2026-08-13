#!/usr/bin/env python3
"""Initialize and evaluate bounded Phase 10 self-hosting acceptance evidence."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import sys
from http.client import HTTPException, HTTPSConnection
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
    ArtifactApiLookup,
    ArtifactApiLookupUnavailable,
    create_phase10_skeleton,
    evaluate_phase10_manifest,
    phase10_reviewed_evidence_sha256,
)
from binnacle.evaluation.phase10_policy import (  # noqa: E402
    Phase10PolicyError,
    load_phase10_policy,
)

GITHUB_API_HOST = "api.github.com"


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


def _read_github_token(path: Path, *, maximum: int) -> str:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 1 <= metadata.st_size <= maximum
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_uid != os.geteuid()
        ):
            raise AcceptanceManifestError("GitHub API token file is not a bounded private file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            raw = source.read(maximum + 1)
    except OSError as exc:
        raise AcceptanceManifestError("GitHub API token file is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    token = raw.rstrip(b"\r\n")
    if (
        len(raw) > maximum
        or not token
        or any(byte <= 0x20 or byte >= 0x7F for byte in token)
        or raw not in {token, token + b"\n", token + b"\r\n"}
    ):
        raise AcceptanceManifestError("GitHub API token file is invalid")
    return token.decode("ascii")


def _fetch_authenticated_artifact_api_observation(
    *,
    token: str,
    repository: str,
    artifact_id: int,
    response_bytes_max: int,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    path = f"/repos/{repository}/actions/artifacts/{artifact_id}"
    connection = HTTPSConnection(
        GITHUB_API_HOST,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "binnacle-phase10-acceptance",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status == 404:
            response.read(response_bytes_max + 1)
            return None
        if response.status != 200:
            response.read(response_bytes_max + 1)
            raise ArtifactApiLookupUnavailable("authenticated GitHub artifact lookup failed")
        content_type = response.getheader("Content-Type", "")
        raw = response.read(response_bytes_max + 1)
        if len(raw) > response_bytes_max or not content_type.lower().startswith("application/json"):
            raise ArtifactApiLookupUnavailable("authenticated GitHub artifact response is invalid")
    except (OSError, TimeoutError, HTTPException, ssl.SSLError) as exc:
        raise ArtifactApiLookupUnavailable(
            "authenticated GitHub artifact lookup unavailable"
        ) from exc
    finally:
        connection.close()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ArtifactApiLookupUnavailable(
            "authenticated GitHub artifact response is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise ArtifactApiLookupUnavailable("authenticated GitHub artifact response is invalid")
    return _sanitize_artifact_api_observation(
        cast(dict[str, Any], value),
        repository=repository,
    )


def _sanitize_artifact_api_observation(
    value: dict[str, Any],
    *,
    repository: str,
) -> dict[str, Any]:
    workflow_run = value.get("workflow_run")
    integer_fields = (value.get("id"), value.get("size_in_bytes"))
    string_fields = (
        value.get("name"),
        value.get("url"),
        value.get("archive_download_url"),
        value.get("digest"),
    )
    if (
        not isinstance(workflow_run, dict)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in integer_fields)
        or not all(isinstance(item, str) and item for item in string_fields)
        or not isinstance(value.get("expired"), bool)
        or isinstance(workflow_run.get("id"), bool)
        or not isinstance(workflow_run.get("id"), int)
        or not isinstance(workflow_run.get("head_sha"), str)
    ):
        raise ArtifactApiLookupUnavailable("authenticated GitHub artifact response is invalid")
    return {
        "repository": repository,
        "id": value["id"],
        "name": value["name"],
        "size_in_bytes": value["size_in_bytes"],
        "url": value["url"],
        "archive_download_url": value["archive_download_url"],
        "expired": value["expired"],
        "digest": value["digest"],
        "workflow_run": {
            "id": workflow_run["id"],
            "head_sha": workflow_run["head_sha"],
        },
    }


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
    review_digest.add_argument("--github-token-file", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate one closed evidence manifest.")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, default=None)
    evaluate.add_argument("--output", choices=("human", "json"), default="human")
    evaluate.add_argument("--require-pass", action="store_true")
    evaluate.add_argument("--github-token-file", type=Path, default=None)
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
                "artifact_api_authentication": policy.artifact_api_authentication,
                "ci_attestation_schema_sha256": policy.ci_attestation_schema_sha256,
                "ci_attestation_collector_commit_oid": (policy.ci_attestation_collector_commit_oid),
                "ci_attestation_collector_sha256": policy.ci_attestation_collector_sha256,
                "repository": policy.repository,
                "protected_branch_ref": policy.protected_branch_ref,
                "allowed_merge_methods": list(policy.allowed_merge_methods),
                "required_ci_jobs": {
                    workflow: list(jobs) for workflow, jobs in policy.required_ci_jobs.items()
                },
                "required_local_check_profiles": dict(policy.required_local_check_profiles),
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
        artifact_api_lookup: ArtifactApiLookup | None = None
        if args.github_token_file is not None:
            token = _read_github_token(
                args.github_token_file,
                maximum=policy.limits["github_api_token_bytes_max"],
            )

            def _lookup(
                repository: str,
                artifact_id: int,
            ) -> dict[str, Any] | None:
                return _fetch_authenticated_artifact_api_observation(
                    token=token,
                    repository=repository,
                    artifact_id=artifact_id,
                    response_bytes_max=policy.limits["github_api_response_bytes_max"],
                    timeout_seconds=policy.limits["github_api_timeout_seconds"],
                )

            artifact_api_lookup = _lookup

        if args.command == "review-digest":
            report = evaluate_phase10_manifest(
                manifest,
                repo_root=args.repo_root,
                authenticated_artifact_api_lookup=artifact_api_lookup,
            )
            if any(finding.code.startswith("ci_artifact_api_") for finding in report.findings):
                raise AcceptanceManifestError(
                    "acceptance review digest requires authenticated GitHub artifact evidence"
                )
            print(phase10_reviewed_evidence_sha256(manifest))
            return 0
        report = evaluate_phase10_manifest(
            manifest,
            repo_root=args.repo_root,
            authenticated_artifact_api_lookup=artifact_api_lookup,
        )
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

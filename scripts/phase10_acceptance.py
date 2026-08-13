#!/usr/bin/env python3
"""Initialize and evaluate bounded Phase 10 self-hosting acceptance evidence."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import ssl
import stat
import sys
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from binnacle.evaluation.digests import canonical_json_bytes, sha256_bytes  # noqa: E402
from binnacle.evaluation.phase10_acceptance import (  # noqa: E402
    AcceptanceManifestError,
    AcceptanceVerdict,
    ArtifactApiLookup,
    ArtifactApiLookupUnavailable,
    CiApiLookup,
    CiApiLookupUnavailable,
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


def _fetch_authenticated_github_json(
    *,
    token: str,
    path: str,
    response_bytes_max: int,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Read one fixed-host GitHub REST JSON object without redirects or proxy routing."""

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
            raise CiApiLookupUnavailable("authenticated GitHub CI lookup failed")
        content_type = response.getheader("Content-Type", "")
        raw = response.read(response_bytes_max + 1)
        if len(raw) > response_bytes_max or not content_type.lower().startswith("application/json"):
            raise CiApiLookupUnavailable("authenticated GitHub CI response is invalid")
    except (OSError, TimeoutError, HTTPException, ssl.SSLError) as exc:
        raise CiApiLookupUnavailable("authenticated GitHub CI lookup unavailable") from exc
    finally:
        connection.close()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise CiApiLookupUnavailable("authenticated GitHub CI response is invalid") from exc
    if not isinstance(value, dict):
        raise CiApiLookupUnavailable("authenticated GitHub CI response is invalid")
    return cast(dict[str, Any], value)


def _fetch_authenticated_ci_api_observation(
    *,
    token: str,
    repository: str,
    job_id: int,
    run_id: int,
    workflow_path: str,
    checkout_oid: str,
    response_bytes_max: int,
    latest_jobs_max: int,
    workflow_source_bytes_max: int,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Read the exact job, latest-job membership, run, and source from GitHub REST."""

    job = _fetch_authenticated_github_json(
        token=token,
        path=f"/repos/{repository}/actions/jobs/{job_id}",
        response_bytes_max=response_bytes_max,
        timeout_seconds=timeout_seconds,
    )
    run = _fetch_authenticated_github_json(
        token=token,
        path=f"/repos/{repository}/actions/runs/{run_id}",
        response_bytes_max=response_bytes_max,
        timeout_seconds=timeout_seconds,
    )
    latest_jobs = _fetch_authenticated_github_json(
        token=token,
        path=(
            f"/repos/{repository}/actions/runs/{run_id}/jobs"
            f"?filter=latest&per_page={latest_jobs_max}"
        ),
        response_bytes_max=response_bytes_max,
        timeout_seconds=timeout_seconds,
    )
    encoded_path = quote(workflow_path, safe="/")
    source = _fetch_authenticated_github_json(
        token=token,
        path=f"/repos/{repository}/contents/{encoded_path}?ref={checkout_oid}",
        response_bytes_max=response_bytes_max,
        timeout_seconds=timeout_seconds,
    )
    if job is None or run is None or latest_jobs is None or source is None:
        return None
    return {
        "repository": repository,
        "job": _sanitize_ci_job_api_observation(job),
        "latest_job_id": _latest_ci_job_id(
            latest_jobs,
            job_id=job_id,
            maximum=latest_jobs_max,
        ),
        "workflow_run": _sanitize_ci_run_api_observation(run, repository=repository),
        "workflow_source": _sanitize_workflow_source_api_observation(
            source,
            workflow_path=workflow_path,
            checkout_oid=checkout_oid,
            maximum=workflow_source_bytes_max,
        ),
    }


def _latest_ci_job_id(
    value: dict[str, Any],
    *,
    job_id: int,
    maximum: int,
) -> int | None:
    """Return the target ID only when it occurs in the complete latest-jobs view."""

    total_count = value.get("total_count")
    jobs = value.get("jobs")
    if (
        isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or not 0 <= total_count <= maximum
        or not isinstance(jobs, list)
        or len(jobs) != total_count
    ):
        raise CiApiLookupUnavailable("authenticated GitHub latest-jobs response is invalid")
    observed_ids: set[int] = set()
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            raise CiApiLookupUnavailable("authenticated GitHub latest-jobs response is invalid")
        sanitized = _sanitize_ci_job_api_observation(cast(dict[str, Any], raw_job))
        current_id = cast(int, sanitized["id"])
        if current_id in observed_ids:
            raise CiApiLookupUnavailable("authenticated GitHub latest-jobs response is invalid")
        observed_ids.add(current_id)
    return job_id if job_id in observed_ids else None


def _sanitize_ci_job_api_observation(value: dict[str, Any]) -> dict[str, Any]:
    integer_names = ("id", "run_id", "run_attempt")
    string_names = (
        "workflow_name",
        "name",
        "head_sha",
        "status",
        "url",
        "check_run_url",
    )
    conclusion = value.get("conclusion")
    if (
        any(
            isinstance(value.get(name), bool) or not isinstance(value.get(name), int)
            for name in integer_names
        )
        or not all(isinstance(value.get(name), str) and value.get(name) for name in string_names)
        or (conclusion is not None and (not isinstance(conclusion, str) or not conclusion))
    ):
        raise CiApiLookupUnavailable("authenticated GitHub job response is invalid")
    return {
        **{name: value[name] for name in integer_names},
        **{name: value[name] for name in string_names},
        "conclusion": conclusion,
    }


def _sanitize_ci_run_api_observation(
    value: dict[str, Any],
    *,
    repository: str,
) -> dict[str, Any]:
    integer_names = ("id", "run_attempt", "workflow_id")
    string_names = ("name", "path", "event", "head_sha", "status", "url", "jobs_url")
    conclusion = value.get("conclusion")
    api_repository = value.get("repository")
    if (
        any(
            isinstance(value.get(name), bool) or not isinstance(value.get(name), int)
            for name in integer_names
        )
        or not all(isinstance(value.get(name), str) and value.get(name) for name in string_names)
        or (conclusion is not None and (not isinstance(conclusion, str) or not conclusion))
        or not isinstance(api_repository, dict)
        or api_repository.get("full_name") != repository
    ):
        raise CiApiLookupUnavailable("authenticated GitHub workflow-run response is invalid")
    return {
        **{name: value[name] for name in integer_names},
        **{name: value[name] for name in string_names},
        "conclusion": conclusion,
    }


def _sanitize_workflow_source_api_observation(
    value: dict[str, Any],
    *,
    workflow_path: str,
    checkout_oid: str,
    maximum: int,
) -> dict[str, Any]:
    size = value.get("size")
    content = value.get("content")
    git_blob_oid = value.get("sha")
    if (
        value.get("type") != "file"
        or value.get("encoding") != "base64"
        or value.get("path") != workflow_path
        or isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= maximum
        or not isinstance(content, str)
        or not isinstance(git_blob_oid, str)
        or not git_blob_oid
    ):
        raise CiApiLookupUnavailable("authenticated GitHub workflow source is invalid")
    try:
        compact_content = "".join(content.split()).encode("ascii")
        raw = base64.b64decode(compact_content, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise CiApiLookupUnavailable("authenticated GitHub workflow source is invalid") from exc
    if len(raw) != size or len(raw) > maximum:
        raise CiApiLookupUnavailable("authenticated GitHub workflow source is invalid")
    return {
        "path": workflow_path,
        "ref": checkout_oid,
        "git_blob_oid": git_blob_oid,
        "size_in_bytes": size,
        "sha256": sha256_bytes(raw),
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
                "ci_api_authentication": policy.ci_api_authentication,
                "ci_attestation_schema_sha256": policy.ci_attestation_schema_sha256,
                "ci_attestation_collector_commit_oid": (policy.ci_attestation_collector_commit_oid),
                "ci_attestation_collector_sha256": policy.ci_attestation_collector_sha256,
                "repository": policy.repository,
                "protected_branch_ref": policy.protected_branch_ref,
                "allowed_merge_methods": list(policy.allowed_merge_methods),
                "required_ci_jobs": {
                    workflow: list(jobs) for workflow, jobs in policy.required_ci_jobs.items()
                },
                "required_ci_workflow_profiles": {
                    workflow: {
                        "workflow_id": profile.workflow_id,
                        "path": profile.path,
                        "source_sha256": profile.source_sha256,
                    }
                    for workflow, profile in policy.required_ci_workflow_profiles.items()
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
        ci_api_lookup: CiApiLookup | None = None
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

            def _ci_lookup(
                repository: str,
                job_id: int,
                run_id: int,
                workflow_path: str,
                checkout_oid: str,
            ) -> dict[str, Any] | None:
                return _fetch_authenticated_ci_api_observation(
                    token=token,
                    repository=repository,
                    job_id=job_id,
                    run_id=run_id,
                    workflow_path=workflow_path,
                    checkout_oid=checkout_oid,
                    response_bytes_max=policy.limits["github_api_response_bytes_max"],
                    latest_jobs_max=policy.limits["github_ci_latest_jobs_max"],
                    workflow_source_bytes_max=policy.limits["workflow_source_bytes_max"],
                    timeout_seconds=policy.limits["github_api_timeout_seconds"],
                )

            ci_api_lookup = _ci_lookup

        if args.command == "review-digest":
            report = evaluate_phase10_manifest(
                manifest,
                repo_root=args.repo_root,
                authenticated_artifact_api_lookup=artifact_api_lookup,
                authenticated_ci_api_lookup=ci_api_lookup,
            )
            if any(
                finding.code.startswith(
                    ("ci_artifact_api_", "ci_api_", "ci_job_api_", "ci_workflow_")
                )
                for finding in report.findings
            ):
                raise AcceptanceManifestError(
                    "acceptance review digest requires authenticated GitHub CI evidence"
                )
            print(phase10_reviewed_evidence_sha256(manifest))
            return 0
        report = evaluate_phase10_manifest(
            manifest,
            repo_root=args.repo_root,
            authenticated_artifact_api_lookup=artifact_api_lookup,
            authenticated_ci_api_lookup=ci_api_lookup,
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

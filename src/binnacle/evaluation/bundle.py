"""Semantic verification and deterministic final evaluation bundle creation."""

from __future__ import annotations

import gzip
import io
import json
import os
import stat
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from binnacle.evaluation.cases import load_evaluation_cases
from binnacle.evaluation.digests import canonical_json_bytes, sha256_bytes
from binnacle.evaluation.evidence import (
    EvidenceFile,
    read_evidence_payload,
    validate_evidence_inventory,
)
from binnacle.evaluation.profile import FrozenEvaluationProfile, load_evaluation_profile

WORKING_MANIFEST_NAME = "evaluation-working.json"
FINAL_MANIFEST_NAME = "evaluation-manifest.json"
BUNDLE_NAME = "evaluation-bundle.tar.gz"
RECEIPT_NAME = "evaluation-bundle.receipt.json"
_PROMOTED_STATUSES = frozenset({"observed-supported", "observed-limited", "host-policy-blocked"})
_PENDING_MARKERS = frozenset({"pending", "unknown", "tbd", "unobserved"})
_MAX_MANIFEST_BYTES = 1_048_576
_REQUIRED_LIVE_CASE_STATUSES = {
    "endpoint-connect": frozenset({"observed-supported"}),
    "protocol-revision-observed": frozenset({"observed-supported"}),
    "tool-discovery-manifest": frozenset({"observed-supported"}),
    "model-tool-selection-binnacle-probe": frozenset({"observed-supported", "observed-limited"}),
    "model-tool-selection-system-inspect": frozenset({"observed-supported", "observed-limited"}),
    "structured-result-rendering": frozenset({"observed-supported", "observed-limited"}),
    "execution-error-rendering": frozenset({"observed-supported", "observed-limited"}),
    "read-entitlement": frozenset({"observed-supported"}),
    "latency-context-cost": frozenset({"observed-supported", "observed-limited"}),
}


class EvaluationVerificationError(ValueError):
    """The evidence workspace cannot truthfully produce a final bundle."""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Bounded successful verification summary."""

    evaluation_id: str
    case_count: int
    evidence_count: int
    reviewed: bool
    approved_for_promotion: bool


@dataclass(frozen=True, slots=True)
class FinalizedBundle:
    """Paths and digests frozen by one successful finalization."""

    manifest_path: Path
    bundle_path: Path
    receipt_path: Path
    manifest_sha256: str
    bundle_sha256: str


def verify_evaluation_manifest(
    manifest: Mapping[str, Any],
    *,
    workspace: Path,
    repo_root: Path,
    require_review: bool = True,
    validate_schema: bool = True,
) -> VerificationReport:
    """Verify schema, frozen sources, attempts, evidence, review, and validity."""

    profile = load_evaluation_profile(repo_root)
    cases = load_evaluation_cases(repo_root, profile=profile)
    schema = _load_schema(repo_root, profile)
    if validate_schema:
        _validate_schema_value(schema, manifest)

    evaluation_id = _required_string(manifest, "evaluation_id")
    manifest_profile = _required_mapping(manifest, "profile")
    if manifest_profile.get("profile_id") != profile.profile_id:
        raise EvaluationVerificationError("manifest profile_id does not match frozen profile")
    if manifest_profile.get("evaluation_profile_sha256") != profile.sha256:
        raise EvaluationVerificationError("evaluation profile digest does not match")
    if manifest_profile.get("evaluation_cases_sha256") != profile.case_manifest.sha256:
        raise EvaluationVerificationError("evaluation cases digest does not match")
    if require_review:
        _reject_pending_profile_values(manifest_profile)

    case_manifest = _required_mapping(manifest, "case_manifest")
    if case_manifest != {
        "path": profile.case_manifest.path.as_posix(),
        "version": profile.case_manifest.version,
        "sha256": profile.case_manifest.sha256,
    }:
        raise EvaluationVerificationError("case_manifest identity does not match frozen source")

    review = _required_mapping(manifest, "review")
    reviewed = _review_is_complete(review)
    if require_review and not reviewed:
        raise EvaluationVerificationError("human review is incomplete")
    approved = review.get("approved_for_promotion") is True

    redaction = _required_mapping(manifest, "redaction")
    redaction_complete = all(
        redaction.get(name) is True
        for name in (
            "credentials_removed",
            "cookies_removed",
            "raw_auth_headers_removed",
            "owner_private_data_reviewed",
        )
    )
    if require_review and not redaction_complete:
        raise EvaluationVerificationError("redaction declaration is incomplete")

    evidence_values = _required_mapping_list(manifest, "evidence_files")
    try:
        evidence = validate_evidence_inventory(
            workspace,
            evidence_values,
            binary_human_reviewed=(
                redaction.get("owner_private_data_reviewed") is True
                and review.get("evidence_complete") is True
            ),
        )
    except ValueError as exc:
        raise EvaluationVerificationError(str(exc)) from exc
    evidence_ids = {item.evidence_id for item in evidence}

    results = _required_mapping_list(manifest, "case_results")
    result_ids: set[str] = set()
    result_statuses: dict[str, str] = {}
    axis_cases: dict[str, set[str]] = {}
    for result in results:
        case_id = _required_string(result, "case_id")
        if case_id in result_ids:
            raise EvaluationVerificationError("case_results contains a duplicate case_id")
        result_ids.add(case_id)
        frozen_case = cases.require(case_id)
        if result.get("axis") != frozen_case.axis:
            raise EvaluationVerificationError(f"case axis differs from frozen case: {case_id}")
        if result.get("risk_class") != frozen_case.risk_class:
            raise EvaluationVerificationError(
                f"case risk_class differs from frozen case: {case_id}"
            )
        _verify_case_attempts(result, frozen_case.risk_class, profile, case_id)
        result_statuses[case_id] = _required_string(result, "status")
        if not frozen_case.allows_status(result_statuses[case_id]):
            raise EvaluationVerificationError(
                f"case status is not permitted by its frozen oracle: {case_id}"
            )
        references = result.get("evidence_refs")
        if not isinstance(references, list) or not references:
            raise EvaluationVerificationError(f"case has no evidence references: {case_id}")
        if any(not isinstance(item, str) or item not in evidence_ids for item in references):
            raise EvaluationVerificationError(
                f"case evidence reference does not resolve: {case_id}"
            )
        axis_cases.setdefault(frozen_case.axis, set()).add(case_id)
    if result_ids != set(cases.cases):
        raise EvaluationVerificationError("case_results must cover every frozen case exactly once")

    conclusions = _required_mapping_list(manifest, "conclusions")
    conclusion_axes: set[str] = set()
    conclusion_statuses: dict[str, str] = {}
    for conclusion in conclusions:
        axis = _required_string(conclusion, "axis")
        if axis in conclusion_axes:
            raise EvaluationVerificationError("conclusions contains a duplicate axis")
        conclusion_axes.add(axis)
        status = _required_string(conclusion, "status")
        profile.requires_status(status)
        conclusion_statuses[axis] = status
        conclusion_case_ids = conclusion.get("case_ids")
        if not isinstance(conclusion_case_ids, list) or set(conclusion_case_ids) != axis_cases.get(
            axis, set()
        ):
            raise EvaluationVerificationError(
                f"conclusion does not cover the exact cases for axis: {axis}"
            )
        case_statuses = {result_statuses[case_id] for case_id in conclusion_case_ids}
        if require_review and len(case_statuses) == 1 and status != next(iter(case_statuses)):
            raise EvaluationVerificationError(
                f"single-case conclusion contradicts its case result: {axis}"
            )
    if conclusion_axes != set(axis_cases):
        raise EvaluationVerificationError("conclusions must cover every frozen case axis")

    _verify_validity(_required_mapping(manifest, "validity"), profile)
    if approved and not all(
        review.get(name) is True
        for name in (
            "profile_match_verified",
            "case_manifest_match_verified",
            "evidence_complete",
        )
    ):
        raise EvaluationVerificationError("promotion approval lacks required review attestations")
    if approved:
        for case_id, allowed_statuses in _REQUIRED_LIVE_CASE_STATUSES.items():
            if result_statuses.get(case_id) not in allowed_statuses:
                raise EvaluationVerificationError(
                    f"promotion approval lacks required live evidence: {case_id}"
                )
            case_axis = cases.require(case_id).axis
            if conclusion_statuses.get(case_axis) not in allowed_statuses:
                raise EvaluationVerificationError(
                    f"promotion conclusion lacks required live evidence: {case_axis}"
                )
    return VerificationReport(
        evaluation_id=evaluation_id,
        case_count=len(results),
        evidence_count=len(evidence),
        reviewed=reviewed,
        approved_for_promotion=approved,
    )


def finalize_evaluation(
    workspace: Path,
    *,
    repo_root: Path,
    completed_at: datetime | None = None,
) -> FinalizedBundle:
    """Validate a reviewed workspace, then freeze manifest, archive, and receipt."""

    root = workspace.resolve()
    working_path = root / WORKING_MANIFEST_NAME
    final_path = root / FINAL_MANIFEST_NAME
    bundle_path = root / BUNDLE_NAME
    receipt_path = root / RECEIPT_NAME
    if any(path.exists() for path in (final_path, bundle_path, receipt_path)):
        raise EvaluationVerificationError("workspace already contains finalized output")
    if working_path.is_symlink() or not working_path.is_file():
        raise EvaluationVerificationError("working manifest is missing or unsafe")
    try:
        raw_manifest = json.loads(_read_bounded_regular_file(working_path))
    except (json.JSONDecodeError, OSError, RecursionError, ValueError) as exc:
        raise EvaluationVerificationError("working manifest is not bounded valid JSON") from exc
    if not isinstance(raw_manifest, dict):
        raise EvaluationVerificationError("working manifest must be a JSON object")
    manifest = cast(dict[str, Any], raw_manifest)
    completion = completed_at or datetime.now(UTC)
    if completion.tzinfo is None:
        raise EvaluationVerificationError("completed_at must be timezone-aware")
    probe = _required_mapping(manifest, "probe")
    mutable_probe = dict(probe)
    mutable_probe["completed_at"] = completion.astimezone(UTC).isoformat().replace("+00:00", "Z")
    manifest["probe"] = mutable_probe

    verify_evaluation_manifest(
        manifest,
        workspace=root,
        repo_root=repo_root,
        require_review=True,
        validate_schema=True,
    )
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    evidence = validate_evidence_inventory(
        root,
        _required_mapping_list(manifest, "evidence_files"),
        binary_human_reviewed=True,
    )
    bundle_bytes = build_deterministic_archive(
        manifest_bytes=manifest_bytes,
        workspace=root,
        evidence=evidence,
    )
    manifest_digest = sha256_bytes(manifest_bytes)
    bundle_digest = sha256_bytes(bundle_bytes)
    receipt = {
        "schema_version": "1.1",
        "bundle_sha256": bundle_digest,
        "manifest_sha256": manifest_digest,
        "profile_id": _required_string(_required_mapping(manifest, "profile"), "profile_id"),
        "created_at": mutable_probe["completed_at"],
    }
    profile = load_evaluation_profile(repo_root)
    schema = _load_schema(repo_root, profile)
    _validate_schema_value(schema, receipt, reference="#/$defs/bundleReceipt")
    receipt_bytes = canonical_json_bytes(receipt) + b"\n"

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_write(final_path, manifest_bytes, mode=0o600)
    _atomic_write(bundle_path, bundle_bytes, mode=0o600)
    _atomic_write(receipt_path, receipt_bytes, mode=0o600)
    return FinalizedBundle(
        manifest_path=final_path,
        bundle_path=bundle_path,
        receipt_path=receipt_path,
        manifest_sha256=manifest_digest,
        bundle_sha256=bundle_digest,
    )


def build_deterministic_archive(
    *,
    manifest_bytes: bytes,
    workspace: Path,
    evidence: tuple[EvidenceFile, ...],
) -> bytes:
    """Build a normalized tar+gzip containing manifest and evidence, never receipt."""

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        _add_tar_bytes(archive, FINAL_MANIFEST_NAME, manifest_bytes, mode=0o600)
        for record in sorted(evidence, key=lambda item: item.path):
            relative = PurePosixPath(record.path).relative_to("evidence")
            payload = read_evidence_payload(workspace / "evidence", relative)
            if sha256_bytes(payload) != record.sha256:
                raise EvaluationVerificationError(
                    f"evidence changed while building archive: {record.evidence_id}"
                )
            _add_tar_bytes(archive, record.path, payload, mode=0o600)
    compressed = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=compressed,
        mtime=0,
    ) as output:
        output.write(tar_buffer.getvalue())
    return compressed.getvalue()


def _add_tar_bytes(archive: tarfile.TarFile, name: str, data: bytes, *, mode: int) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, io.BytesIO(data))


def _verify_case_attempts(
    result: Mapping[str, Any],
    risk_class: str,
    profile: FrozenEvaluationProfile,
    case_id: str,
) -> None:
    risk = profile.risk_classes[risk_class]
    required = _required_integer(result, "attempts_required")
    completed = _required_integer(result, "attempts_completed")
    passes = _required_integer(result, "passes")
    failures = _required_integer(result, "failures")
    blocked = _required_integer(result, "blocked")
    if required != risk.minimum_attempts:
        raise EvaluationVerificationError(f"attempt floor differs from frozen profile: {case_id}")
    if completed != passes + failures + blocked:
        raise EvaluationVerificationError(f"attempt totals are inconsistent: {case_id}")
    status = _required_string(result, "status")
    profile.requires_status(status)
    if status in _PROMOTED_STATUSES and completed < required:
        raise EvaluationVerificationError(f"promoted case lacks minimum attempts: {case_id}")
    if status == "observed-supported" and (
        completed == 0 or passes / completed < risk.target_pass_rate
    ):
        raise EvaluationVerificationError(f"passing rate is below frozen target: {case_id}")
    if status == "host-policy-blocked" and blocked < required:
        raise EvaluationVerificationError(f"blocked case lacks repeated evidence: {case_id}")
    if status == "test-failed" and failures == 0:
        raise EvaluationVerificationError(f"failed case has no failed attempt: {case_id}")


def _verify_validity(
    validity: Mapping[str, Any],
    profile: FrozenEvaluationProfile,
) -> None:
    valid_from = _timestamp(validity.get("valid_from"), "valid_from")
    valid_until = _timestamp(validity.get("valid_until"), "valid_until")
    if valid_until <= valid_from:
        raise EvaluationVerificationError("validity interval is not positive")
    if (valid_until - valid_from).total_seconds() > profile.maximum_validity_days * 86_400:
        raise EvaluationVerificationError("validity exceeds frozen maximum_days")
    triggers = validity.get("rerun_triggers")
    if not isinstance(triggers, list) or set(triggers) != set(profile.rerun_triggers):
        raise EvaluationVerificationError("validity rerun_triggers differ from frozen profile")


def _review_is_complete(review: Mapping[str, Any]) -> bool:
    reviewer = review.get("reviewer")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewer, str) or reviewer.casefold() in _PENDING_MARKERS:
        return False
    try:
        _timestamp(reviewed_at, "reviewed_at")
    except EvaluationVerificationError:
        return False
    return isinstance(review.get("approved_for_promotion"), bool)


def _reject_pending_profile_values(profile: Mapping[str, Any]) -> None:
    for name, value in profile.items():
        if isinstance(value, str) and value.casefold() in _PENDING_MARKERS:
            raise EvaluationVerificationError(f"profile field remains pending: {name}")


def _load_schema(repo_root: Path, profile: FrozenEvaluationProfile) -> Mapping[str, Any]:
    path = repo_root.resolve() / profile.manifest_schema
    if path.is_symlink() or not path.is_file():
        raise EvaluationVerificationError("evaluation schema is missing or unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise EvaluationVerificationError("evaluation schema is invalid JSON") from exc
    if not isinstance(value, dict):
        raise EvaluationVerificationError("evaluation schema must be an object")
    return cast(Mapping[str, Any], value)


def _validate_schema_value(
    schema: Mapping[str, Any],
    value: object,
    *,
    reference: str | None = None,
) -> None:
    selected: Mapping[str, Any]
    if reference is None:
        selected = schema
    else:
        selected = {"$ref": reference, "$defs": schema.get("$defs", {})}
    validator = Draft202012Validator(selected, format_checker=FormatChecker())
    if next(validator.iter_errors(value), None) is not None:
        raise EvaluationVerificationError("evaluation value does not satisfy the frozen schema")


def _required_mapping(values: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = values.get(name)
    if not isinstance(value, Mapping):
        raise EvaluationVerificationError(f"{name} must be an object")
    return cast(Mapping[str, Any], value)


def _required_mapping_list(
    values: Mapping[str, Any],
    name: str,
) -> list[Mapping[str, Any]]:
    value = values.get(name)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise EvaluationVerificationError(f"{name} must be a non-empty object array")
    return cast(list[Mapping[str, Any]], value)


def _required_string(values: Mapping[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise EvaluationVerificationError(f"{name} must be a non-empty string")
    return value


def _required_integer(values: Mapping[str, Any], name: str) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationVerificationError(f"{name} must be a non-negative integer")
    return value


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationVerificationError(f"{name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationVerificationError(f"{name} must be a timestamp") from exc
    if parsed.tzinfo is None:
        raise EvaluationVerificationError(f"{name} must include a timezone")
    return parsed


def _atomic_write(path: Path, data: bytes, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise EvaluationVerificationError("finalized output appeared concurrently") from exc
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read_bounded_regular_file(path: Path) -> bytes:
    """Read the exact checked inode while enforcing the manifest size bound."""

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
            or not 0 <= metadata.st_size <= _MAX_MANIFEST_BYTES
        ):
            raise EvaluationVerificationError("working manifest is missing, unsafe, or unbounded")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            data = source.read(_MAX_MANIFEST_BYTES + 1)
        if len(data) > _MAX_MANIFEST_BYTES:
            raise EvaluationVerificationError("working manifest is unbounded")
        return data
    except OSError as exc:
        raise EvaluationVerificationError("working manifest is missing or unsafe") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


__all__ = [
    "BUNDLE_NAME",
    "FINAL_MANIFEST_NAME",
    "RECEIPT_NAME",
    "WORKING_MANIFEST_NAME",
    "EvaluationVerificationError",
    "FinalizedBundle",
    "VerificationReport",
    "build_deterministic_archive",
    "finalize_evaluation",
    "verify_evaluation_manifest",
]

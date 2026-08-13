"""Bounded GitHub Actions checkout identity used by Phase 10 integration evidence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_COLLECTOR_FILE_BYTES = 1_048_576
CI_ATTESTATION_COLLECTOR_PATHS = (
    "scripts/ci_checkout_attestation.py",
    "src/binnacle/__init__.py",
    "src/binnacle/evaluation/__init__.py",
    "src/binnacle/evaluation/ci_attestation.py",
    "src/binnacle/evaluation/digests.py",
)


class CiAttestationError(ValueError):
    """The event/environment/checkout tuple cannot be attested safely."""


@dataclass(frozen=True, slots=True)
class GitCheckoutIdentity:
    """Exact object identity read independently from the checked-out repository."""

    oid: str
    tree_oid: str
    parent_oids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_oid(self.oid, "checkout commit")
        _require_oid(self.tree_oid, "checkout tree")
        if len(self.parent_oids) > 64:
            raise CiAttestationError("checkout has too many parents")
        for parent in self.parent_oids:
            _require_oid(parent, "checkout parent")


def build_ci_checkout_attestation(
    *,
    event: Mapping[str, Any],
    environment: Mapping[str, str],
    checkout: GitCheckoutIdentity,
    collector_commit_oid: str,
    collector_sha256: str,
    job_name: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Correlate event identities with actual Git checkout facts without inference."""

    repository = _required_environment(environment, "GITHUB_REPOSITORY", maximum=256)
    event_name = _required_environment(environment, "GITHUB_EVENT_NAME", maximum=64)
    workflow_name = _required_environment(environment, "GITHUB_WORKFLOW", maximum=256)
    github_sha = _required_oid_environment(environment, "GITHUB_SHA")
    run_id = _required_positive_integer(environment, "GITHUB_RUN_ID")
    run_attempt = _required_positive_integer(environment, "GITHUB_RUN_ATTEMPT", maximum=1000)
    collector_commit_oid = _require_oid(collector_commit_oid, "collector commit")
    if _DIGEST_RE.fullmatch(collector_sha256) is None:
        raise CiAttestationError("collector bundle digest is invalid")
    if not job_name or len(job_name.encode("utf-8")) > 256:
        raise CiAttestationError("CI job name is missing or too large")
    event_repository = _required_mapping(event, "repository")
    full_name = event_repository.get("full_name")
    if not isinstance(full_name, str) or full_name != repository:
        raise CiAttestationError("event repository does not match workflow repository")

    candidate_oid: str | None = None
    base_oid: str | None = None
    after_oid: str | None = None
    kind = "unbound"
    if event_name == "pull_request":
        pull_request = _required_mapping(event, "pull_request")
        candidate_oid = _nested_oid(pull_request, "head")
        base_oid = _nested_oid(pull_request, "base")
        if github_sha == checkout.oid and checkout.parent_oids == (base_oid, candidate_oid):
            kind = "pull_request_integration"
    elif event_name == "push":
        after_oid = _required_oid(event, "after")
        if github_sha == checkout.oid == after_oid:
            kind = "push_commit"
    else:
        raise CiAttestationError("workflow event is outside the reviewed CI profile")

    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CiAttestationError("CI attestation timestamp must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    return {
        "schema_version": "1.0",
        "repository": repository,
        "event_name": event_name,
        "workflow_name": workflow_name,
        "job_name": job_name,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "collector_commit_oid": collector_commit_oid,
        "collector_sha256": collector_sha256,
        "event_candidate_oid": candidate_oid,
        "event_base_oid": base_oid,
        "event_after_oid": after_oid,
        "github_sha": github_sha,
        "checkout_oid": checkout.oid,
        "checkout_tree_oid": checkout.tree_oid,
        "checkout_parent_oids": list(checkout.parent_oids),
        "checkout_kind": kind,
        "created_at": timestamp.isoformat().replace("+00:00", "Z"),
    }


def ci_attestation_is_bound(value: Mapping[str, object]) -> bool:
    """Return whether the record proves the reviewed event-to-checkout relationship."""

    return value.get("checkout_kind") in {"pull_request_integration", "push_commit"}


def ci_attestation_collector_sha256(repo_root: Path) -> str:
    """Hash the exact standard-library-only collector bundle with path separation."""

    root = repo_root.resolve()
    records: list[bytes] = []
    for relative in CI_ATTESTATION_COLLECTOR_PATHS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise CiAttestationError(f"collector member is missing or unsafe: {relative}")
        try:
            size = path.stat().st_size
            if not 1 <= size <= _MAX_COLLECTOR_FILE_BYTES:
                raise CiAttestationError(f"collector member is unbounded: {relative}")
            content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise CiAttestationError(f"collector member is unavailable: {relative}") from exc
        records.append(relative.encode("utf-8") + b"\0" + content_sha256.encode("ascii") + b"\n")
    return hashlib.sha256(b"".join(records)).hexdigest()


def _required_environment(
    environment: Mapping[str, str],
    name: str,
    *,
    maximum: int,
) -> str:
    value = environment.get(name)
    if value is None or not value or len(value.encode("utf-8")) > maximum:
        raise CiAttestationError(f"required CI environment identity is invalid: {name}")
    return value


def _required_oid_environment(environment: Mapping[str, str], name: str) -> str:
    value = _required_environment(environment, name, maximum=64)
    return _require_oid(value, name)


def _required_positive_integer(
    environment: Mapping[str, str],
    name: str,
    *,
    maximum: int = 9_223_372_036_854_775_807,
) -> int:
    raw = _required_environment(environment, name, maximum=20)
    if not raw.isascii() or not raw.isdecimal():
        raise CiAttestationError(f"required CI numeric identity is invalid: {name}")
    value = int(raw)
    if not 1 <= value <= maximum:
        raise CiAttestationError(f"required CI numeric identity is invalid: {name}")
    return value


def _required_mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise CiAttestationError(f"event field is missing or invalid: {name}")
    return cast(dict[str, Any], result)


def _nested_oid(value: Mapping[str, Any], name: str) -> str:
    nested = _required_mapping(value, name)
    return _required_oid(nested, "sha")


def _required_oid(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise CiAttestationError(f"event OID is missing or invalid: {name}")
    return _require_oid(result, name)


def _require_oid(value: str, name: str) -> str:
    if _OID_RE.fullmatch(value) is None:
        raise CiAttestationError(f"Git OID is invalid: {name}")
    return value


__all__ = [
    "CI_ATTESTATION_COLLECTOR_PATHS",
    "CiAttestationError",
    "GitCheckoutIdentity",
    "build_ci_checkout_attestation",
    "ci_attestation_collector_sha256",
    "ci_attestation_is_bound",
]

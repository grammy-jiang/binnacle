"""Deterministic digest algorithms for Phase 3 evaluation identities."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact bytes."""

    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular non-symlink file without loading it all into memory."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("digest source must be a regular non-symlink file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(131_072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value with the repository's stable digest encoding."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    """Hash a canonical JSON value."""

    return sha256_bytes(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class DistributionContentDigest:
    """Identity of installed distribution bytes used by the evaluator."""

    distribution_name: str
    distribution_version: str
    algorithm: str
    sha256: str
    file_count: int


def python_distribution_content_digest(name: str) -> DistributionContentDigest:
    """Implement ``python-distribution-content-v1`` for the installed distribution."""

    distribution = importlib.metadata.distribution(name)
    files = distribution.files
    if files is None:
        raise ValueError("installed distribution does not expose a content inventory")
    records: list[bytes] = []
    for package_path in files:
        relative = PurePosixPath(str(package_path))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "__pycache__" in relative.parts
            or relative.suffix in {".pyc", ".pyo"}
        ):
            continue
        installed_path = Path(str(distribution.locate_file(package_path)))
        if installed_path.is_symlink() or not installed_path.is_file():
            raise ValueError("installed distribution inventory member is missing or unsafe")
        record = (
            relative.as_posix().encode("utf-8")
            + b"\0"
            + sha256_file(installed_path).encode("ascii")
            + b"\n"
        )
        records.append(record)
    records.sort()
    if not records:
        raise ValueError("installed distribution has no regular content files")
    return DistributionContentDigest(
        distribution_name=name,
        distribution_version=distribution.version,
        algorithm="python-distribution-content-v1",
        sha256=sha256_bytes(b"".join(records)),
        file_count=len(records),
    )


def policy_bundle_identity(
    *,
    repo_root: Path,
    controller_profile_sha256: str,
    runtime_manifest_sha256: str,
    revision_contract_sha256: str,
) -> tuple[dict[str, Any], str]:
    """Build and hash the conservative Phase 3 policy-bundle projection."""

    root = repo_root.resolve()
    policy_root = root / "spec/policy"
    paths = sorted(
        path
        for path in policy_root.rglob("*")
        if path.suffix in {".json", ".yaml"} and path.is_file()
    )
    if not paths:
        raise ValueError("policy bundle contains no reviewed policy files")
    inventory: list[dict[str, str]] = []
    for path in paths:
        if path.is_symlink():
            raise ValueError("policy bundle may not contain symbolic links")
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    value: dict[str, Any] = {
        "format": "phase3-policy-bundle-v1",
        "spec_policy_files": inventory,
        "controller_profile_sha256": _require_digest(controller_profile_sha256),
        "runtime_manifest_sha256": _require_digest(runtime_manifest_sha256),
        "revision_contract_sha256": _require_digest(revision_contract_sha256),
    }
    return value, canonical_json_sha256(value)


def _require_digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("digest input must be lowercase SHA-256")
    return value


__all__ = [
    "DistributionContentDigest",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "policy_bundle_identity",
    "python_distribution_content_digest",
    "sha256_bytes",
    "sha256_file",
]

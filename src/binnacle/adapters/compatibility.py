"""Compiled compatibility profile and development-build adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import binnacle
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import CompatibilityObservation, CompatibilityProfileSnapshot
from binnacle.domain.runtime import BuildIdentity


def compute_build_identity(*, version: str) -> BuildIdentity:
    """Hash installed package sources and generated registry resources."""

    package_file = binnacle.__file__
    if package_file is None:
        raise RuntimeError("Binnacle package path is unavailable")
    package_root = Path(package_file).resolve().parent
    paths = sorted(package_root.rglob("*.py"))
    paths.extend(
        sorted(
            path
            for path in (package_root / "_generated").glob("compatibility_*_registry*.json")
            if path.is_file()
        )
    )
    digest = hashlib.sha256()
    for path in sorted(
        set(paths),
        key=lambda candidate: candidate.relative_to(package_root).as_posix(),
    ):
        relative_path = path.relative_to(package_root).as_posix()
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
    return BuildIdentity(version=version, build_sha256=digest.hexdigest())


class CompiledCompatibilityProfileReader:
    """Read only the no-live-evidence baseline compiled into the registry."""

    def __init__(self, registry: ContractRegistry) -> None:
        self._registry = registry

    def read(self) -> CompatibilityProfileSnapshot:
        baseline = self._registry.compatibility_baseline
        raw_observations = baseline.get("observations")
        if not isinstance(raw_observations, (list, tuple)):
            raise RuntimeError("compiled compatibility observations are invalid")
        observations = tuple(self._observation(value) for value in raw_observations)
        limitations = baseline.get("limitations")
        if not isinstance(limitations, (list, tuple)) or not all(
            isinstance(value, str) for value in limitations
        ):
            raise RuntimeError("compiled compatibility limitations are invalid")
        return CompatibilityProfileSnapshot(
            profile_version=_string(baseline, "profile_version"),
            observed_protocol_revision=_optional_string(baseline, "observed_protocol_revision"),
            observations=observations,
            evidence_bundle_sha256=_optional_string(baseline, "evidence_bundle_sha256"),
            limitations=tuple(limitations),
        )

    @staticmethod
    def _observation(value: object) -> CompatibilityObservation:
        if not isinstance(value, Mapping):
            raise RuntimeError("compiled compatibility observation is invalid")
        return CompatibilityObservation(
            axis=_string(value, "axis"),
            status=_string(value, "status"),
            summary=_string(value, "summary"),
        )


def _string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"compiled compatibility {key} is invalid")
    return value


def _optional_string(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if value is not None and not isinstance(value, str):
        raise RuntimeError(f"compiled compatibility {key} is invalid")
    return value

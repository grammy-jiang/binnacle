"""Tests for compiled compatibility and deterministic build adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import binnacle
from binnacle.adapters.compatibility import (
    CompiledCompatibilityProfileReader,
    compute_build_identity,
)
from binnacle.contracts import ContractRegistry


@dataclass
class _FakeRegistry:
    compatibility_baseline: Mapping[str, object]


def _reader(baseline: Mapping[str, object]) -> CompiledCompatibilityProfileReader:
    return CompiledCompatibilityProfileReader(
        cast(ContractRegistry, _FakeRegistry(compatibility_baseline=baseline))
    )


def _expected_build_digest(package_root: Path) -> str:
    paths = sorted(package_root.rglob("*.py"))
    paths.extend(sorted((package_root / "_generated").glob("compatibility_core_registry*.json")))
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(package_root).as_posix()):
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
    return digest.hexdigest()


def test_build_identity_hashes_only_reviewed_package_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "binnacle"
    generated = package_root / "_generated"
    generated.mkdir(parents=True)
    package_file = package_root / "__init__.py"
    package_file.write_text("VERSION = 1\n", encoding="utf-8")
    source = package_root / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    (generated / "compatibility_core_registry.json").write_text("{}\n", encoding="utf-8")
    (generated / "compatibility_core_registry.digest.json").write_text("{}\n", encoding="utf-8")
    ignored = package_root / "notes.txt"
    ignored.write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(binnacle, "__file__", str(package_file))

    first = compute_build_identity(version="fixture")
    ignored.write_text("changed but ignored", encoding="utf-8")
    second = compute_build_identity(version="fixture")
    source.write_text("VALUE = 2\n", encoding="utf-8")
    changed = compute_build_identity(version="fixture")

    assert first.version == "fixture"
    assert first.build_sha256 == second.build_sha256
    assert first.build_sha256 != changed.build_sha256
    assert changed.build_sha256 == _expected_build_digest(package_root)


def test_build_identity_requires_package_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binnacle, "__file__", None)

    with pytest.raises(RuntimeError, match="package path"):
        compute_build_identity(version="fixture")


def test_compiled_profile_contains_no_fabricated_host_evidence(
    contract_registry: ContractRegistry,
) -> None:
    profile = CompiledCompatibilityProfileReader(contract_registry).read()

    assert profile.profile_version == contract_registry.evaluation_profile_version
    assert profile.observed_protocol_revision is None
    assert profile.evidence_bundle_sha256 is None
    assert profile.observations
    assert not {
        "observed-supported",
        "observed-limited",
    }.intersection(observation.status for observation in profile.observations)


def test_compiled_profile_parses_complete_snapshot() -> None:
    profile = _reader(
        {
            "profile_version": "1.1.0",
            "observed_protocol_revision": "2026-07-28",
            "observations": [
                {"axis": "protocol_revision", "status": "not-tested", "summary": "None."}
            ],
            "evidence_bundle_sha256": "a" * 64,
            "limitations": ["Fixture limitation."],
        }
    ).read()

    assert profile.observed_protocol_revision == "2026-07-28"
    assert profile.evidence_bundle_sha256 == "a" * 64
    assert profile.observations[0].axis == "protocol_revision"


@pytest.mark.parametrize(
    ("baseline", "message"),
    [
        ({"observations": None}, "observations"),
        (
            {
                "observations": [1],
                "limitations": [],
                "profile_version": "1",
                "observed_protocol_revision": None,
                "evidence_bundle_sha256": None,
            },
            "observation",
        ),
        (
            {
                "observations": [{"status": "not-tested", "summary": "none"}],
                "limitations": [],
                "profile_version": "1",
                "observed_protocol_revision": None,
                "evidence_bundle_sha256": None,
            },
            "axis",
        ),
        (
            {
                "observations": [],
                "limitations": "not-an-array",
                "profile_version": "1",
                "observed_protocol_revision": None,
                "evidence_bundle_sha256": None,
            },
            "limitations",
        ),
        (
            {
                "observations": [],
                "limitations": [],
                "profile_version": 1,
                "observed_protocol_revision": None,
                "evidence_bundle_sha256": None,
            },
            "profile_version",
        ),
        (
            {
                "observations": [],
                "limitations": [],
                "profile_version": "1",
                "observed_protocol_revision": 1,
                "evidence_bundle_sha256": None,
            },
            "observed_protocol_revision",
        ),
    ],
)
def test_invalid_compiled_profile_is_rejected(
    baseline: Mapping[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _reader(baseline).read()

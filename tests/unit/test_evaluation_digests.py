"""Reproducible evaluation digest tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.evaluation.digests import (
    canonical_json_bytes,
    canonical_json_sha256,
    policy_bundle_identity,
    python_distribution_content_digest,
    sha256_file,
)


def test_canonical_json_digest_is_key_order_independent() -> None:
    first = {"b": [2, 1], "a": {"value": True}}
    second = {"a": {"value": True}, "b": [2, 1]}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_sha256(first) == canonical_json_sha256(second)
    with pytest.raises(ValueError):
        canonical_json_bytes({"invalid": float("nan")})


def test_policy_bundle_inventory_is_sorted_and_reproducible(repo_root: Path) -> None:
    digest = "a" * 64
    first, first_digest = policy_bundle_identity(
        repo_root=repo_root,
        controller_profile_sha256=digest,
        runtime_manifest_sha256="b" * 64,
        revision_contract_sha256="c" * 64,
    )
    second, second_digest = policy_bundle_identity(
        repo_root=repo_root,
        controller_profile_sha256=digest,
        runtime_manifest_sha256="b" * 64,
        revision_contract_sha256="c" * 64,
    )

    paths = [item["path"] for item in first["spec_policy_files"]]
    assert paths == sorted(paths)
    assert first == second
    assert first_digest == second_digest
    assert len(first_digest) == 64


def test_installed_mcp_distribution_digest_is_stable() -> None:
    first = python_distribution_content_digest("mcp")
    second = python_distribution_content_digest("mcp")

    assert first == second
    assert first.algorithm == "python-distribution-content-v1"
    assert first.file_count > 0
    assert len(first.sha256) == 64


def test_file_digest_rejects_symbolic_link(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"value")
    link = tmp_path / "link"
    link.symlink_to(source)

    with pytest.raises(ValueError, match="non-symlink"):
        sha256_file(link)

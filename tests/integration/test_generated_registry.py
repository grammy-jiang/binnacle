"""Integration tests for deterministic compatibility-core registry generation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from scripts import compile_mcp_registry as compiler

from binnacle.contracts import (
    EXPECTED_REVISIONS,
    EXPECTED_TOOL_NAMES,
    EXPECTED_WRITE_PROBE_TOOL_NAMES,
    ContractRegistry,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_compiler_output_is_deterministic_and_checked_in() -> None:
    first_registry, first_digest = compiler.compile_registry()
    second_registry, second_digest = compiler.compile_registry()

    assert first_registry == second_registry
    assert first_digest == second_digest
    assert first_registry == compiler.REGISTRY_PATH.read_bytes()
    assert first_digest == compiler.DIGEST_PATH.read_bytes()
    assert compiler._write_or_check(check=True) == 0


def test_write_probe_projection_is_deterministic_exact_and_checked_in() -> None:
    registry_path, digest_path, _format, expected_count = compiler.PROJECTIONS[
        "compatibility-write-probe"
    ]
    first_registry, first_digest = compiler.compile_registry("compatibility-write-probe")
    second_registry, second_digest = compiler.compile_registry("compatibility-write-probe")
    registry = json.loads(first_registry)

    assert first_registry == second_registry == registry_path.read_bytes()
    assert first_digest == second_digest == digest_path.read_bytes()
    assert expected_count == 8
    assert tuple(tool["name"] for tool in registry["tools"]) == EXPECTED_WRITE_PROBE_TOOL_NAMES
    assert ContractRegistry.load_phase("compatibility-write-probe").catalogue_phase == (
        "compatibility-write-probe"
    )


def test_check_detects_missing_and_drifted_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "registry.json"
    digest_path = tmp_path / "digest.json"
    monkeypatch.setattr(compiler, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(compiler, "DIGEST_PATH", digest_path)

    assert compiler._write_or_check(check=True) == 1
    assert compiler._write_or_check(check=False) == 0
    assert compiler._write_or_check(check=True) == 0
    registry_path.write_text("{}\n", encoding="utf-8")
    assert compiler._write_or_check(check=True) == 1


def test_source_manifest_projects_exact_metadata_and_schemas() -> None:
    manifest = _load_yaml(ROOT / "spec/mcp/bootstrap-tool-manifest.yaml")
    generated = json.loads(compiler.REGISTRY_PATH.read_text(encoding="utf-8"))
    selected = [tool for tool in manifest["tools"] if "compatibility-core" in tool["phases"]]

    assert tuple(tool["name"] for tool in selected) == EXPECTED_TOOL_NAMES
    assert tuple(tool["name"] for tool in generated["tools"]) == EXPECTED_TOOL_NAMES
    for source, projected in zip(selected, generated["tools"], strict=True):
        for field in (
            "name",
            "title",
            "description",
            "contract_version",
            "handler_binding",
            "information_class",
            "confirmation_class",
            "annotations",
        ):
            assert projected[field] == source[field]
        for schema_key in ("input_schema", "output_schema"):
            assert projected[schema_key]["source_ref"] == source[f"{schema_key}_ref"]
            canonical = compiler._canonical_bytes(projected[schema_key]["schema"])
            assert (
                projected[schema_key]["definition_sha256"] == hashlib.sha256(canonical).hexdigest()
            )


def test_schema_definition_digest_changes_with_semantics() -> None:
    generated = json.loads(compiler.REGISTRY_PATH.read_text(encoding="utf-8"))
    schema = generated["tools"][0]["input_schema"]["schema"]
    changed = copy.deepcopy(schema)
    changed["description"] = "semantic change"

    assert compiler._sha256_bytes(compiler._canonical_bytes(schema)) != compiler._sha256_bytes(
        compiler._canonical_bytes(changed)
    )


def test_compiler_rejects_schema_paths_outside_reviewed_allowlist() -> None:
    resolver = compiler.SchemaResolver()

    with pytest.raises(ValueError, match="reviewed allowlist"):
        resolver.from_manifest_ref("pyproject.toml#")


def test_detached_digest_is_not_self_referential() -> None:
    registry_bytes = compiler.REGISTRY_PATH.read_bytes()
    digest = json.loads(compiler.DIGEST_PATH.read_text(encoding="utf-8"))

    assert "detached_digest_sha256" not in digest
    assert digest["registry_sha256"] == hashlib.sha256(registry_bytes).hexdigest()
    assert digest["compiler_format"] == compiler.REGISTRY_FORMAT


def test_revision_machine_contract_is_exact_and_schema_valid() -> None:
    revision = _load_yaml(ROOT / "spec/mcp/revision-support.yaml")
    schema = json.loads(
        (ROOT / "schemas/mcp/revision-support.schema.json").read_text(encoding="utf-8")
    )
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    assert not list(Draft202012Validator(schema).iter_errors(revision))
    assert tuple(item["revision"] for item in revision["revisions"]) == EXPECTED_REVISIONS
    assert revision["target_revision"] == EXPECTED_REVISIONS[0]


def test_runtime_registry_imports_every_visible_binding() -> None:
    registry = ContractRegistry.load()

    assert tuple(registry.tools) == EXPECTED_TOOL_NAMES
    assert all("probe_workspace" not in tool.handler_binding for tool in registry.tools.values())

"""Canonical Phase 9 contract, schema, evaluation, and promotion-boundary tests."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from scripts import compile_mcp_registry as compiler

from binnacle.contracts import ContractRegistry
from binnacle.privileged_tools import PrivilegedToolNotPromoted

PHASE9_CLASSES = {
    "privileged_prepare": ("normal-result", "HC0"),
    "package_inspect": ("normal-result", "HC0"),
    "package_install": ("restricted-result", "HC2"),
    "binnacle_service_inspect": ("normal-result", "HC0"),
    "binnacle_service_restart": ("restricted-result", "HC2"),
    "restart_preflight": ("normal-result", "HC0"),
    "binnacle_restart": ("restricted-result", "HC2"),
    "binnacle_runtime_inspect": ("normal-result", "HC0"),
}


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_bytes())
    assert isinstance(value, dict)
    return value


def test_phase9_manifest_contracts_are_exact_but_not_runtime_promoted(repo_root: Path) -> None:
    manifest = _yaml(repo_root / "spec/mcp/bootstrap-tool-manifest.yaml")
    operations = _yaml(repo_root / "spec/operation/privileged-operations.yaml")
    host = _yaml(repo_root / "spec/policy/host-confirmation-classes.yaml")
    profiles = _yaml(repo_root / "spec/policy/privileged-profiles.yaml")
    tools = {tool["name"]: tool for tool in manifest["tools"]}

    assert manifest["manifest_version"] == "1.2.0"
    assert tuple(tools)[-8:] == tuple(PHASE9_CLASSES)
    assert set(operations["tools"]) == set(PHASE9_CLASSES)
    assert operations["runtime_promotion"] == "disabled"
    assert profiles["runtime_promotion"] == "disabled"
    assert profiles["promotion_gates"]["v1_operational_catalogue_enabled"] is False
    assert "host_reboot" not in tools
    assert "host_reboot" not in operations["tools"]

    for name, (information_class, confirmation_class) in PHASE9_CLASSES.items():
        tool = tools[name]
        operation = operations["tools"][name]
        assert tool["contract_version"] == "1.0"
        assert tool["phases"] == ["v1-operational"]
        assert tool["information_class"] == information_class
        assert tool["confirmation_class"] == confirmation_class
        assert operation["information_class"] == information_class
        assert operation["confirmation_class"] == confirmation_class
        assert host["initial_tool_classification"][name] == confirmation_class

    assert not set(ContractRegistry.load().tools).intersection(PHASE9_CLASSES)
    assert not set(ContractRegistry.load_phase("compatibility-write-probe").tools).intersection(
        PHASE9_CLASSES
    )


def test_every_phase9_schema_ref_resolves_and_is_draft_2020_12(repo_root: Path) -> None:
    manifest = _yaml(repo_root / "spec/mcp/bootstrap-tool-manifest.yaml")
    resolver = compiler.SchemaResolver()
    tools = {tool["name"]: tool for tool in manifest["tools"]}

    for name in PHASE9_CLASSES:
        for field in ("input_schema_ref", "output_schema_ref"):
            schema, digest = resolver.from_manifest_ref(tools[name][field])
            Draft202012Validator.check_schema(schema)
            assert len(digest) == 64


@pytest.mark.anyio
async def test_unpromoted_phase9_bindings_import_and_fail_closed(repo_root: Path) -> None:
    manifest = _yaml(repo_root / "spec/mcp/bootstrap-tool-manifest.yaml")
    tools = {tool["name"]: tool for tool in manifest["tools"]}

    for name in PHASE9_CLASSES:
        module_name, _, attribute_name = tools[name]["handler_binding"].rpartition(".")
        handler = getattr(importlib.import_module(module_name), attribute_name)
        assert inspect.iscoroutinefunction(handler)
        with pytest.raises(PrivilegedToolNotPromoted, match="not promoted"):
            await handler()


def test_phase9_evaluation_cases_use_the_frozen_attempt_floor_classes(repo_root: Path) -> None:
    profile = _yaml(repo_root / "spec/mcp/evaluation-profile.yaml")
    cases = _yaml(repo_root / "spec/mcp/evaluation-cases.yaml")
    categories = profile["phase9_privileged_self_management"]["category_risk_classes"]
    by_id = {case["case_id"]: case for case in cases["cases"]}

    assert cases["case_manifest_version"] == "1.3.0"
    assert len(by_id) == 63
    assert categories == {
        "selection_rendering": {
            "risk_class": "tool_selection_and_result_rendering",
            "minimum_attempts": 10,
        },
        "confirmation_entitlement": {
            "risk_class": "confirmation_and_entitlement",
            "minimum_attempts": 5,
        },
        "execute_retry_cancel": {
            "risk_class": "write_cancellation_retry_cache_confirmation",
            "minimum_attempts": 20,
        },
        "concurrency_race_reconnect": {
            "risk_class": "concurrency_race_reconnect_instability",
            "minimum_attempts": 20,
        },
    }
    assert by_id["phase9-privileged-prepared-view"]["risk_class"] == (
        "tool_selection_and_result_rendering"
    )
    assert by_id["phase9-hc2-confirm-allow"]["risk_class"] == ("confirmation_and_entitlement")
    assert by_id["phase9-package-install-exact-plan"]["risk_class"] == (
        "write_cancellation_retry_cache_confirmation"
    )
    assert by_id["phase9-broker-restart-accepted-resume"]["risk_class"] == (
        "concurrency_race_reconnect_instability"
    )


def test_generated_compatibility_registries_bind_the_advanced_source_only() -> None:
    for phase in compiler.PROJECTIONS:
        registry_bytes, _digest_bytes = compiler.compile_registry(phase)
        registry = json.loads(registry_bytes)
        assert registry["source_manifest"]["version"] == "1.2.0"
        assert registry["evaluation_profile_version"] == "1.3.0"
        assert not {tool["name"] for tool in registry["tools"]}.intersection(PHASE9_CLASSES)
        assert not any(
            observation["axis"].startswith("phase9_")
            for observation in registry["compatibility_baseline"]["observations"]
        )

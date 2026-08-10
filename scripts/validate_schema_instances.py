#!/usr/bin/env python3
"""Validate representative positive and negative instances against Binnacle schemas."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    registry = Registry()
    for path in sorted((ROOT / "schemas").rglob("*.json")):
        document = load_json(path)
        schema_id = document.get("$id")
        if schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(document))
    return registry


REGISTRY = build_registry()


def errors_for(ref: str, instance: Any) -> list[str]:
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": ref,
    }
    validator = Draft202012Validator(wrapper, registry=REGISTRY)
    return [error.message for error in validator.iter_errors(instance)]


def expect_valid(name: str, ref: str, instance: Any) -> None:
    errors = errors_for(ref, instance)
    if errors:
        ERRORS.append(f"{name}: expected valid; got {errors}")


def expect_invalid(name: str, ref: str, instance: Any) -> None:
    if not errors_for(ref, instance):
        ERRORS.append(f"{name}: expected invalid but validation passed")


def success(tool: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "call_status": "succeeded",
        "tool": {"name": tool, "contract_version": "1.1"},
        "request_id": f"request-{tool}",
        "data": data,
        "operation": None,
        "evidence": [],
        "warnings": [],
    }


def validate_numeric_facts() -> None:
    expect_valid(
        "common integer bounded fact",
        "https://binnacle.dev/schemas/mcp/binnacle-common.schema.json#/$defs/boundedValue",
        8,
    )
    expect_valid(
        "common floating bounded fact",
        "https://binnacle.dev/schemas/mcp/binnacle-common.schema.json#/$defs/boundedValue",
        1.5,
    )
    expect_valid(
        "audit integer safe fact",
        "https://binnacle.dev/schemas/audit/audit-event.schema.json#/$defs/safeFact",
        {"name": "tool_count", "value": 8, "classification": "normal-result"},
    )


def validate_idempotency_keys() -> None:
    ref = "https://binnacle.dev/schemas/mcp/bootstrap-inputs.schema.json#/$defs/idempotencyKey"
    expect_valid("128-bit lowercase hex key", ref, "00112233445566778899aabbccddeeff")
    expect_valid("128-bit base64url key", ref, "ABCDEFGHIJKLMNOPQRSTUV")
    expect_valid("base64url punctuation key", ref, "ABCDE_FGHIJKLMNOPQRST-")
    expect_invalid("short base64url key", ref, "short-key")

    write_ref = (
        "https://binnacle.dev/schemas/mcp/bootstrap-inputs.schema.json"
        "#/$defs/probe_workspace_write.input.v1_1"
    )
    expect_valid(
        "write accepts base64url idempotency key",
        write_ref,
        {
            "prepared_operation_id": "prep-1",
            "execution_nonce": "ZYXWVUTSRQPONMLKJIHGFE",
            "idempotency_key": "ABCDEFGHIJKLMNOPQRSTUV",
            "relative_path": "test.txt",
            "text": "test",
            "overwrite": False,
        },
    )


def validate_system_inspect_sections() -> None:
    ref = (
        "https://binnacle.dev/schemas/mcp/bootstrap-outputs.schema.json"
        "#/$defs/system_inspect.output.v1_1"
    )
    expect_valid(
        "system_inspect selected kernel section",
        ref,
        success(
            "system_inspect",
            {
                "hostname": "pi-a",
                "returned_sections": ["kernel"],
                "sections": {"kernel": "6.12.0-rpi"},
            },
        ),
    )
    expect_valid(
        "system_inspect selected memory section",
        ref,
        success(
            "system_inspect",
            {
                "hostname": "pi-a",
                "returned_sections": ["memory"],
                "sections": {
                    "memory": {"total_bytes": 8589934592, "available_bytes": 4294967296}
                },
            },
        ),
    )
    expect_valid(
        "system_inspect selected filesystems section",
        ref,
        success(
            "system_inspect",
            {
                "hostname": "pi-a",
                "returned_sections": ["filesystems"],
                "sections": {
                    "filesystems": [
                        {
                            "mount_point": "/",
                            "filesystem_type": "ext4",
                            "source": "/dev/mmcblk0p2",
                            "total_bytes": 67108864,
                            "available_bytes": 33554432,
                        }
                    ]
                },
            },
        ),
    )
    expect_invalid(
        "system_inspect cannot claim a returned section without data",
        ref,
        success(
            "system_inspect",
            {"hostname": "pi-a", "returned_sections": ["filesystems"], "sections": {}},
        ),
    )


def validate_cleanup_outcomes() -> None:
    ref = (
        "https://binnacle.dev/schemas/mcp/bootstrap-outputs.schema.json"
        "#/$defs/probe_workspace_cleanup.output.v1_1"
    )
    base = {
        "relative_path": "test.txt",
        "artifact_id": "artifact-1",
        "content_sha256": "a" * 64,
    }
    expect_valid(
        "cleanup removed",
        ref,
        success("probe_workspace_cleanup", {**base, "removed": True, "already_missing": False}),
    )
    expect_valid(
        "cleanup already missing",
        ref,
        success("probe_workspace_cleanup", {**base, "removed": False, "already_missing": True}),
    )
    expect_invalid(
        "cleanup cannot be both removed and missing",
        ref,
        success("probe_workspace_cleanup", {**base, "removed": True, "already_missing": True}),
    )
    expect_invalid(
        "cleanup cannot be neither removed nor missing",
        ref,
        success("probe_workspace_cleanup", {**base, "removed": False, "already_missing": False}),
    )


def validate_wire_error_fixture() -> None:
    fixture_path = ROOT / "tests/fixtures/mcp/mcp-2026-wire.yaml"
    fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    case = next(case for case in fixture["cases"] if case["id"] == "execution-error-valid")
    structured = case["wire_result"]["structuredContent"]
    ref = (
        "https://binnacle.dev/schemas/mcp/bootstrap-outputs.schema.json"
        "#/$defs/probe_workspace_write.output.v1_1"
    )
    expect_valid("positive execution-error fixture", ref, structured)

    success_case = next(case for case in fixture["cases"] if case["id"] == "tool-call-success-valid")
    expect_valid(
        "positive Tool success fixture",
        "https://binnacle.dev/schemas/mcp/bootstrap-outputs.schema.json#/$defs/binnacle_probe.output.v1_1",
        success_case["wire_result"]["structuredContent"],
    )


def validate_uncertain_retry() -> None:
    ref = (
        "https://binnacle.dev/schemas/mcp/binnacle-common.schema.json"
        "#/$defs/operationSnapshot"
    )
    error = {
        "code": "uncertain_outcome",
        "message": "Effect could not be verified.",
        "retryable": False,
        "retry_action": "reconcile",
        "operation_id": "op-1",
        "details": [],
    }
    expect_valid(
        "uncertain retained operation is non-retryable",
        ref,
        {
            "operation_id": "op-1",
            "state": "uncertain",
            "terminality": "effect_terminal_reconcilable",
            "state_version": 2,
            "effect_knowledge": "uncertain",
            "progress": {"known": False, "millionths": None, "unit": None},
            "automatic_retry_allowed": False,
            "error": error,
        },
    )
    expect_invalid(
        "uncertain retained operation cannot auto-retry",
        ref,
        {
            "operation_id": "op-1",
            "state": "uncertain",
            "terminality": "effect_terminal_reconcilable",
            "state_version": 2,
            "effect_knowledge": "uncertain",
            "progress": {"known": False, "millionths": None, "unit": None},
            "automatic_retry_allowed": True,
            "error": error,
        },
    )


def main() -> int:
    validate_numeric_facts()
    validate_idempotency_keys()
    validate_system_inspect_sections()
    validate_cleanup_outcomes()
    validate_wire_error_fixture()
    validate_uncertain_retry()

    if ERRORS:
        print("Representative schema validation failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Representative schema validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

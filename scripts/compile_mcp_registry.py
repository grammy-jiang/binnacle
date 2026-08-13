#!/usr/bin/env python3
"""Compile the reviewed compatibility MCP projections deterministically."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "src/binnacle/_generated"
COMPILER_VERSION = "1.0.0"
PROJECTIONS = {
    "compatibility-core": (
        OUTPUT_DIR / "compatibility_core_registry.json",
        OUTPUT_DIR / "compatibility_core_registry.digest.json",
        "binnacle-compatibility-core-v1",
        5,
    ),
    "compatibility-write-probe": (
        OUTPUT_DIR / "compatibility_write_probe_registry.json",
        OUTPUT_DIR / "compatibility_write_probe_registry.digest.json",
        "binnacle-compatibility-write-probe-v1",
        8,
    ),
}
# Backward-compatible names identify the default core projection.
REGISTRY_PATH = PROJECTIONS["compatibility-core"][0]
DIGEST_PATH = PROJECTIONS["compatibility-core"][1]
REGISTRY_FORMAT = PROJECTIONS["compatibility-core"][2]

MANIFEST_PATH = ROOT / "spec/mcp/bootstrap-tool-manifest.yaml"
REVISION_PATH = ROOT / "spec/mcp/revision-support.yaml"
EVALUATION_PROFILE_PATH = ROOT / "spec/mcp/evaluation-profile.yaml"
EVALUATION_CASES_PATH = ROOT / "spec/mcp/evaluation-cases.yaml"
SCHEMA_PATHS = (
    ROOT / "schemas/mcp/binnacle-common.schema.json",
    ROOT / "schemas/mcp/bootstrap-inputs.schema.json",
    ROOT / "schemas/mcp/bootstrap-outputs.schema.json",
)

SERVER_NOT_IMPLEMENTED_AXES = {
    "write_discovery_and_metadata",
    "write_entitlement",
    "host_confirmation",
    "retry_safety",
    "cancellation",
    "reconnect",
    "write_reconnect",
    "concurrency",
    "probe_workspace_integrity",
}
NOT_APPLICABLE_AXES = {
    "resources",
    "mrtr_elicitation",
    "tasks",
    "information_boundary",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _normalize(child)
            for key, child in value.items()
        }
    return value


def _canonical_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    return (json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pointer_get(document: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return document
    current = document
    for raw_token in pointer.lstrip("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


class SchemaResolver:
    """Resolve repository schema references into standalone schema objects."""

    def __init__(self) -> None:
        self._allowed_paths = frozenset(path.resolve() for path in SCHEMA_PATHS)
        self._documents = {path.resolve(): _load_json(path) for path in SCHEMA_PATHS}

    @property
    def documents(self) -> dict[Path, dict[str, Any]]:
        return self._documents

    def from_manifest_ref(self, reference: str) -> tuple[dict[str, Any], str]:
        path_part, separator, fragment = reference.partition("#")
        if not separator:
            fragment = ""
        path = (ROOT / path_part).resolve()
        self._require_allowed_path(path, reference)
        document = self._documents.setdefault(path, _load_json(path))
        selected = copy.deepcopy(_pointer_get(document, fragment))
        resolved = self._resolve(selected, path, stack=())
        if not isinstance(resolved, dict):
            raise ValueError(f"schema reference {reference} did not resolve to an object")
        return resolved, _sha256_bytes(_canonical_bytes(resolved))

    def _resolve(self, value: Any, current_path: Path, *, stack: tuple[str, ...]) -> Any:
        if isinstance(value, list):
            return [self._resolve(item, current_path, stack=stack) for item in value]
        if not isinstance(value, dict):
            return value

        reference = value.get("$ref")
        if isinstance(reference, str):
            target_path, fragment = self._target(reference, current_path)
            self._require_allowed_path(target_path, reference)
            cycle_key = f"{target_path}#{fragment}"
            if cycle_key in stack:
                raise ValueError(f"recursive schema reference is not supported: {cycle_key}")
            document = self._documents.setdefault(target_path, _load_json(target_path))
            target = copy.deepcopy(_pointer_get(document, fragment))
            resolved = self._resolve(target, target_path, stack=(*stack, cycle_key))
            if not isinstance(resolved, dict):
                raise ValueError(f"schema reference {reference} did not resolve to an object")
            siblings = {
                key: self._resolve(child, current_path, stack=stack)
                for key, child in value.items()
                if key != "$ref"
            }
            return {**resolved, **siblings}

        return {
            key: self._resolve(child, current_path, stack=stack) for key, child in value.items()
        }

    def _require_allowed_path(self, path: Path, reference: str) -> None:
        if path.resolve() not in self._allowed_paths:
            raise ValueError(f"schema reference is outside the reviewed allowlist: {reference}")

    @staticmethod
    def _target(reference: str, current_path: Path) -> tuple[Path, str]:
        if reference.startswith("#"):
            return current_path, reference[1:]
        parsed = urlparse(reference)
        if parsed.scheme in ("http", "https"):
            prefix = "/schemas/"
            if prefix not in parsed.path:
                raise ValueError(f"unsupported external schema reference: {reference}")
            path = ROOT / "schemas" / parsed.path.split(prefix, 1)[1]
            return path.resolve(), parsed.fragment
        path_part, separator, fragment = reference.partition("#")
        path = (current_path.parent / path_part).resolve()
        return path, fragment if separator else ""


def _compatibility_baseline(
    profile: dict[str, Any], cases: dict[str, Any], *, phase: str
) -> dict[str, Any]:
    seen: set[str] = set()
    observations: list[dict[str, str]] = []
    for case in cases.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = case.get("case_id")
        if isinstance(case_id, str) and case_id.startswith("phase9-"):
            # Canonical repository-only cases must not change the baseline of either
            # currently served compatibility projection before Phase 9 promotion.
            continue
        axis = case.get("axis")
        if not isinstance(axis, str) or axis in seen:
            continue
        seen.add(axis)
        if axis in SERVER_NOT_IMPLEMENTED_AXES and phase == "compatibility-core":
            status = "server-not-implemented"
            summary = "The required consequential server capability is absent in Phase 2."
        elif axis in SERVER_NOT_IMPLEMENTED_AXES:
            status = "declared-unexercised"
            summary = "The Phase 5 probe is implemented but has no real host evidence."
        elif axis in NOT_APPLICABLE_AXES:
            status = "not-applicable"
            summary = "The optional probe is not promoted in the Phase 2 catalogue."
        else:
            status = "not-tested"
            summary = "No real ChatGPT host evidence has been recorded."
        observations.append({"axis": axis, "status": status, "summary": summary})

    return {
        "profile_version": profile["profile_version"],
        "observed_protocol_revision": None,
        "observations": observations,
        "evidence_bundle_sha256": None,
        "limitations": [
            f"Only local {phase} server evidence exists.",
            "No real ChatGPT account, workspace, transport, or UI behavior has been observed.",
        ],
    }


def compile_registry(phase: str = "compatibility-core") -> tuple[bytes, bytes]:
    try:
        _, _, registry_format, expected_count = PROJECTIONS[phase]
    except KeyError as exc:
        raise ValueError(f"unknown catalogue projection: {phase}") from exc
    manifest = _load_yaml(MANIFEST_PATH)
    revision = _load_yaml(REVISION_PATH)
    evaluation_profile = _load_yaml(EVALUATION_PROFILE_PATH)
    evaluation_cases = _load_yaml(EVALUATION_CASES_PATH)
    resolver = SchemaResolver()

    selected_tools: list[dict[str, Any]] = []
    for raw_tool in manifest.get("tools", []):
        if not isinstance(raw_tool, dict):
            raise ValueError("Tool manifest contains a non-object Tool")
        phases = raw_tool.get("phases", [])
        if phase not in phases:
            continue
        input_schema, input_digest = resolver.from_manifest_ref(raw_tool["input_schema_ref"])
        output_schema, output_digest = resolver.from_manifest_ref(raw_tool["output_schema_ref"])
        selected_tools.append(
            {
                "name": raw_tool["name"],
                "title": raw_tool["title"],
                "description": raw_tool["description"],
                "contract_version": raw_tool["contract_version"],
                "handler_binding": raw_tool["handler_binding"],
                "information_class": raw_tool["information_class"],
                "confirmation_class": raw_tool["confirmation_class"],
                "annotations": raw_tool["annotations"],
                "input_schema": {
                    "source_ref": raw_tool["input_schema_ref"],
                    "definition_sha256": input_digest,
                    "schema": input_schema,
                },
                "output_schema": {
                    "source_ref": raw_tool["output_schema_ref"],
                    "definition_sha256": output_digest,
                    "schema": output_schema,
                },
            }
        )

    if len(selected_tools) != expected_count:
        raise ValueError(f"expected {expected_count} {phase} Tools, found {len(selected_tools)}")

    revisions = revision.get("revisions")
    if not isinstance(revisions, list):
        raise ValueError("revision contract must contain a revisions array")
    supported_revisions = [entry["revision"] for entry in revisions]
    revision_eras = {entry["revision"]: entry["era"] for entry in revisions}
    schema_registry_digest = _sha256_bytes(
        _canonical_bytes(
            {
                str(path.relative_to(ROOT)): document
                for path, document in sorted(
                    resolver.documents.items(), key=lambda item: str(item[0])
                )
            }
        )
    )
    catalogue_digest = _sha256_bytes(_canonical_bytes(selected_tools))
    manifest_digest = _sha256_bytes(MANIFEST_PATH.read_bytes())
    revision_digest = _sha256_bytes(REVISION_PATH.read_bytes())

    registry = {
        "registry_format": registry_format,
        "source_manifest": {
            "id": manifest["manifest_id"],
            "version": manifest["manifest_version"],
            "sha256": manifest_digest,
        },
        "schema_registry_sha256": schema_registry_digest,
        "revision_contract_sha256": revision_digest,
        "evaluation_profile_version": evaluation_profile["profile_version"],
        "supported_revisions": supported_revisions,
        "revision_eras": revision_eras,
        "tools": selected_tools,
        "schemas": {
            str(path.relative_to(ROOT)): document
            for path, document in sorted(resolver.documents.items(), key=lambda item: str(item[0]))
        },
        "compatibility_baseline": _compatibility_baseline(
            evaluation_profile, evaluation_cases, phase=phase
        ),
        "catalogue_sha256": catalogue_digest,
    }
    registry_bytes = _pretty_bytes(registry)
    digest_record = {
        "compiler_format": registry_format,
        "compiler_version": COMPILER_VERSION,
        "registry_sha256": _sha256_bytes(registry_bytes),
        "source_manifest_sha256": manifest_digest,
        "schema_registry_sha256": schema_registry_digest,
        "revision_contract_sha256": revision_digest,
        "catalogue_sha256": catalogue_digest,
    }
    return registry_bytes, _pretty_bytes(digest_record)


def _write_or_check(*, check: bool) -> int:
    try:
        compiled = {phase: compile_registry(phase) for phase in PROJECTIONS}
    except (KeyError, OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"Registry compilation failed: {exc}", file=sys.stderr)
        return 1

    expected = tuple(
        (path, content)
        for phase, (registry_bytes, digest_bytes) in compiled.items()
        for path, content in zip(
            (
                (REGISTRY_PATH, DIGEST_PATH)
                if phase == "compatibility-core"
                else PROJECTIONS[phase][:2]
            ),
            (registry_bytes, digest_bytes),
            strict=True,
        )
    )
    if check:
        failures = []
        for path, content in expected:
            try:
                existing = path.read_bytes()
            except OSError:
                failures.append(_display_path(path))
            else:
                if existing != content:
                    failures.append(_display_path(path))
        if failures:
            print(
                "Generated MCP registry is out of date: " + ", ".join(failures),
                file=sys.stderr,
            )
            return 1
        print("Generated MCP registry is current.")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in expected:
        path.write_bytes(content)
    print("Generated compatibility-core and compatibility-write-probe MCP registries.")
    return 0


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return _write_or_check(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

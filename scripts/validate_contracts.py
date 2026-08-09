#!/usr/bin/env python3
"""Validate Binnacle's machine-readable contracts and cross-document invariants."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
MERGE_TAG = "tag:yaml.org,2002:merge"


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects ordinary duplicate keys and supports YAML merges."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    has_merge = any(key_node.tag == MERGE_TAG for key_node, _ in node.value)
    if has_merge:
        loader.flatten_mapping(node)

    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping and not has_merge:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def fail(message: str) -> None:
    ERRORS.append(message)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except Exception as exc:  # noqa: BLE001 - aggregate validation failures
        fail(f"{path.relative_to(ROOT)}: YAML parse failed: {exc}")
        return None


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except Exception as exc:  # noqa: BLE001 - aggregate validation failures
        fail(f"{path.relative_to(ROOT)}: JSON parse failed: {exc}")
        return None


def pointer_get(document: Any, pointer: str) -> Any:
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


def local_ref_target(ref: str, referring_path: Path) -> tuple[Path, str] | None:
    if ref.startswith("#"):
        return referring_path, ref[1:]

    parsed = urlparse(ref)
    if parsed.scheme in ("http", "https"):
        prefix = "/schemas/"
        if prefix not in parsed.path:
            return None
        local_path = ROOT / "schemas" / parsed.path.split(prefix, 1)[1]
        return local_path, parsed.fragment

    path_part, separator, fragment = ref.partition("#")
    local_path = ROOT / path_part if not path_part.startswith("/") else Path(path_part)
    return local_path, fragment if separator else ""


def walk_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                refs.append(child)
            else:
                refs.extend(walk_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(walk_refs(child))
    return refs


def find_enums(value: Any, required_member: str) -> list[list[str]]:
    found: list[list[str]] = []
    if isinstance(value, dict):
        enum = value.get("enum")
        if isinstance(enum, list) and required_member in enum and all(isinstance(item, str) for item in enum):
            found.append(enum)
        for child in value.values():
            found.extend(find_enums(child, required_member))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_enums(child, required_member))
    return found


def validate_parse_and_schemas() -> None:
    yaml_roots = [ROOT / "spec", ROOT / "tests" / "fixtures"]
    for directory in yaml_roots:
        for path in sorted(directory.rglob("*.yaml")):
            load_yaml(path)
        for path in sorted(directory.rglob("*.yml")):
            load_yaml(path)

    schema_paths = sorted((ROOT / "schemas").rglob("*.json"))
    for path in schema_paths:
        schema = load_json(path)
        if schema is None:
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001
            fail(f"{path.relative_to(ROOT)}: invalid Draft 2020-12 schema: {exc}")
            continue

        for ref in walk_refs(schema):
            target = local_ref_target(ref, path)
            if target is None:
                continue
            target_path, fragment = target
            if not target_path.exists():
                fail(f"{path.relative_to(ROOT)}: unresolved $ref path {ref}")
                continue
            target_doc = load_json(target_path)
            if target_doc is None:
                continue
            if fragment:
                try:
                    pointer_get(target_doc, fragment)
                except (KeyError, IndexError, ValueError):
                    fail(f"{path.relative_to(ROOT)}: unresolved $ref pointer {ref}")


def validate_tool_manifest() -> None:
    manifest_path = ROOT / "spec/mcp/bootstrap-tool-manifest.yaml"
    manifest = load_yaml(manifest_path)
    if not isinstance(manifest, dict):
        return

    tools = manifest.get("tools")
    if not isinstance(tools, list):
        fail("bootstrap Tool manifest must contain a tools array")
        return
    if len(tools) != 8:
        fail(f"bootstrap Tool manifest must contain exactly 8 Tools, found {len(tools)}")

    names: set[str] = set()
    classes: dict[str, str] = {}
    for tool in tools:
        if not isinstance(tool, dict):
            fail("bootstrap Tool manifest contains a non-object Tool")
            continue
        name = tool.get("name")
        if not isinstance(name, str):
            fail("bootstrap Tool missing string name")
            continue
        if name in names:
            fail(f"duplicate Tool name: {name}")
        names.add(name)
        classes[name] = str(tool.get("confirmation_class"))

        for field in ("input_schema_ref", "output_schema_ref"):
            ref = tool.get(field)
            if not isinstance(ref, str):
                fail(f"{name}: missing {field}")
                continue
            path_part, _, fragment = ref.partition("#")
            target_path = ROOT / path_part
            if not target_path.exists():
                fail(f"{name}: {field} path does not exist: {path_part}")
                continue
            document = load_json(target_path)
            if document is None:
                continue
            try:
                pointer_get(document, fragment)
            except (KeyError, IndexError, ValueError):
                fail(f"{name}: {field} pointer does not resolve: {ref}")

    host_policy = load_yaml(ROOT / "spec/policy/host-confirmation-classes.yaml")
    if isinstance(host_policy, dict):
        initial = host_policy.get("initial_tool_classification")
        if initial != classes:
            fail(
                "host-confirmation initial_tool_classification does not exactly match "
                "the Tool manifest"
            )

    if "manifest_sha256" in manifest or "signature" in manifest:
        fail("source Tool manifest must not contain its own digest/signature")


def validate_evaluation_contract() -> None:
    profile_path = ROOT / "spec/mcp/evaluation-profile.yaml"
    cases_path = ROOT / "spec/mcp/evaluation-cases.yaml"
    profile = load_yaml(profile_path)
    cases = load_yaml(cases_path)
    if not isinstance(profile, dict) or not isinstance(cases, dict):
        return

    expected_digest = profile.get("case_manifest", {}).get("sha256")
    actual_digest = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    if expected_digest != actual_digest:
        fail(
            "evaluation case-manifest digest mismatch: "
            f"expected {expected_digest}, actual {actual_digest}"
        )

    expected_version = profile.get("case_manifest", {}).get("version")
    if expected_version != cases.get("case_manifest_version"):
        fail("evaluation case-manifest version mismatch")

    profile_statuses = profile.get("canonical_statuses")
    evaluation_schema = load_json(ROOT / "schemas/mcp/evaluation-manifest.schema.json")
    output_schema = load_json(ROOT / "schemas/mcp/bootstrap-outputs.schema.json")
    if isinstance(evaluation_schema, dict):
        schema_statuses = evaluation_schema.get("$defs", {}).get("status", {}).get("enum")
        if profile_statuses != schema_statuses:
            fail("evaluation profile statuses do not match evaluation schema")
    if isinstance(output_schema, dict):
        candidates = find_enums(output_schema, "observed-supported")
        if not candidates or profile_statuses not in candidates:
            fail("compatibility_report statuses do not match evaluation profile")

    profile_text = (ROOT / "docs/mcp-profile.md").read_text(encoding="utf-8")
    if isinstance(profile_statuses, list):
        for status in profile_statuses:
            if f"`{status}`" not in profile_text:
                fail(f"mcp-profile.md does not document canonical status {status}")

    risk_profile = profile.get("risk_classes")
    risk_cases = cases.get("risk_classes")
    if isinstance(risk_profile, dict) and isinstance(risk_cases, dict):
        if set(risk_profile) != set(risk_cases):
            fail("evaluation risk-class names differ between profile and case manifest")
        for name in set(risk_profile) & set(risk_cases):
            if risk_profile[name].get("minimum_attempts") != risk_cases[name].get("minimum_attempts"):
                fail(f"evaluation minimum attempts differ for {name}")

    case_ids: set[str] = set()
    for case in cases.get("cases", []):
        case_id = case.get("case_id")
        if case_id in case_ids:
            fail(f"duplicate evaluation case_id: {case_id}")
        case_ids.add(case_id)
        for required in ("axis", "risk_class", "setup", "action", "oracle", "timeout_seconds", "prohibited_effects", "evidence"):
            if required not in case:
                fail(f"evaluation case {case_id} missing {required}")
        if case.get("risk_class") not in risk_cases:
            fail(f"evaluation case {case_id} uses unknown risk class")


def validate_audit_release_and_results() -> None:
    audit_schema = load_json(ROOT / "schemas/audit/audit-event.schema.json")
    if isinstance(audit_schema, dict):
        properties = audit_schema.get("properties", {})
        if "event_type" in properties:
            fail("audit schema must use payload.kind as the sole event discriminator")
        if properties.get("canonicalization", {}).get("const") != "rfc8785-jcs+sha256-v1":
            fail("audit schema canonicalization profile mismatch")

    release_schema = load_json(ROOT / "schemas/supply-chain/release-manifest.schema.json")
    if isinstance(release_schema, dict):
        payload_props = release_schema.get("$defs", {}).get("releasePayload", {}).get("properties", {})
        forbidden = {"payload_sha256", "manifest_sha256", "signatures", "signature"}
        present = forbidden & set(payload_props)
        if present:
            fail(f"release payload contains self-referential integrity fields: {sorted(present)}")

        sbom_schema = payload_props.get("sboms", {})
        required_types = {
            clause.get("contains", {}).get("properties", {}).get("document_type", {}).get("const")
            for clause in sbom_schema.get("allOf", [])
        }
        if required_types != {"source_build", "runtime", "deployed_inventory"}:
            fail("release schema must require source/build, runtime, and deployed inventory documents")

    result_policy = load_yaml(ROOT / "spec/mcp/result-limits.yaml")
    if isinstance(result_policy, dict):
        limits = result_policy.get("limits", {})
        if "model_content_bytes" in limits:
            fail("result limits must use model_readable_content_bytes_max")
        if limits.get("decoded_chunk_default_bytes", 0) > limits.get("decoded_chunk_max_bytes", 0):
            fail("default decoded chunk exceeds maximum")
        if limits.get("decoded_chunk_max_bytes", 0) > 32768:
            fail("decoded chunk maximum exceeds reviewed 32 KiB ceiling")
        if limits.get("structured_content_serialized_bytes_max", 0) > limits.get(
            "complete_tool_result_serialized_bytes_max", 0
        ):
            fail("structured content limit exceeds complete Tool result limit")

    large_doc = (ROOT / "docs/mcp-large-results.md").read_text(encoding="utf-8")
    if "Personal V1" in large_doc:
        fail("mcp-large-results.md must use the current Binnacle V1 terminology")


def validate_repository_vocabulary() -> None:
    paths = [
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob("spec/**/*.yaml"),
        *ROOT.glob("schemas/**/*.json"),
        *ROOT.glob("tests/fixtures/**/*.yaml"),
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "protected-result" in text:
            fail(f"{path.relative_to(ROOT)}: obsolete information class protected-result")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                fail(f"{path.relative_to(ROOT)}:{number}: trailing whitespace")
            if "\t" in line:
                fail(f"{path.relative_to(ROOT)}:{number}: tab character")


def main() -> int:
    validate_parse_and_schemas()
    validate_tool_manifest()
    validate_evaluation_contract()
    validate_audit_release_and_results()
    validate_repository_vocabulary()

    if ERRORS:
        print("Contract validation failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

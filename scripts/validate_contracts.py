#!/usr/bin/env python3
"""Validate Binnacle's machine-readable contracts and cross-document invariants."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    # The contract-only workflow intentionally does not install the package.
    # Validate bindings against the checked-out implementation in that context.
    sys.path.insert(0, str(SOURCE_ROOT))

from binnacle.evaluation.phase10_acceptance import (  # noqa: E402
    AcceptanceVerdict,
    evaluate_phase10_manifest,
)
from binnacle.evaluation.phase10_policy import (  # noqa: E402
    Phase10PolicyError,
    load_phase10_policy,
)

ERRORS: list[str] = []
MERGE_TAG = "tag:yaml.org,2002:merge"
PHASE9_TOOL_CLASSES = {
    "privileged_prepare": ("normal-result", "HC0"),
    "package_inspect": ("normal-result", "HC0"),
    "package_install": ("restricted-result", "HC2"),
    "binnacle_service_inspect": ("normal-result", "HC0"),
    "binnacle_service_restart": ("restricted-result", "HC2"),
    "restart_preflight": ("normal-result", "HC0"),
    "binnacle_restart": ("restricted-result", "HC2"),
    "binnacle_runtime_inspect": ("normal-result", "HC0"),
}
EXPECTED_MANIFEST_TOOLS = (
    "binnacle_probe",
    "system_inspect",
    "probe_result_formats",
    "probe_error",
    "compatibility_report",
    "probe_workspace_prepare",
    "probe_workspace_write",
    "probe_workspace_cleanup",
    *PHASE9_TOOL_CLASSES,
)


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects ordinary duplicate keys and supports YAML merges."""


def _construct_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
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


def _mapping(value: Any, *, context: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        fail(f"{context}: expected an object")
        return None
    if not all(isinstance(key, str) for key in value):
        fail(f"{context}: object keys must be strings")
        return None
    return value


def _same_typed_value(actual: Any, expected: Any) -> bool:
    """Compare scalar contract values without bool/int equality coercion."""

    return type(actual) is type(expected) and actual == expected


def _fixture_cases_by_id(
    document: Any,
    *,
    context: str,
) -> dict[str, dict[str, Any]]:
    root = _mapping(document, context=context)
    if root is None:
        return {}
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        fail(f"{context}: cases must be an array")
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for index, raw_case in enumerate(raw_cases):
        case = _mapping(raw_case, context=f"{context}: cases[{index}]")
        if case is None:
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            fail(f"{context}: cases[{index}] has a missing or invalid id")
            continue
        if case_id in indexed:
            fail(f"{context}: duplicate fixture case id {case_id}")
            continue
        indexed[case_id] = case
    return indexed


def _require_fixture_case(
    cases: dict[str, dict[str, Any]],
    case_id: str,
    *,
    kind: str | None = None,
    profile: str | None = None,
    fields: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
) -> None:
    case = cases.get(case_id)
    if case is None:
        fail(f"required fixture case is missing: {case_id}")
        return
    if kind is not None and case.get("kind") != kind:
        fail(f"fixture case {case_id}: kind must be {kind!r}")
    if profile is not None and case.get("profile") != profile:
        fail(f"fixture case {case_id}: profile must be {profile!r}")
    if fields is not None:
        for key, value in fields.items():
            if key not in case:
                fail(f"fixture case {case_id}: {key} is required")
            elif not _same_typed_value(case[key], value):
                fail(f"fixture case {case_id}: {key} must be {value!r}, found {case[key]!r}")
    if expected is None:
        return
    actual = _mapping(case.get("expect"), context=f"fixture case {case_id}: expect")
    if actual is None:
        return
    for key, value in expected.items():
        if key not in actual:
            fail(f"fixture case {case_id}: expect.{key} is required")
        elif not _same_typed_value(actual[key], value):
            fail(f"fixture case {case_id}: expect.{key} must be {value!r}, found {actual[key]!r}")


def _merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_mappings(current, value)
        else:
            merged[key] = value
    return merged


def _profile_section_policy(
    policy: dict[str, Any],
    profile_id: str,
    *,
    section: str,
    inherits_global_key: str | None = None,
) -> dict[str, Any] | None:
    global_section = _mapping(
        policy.get(section),
        context=f"command policy: {section}",
    )
    profiles = _mapping(policy.get("profiles"), context="command policy: profiles")
    if global_section is None or profiles is None:
        return None
    if profile_id == "default":
        return dict(global_section)

    resolving: set[str] = set()

    def resolve(current_id: str) -> dict[str, Any] | None:
        if current_id in resolving:
            fail(f"command policy: cyclic profile inheritance at {current_id}")
            return None
        profile = _mapping(
            profiles.get(current_id),
            context=f"command policy: profile {current_id}",
        )
        if profile is None:
            return None
        resolving.add(current_id)
        parent_id = profile.get("inherits")
        if parent_id is None:
            effective = dict(global_section)
            if inherits_global_key is not None and profile.get(inherits_global_key) is not True:
                fail(f"command policy: profile {current_id} must set {inherits_global_key}=true")
        elif isinstance(parent_id, str):
            parent = resolve(parent_id)
            if parent is None:
                resolving.remove(current_id)
                return None
            effective = parent
        else:
            fail(f"command policy: profile {current_id} inherits must be a string")
            resolving.remove(current_id)
            return None
        if (
            inherits_global_key is not None
            and inherits_global_key in profile
            and profile[inherits_global_key] is not True
        ):
            fail(f"command policy: profile {current_id} must not disable {inherits_global_key}")
        override = profile.get(section, {})
        override_mapping = _mapping(
            override,
            context=f"command policy: profile {current_id} {section}",
        )
        resolving.remove(current_id)
        if override_mapping is None:
            return None
        return _merge_mappings(effective, override_mapping)

    return resolve(profile_id)


def _profile_network_policy(
    policy: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | None:
    return _profile_section_policy(policy, profile_id, section="network")


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
        if (
            isinstance(enum, list)
            and required_member in enum
            and all(isinstance(item, str) for item in enum)
        ):
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
    if len(tools) != len(EXPECTED_MANIFEST_TOOLS):
        fail(
            "bootstrap Tool manifest must contain exactly "
            f"{len(EXPECTED_MANIFEST_TOOLS)} Tools, found {len(tools)}"
        )

    names: set[str] = set()
    ordered_names: list[str] = []
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
        ordered_names.append(name)
        classes[name] = str(tool.get("confirmation_class"))

        binding = tool.get("handler_binding")
        if not isinstance(binding, str) or "." not in binding:
            fail(f"{name}: missing or invalid handler_binding")
        else:
            module_name, _, attribute_name = binding.rpartition(".")
            try:
                handler = getattr(importlib.import_module(module_name), attribute_name)
            except (ImportError, AttributeError) as exc:
                fail(f"{name}: handler_binding is unavailable: {type(exc).__name__}")
            else:
                if not inspect.iscoroutinefunction(handler):
                    fail(f"{name}: handler_binding is not async")

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

    if tuple(ordered_names) != EXPECTED_MANIFEST_TOOLS:
        fail("bootstrap Tool manifest order or names differ from the reviewed contract")

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


def validate_phase9_privileged_contracts() -> None:
    """Cross-check the unpromoted Phase 9 surface without enabling a runtime catalogue."""

    manifest = load_yaml(ROOT / "spec/mcp/bootstrap-tool-manifest.yaml")
    operation = load_yaml(ROOT / "spec/operation/privileged-operations.yaml")
    host = load_yaml(ROOT / "spec/policy/host-confirmation-classes.yaml")
    capability = load_yaml(ROOT / "spec/policy/capability-zones.yaml")
    profiles = load_yaml(ROOT / "spec/policy/privileged-profiles.yaml")
    limits = load_yaml(ROOT / "spec/mcp/result-limits.yaml")
    evaluation = load_yaml(ROOT / "spec/mcp/evaluation-profile.yaml")
    documents = (manifest, operation, host, capability, profiles, limits, evaluation)
    if not all(isinstance(document, dict) for document in documents):
        return
    assert isinstance(manifest, dict)
    assert isinstance(operation, dict)
    assert isinstance(host, dict)
    assert isinstance(capability, dict)
    assert isinstance(profiles, dict)
    assert isinstance(limits, dict)
    assert isinstance(evaluation, dict)

    raw_tools = manifest.get("tools")
    if not isinstance(raw_tools, list):
        return
    manifest_tools = {
        tool.get("name"): tool
        for tool in raw_tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    operation_tools = _mapping(
        operation.get("tools"),
        context="privileged operations: tools",
    )
    host_classes = _mapping(
        host.get("initial_tool_classification"),
        context="host confirmation: initial_tool_classification",
    )
    if operation_tools is None or host_classes is None:
        return

    for tool_name, (information_class, confirmation_class) in PHASE9_TOOL_CLASSES.items():
        source = _mapping(
            manifest_tools.get(tool_name),
            context=f"Phase 9 manifest Tool {tool_name}",
        )
        contract = _mapping(
            operation_tools.get(tool_name),
            context=f"privileged operation {tool_name}",
        )
        if source is None or contract is None:
            continue
        _require_values(
            source,
            {
                "contract_version": "1.0",
                "information_class": information_class,
                "confirmation_class": confirmation_class,
                "phases": ["v1-operational"],
            },
            context=f"Phase 9 manifest Tool {tool_name}",
        )
        _require_values(
            contract,
            {
                "operation_contract_version": "1.0",
                "information_class": information_class,
                "confirmation_class": confirmation_class,
            },
            context=f"privileged operation {tool_name}",
        )
        if host_classes.get(tool_name) != confirmation_class:
            fail(f"host confirmation class differs for Phase 9 Tool {tool_name}")

    if set(operation_tools) != set(PHASE9_TOOL_CLASSES):
        fail("privileged operation Tool set is not the exact reviewed Phase 9 set")
    if "host_reboot" in manifest_tools or "host_reboot" in operation_tools:
        fail("host_reboot must remain absent from manifest and operation contracts")
    if operation.get("runtime_promotion") != "disabled":
        fail("privileged operation runtime promotion must remain disabled")
    if profiles.get("runtime_promotion") != "disabled":
        fail("privileged profile runtime promotion must remain disabled")

    privileged_prepare_execute = _mapping(
        host.get("privileged_prepare_execute"),
        context="host confirmation: privileged_prepare_execute",
    )
    _require_values(
        privileged_prepare_execute,
        {
            "prepare_tool": "privileged_prepare",
            "execute_tools": [
                "package_install",
                "binnacle_service_restart",
                "binnacle_restart",
            ],
            "preparation_is_owner_authority": False,
            "retained_retry_only": True,
            "uncertain_effect_auto_retry": False,
        },
        context="host confirmation: privileged_prepare_execute",
    )

    extension = _mapping(
        capability.get("privileged_self_management_extension"),
        context="capability policy: privileged_self_management_extension",
    )
    _require_values(
        extension,
        {"extension_version": "1.0.0", "runtime_promotion": "disabled"},
        context="capability policy: privileged_self_management_extension",
    )
    promotion = _mapping(
        profiles.get("promotion_gates"),
        context="privileged profiles: promotion_gates",
    )
    _require_values(
        promotion,
        {
            "evidence_missing_does_not_block_repository_implementation": True,
            "v1_operational_catalogue_enabled": False,
        },
        context="privileged profiles: promotion_gates",
    )

    phase9_limits = _mapping(
        limits.get("phase9_tool_limits"),
        context="result limits: phase9_tool_limits",
    )
    if phase9_limits is not None:
        missing_limits = set(PHASE9_TOOL_CLASSES) - set(phase9_limits)
        if missing_limits:
            fail(f"Phase 9 result limits are missing Tools: {sorted(missing_limits)}")
        if phase9_limits.get("runtime_promotion") != "disabled":
            fail("Phase 9 result-limit runtime promotion must remain disabled")

    evaluation_phase9 = _mapping(
        evaluation.get("phase9_privileged_self_management"),
        context="evaluation profile: phase9_privileged_self_management",
    )
    _require_values(
        evaluation_phase9,
        {
            "repository_implementation_may_complete_without_live_host_or_pi_evidence": True,
            "runtime_promotion": "disabled",
            "runtime_promotion_requires_candidate_pi_evidence": True,
            "runtime_promotion_requires_real_chatgpt_hc2_evidence": True,
            "v1_operational_tools_default_visible": False,
            "host_reboot_contract_absent": True,
        },
        context="evaluation profile: phase9_privileged_self_management",
    )
    if evaluation_phase9 is not None:
        categories = _mapping(
            evaluation_phase9.get("category_risk_classes"),
            context="evaluation profile: Phase 9 category_risk_classes",
        )
        expected_categories = {
            "selection_rendering": ("tool_selection_and_result_rendering", 10),
            "confirmation_entitlement": ("confirmation_and_entitlement", 5),
            "execute_retry_cancel": ("write_cancellation_retry_cache_confirmation", 20),
            "concurrency_race_reconnect": (
                "concurrency_race_reconnect_instability",
                20,
            ),
        }
        if categories is not None and set(categories) != set(expected_categories):
            fail("Phase 9 evaluation category set differs from the reviewed contract")
        if categories is not None:
            for category, (risk_class, minimum_attempts) in expected_categories.items():
                values = _mapping(
                    categories.get(category),
                    context=f"evaluation profile: Phase 9 category {category}",
                )
                _require_values(
                    values,
                    {
                        "risk_class": risk_class,
                        "minimum_attempts": minimum_attempts,
                    },
                    context=f"evaluation profile: Phase 9 category {category}",
                )


def validate_revision_support_contract() -> None:
    """Validate the finite machine revision contract and evaluation cross-reference."""

    contract_path = ROOT / "spec/mcp/revision-support.yaml"
    schema_path = ROOT / "schemas/mcp/revision-support.schema.json"
    contract = load_yaml(contract_path)
    schema = load_json(schema_path)
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        return

    for error in Draft202012Validator(schema).iter_errors(contract):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        fail(f"revision support contract: {location}: {error.message}")

    expected = (
        "2026-07-28",
        "2025-11-25",
        "2025-06-18",
        "2025-03-26",
    )
    raw_revisions = contract.get("revisions")
    if not isinstance(raw_revisions, list):
        return
    entries = [entry for entry in raw_revisions if isinstance(entry, dict)]
    actual = tuple(entry.get("revision") for entry in entries)
    if actual != expected:
        fail(f"revision support contract: expected finite ordered set {expected!r}")
    if contract.get("target_revision") != expected[0]:
        fail("revision support contract: target revision must be 2026-07-28")
    for index, entry in enumerate(entries):
        expected_era = "modern" if index == 0 else "legacy"
        expected_profile = "target-stateless" if index == 0 else "legacy-streamable-http"
        if entry.get("era") != expected_era:
            fail(f"revision support contract: {expected[index]} era must be {expected_era}")
        if entry.get("profile") != expected_profile:
            fail(f"revision support contract: {expected[index]} profile must be {expected_profile}")

    evaluation = load_yaml(ROOT / "spec/mcp/evaluation-cases.yaml")
    if not isinstance(evaluation, dict):
        return
    cases = evaluation.get("cases")
    if not isinstance(cases, list):
        fail("evaluation cases: cases must be an array")
        return
    protocol_case = next(
        (
            case
            for case in cases
            if isinstance(case, dict) and case.get("axis") == "protocol_revision"
        ),
        None,
    )
    if not isinstance(protocol_case, dict):
        fail("evaluation cases: protocol_revision case is missing")
        return
    setup = protocol_case.get("setup")
    if not isinstance(setup, dict) or tuple(setup.get("supported_revision_set", ())) != expected:
        fail("evaluation cases: supported revision set diverges from machine contract")


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
            if risk_profile[name].get("minimum_attempts") != risk_cases[name].get(
                "minimum_attempts"
            ):
                fail(f"evaluation minimum attempts differ for {name}")

    case_ids: set[str] = set()
    for case in cases.get("cases", []):
        case_id = case.get("case_id")
        if case_id in case_ids:
            fail(f"duplicate evaluation case_id: {case_id}")
        case_ids.add(case_id)
        for required in (
            "axis",
            "risk_class",
            "setup",
            "action",
            "oracle",
            "timeout_seconds",
            "prohibited_effects",
            "evidence",
        ):
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
        payload_props = (
            release_schema.get("$defs", {}).get("releasePayload", {}).get("properties", {})
        )
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
            fail(
                "release schema must require source/build, runtime, and deployed "
                "inventory documents"
            )

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


def _require_values(
    actual: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    *,
    context: str,
) -> None:
    if actual is None:
        return
    for key, value in expected.items():
        if key not in actual:
            fail(f"{context}: {key} is required")
        elif not _same_typed_value(actual[key], value):
            fail(f"{context}: {key} must be {value!r}, found {actual[key]!r}")


def validate_bootstrap_command_profile_alignment() -> None:
    command_policy = load_yaml(ROOT / "spec/policy/command-profiles.yaml")
    capability_policy = load_yaml(ROOT / "spec/policy/capability-zones.yaml")
    isolation_fixture = load_yaml(ROOT / "tests/fixtures/security/command-isolation.yaml")
    composition_fixture = load_yaml(ROOT / "tests/fixtures/security/capability-composition.yaml")
    command_policy_root = _mapping(command_policy, context="command policy")
    capability_policy_root = _mapping(capability_policy, context="capability policy")
    if command_policy_root is None or capability_policy_root is None:
        return
    command_policy = command_policy_root
    capability_policy = capability_policy_root

    for document, context in (
        (command_policy, "command policy"),
        (capability_policy, "capability policy"),
        (isolation_fixture, "command-isolation fixture"),
        (composition_fixture, "capability-composition fixture"),
    ):
        mapping = _mapping(document, context=context)
        if mapping is not None and mapping.get("policy_version") != "1.2.0":
            fail(f"{context}: policy_version must be '1.2.0'")

    profiles = _mapping(command_policy.get("profiles"), context="command policy: profiles")
    if profiles is None:
        return
    general = _mapping(
        profiles.get("workspace-general-v1"),
        context="command policy: profile workspace-general-v1",
    )
    check = _mapping(
        profiles.get("workspace-check-v1"),
        context="command policy: profile workspace-check-v1",
    )
    self_management = _mapping(
        profiles.get("self-management"),
        context="command policy: profile self-management",
    )
    _require_values(
        general,
        {
            "command_run_visible": True,
            "command_run_allowed": True,
            "inherits_global_devices": True,
            "inherits_global_credentials": True,
        },
        context="command policy: profile workspace-general-v1",
    )
    _require_values(
        check,
        {
            "inherits": "workspace-general-v1",
            "command_run_visible": True,
            "command_run_allowed": True,
        },
        context="command policy: profile workspace-check-v1",
    )
    _require_values(
        self_management,
        {"command_run_visible": False, "command_run_allowed": False},
        context="command policy: profile self-management",
    )

    required_network = {
        "mode": "application",
        "ipv4": "allowed",
        "ipv6": "allowed",
        "dns": "allowed",
        "unix_sockets": "denied",
        "inherited_sockets": "denied",
        "protected_control_plane_ipc": "denied",
        "raw_packet": "denied",
        "network_admin": "denied",
        "mediated_egress_only": False,
    }
    required_listener = {
        "loopback": "allowed",
        "non_loopback": "explicit",
        "explicit_exposure_required": True,
    }
    for profile_id in ("workspace-general-v1", "workspace-check-v1"):
        network = _profile_network_policy(command_policy, profile_id)
        _require_values(network, required_network, context=f"effective network {profile_id}")
        listener = None
        if network is not None:
            listener = _mapping(
                network.get("listener_bind"),
                context=f"effective network {profile_id}: listener_bind",
            )
        _require_values(listener, required_listener, context=f"listener policy {profile_id}")

    default_network = _profile_network_policy(command_policy, "default")
    _require_values(
        default_network,
        {
            "default": "denied",
            "ipv4": "denied",
            "ipv6": "denied",
            "dns": "denied",
            "unix_sockets": "denied",
            "inherited_sockets": "denied",
            "protected_control_plane_ipc": "denied",
            "raw_packet": "denied",
            "network_admin": "denied",
        },
        context="default command network",
    )
    default_listener = None
    if default_network is not None:
        default_listener = _mapping(
            default_network.get("listener_bind"),
            context="default command network: listener_bind",
        )
    _require_values(
        default_listener,
        {
            "loopback": "denied",
            "non_loopback": "denied",
            "explicit_exposure_required": True,
        },
        context="default command listener policy",
    )
    devices = _mapping(command_policy.get("devices"), context="command policy: devices")
    credentials = _mapping(
        command_policy.get("credentials"),
        context="command policy: credentials",
    )
    _require_values(
        devices,
        {"default": "denied", "arbitrary_device_nodes": "denied"},
        context="command policy: devices",
    )
    _require_values(
        credentials,
        {
            "raw_credentials": "denied",
            "credential_helpers": "denied",
            "inherited_agents": "denied",
        },
        context="command policy: credentials",
    )
    required_devices = {"default": "denied", "arbitrary_device_nodes": "denied"}
    required_credentials = {
        "raw_credentials": "denied",
        "credential_helpers": "denied",
        "inherited_agents": "denied",
    }
    for profile_id, profile in (
        ("workspace-general-v1", general),
        ("workspace-check-v1", check),
    ):
        if profile is not None:
            for section in ("devices", "credentials"):
                if section in profile:
                    fail(
                        f"command policy: profile {profile_id} must inherit global "
                        f"{section} without a local override"
                    )
        effective_devices = _profile_section_policy(
            command_policy,
            profile_id,
            section="devices",
            inherits_global_key="inherits_global_devices",
        )
        effective_credentials = _profile_section_policy(
            command_policy,
            profile_id,
            section="credentials",
            inherits_global_key="inherits_global_credentials",
        )
        _require_values(
            effective_devices,
            required_devices,
            context=f"effective devices {profile_id}",
        )
        _require_values(
            effective_credentials,
            required_credentials,
            context=f"effective credentials {profile_id}",
        )
    privilege = _mapping(command_policy.get("privilege"), context="command policy: privilege")
    if privilege is not None:
        if privilege.get("syscall_policy_required") is True:
            fail("command policy: legacy syscall_policy_required must not gate Bootstrap")
        if privilege.get("mandatory_access_control_required") is True:
            fail("command policy: legacy mandatory_access_control_required must not gate Bootstrap")
        advanced_syscall = _mapping(
            privilege.get("advanced_syscall_policy"),
            context="command policy: privilege.advanced_syscall_policy",
        )
        mandatory_access = _mapping(
            privilege.get("mandatory_access_control"),
            context="command policy: privilege.mandatory_access_control",
        )
        _require_values(
            advanced_syscall,
            {"bootstrap_required": False, "target_hardening": True},
            context="command policy: privilege.advanced_syscall_policy",
        )
        _require_values(
            mandatory_access,
            {"bootstrap_required": False, "target_hardening": True},
            context="command policy: privilege.mandatory_access_control",
        )

    command_composition = _mapping(
        capability_policy.get("command_run"),
        context="capability policy: command_run",
    )
    if command_composition is not None:
        for legacy_field in ("network_available", "mediated_egress_only"):
            if legacy_field in command_composition:
                fail(
                    "capability policy: command_run must not retain universal legacy field "
                    f"{legacy_field}"
                )
    _require_values(
        command_composition,
        {
            "network_authority": "profile-defined",
            "bootstrap_development_application_network": "allowed",
            "listener_bind_default": "loopback",
            "non_loopback_listener_requires_explicit_exposure": True,
            "raw_credentials_available": False,
            "credential_helpers_available": False,
            "device_access_available": False,
            "local_control_sockets_available": False,
            "raw_packet_network_available": False,
            "network_admin_available": False,
            "protected_data_egress_requires_exact_contract": True,
            "credential_bearing_effect_requires_dedicated_operation": True,
        },
        context="capability policy: command_run",
    )

    isolation_cases = _fixture_cases_by_id(
        isolation_fixture,
        context="command-isolation fixture",
    )
    isolation_requirements = (
        (
            "development-ipv4-application-network",
            "positive",
            "workspace-general-v1",
            {"ipv4": "allowed"},
        ),
        (
            "development-ipv6-application-network",
            "positive",
            "workspace-general-v1",
            {"ipv6": "allowed"},
        ),
        ("development-dns-resolution", "positive", "workspace-general-v1", {"dns": "allowed"}),
        (
            "development-loopback-listener-allowed",
            "positive",
            "workspace-general-v1",
            {"loopback_listener": "allowed"},
        ),
        (
            "development-non-loopback-listener-requires-explicit-exposure",
            "negative",
            "workspace-general-v1",
            {"non_loopback_listener": "explicit", "explicit_exposure_required": True},
        ),
        (
            "default-profile-network-denied",
            "positive",
            "default",
            {
                "ipv4": "denied",
                "ipv6": "denied",
                "dns": "denied",
                "loopback_listener": "denied",
                "non_loopback_listener": "denied",
            },
        ),
        (
            "development-unix-control-socket-denied",
            "negative",
            "workspace-general-v1",
            {"unix_sockets": "denied", "protected_control_plane_ipc": "denied"},
        ),
        (
            "development-inherited-socket-denied",
            "negative",
            "workspace-general-v1",
            {"inherited_sockets": "denied"},
        ),
        (
            "development-raw-packet-denied",
            "negative",
            "workspace-general-v1",
            {"raw_packet": "denied", "network_admin": "denied"},
        ),
        (
            "development-credential-agent-denied",
            "negative",
            "workspace-general-v1",
            {
                "raw_credentials": "denied",
                "credential_helpers": "denied",
                "inherited_agents": "denied",
            },
        ),
        (
            "workspace-check-profile-consistent",
            "positive",
            "workspace-check-v1",
            {
                "command_run_visible": True,
                "command_run_allowed": True,
                "ipv4": "allowed",
                "ipv6": "allowed",
                "dns": "allowed",
                "loopback_listener": "allowed",
                "non_loopback_listener": "explicit",
                "explicit_exposure_required": True,
                "unix_sockets": "denied",
                "inherited_sockets": "denied",
                "protected_control_plane_ipc": "denied",
                "raw_packet": "denied",
                "network_admin": "denied",
                "device_default": "denied",
                "raw_credentials": "denied",
                "credential_helpers": "denied",
                "inherited_agents": "denied",
            },
        ),
        (
            "self-management-hidden",
            "positive",
            "self-management",
            {
                "command_run_visible": False,
                "command_run_allowed": False,
                "dedicated_self_management_tools_required": True,
            },
        ),
    )
    for case_id, kind, profile, expected in isolation_requirements:
        _require_fixture_case(
            isolation_cases,
            case_id,
            kind=kind,
            profile=profile,
            expected=expected,
        )
    _require_fixture_case(
        isolation_cases,
        "development-non-loopback-listener-with-explicit-exposure",
        kind="positive",
        profile="workspace-general-v1",
        fields={"explicit_exposure_granted": True},
        expected={"non_loopback_listener": "allowed"},
    )

    composition_cases = _fixture_cases_by_id(
        composition_fixture,
        context="capability-composition fixture",
    )
    composition_requirements = (
        (
            "command-default-profile-network-deny",
            "positive",
            "default",
            {
                "network_authority": "denied",
                "credential_helpers_available": False,
                "device_access_available": False,
                "local_control_sockets_available": False,
            },
        ),
        (
            "development-command-application-network-allowed",
            "positive",
            "workspace-general-v1",
            {
                "ipv4": "allowed",
                "ipv6": "allowed",
                "dns": "allowed",
                "credential_helpers_available": False,
                "device_access_available": False,
                "local_control_sockets_available": False,
            },
        ),
        (
            "development-loopback-listener-default",
            "positive",
            "workspace-general-v1",
            {"loopback_listener": "allowed"},
        ),
        (
            "development-non-loopback-listener-needs-explicit-exposure",
            "negative",
            "workspace-general-v1",
            {
                "non_loopback_listener": "explicit",
                "explicit_exposure_required": True,
                "effect_without_exposure": "denied",
            },
        ),
        (
            "development-network-does-not-grant-credential-broker",
            "negative",
            "workspace-general-v1",
            {
                "raw_credentials_available": False,
                "credential_helpers_available": False,
                "credential_broker_available": False,
            },
        ),
        (
            "development-network-does-not-grant-protected-data",
            "negative",
            "workspace-general-v1",
            {"protected_data_available": False, "exact_contract_required": True},
        ),
    )
    for case_id, kind, profile, expected in composition_requirements:
        _require_fixture_case(
            composition_cases,
            case_id,
            kind=kind,
            profile=profile,
            expected=expected,
        )


def validate_bootstrap_self_hosting_scope_alignment() -> None:
    required_markers = {
        ROOT / "docs/design-principles.rst": (
            "signed commits and push development branches",
            "minimum privileged package, service, and Binnacle-restart operations",
        ),
        ROOT / "docs/bootstrap-v1.rst": (
            "install a missing development OS package",
            "create a signed commit",
            "push the branch",
            "perform the controlled Binnacle restart path",
        ),
        ROOT / "docs/bootstrap-implementation-plan.rst": (
            "signed Git commit and branch push",
            "install a specifically requested development OS package",
            "perform the controlled Binnacle restart path",
        ),
    }
    for path, markers in required_markers.items():
        try:
            text = " ".join(path.read_text(encoding="utf-8").split())
        except OSError as exc:
            fail(f"{path.relative_to(ROOT)}: unable to read Bootstrap scope document: {exc}")
            continue
        for marker in markers:
            if marker not in text:
                fail(
                    f"{path.relative_to(ROOT)}: missing Bootstrap self-hosting "
                    f"scope marker {marker!r}"
                )


def validate_phase10_acceptance_contract() -> None:
    """Keep the Phase 10 evaluator, schemas, fixtures, CI, and procedure coherent."""

    try:
        policy = load_phase10_policy(ROOT)
    except Phase10PolicyError as exc:
        fail(f"Phase 10 policy: {exc}")
        return
    if policy.repository != "grammy-jiang/binnacle":
        fail("Phase 10 policy repository differs from the reviewed repository")
    if policy.protected_branch_ref != "refs/heads/master":
        fail("Phase 10 policy protected branch differs from refs/heads/master")

    schema = load_json(ROOT / "schemas/acceptance/phase10-run.schema.json")
    ci_attestation_schema = load_json(
        ROOT / "schemas/acceptance/ci-checkout-attestation.schema.json"
    )
    manifest = load_json(ROOT / "tests/fixtures/acceptance/phase10-pass.json")
    cases_document = load_json(ROOT / "tests/fixtures/acceptance/phase10-evaluator-cases.json")
    if (
        not isinstance(schema, dict)
        or not isinstance(ci_attestation_schema, dict)
        or not isinstance(manifest, dict)
    ):
        return

    embedded_attestation = schema.get("$defs", {}).get("ciCheckoutAttestation")
    expected_embedded_attestation = {
        name: ci_attestation_schema[name]
        for name in ("type", "additionalProperties", "properties", "required")
    }
    if embedded_attestation != expected_embedded_attestation:
        fail("Phase 10 run schema embeds a stale CI checkout-attestation contract")

    expected_limits = {
        "candidate_generations_max": schema.get("properties", {})
        .get("candidate_generations", {})
        .get("maxItems"),
        "integration_generations_max": schema.get("properties", {})
        .get("integration_generations", {})
        .get("maxItems"),
        "security_checks_max": schema.get("properties", {})
        .get("security_checks", {})
        .get("maxItems"),
        "ci_evidence_per_integration_max": schema.get("$defs", {})
        .get("integrationGeneration", {})
        .get("properties", {})
        .get("ci_evidence", {})
        .get("maxItems"),
        "evidence_reference_id_bytes_max": schema.get("$defs", {})
        .get("identifier", {})
        .get("maxLength"),
    }
    for name, schema_limit in expected_limits.items():
        if policy.limits.get(name) != schema_limit:
            fail(f"Phase 10 policy {name} differs from acceptance schema")

    if manifest.get("policy_sha256") != policy.sha256:
        fail("Phase 10 PASS fixture policy identity is stale")
    try:
        report = evaluate_phase10_manifest(manifest, repo_root=ROOT)
    except Exception as exc:  # noqa: BLE001 - aggregate validation failures
        fail(f"Phase 10 PASS fixture could not be evaluated: {exc}")
    else:
        if report.verdict is not AcceptanceVerdict.PASS:
            fail("Phase 10 PASS fixture does not produce PASS")

    cases = _fixture_cases_by_id(cases_document, context="Phase 10 evaluator fixture")
    required_cases = {
        "ci-from-unreviewed-collector-fails",
        "relabelled-ci-attestation-fails",
        "reused-ci-attestation-fails",
        "complete-exact-chain-passes",
        "moved-pr-head-fails",
        "owner-review-on-old-evidence-is-incomplete",
        "push-through-wrong-remote-profile-fails",
        "review-on-old-candidate-is-incomplete",
        "review-on-old-base-is-incomplete",
        "ci-on-old-candidate-is-incomplete",
        "ci-with-wrong-parents-is-incomplete",
        "ci-tree-mismatch-fails",
        "stale-policy-is-incomplete",
        "post-restart-runtime-profile-mismatch-fails",
        "unresolved-effect-is-incomplete",
    }
    missing_cases = required_cases - set(cases)
    if missing_cases:
        fail(f"Phase 10 evaluator fixture is missing cases: {sorted(missing_cases)}")

    collector_action = (
        f"{policy.repository}/.github/actions/phase10-checkout-attestation@"
        f"{policy.ci_attestation_collector_commit_oid}"
    )
    workflow_jobs = {
        ROOT / ".github/workflows/contracts.yml": {
            "validate-contracts": "validate-contracts",
        },
        ROOT / ".github/workflows/python.yml": {
            "test": "Test Python ${{ matrix.python-version }}",
            "quality": "Code, contract, dependency, and document quality",
        },
    }
    for path, expected_jobs in workflow_jobs.items():
        workflow = load_yaml(path)
        if not isinstance(workflow, dict):
            fail(f"{path.relative_to(ROOT)}: workflow must be an object")
            continue
        # PyYAML's YAML 1.1 resolver parses GitHub's top-level ``on`` key as
        # boolean true. Only the jobs mapping is material to this invariant.
        jobs = _mapping(
            workflow.get("jobs"),
            context=f"{path.relative_to(ROOT)}: jobs",
        )
        if jobs is None:
            continue
        if set(jobs) != set(expected_jobs):
            fail(
                f"{path.relative_to(ROOT)}: Phase 10 attestation job set differs "
                "from the reviewed workflow"
            )
            continue
        for job_id, expected_job_name in expected_jobs.items():
            job = _mapping(jobs[job_id], context=f"{path.relative_to(ROOT)}: job {job_id}")
            if job is None:
                continue
            steps = job.get("steps")
            if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
                fail(f"{path.relative_to(ROOT)}: job {job_id} steps are invalid")
                continue
            checkout_indexes = [
                index
                for index, step in enumerate(steps)
                if isinstance(step.get("uses"), str)
                and step["uses"].startswith("actions/checkout@")
            ]
            collector_indexes = [
                index for index, step in enumerate(steps) if step.get("uses") == collector_action
            ]
            upload_indexes = [
                index
                for index, step in enumerate(steps)
                if isinstance(step.get("uses"), str)
                and step["uses"].startswith("actions/upload-artifact@")
            ]
            if (
                len(checkout_indexes) != 1
                or len(collector_indexes) != 1
                or len(upload_indexes) != 1
            ):
                fail(
                    f"{path.relative_to(ROOT)}: job {job_id} must contain exactly one "
                    "checkout, trusted collector, and attestation upload"
                )
                continue
            checkout_index = checkout_indexes[0]
            collector_index = collector_indexes[0]
            upload_index = upload_indexes[0]
            if collector_index != checkout_index + 1 or upload_index != collector_index + 1:
                fail(
                    f"{path.relative_to(ROOT)}: job {job_id} must attest and upload "
                    "immediately after checkout, before candidate-controlled work"
                )
            collector_step = steps[collector_index]
            collector_inputs = _mapping(
                collector_step.get("with"),
                context=f"{path.relative_to(ROOT)}: job {job_id} collector inputs",
            )
            if collector_inputs is not None:
                if collector_inputs.get("output") != (
                    "${{ runner.temp }}/phase10-ci-checkout.json"
                ):
                    fail(
                        f"{path.relative_to(ROOT)}: job {job_id} collector output must "
                        "be outside the candidate checkout"
                    )
                if collector_inputs.get("job-name") != expected_job_name:
                    fail(
                        f"{path.relative_to(ROOT)}: job {job_id} collector job identity "
                        "differs from the reviewed policy"
                    )
            upload_step = steps[upload_index]
            upload_inputs = _mapping(
                upload_step.get("with"),
                context=f"{path.relative_to(ROOT)}: job {job_id} upload inputs",
            )
            if upload_inputs is not None:
                if upload_inputs.get("path") != "${{ runner.temp }}/phase10-ci-checkout.json":
                    fail(
                        f"{path.relative_to(ROOT)}: job {job_id} uploads the wrong attestation path"
                    )
                if upload_inputs.get("if-no-files-found") != "error":
                    fail(
                        f"{path.relative_to(ROOT)}: job {job_id} permits a missing "
                        "attestation artifact"
                    )

    workflow_requirements = {
        ROOT / ".github/actions/phase10-checkout-attestation/action.yml": (
            "/usr/bin/python3 -I -S",
            'collector_root="${BINNACLE_ACTION_PATH}/../../.."',
            '--collector-commit "${BINNACLE_ACTION_REF}"',
            '--expected-collector-sha256 "${BINNACLE_COLLECTOR_SHA256}"',
            policy.ci_attestation_collector_sha256,
        ),
        ROOT / "docs/operations/phase10-self-hosting-acceptance.rst": (
            "Evidence-independent repository implementation",
            "Real-device acceptance promotion",
            "scripts/phase10_acceptance.py",
            "review-digest",
        ),
        ROOT / "scripts/ci_checkout_attestation.py": (
            '_GIT_BINARY = "/usr/bin/git"',
            '"GIT_CONFIG_GLOBAL": "/dev/null"',
            '"GIT_NO_REPLACE_OBJECTS": "1"',
        ),
        ROOT / "src/binnacle/evaluation/__init__.py": (
            "Public exports are loaded lazily",
            "def __getattr__",
        ),
        ROOT / "tests/integration/test_phase10_acceptance_cli.py": (
            "test_checkout_command_runs_from_reviewed_bundle_in_isolated_stdlib_mode",
            '"/usr/bin/python3"',
            '"-I"',
            '"-S"',
        ),
    }
    for path, markers in workflow_requirements.items():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            fail(f"{path.relative_to(ROOT)}: Phase 10 integration file is unavailable: {exc}")
            continue
        for marker in markers:
            if marker not in text:
                fail(f"{path.relative_to(ROOT)}: missing Phase 10 marker {marker!r}")


def validate_repository_vocabulary() -> None:
    paths = [
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob("docs/**/*.rst"),
        *ROOT.glob("spec/**/*.yaml"),
        *ROOT.glob("spec/**/*.json"),
        *ROOT.glob("schemas/**/*.json"),
        *ROOT.glob("tests/fixtures/**/*.yaml"),
        *ROOT.glob("tests/fixtures/**/*.json"),
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
    validate_bootstrap_command_profile_alignment()
    validate_bootstrap_self_hosting_scope_alignment()
    validate_phase10_acceptance_contract()
    validate_tool_manifest()
    validate_phase9_privileged_contracts()
    validate_revision_support_contract()
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

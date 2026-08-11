#!/usr/bin/env python3
"""Validate Binnacle's machine-readable contracts and cross-document invariants."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
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
            elif case[key] != value:
                fail(f"fixture case {case_id}: {key} must be {value!r}, found {case[key]!r}")
    if expected is None:
        return
    actual = _mapping(case.get("expect"), context=f"fixture case {case_id}: expect")
    if actual is None:
        return
    for key, value in expected.items():
        if key not in actual:
            fail(f"fixture case {case_id}: expect.{key} is required")
        elif actual[key] != value:
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
        elif actual[key] != value:
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
    validate_bootstrap_command_profile_alignment()
    validate_bootstrap_self_hosting_scope_alignment()
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

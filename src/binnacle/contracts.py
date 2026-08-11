"""Immutable runtime projection of reviewed MCP contracts."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import posixpath
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

EXPECTED_TOOL_NAMES = (
    "binnacle_probe",
    "system_inspect",
    "probe_result_formats",
    "probe_error",
    "compatibility_report",
)
EXPECTED_REVISIONS = (
    "2026-07-28",
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
)
REGISTRY_KEYS = frozenset(
    {
        "registry_format",
        "source_manifest",
        "schema_registry_sha256",
        "revision_contract_sha256",
        "evaluation_profile_version",
        "supported_revisions",
        "revision_eras",
        "tools",
        "schemas",
        "compatibility_baseline",
        "catalogue_sha256",
    }
)
DIGEST_KEYS = frozenset(
    {
        "compiler_format",
        "compiler_version",
        "registry_sha256",
        "source_manifest_sha256",
        "schema_registry_sha256",
        "revision_contract_sha256",
        "catalogue_sha256",
    }
)
SOURCE_MANIFEST_KEYS = frozenset({"id", "version", "sha256"})
TOOL_KEYS = frozenset(
    {
        "name",
        "title",
        "description",
        "contract_version",
        "handler_binding",
        "information_class",
        "confirmation_class",
        "annotations",
        "input_schema",
        "output_schema",
    }
)
TOOL_METADATA_FIELDS = (
    "name",
    "title",
    "description",
    "contract_version",
    "information_class",
    "confirmation_class",
    "annotations",
)
SCHEMA_BINDING_KEYS = frozenset({"source_ref", "definition_sha256", "schema"})
ANNOTATION_KEYS = frozenset({"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"})
SCHEMA_DOCUMENT_PATHS = frozenset(
    {
        "schemas/mcp/binnacle-common.schema.json",
        "schemas/mcp/bootstrap-inputs.schema.json",
        "schemas/mcp/bootstrap-outputs.schema.json",
    }
)
BASELINE_KEYS = frozenset(
    {
        "profile_version",
        "observed_protocol_revision",
        "observations",
        "evidence_bundle_sha256",
        "limitations",
    }
)
OBSERVATION_KEYS = frozenset({"axis", "status", "summary"})
PHASE2_SERVER_NOT_IMPLEMENTED_AXES = frozenset(
    {
        "write_entitlement",
        "host_confirmation",
        "retry_safety",
        "cancellation",
        "reconnect",
        "concurrency",
    }
)
PHASE2_NOT_APPLICABLE_AXES = frozenset(
    {
        "resources",
        "mrtr_elicitation",
        "tasks",
        "information_boundary",
    }
)
PHASE2_BASELINE_LIMITATIONS = (
    "Only local compatibility-core server evidence exists.",
    "No real ChatGPT account, workspace, transport, or UI behavior has been observed.",
)
PHASE2_BASELINE_SUMMARIES = MappingProxyType(
    {
        "not-tested": "No real ChatGPT host evidence has been recorded.",
        "server-not-implemented": (
            "The required consequential server capability is absent in Phase 2."
        ),
        "not-applicable": "The optional probe is not promoted in the Phase 2 catalogue.",
    }
)
PHASE2_OBSERVATION_AXES = (
    "connectivity",
    "protocol_revision",
    "discovery_and_metadata",
    "tool_selection",
    "result_handling",
    "error_handling",
    "read_entitlement",
    "write_entitlement",
    "host_confirmation",
    "retry_safety",
    "cancellation",
    "reconnect",
    "concurrency",
    "resources",
    "mrtr_elicitation",
    "tasks",
    "information_boundary",
    "cross_server_behavior",
    "performance",
)
EXPECTED_HANDLER_BINDINGS = MappingProxyType(
    {
        "binnacle_probe": "binnacle.bootstrap.binnacle_probe.v1_1",
        "system_inspect": "binnacle.bootstrap.system_inspect.v1_1",
        "probe_result_formats": "binnacle.bootstrap.probe_result_formats.v1_1",
        "probe_error": "binnacle.bootstrap.probe_error.v1_1",
        "compatibility_report": "binnacle.bootstrap.compatibility_report.v1_1",
    }
)
EXPECTED_TOOL_METADATA_SHA256 = MappingProxyType(
    {
        "binnacle_probe": "f3e2e1a38773506f38448f4fd3e89d80c16896140409b36a59155c24f5dbc40c",
        "system_inspect": "fd3d9de3b68a9cb0b12be340e6f7da64f4bf53229717ef916e02f2498f2e7a86",
        "probe_result_formats": (
            "314ec24fa13f826eb5061d761aab6e4b763eee9a195d66e79f3bed35e23e69d7"
        ),
        "probe_error": "d45e3c32bcb22ac1dfce6c74c72e1e9ff41e2e8ac2b8b6e81dc21da8a93356d2",
        "compatibility_report": (
            "b87c22a3ac4370b27830ad867e3684fffb1b1944cf52cce2d826f98b0d87c493"
        ),
    }
)
EXPECTED_SOURCE_MANIFEST = MappingProxyType(
    {
        "id": "binnacle-bootstrap-tools",
        "version": "1.1.0",
        "sha256": "e2e28381067e4445c03abb5217e36c6efa63a58c3906ec1684fffa41b9e6acc1",
    }
)
EXPECTED_REGISTRY_IDENTITIES = MappingProxyType(
    {
        "schema_registry_sha256": (
            "042e862b1222641b573e2725aca24592be80a1cdd8d66214e1bc5f1f5ce9dfb1"
        ),
        "revision_contract_sha256": (
            "8207b7e9ea90aec37ec3bd6f2c0e688fcc0a928d234c4fee1f22a270ae787bd0"
        ),
        "evaluation_profile_version": "1.1.0",
        "catalogue_sha256": ("9ecb9823da48b65bd168930e2c3a6650eaf0d0af149ef98fd3a6d36fd873194a"),
    }
)


class ContractRegistryError(RuntimeError):
    """Generated registry, schema, or binding integrity is invalid."""


class InputContractError(ValueError):
    """Tool arguments fail the exact compiled input schema."""


class OutputContractError(RuntimeError):
    """A Tool result fails the exact compiled output schema."""


@dataclass(frozen=True, slots=True)
class SchemaBinding:
    source_ref: str
    definition_sha256: str
    schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    title: str
    description: str
    contract_version: str
    handler_binding: str
    information_class: str
    confirmation_class: str
    annotations: Mapping[str, bool]
    input_schema: SchemaBinding
    output_schema: SchemaBinding


@dataclass(frozen=True, slots=True)
class ContractRegistry:
    manifest_id: str
    manifest_version: str
    manifest_sha256: str
    schema_registry_sha256: str
    revision_contract_sha256: str
    catalogue_sha256: str
    evaluation_profile_version: str
    supported_revisions: tuple[str, ...]
    revision_eras: Mapping[str, str]
    tools: Mapping[str, ToolContract]
    compatibility_baseline: Mapping[str, Any]
    _input_validators: Mapping[str, Draft202012Validator] = field(repr=False)
    _output_validators: Mapping[str, Draft202012Validator] = field(repr=False)

    @classmethod
    def load(cls) -> ContractRegistry:
        generated = resources.files("binnacle._generated")
        registry_bytes = generated.joinpath("compatibility_core_registry.json").read_bytes()
        digest_bytes = generated.joinpath("compatibility_core_registry.digest.json").read_bytes()
        return cls.from_bytes(registry_bytes=registry_bytes, digest_bytes=digest_bytes)

    @classmethod
    def from_bytes(
        cls,
        *,
        registry_bytes: bytes,
        digest_bytes: bytes,
    ) -> ContractRegistry:
        try:
            registry = json.loads(registry_bytes)
            digest = json.loads(digest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractRegistryError(f"generated registry JSON is invalid: {exc}") from exc
        if not isinstance(registry, dict) or not isinstance(digest, dict):
            raise ContractRegistryError("generated registry and digest must be objects")
        _require_exact_keys(registry, REGISTRY_KEYS, "registry")
        _require_exact_keys(digest, DIGEST_KEYS, "digest")

        actual_registry_digest = hashlib.sha256(registry_bytes).hexdigest()
        if digest.get("registry_sha256") != actual_registry_digest:
            raise ContractRegistryError("generated registry digest mismatch")
        if registry.get("registry_format") != "binnacle-compatibility-core-v1":
            raise ContractRegistryError("unsupported generated registry format")
        if digest.get("compiler_format") != registry.get("registry_format"):
            raise ContractRegistryError("detached compiler format mismatch")
        if digest.get("compiler_version") != "1.0.0":
            raise ContractRegistryError("unsupported registry compiler version")

        for registry_key, digest_key in (
            ("schema_registry_sha256", "schema_registry_sha256"),
            ("revision_contract_sha256", "revision_contract_sha256"),
            ("catalogue_sha256", "catalogue_sha256"),
        ):
            if registry.get(registry_key) != digest.get(digest_key):
                raise ContractRegistryError(f"detached {registry_key} mismatch")

        source_manifest = _require_mapping(registry.get("source_manifest"), "source_manifest")
        _require_exact_keys(source_manifest, SOURCE_MANIFEST_KEYS, "source_manifest")
        if source_manifest.get("sha256") != digest.get("source_manifest_sha256"):
            raise ContractRegistryError("detached source manifest digest mismatch")

        schemas = _require_mapping(registry.get("schemas"), "schemas")
        _require_exact_keys(schemas, SCHEMA_DOCUMENT_PATHS, "schemas")
        actual_schema_registry_digest = _canonical_sha256(schemas)
        if actual_schema_registry_digest != registry.get("schema_registry_sha256"):
            raise ContractRegistryError("compiled schema registry digest mismatch")

        revisions = registry.get("supported_revisions")
        if not isinstance(revisions, list) or tuple(revisions) != EXPECTED_REVISIONS:
            raise ContractRegistryError("generated revision set is not the reviewed finite set")
        revision_eras = _require_mapping(registry.get("revision_eras"), "revision_eras")
        if revision_eras != {
            EXPECTED_REVISIONS[0]: "modern",
            **{revision: "legacy" for revision in EXPECTED_REVISIONS[1:]},
        }:
            raise ContractRegistryError("generated revision eras are invalid")

        raw_tools = registry.get("tools")
        if not isinstance(raw_tools, list):
            raise ContractRegistryError("generated tools must be an array")
        if tuple(tool.get("name") for tool in raw_tools if isinstance(tool, dict)) != (
            EXPECTED_TOOL_NAMES
        ):
            raise ContractRegistryError("generated catalogue is not exactly compatibility-core")
        if _canonical_sha256(raw_tools) != registry.get("catalogue_sha256"):
            raise ContractRegistryError("compiled catalogue digest mismatch")

        tools: dict[str, ToolContract] = {}
        input_validators: dict[str, Draft202012Validator] = {}
        output_validators: dict[str, Draft202012Validator] = {}
        for raw_tool in raw_tools:
            tool = _parse_tool(_require_mapping(raw_tool, "tool"), schemas=schemas)
            if "probe_workspace" in tool.handler_binding:
                raise ContractRegistryError("write-probe binding is visible")
            _validate_handler_binding(tool.handler_binding)
            if tool.handler_binding != EXPECTED_HANDLER_BINDINGS[tool.name]:
                raise ContractRegistryError(
                    f"handler binding does not match reviewed projection: {tool.name}"
                )
            input_schema = mutable_json_object(tool.input_schema.schema)
            output_schema = mutable_json_object(tool.output_schema.schema)
            try:
                Draft202012Validator.check_schema(input_schema)
                Draft202012Validator.check_schema(output_schema)
            except Exception as exc:
                raise ContractRegistryError(f"invalid schema for {tool.name}: {exc}") from exc
            tools[tool.name] = tool
            input_validators[tool.name] = Draft202012Validator(input_schema)
            output_validators[tool.name] = Draft202012Validator(output_schema)

        baseline = _require_mapping(
            registry.get("compatibility_baseline"), "compatibility_baseline"
        )
        _validate_compatibility_baseline(
            baseline,
            evaluation_profile_version=_require_string(
                registry,
                "evaluation_profile_version",
            ),
        )
        if source_manifest != EXPECTED_SOURCE_MANIFEST:
            raise ContractRegistryError(
                "generated source manifest does not match the reviewed Phase 2 identity"
            )
        for key, expected_value in EXPECTED_REGISTRY_IDENTITIES.items():
            if registry.get(key) != expected_value:
                raise ContractRegistryError(
                    f"generated {key} does not match the reviewed Phase 2 identity"
                )
        return cls(
            manifest_id=_require_string(source_manifest, "id"),
            manifest_version=_require_string(source_manifest, "version"),
            manifest_sha256=_require_string(source_manifest, "sha256"),
            schema_registry_sha256=_require_string(registry, "schema_registry_sha256"),
            revision_contract_sha256=_require_string(registry, "revision_contract_sha256"),
            catalogue_sha256=_require_string(registry, "catalogue_sha256"),
            evaluation_profile_version=_require_string(registry, "evaluation_profile_version"),
            supported_revisions=tuple(revisions),
            revision_eras=MappingProxyType(dict(revision_eras)),
            tools=MappingProxyType(tools),
            compatibility_baseline=_freeze_mapping(baseline),
            _input_validators=MappingProxyType(input_validators),
            _output_validators=MappingProxyType(output_validators),
        )

    def validate_input(self, tool_name: str, value: Mapping[str, object]) -> None:
        self._validate(self._input_validators, tool_name, value, InputContractError)

    def validate_output(self, tool_name: str, value: Mapping[str, object]) -> None:
        self._validate(self._output_validators, tool_name, value, OutputContractError)

    @staticmethod
    def _validate(
        validators: Mapping[str, Draft202012Validator],
        tool_name: str,
        value: Mapping[str, object],
        error_type: type[InputContractError] | type[OutputContractError],
    ) -> None:
        validator = validators.get(tool_name)
        if validator is None:
            raise error_type(f"unknown Tool contract: {tool_name}")
        error = next(iter(validator.iter_errors(dict(value))), None)
        if error is not None:
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            keyword = error.validator if isinstance(error.validator, str) else "schema"
            raise error_type(f"{tool_name} contract failed at {location} ({keyword})")

    def era_for(self, revision: str) -> str:
        try:
            return self.revision_eras[revision]
        except KeyError as exc:
            raise InputContractError(f"unsupported MCP revision: {revision}") from exc


def _require_mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractRegistryError(f"generated {context} must be an object")
    return value


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ContractRegistryError(f"generated {key} must be a non-empty string")
    return value


def _require_exact_keys(
    mapping: Mapping[str, Any],
    expected: frozenset[str],
    context: str,
) -> None:
    actual = frozenset(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractRegistryError(
            f"generated {context} keys are not closed (missing={missing}, extra={extra})"
        )


def _canonical_sha256(value: Any) -> str:
    normalized = _normalize(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mutable_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached mutable JSON object from a frozen registry mapping."""

    return {str(key): _thaw_json(child) for key, child in value.items()}


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(child) for child in value]
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _freeze_json(child) for key, child in value.items()})


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
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


def _parse_schema(
    value: object,
    context: str,
    *,
    schemas: Mapping[str, Any],
) -> SchemaBinding:
    raw = _require_mapping(value, context)
    _require_exact_keys(raw, SCHEMA_BINDING_KEYS, context)
    schema = _require_mapping(raw.get("schema"), f"{context}.schema")
    definition_sha256 = _require_string(raw, "definition_sha256")
    if _canonical_sha256(schema) != definition_sha256:
        raise ContractRegistryError(f"generated {context} definition digest mismatch")
    source_ref = _require_string(raw, "source_ref")
    resolved_source = _resolve_schema_source(source_ref, schemas, context=context)
    if _canonical_sha256(resolved_source) != definition_sha256:
        raise ContractRegistryError(f"generated {context} does not match source_ref")
    return SchemaBinding(
        source_ref=source_ref,
        definition_sha256=definition_sha256,
        schema=_freeze_mapping(schema),
    )


def _parse_tool(
    raw: dict[str, Any],
    *,
    schemas: Mapping[str, Any],
) -> ToolContract:
    _require_exact_keys(raw, TOOL_KEYS, "tool")
    raw_annotations = _require_mapping(raw.get("annotations"), "annotations")
    _require_exact_keys(raw_annotations, ANNOTATION_KEYS, "annotations")
    annotations: dict[str, bool] = {}
    for key, value in raw_annotations.items():
        if not isinstance(value, bool):
            raise ContractRegistryError(f"Tool annotation {key} must be boolean")
        annotations[key] = value
    name = _require_string(raw, "name")
    title = _require_string(raw, "title")
    description = _require_string(raw, "description")
    contract_version = _require_string(raw, "contract_version")
    handler_binding = _require_string(raw, "handler_binding")
    information_class = _require_string(raw, "information_class")
    confirmation_class = _require_string(raw, "confirmation_class")
    metadata_projection = {field: raw.get(field) for field in TOOL_METADATA_FIELDS}
    expected_metadata_sha256 = EXPECTED_TOOL_METADATA_SHA256.get(name)
    if (
        expected_metadata_sha256 is None
        or _canonical_sha256(metadata_projection) != expected_metadata_sha256
    ):
        raise ContractRegistryError(f"Tool metadata does not match reviewed projection: {name}")
    return ToolContract(
        name=name,
        title=title,
        description=description,
        contract_version=contract_version,
        handler_binding=handler_binding,
        information_class=information_class,
        confirmation_class=confirmation_class,
        annotations=MappingProxyType(annotations),
        input_schema=_parse_schema(
            raw.get("input_schema"),
            "input_schema",
            schemas=schemas,
        ),
        output_schema=_parse_schema(
            raw.get("output_schema"),
            "output_schema",
            schemas=schemas,
        ),
    )


def _resolve_schema_source(
    source_ref: str,
    schemas: Mapping[str, Any],
    *,
    context: str,
) -> dict[str, Any]:
    try:
        path, fragment = _schema_target(source_ref, current_path=None)
        selected = _json_pointer_get(_schema_document(schemas, path), fragment)
        resolved = _resolve_schema_value(
            selected,
            current_path=path,
            schemas=schemas,
            stack=(),
        )
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ContractRegistryError(f"generated {context} source_ref is invalid") from exc
    if not isinstance(resolved, dict):
        raise ContractRegistryError(f"generated {context} source_ref is not an object")
    return resolved


def _resolve_schema_value(
    value: Any,
    *,
    current_path: str,
    schemas: Mapping[str, Any],
    stack: tuple[str, ...],
) -> Any:
    if isinstance(value, list):
        return [
            _resolve_schema_value(
                item,
                current_path=current_path,
                schemas=schemas,
                stack=stack,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    reference = value.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise ValueError("schema $ref must be a string")
        target_path, fragment = _schema_target(reference, current_path=current_path)
        cycle_key = f"{target_path}#{fragment}"
        if cycle_key in stack:
            raise ValueError("recursive schema reference")
        selected = _json_pointer_get(_schema_document(schemas, target_path), fragment)
        resolved = _resolve_schema_value(
            selected,
            current_path=target_path,
            schemas=schemas,
            stack=(*stack, cycle_key),
        )
        if not isinstance(resolved, dict):
            raise ValueError("schema reference did not resolve to an object")
        siblings = {
            key: _resolve_schema_value(
                child,
                current_path=current_path,
                schemas=schemas,
                stack=stack,
            )
            for key, child in value.items()
            if key != "$ref"
        }
        return {**resolved, **siblings}

    return {
        key: _resolve_schema_value(
            child,
            current_path=current_path,
            schemas=schemas,
            stack=stack,
        )
        for key, child in value.items()
    }


def _schema_target(reference: str, *, current_path: str | None) -> tuple[str, str]:
    if reference.startswith("#"):
        if current_path is None:
            raise ValueError("top-level schema reference requires a path")
        return current_path, reference[1:]

    parsed = urlparse(reference)
    if parsed.scheme in ("http", "https"):
        prefix = "/schemas/"
        if prefix not in parsed.path:
            raise ValueError("external schema reference is outside the allowlist")
        path = f"schemas/{parsed.path.split(prefix, 1)[1]}"
        fragment = parsed.fragment
    else:
        path_part, separator, fragment = reference.partition("#")
        if path_part.startswith("schemas/"):
            path = posixpath.normpath(path_part)
        elif current_path is not None:
            path = posixpath.normpath(posixpath.join(posixpath.dirname(current_path), path_part))
        else:
            raise ValueError("top-level schema reference requires a reviewed path")
        if not separator:
            fragment = ""

    if path not in SCHEMA_DOCUMENT_PATHS:
        raise ValueError("schema reference is outside the reviewed allowlist")
    return path, fragment


def _schema_document(schemas: Mapping[str, Any], path: str) -> dict[str, Any]:
    document = schemas.get(path)
    if not isinstance(document, dict):
        raise TypeError("schema document must be an object")
    return document


def _json_pointer_get(document: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return document
    if not pointer.startswith("/"):
        raise ValueError("schema fragment must be a JSON pointer")
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


def _validate_compatibility_baseline(
    baseline: dict[str, Any],
    *,
    evaluation_profile_version: str,
) -> None:
    _require_exact_keys(baseline, BASELINE_KEYS, "compatibility_baseline")
    if _require_string(baseline, "profile_version") != evaluation_profile_version:
        raise ContractRegistryError("generated compatibility profile version mismatch")
    if baseline.get("observed_protocol_revision") is not None:
        raise ContractRegistryError("Phase 2 baseline must not claim an observed revision")
    if baseline.get("evidence_bundle_sha256") is not None:
        raise ContractRegistryError("Phase 2 baseline must not claim a live evidence bundle")
    limitations = baseline.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(value, str) and value for value in limitations)
    ):
        raise ContractRegistryError("generated compatibility limitations are invalid")
    if tuple(limitations) != PHASE2_BASELINE_LIMITATIONS:
        raise ContractRegistryError(
            "generated compatibility limitations do not match the Phase 2 baseline"
        )
    observations = baseline.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ContractRegistryError("generated compatibility observations are invalid")
    axes: list[str] = []
    seen_axes: set[str] = set()
    for value in observations:
        observation = _require_mapping(value, "compatibility observation")
        _require_exact_keys(observation, OBSERVATION_KEYS, "compatibility observation")
        axis = _require_string(observation, "axis")
        status = _require_string(observation, "status")
        summary = _require_string(observation, "summary")
        if axis in PHASE2_SERVER_NOT_IMPLEMENTED_AXES:
            expected_status = "server-not-implemented"
        elif axis in PHASE2_NOT_APPLICABLE_AXES:
            expected_status = "not-applicable"
        else:
            expected_status = "not-tested"
        if status != expected_status:
            raise ContractRegistryError(
                "generated compatibility observation violates the Phase 2 status classification"
            )
        if summary != PHASE2_BASELINE_SUMMARIES[expected_status]:
            raise ContractRegistryError(
                "generated compatibility observation summary does not match the Phase 2 baseline"
            )
        if axis in seen_axes:
            raise ContractRegistryError("generated compatibility observation axis is duplicated")
        seen_axes.add(axis)
        axes.append(axis)
    if tuple(axes) != PHASE2_OBSERVATION_AXES:
        raise ContractRegistryError(
            "generated compatibility observation axis projection does not match Phase 2"
        )


def _validate_handler_binding(binding: str) -> None:
    module_name, separator, attribute_name = binding.rpartition(".")
    if not separator:
        raise ContractRegistryError(f"invalid handler binding: {binding}")
    try:
        module = importlib.import_module(module_name)
        handler = getattr(module, attribute_name)
    except (ImportError, AttributeError) as exc:
        raise ContractRegistryError(f"handler binding is unavailable: {binding}") from exc
    if not inspect.iscoroutinefunction(handler):
        raise ContractRegistryError(f"handler binding is not async: {binding}")

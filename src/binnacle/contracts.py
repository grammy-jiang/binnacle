"""Immutable runtime projection of reviewed MCP contracts."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType
from typing import Any

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
            tool = _parse_tool(_require_mapping(raw_tool, "tool"))
            if "probe_workspace" in tool.handler_binding:
                raise ContractRegistryError("write-probe binding is visible")
            _validate_handler_binding(tool.handler_binding)
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


def _parse_schema(value: object, context: str) -> SchemaBinding:
    raw = _require_mapping(value, context)
    _require_exact_keys(raw, SCHEMA_BINDING_KEYS, context)
    schema = _require_mapping(raw.get("schema"), f"{context}.schema")
    definition_sha256 = _require_string(raw, "definition_sha256")
    if _canonical_sha256(schema) != definition_sha256:
        raise ContractRegistryError(f"generated {context} definition digest mismatch")
    return SchemaBinding(
        source_ref=_require_string(raw, "source_ref"),
        definition_sha256=definition_sha256,
        schema=_freeze_mapping(schema),
    )


def _parse_tool(raw: dict[str, Any]) -> ToolContract:
    _require_exact_keys(raw, TOOL_KEYS, "tool")
    raw_annotations = _require_mapping(raw.get("annotations"), "annotations")
    _require_exact_keys(raw_annotations, ANNOTATION_KEYS, "annotations")
    annotations: dict[str, bool] = {}
    for key, value in raw_annotations.items():
        if not isinstance(value, bool):
            raise ContractRegistryError(f"Tool annotation {key} must be boolean")
        annotations[key] = value
    return ToolContract(
        name=_require_string(raw, "name"),
        title=_require_string(raw, "title"),
        description=_require_string(raw, "description"),
        contract_version=_require_string(raw, "contract_version"),
        handler_binding=_require_string(raw, "handler_binding"),
        information_class=_require_string(raw, "information_class"),
        confirmation_class=_require_string(raw, "confirmation_class"),
        annotations=MappingProxyType(annotations),
        input_schema=_parse_schema(raw.get("input_schema"), "input_schema"),
        output_schema=_parse_schema(raw.get("output_schema"), "output_schema"),
    )


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
    observations = baseline.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ContractRegistryError("generated compatibility observations are invalid")
    axes: set[str] = set()
    for value in observations:
        observation = _require_mapping(value, "compatibility observation")
        _require_exact_keys(observation, OBSERVATION_KEYS, "compatibility observation")
        axis = _require_string(observation, "axis")
        _require_string(observation, "status")
        _require_string(observation, "summary")
        if axis in axes:
            raise ContractRegistryError("generated compatibility observation axis is duplicated")
        axes.add(axis)


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

"""Tests for the fail-closed generated runtime contract registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from binnacle.contracts import (
    EXPECTED_REVISIONS,
    EXPECTED_TOOL_NAMES,
    ContractRegistry,
    ContractRegistryError,
    InputContractError,
    OutputContractError,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "src/binnacle/_generated/compatibility_core_registry.json"
DIGEST_PATH = ROOT / "src/binnacle/_generated/compatibility_core_registry.digest.json"


def _documents() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8")),
        json.loads(DIGEST_PATH.read_text(encoding="utf-8")),
    )


def _encoded(
    registry: dict[str, Any],
    digest: dict[str, Any],
) -> tuple[bytes, bytes]:
    registry_bytes = (
        json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    digest["registry_sha256"] = hashlib.sha256(registry_bytes).hexdigest()
    digest_bytes = (
        json.dumps(digest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    return registry_bytes, digest_bytes


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _refresh_catalogue_digest(
    registry: dict[str, Any],
    digest: dict[str, Any],
) -> None:
    catalogue_sha256 = _canonical_sha256(registry["tools"])
    registry["catalogue_sha256"] = catalogue_sha256
    digest["catalogue_sha256"] = catalogue_sha256


def test_load_returns_exact_immutable_catalogue(
    contract_registry: ContractRegistry,
) -> None:
    assert tuple(contract_registry.tools) == EXPECTED_TOOL_NAMES
    assert contract_registry.supported_revisions == EXPECTED_REVISIONS
    assert contract_registry.era_for(EXPECTED_REVISIONS[0]) == "modern"
    assert contract_registry.era_for(EXPECTED_REVISIONS[-1]) == "legacy"
    with pytest.raises(TypeError):
        contract_registry.tools["extra"] = contract_registry.tools["binnacle_probe"]  # type: ignore[index]

    input_schema = contract_registry.tools["probe_result_formats"].input_schema.schema
    properties = input_schema["properties"]
    assert isinstance(properties, Mapping)
    with pytest.raises(TypeError):
        properties["extra"] = {}  # type: ignore[index]

    observations = contract_registry.compatibility_baseline["observations"]
    assert isinstance(observations, tuple)
    with pytest.raises(TypeError):
        observations[0]["status"] = "observed-supported"


def test_input_and_output_validation_fail_closed(
    contract_registry: ContractRegistry,
) -> None:
    contract_registry.validate_input("binnacle_probe", {})
    contract_registry.validate_input("probe_result_formats", {"array_length": 16})

    with pytest.raises(InputContractError, match="array_length"):
        contract_registry.validate_input("probe_result_formats", {"array_length": 17})
    with pytest.raises(InputContractError, match="unknown Tool"):
        contract_registry.validate_input("unknown", {})
    with pytest.raises(OutputContractError, match="binnacle_probe"):
        contract_registry.validate_output("binnacle_probe", {})
    with pytest.raises(OutputContractError, match="unknown Tool"):
        contract_registry.validate_output("unknown", {})
    with pytest.raises(InputContractError, match="unsupported MCP revision"):
        contract_registry.era_for("2024-11-05")


def test_input_contract_errors_do_not_echo_untrusted_values(
    contract_registry: ContractRegistry,
) -> None:
    secret_value = "credential-like-input-that-must-not-be-echoed"

    with pytest.raises(InputContractError) as captured:
        contract_registry.validate_input(
            "probe_result_formats",
            {"array_length": secret_value},
        )

    assert "array_length" in str(captured.value)
    assert "type" in str(captured.value)
    assert secret_value not in str(captured.value)


@pytest.mark.parametrize(
    ("registry_bytes", "digest_bytes"),
    [
        (b"{", b"{}"),
        (b"[]", b"{}"),
        (b"{}", b"[]"),
    ],
)
def test_invalid_generated_json_is_rejected(
    registry_bytes: bytes,
    digest_bytes: bytes,
) -> None:
    with pytest.raises(ContractRegistryError, match="generated registry"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_detached_registry_digest_mismatch_is_rejected() -> None:
    registry_bytes = REGISTRY_PATH.read_bytes()
    digest = json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
    digest["registry_sha256"] = "0" * 64

    with pytest.raises(ContractRegistryError, match="registry digest mismatch"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=json.dumps(digest).encode(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("registry_format", "unknown"), "registry format"),
        (("schema_registry_sha256", "0" * 64), "schema_registry_sha256"),
        (("revision_contract_sha256", "0" * 64), "revision_contract_sha256"),
        (("catalogue_sha256", "0" * 64), "catalogue_sha256"),
    ],
)
def test_registry_metadata_drift_is_rejected(
    mutation: tuple[str, str],
    message: str,
) -> None:
    registry, digest = _documents()
    registry[mutation[0]] = mutation[1]
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_source_manifest_digest_drift_is_rejected() -> None:
    registry, digest = _documents()
    registry["source_manifest"]["sha256"] = "0" * 64
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="source manifest"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_self_consistent_source_manifest_drift_is_rejected() -> None:
    registry, digest = _documents()
    registry["source_manifest"] = {
        "id": "unreviewed-manifest",
        "version": "9.9.9",
        "sha256": "a" * 64,
    }
    digest["source_manifest_sha256"] = "a" * 64
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="reviewed Phase 2 identity"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_self_consistent_evaluation_profile_version_drift_is_rejected() -> None:
    registry, digest = _documents()
    registry["evaluation_profile_version"] = "9.9.9"
    registry["compatibility_baseline"]["profile_version"] = "9.9.9"
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="reviewed Phase 2 identity"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("document", "key", "message"),
    [
        ("registry", "unexpected", "registry keys are not closed"),
        ("digest", "unexpected", "digest keys are not closed"),
        ("source_manifest", "unexpected", "source_manifest keys are not closed"),
    ],
)
def test_generated_metadata_objects_are_closed(
    document: str,
    key: str,
    message: str,
) -> None:
    registry, digest = _documents()
    target = (
        registry
        if document == "registry"
        else digest
        if document == "digest"
        else registry["source_manifest"]
    )
    target[key] = True
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_schema_registry_digest_is_recomputed() -> None:
    registry, digest = _documents()
    registry["schemas"]["schemas/mcp/binnacle-common.schema.json"]["title"] = "drift"
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="schema registry digest mismatch"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_selected_schema_definition_digest_is_recomputed() -> None:
    registry, digest = _documents()
    registry["tools"][0]["input_schema"]["schema"]["description"] = "valid drift"
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="definition digest mismatch"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_compiled_schema_must_match_its_embedded_source_reference() -> None:
    registry, digest = _documents()
    binding = registry["tools"][0]["input_schema"]
    binding["schema"]["description"] = "self-consistent compiled drift"
    binding["definition_sha256"] = _canonical_sha256(binding["schema"])
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="does not match source_ref"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_compiled_catalogue_digest_is_recomputed() -> None:
    registry, digest = _documents()
    registry["tools"][0]["title"] = "drift"
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="catalogue digest mismatch"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("observed_protocol_revision", "2026-07-28"), "must not claim"),
        (("evidence_bundle_sha256", "a" * 64), "must not claim"),
        (("profile_version", "9.9.9"), "profile version mismatch"),
        (("limitations", []), "limitations are invalid"),
    ],
)
def test_compatibility_baseline_cannot_claim_live_evidence_or_drift(
    mutation: tuple[str, object],
    message: str,
) -> None:
    registry, digest = _documents()
    registry["compatibility_baseline"][mutation[0]] = mutation[1]
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("axis", "status"),
    [
        ("connectivity", "observed-supported"),
        ("write_entitlement", "not-tested"),
        ("resources", "server-not-implemented"),
    ],
)
def test_compatibility_baseline_statuses_match_phase2_classification(
    axis: str,
    status: str,
) -> None:
    registry, digest = _documents()
    observation = next(
        value
        for value in registry["compatibility_baseline"]["observations"]
        if value["axis"] == axis
    )
    observation["status"] = status
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="Phase 2 status classification"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize("field", ["summary", "limitations"])
def test_compatibility_baseline_prose_cannot_claim_live_host_evidence(field: str) -> None:
    registry, digest = _documents()
    baseline = registry["compatibility_baseline"]
    if field == "summary":
        baseline["observations"][0]["summary"] = "Observed real ChatGPT support."
    else:
        baseline["limitations"][0] = "Real ChatGPT host behavior was verified."
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="Phase 2 baseline"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize("mutation", ["remove", "replace", "reorder"])
def test_compatibility_baseline_requires_exact_phase2_axis_projection(
    mutation: str,
) -> None:
    registry, digest = _documents()
    observations = registry["compatibility_baseline"]["observations"]
    if mutation == "remove":
        observations.pop()
    elif mutation == "replace":
        observations[0]["axis"] = "unreviewed_axis"
    else:
        observations.reverse()
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="axis projection"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("supported_revisions", ["2026-07-28"], "revision set"),
        ("revision_eras", {"2026-07-28": "legacy"}, "revision eras"),
        ("tools", {}, "tools must be an array"),
    ],
)
def test_closed_revision_and_tool_shapes_are_enforced(
    field: str,
    value: object,
    message: str,
) -> None:
    registry, digest = _documents()
    registry[field] = value
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_tool_order_drift_is_rejected() -> None:
    registry, digest = _documents()
    registry["tools"] = list(reversed(registry["tools"]))
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="exactly compatibility-core"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        ("binnacle.bootstrap.probe_workspace_write.v1_1", "write-probe"),
        ("binnacle.bootstrap.missing.v1_1", "binding is unavailable"),
        ("binnacle.domain.mcp.to_json_value", "binding is not async"),
        ("missing_separator", "invalid handler binding"),
    ],
)
def test_invalid_handler_binding_aborts_registry_load(
    binding: str,
    message: str,
) -> None:
    registry, digest = _documents()
    registry["tools"][0]["handler_binding"] = binding
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_handler_binding_must_match_the_reviewed_tool_projection() -> None:
    registry, digest = _documents()
    registry["tools"][0]["handler_binding"] = "binnacle.bootstrap.compatibility_report.v1_1"
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="reviewed projection"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Unreviewed Tool title"),
        ("description", "Unreviewed model-facing behavior."),
        ("contract_version", "9.9"),
        ("information_class", "restricted-result"),
        ("confirmation_class", "HC3"),
        (
            "annotations",
            {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
    ],
)
def test_all_model_facing_tool_metadata_matches_the_reviewed_projection(
    field: str,
    value: object,
) -> None:
    registry, digest = _documents()
    registry["tools"][0][field] = value
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="metadata does not match reviewed"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_invalid_compiled_schema_aborts_registry_load() -> None:
    registry, digest = _documents()
    invalid_schema = {"type": "not-a-type"}
    registry["tools"][0]["input_schema"]["schema"] = invalid_schema
    registry["tools"][0]["input_schema"]["definition_sha256"] = _canonical_sha256(
        registry["tools"][0]["input_schema"]["schema"]
    )
    registry["schemas"]["schemas/mcp/bootstrap-inputs.schema.json"]["$defs"][
        "binnacle_probe.input.v1_1"
    ] = invalid_schema
    schema_registry_sha256 = _canonical_sha256(registry["schemas"])
    registry["schema_registry_sha256"] = schema_registry_sha256
    digest["schema_registry_sha256"] = schema_registry_sha256
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match="invalid schema"):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("annotations", {"readOnlyHint": "yes"}, "annotation"),
        ("input_schema", [], "input_schema"),
        ("title", "", "title"),
    ],
)
def test_invalid_tool_metadata_aborts_registry_load(
    field: str,
    value: object,
    message: str,
) -> None:
    registry, digest = _documents()
    registry["tools"][0][field] = value
    _refresh_catalogue_digest(registry, digest)
    registry_bytes, digest_bytes = _encoded(registry, digest)

    with pytest.raises(ContractRegistryError, match=message):
        ContractRegistry.from_bytes(
            registry_bytes=registry_bytes,
            digest_bytes=digest_bytes,
        )


def test_reviewed_hyphenated_identifier_requires_no_schema_change() -> None:
    common = json.loads(
        (ROOT / "schemas/mcp/binnacle-common.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(common["$defs"]["identifier"])

    assert not list(validator.iter_errors("binnacle-bootstrap-tools"))
    for invalid in (
        " leading",
        "contains/slash",
        "line\nbreak",
        ".leading-punctuation",
        "binnacle" + chr(0x2010) + "bootstrap",
        "binnacle" + chr(0x200B) + "bootstrap",
    ):
        assert list(validator.iter_errors(invalid)), invalid

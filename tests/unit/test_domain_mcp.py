"""Tests for framework-independent MCP domain serialization."""

from dataclasses import FrozenInstanceError

import pytest

from binnacle.domain.mcp import (
    BinnacleError,
    CataloguePhase,
    DiagnosticFact,
    ExecutionErrorEnvelope,
    ProbeErrorCase,
    ProtocolEra,
    SuccessEnvelope,
    ToolIdentity,
    WarningRecord,
    envelope_to_mapping,
    to_json_value,
)


def test_success_envelope_serializes_nested_immutable_values() -> None:
    envelope = SuccessEnvelope(
        schema_version="1.1",
        call_status="succeeded",
        tool=ToolIdentity(name="probe_result_formats", contract_version="1.1"),
        request_id="req_fixture",
        data={
            "era": ProtocolEra.MODERN,
            "phase": CataloguePhase.COMPATIBILITY_CORE,
            "items": (1, True, None),
        },
        warnings=(WarningRecord(code="fixture_warning", message="Fixture warning."),),
    )

    value = envelope_to_mapping(envelope)

    assert value["operation"] is None
    assert value["data"] == {
        "era": "modern",
        "phase": "compatibility-core",
        "items": [1, True, None],
    }
    assert value["warnings"] == [{"code": "fixture_warning", "message": "Fixture warning."}]


def test_execution_error_serializes_diagnostic_facts() -> None:
    envelope = ExecutionErrorEnvelope(
        schema_version="1.1",
        call_status="execution_error",
        tool=ToolIdentity(name="probe_error", contract_version="1.1"),
        request_id="req_error",
        error=BinnacleError(
            code="policy_rejected",
            message="Synthetic policy rejection.",
            retryable=False,
            retry_action="none",
            details=(DiagnosticFact(name="case", value="policy_rejection"),),
        ),
    )

    value = envelope_to_mapping(envelope)

    assert value["error"] == {
        "code": "policy_rejected",
        "message": "Synthetic policy rejection.",
        "retryable": False,
        "retry_action": "none",
        "operation_id": None,
        "details": [
            {
                "name": "case",
                "value": "policy_rejection",
                "classification": "normal-result",
            }
        ],
    }


def test_unsupported_serialization_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="unsupported domain serialization type"):
        to_json_value({"not-json"})


def test_domain_values_are_frozen() -> None:
    warning = WarningRecord(code="code", message="message")

    with pytest.raises(FrozenInstanceError):
        warning.code = "changed"  # type: ignore[misc]


def test_probe_error_case_is_closed() -> None:
    assert tuple(case.value for case in ProbeErrorCase) == (
        "invalid_input",
        "policy_rejection",
        "known_execution_failure",
        "timeout",
        "uncertain_outcome",
        "bounded_delay",
    )

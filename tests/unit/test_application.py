"""Tests for the framework-independent application lifecycle."""

import pytest
from tests.conftest import FakeSystemInspector

from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    BinnacleProbeRequest,
    CompatibilityReportRequest,
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeErrorCase,
    ProbeErrorRequest,
    ProbeResultFormatsRequest,
    ProtocolEra,
    SystemInspectRequest,
    envelope_to_mapping,
)
from binnacle.domain.runtime import PackageIdentity
from binnacle.domain.system import (
    DEFAULT_SYSTEM_SECTIONS,
    InspectionError,
    SystemSection,
    SystemSnapshot,
)


def _context() -> McpCallContext:
    return McpCallContext(
        revision="2026-07-28",
        era=ProtocolEra.MODERN,
        request_id="req_fixture",
    )


@pytest.mark.anyio
async def test_application_start_is_idempotent(package_identity: PackageIdentity) -> None:
    application = BinnacleApplication(identity=package_identity)

    await application.start()
    await application.start()

    assert application.is_started
    assert application.identity is package_identity


@pytest.mark.anyio
async def test_application_stop_is_idempotent(package_identity: PackageIdentity) -> None:
    application = BinnacleApplication(identity=package_identity)
    await application.start()

    await application.stop()
    await application.stop()

    assert not application.is_started


@pytest.mark.anyio
async def test_application_readiness_requires_exact_composition(
    package_identity: PackageIdentity,
    contract_registry: ContractRegistry,
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    application = BinnacleApplication(
        identity=package_identity,
        compatibility=compatibility_use_cases,
        contracts=contract_registry,
    )
    assert not application.is_ready

    application.set_registered_tool_count(5)
    await application.start()
    assert application.is_ready
    assert application.compatibility is compatibility_use_cases
    assert application.contracts is contract_registry

    application.set_registered_tool_count(4)
    assert not application.is_ready
    await application.stop()
    assert not application.is_ready


def test_uncomposed_application_dependencies_fail_closed(
    package_identity: PackageIdentity,
) -> None:
    application = BinnacleApplication(identity=package_identity)

    with pytest.raises(RuntimeError, match="use cases"):
        _ = application.compatibility
    with pytest.raises(RuntimeError, match="contract registry"):
        _ = application.contracts


@pytest.mark.anyio
async def test_binnacle_probe_maps_build_device_manifest_and_context(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await compatibility_use_cases.binnacle_probe(
        BinnacleProbeRequest(),
        _context(),
    )
    value = envelope_to_mapping(result)

    assert value["request_id"] == "req_fixture"
    data = value["data"]
    assert isinstance(data, dict)
    assert data["build_sha256"] == "a" * 64
    assert data["device_id"] == "device_fixture"
    assert data["protocol_revision"] == "2026-07-28"
    assert data["protocol_era"] == "modern"
    assert data["catalogue_phase"] == "compatibility-core"
    assert data["request_correlation_id"] == "req_fixture"


@pytest.mark.anyio
async def test_system_inspect_defaults_and_canonicalizes_sections(
    compatibility_use_cases: CompatibilityUseCases,
    fake_system_inspector: FakeSystemInspector,
) -> None:
    default_result = await compatibility_use_cases.system_inspect(
        SystemInspectRequest(),
        _context(),
    )
    explicit_result = await compatibility_use_cases.system_inspect(
        SystemInspectRequest(
            sections=(SystemSection.MEMORY, SystemSection.OS, SystemSection.MEMORY)
        ),
        _context(),
    )

    assert fake_system_inspector.requests == [
        DEFAULT_SYSTEM_SECTIONS,
        (SystemSection.OS, SystemSection.MEMORY),
    ]
    default_value = envelope_to_mapping(default_result)
    assert default_value["call_status"] == "succeeded"
    explicit_value = envelope_to_mapping(explicit_result)
    explicit_data = explicit_value["data"]
    assert isinstance(explicit_data, dict)
    assert explicit_data["returned_sections"] == ["os", "memory"]


@pytest.mark.anyio
async def test_system_inspection_failure_becomes_execution_error(
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingInspector:
        async def inspect(
            self,
            sections: tuple[SystemSection, ...],
        ) -> SystemSnapshot:
            del sections
            raise InspectionError("fixture inspection failed")

    monkeypatch.setattr(
        compatibility_use_cases,
        "_system_inspector",
        FailingInspector(),
    )

    result = await compatibility_use_cases.system_inspect(
        SystemInspectRequest(),
        _context(),
    )

    assert isinstance(result, ExecutionErrorEnvelope)
    assert result.error.code == "inspection_failed"
    assert result.error.retryable is False


@pytest.mark.anyio
async def test_incomplete_system_snapshot_becomes_execution_error(
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IncompleteInspector:
        async def inspect(
            self,
            sections: tuple[SystemSection, ...],
        ) -> SystemSnapshot:
            return SystemSnapshot(
                hostname="fixture",
                returned_sections=sections,
            )

    monkeypatch.setattr(
        compatibility_use_cases,
        "_system_inspector",
        IncompleteInspector(),
    )

    result = await compatibility_use_cases.system_inspect(
        SystemInspectRequest(sections=(SystemSection.OS,)),
        _context(),
    )

    assert isinstance(result, ExecutionErrorEnvelope)
    assert result.error.code == "inspection_failed"


@pytest.mark.anyio
@pytest.mark.parametrize("array_length", [0, 1, 3, 16])
@pytest.mark.parametrize("nullable_value", [None, "fixture"])
@pytest.mark.parametrize("include_warning", [False, True])
async def test_probe_result_formats_covers_reviewed_shapes(
    compatibility_use_cases: CompatibilityUseCases,
    array_length: int,
    nullable_value: str | None,
    include_warning: bool,
) -> None:
    result = await compatibility_use_cases.probe_result_formats(
        ProbeResultFormatsRequest(
            array_length=array_length,
            nullable_value=nullable_value,
            include_warning=include_warning,
        ),
        _context(),
    )

    assert result.data.array_values == tuple(range(array_length))
    assert result.data.nullable_value == nullable_value
    assert result.data.warning_included is include_warning
    assert bool(result.warnings) is include_warning


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "code", "retry_action"),
    [
        (ProbeErrorCase.INVALID_INPUT, "synthetic_invalid_input", "none"),
        (ProbeErrorCase.POLICY_REJECTION, "policy_rejected", "none"),
        (
            ProbeErrorCase.KNOWN_EXECUTION_FAILURE,
            "known_execution_failure",
            "none",
        ),
        (ProbeErrorCase.TIMEOUT, "synthetic_timeout", "none"),
        (
            ProbeErrorCase.UNCERTAIN_OUTCOME,
            "synthetic_uncertain_outcome",
            "reconcile",
        ),
    ],
)
async def test_probe_error_returns_canonical_execution_errors(
    compatibility_use_cases: CompatibilityUseCases,
    case: ProbeErrorCase,
    code: str,
    retry_action: str,
) -> None:
    result = await compatibility_use_cases.probe_error(
        ProbeErrorRequest(case=case),
        _context(),
    )

    assert isinstance(result, ExecutionErrorEnvelope)
    assert result.error.code == code
    assert result.error.retry_action == retry_action


@pytest.mark.anyio
async def test_bounded_delay_is_only_successful_error_probe(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    missing = await compatibility_use_cases.probe_error(
        ProbeErrorRequest(case=ProbeErrorCase.BOUNDED_DELAY),
        _context(),
    )
    completed = await compatibility_use_cases.probe_error(
        ProbeErrorRequest(case=ProbeErrorCase.BOUNDED_DELAY, delay_ms=1),
        _context(),
    )

    assert isinstance(missing, ExecutionErrorEnvelope)
    assert missing.error.code == "synthetic_invalid_input"
    assert not isinstance(completed, ExecutionErrorEnvelope)
    assert completed.data.completed is True
    assert completed.data.delay_ms == 1


@pytest.mark.anyio
async def test_compatibility_report_preserves_no_evidence_baseline(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await compatibility_use_cases.compatibility_report(
        CompatibilityReportRequest(),
        _context(),
    )

    assert result.data.observed_protocol_revision is None
    assert result.data.evidence_bundle_sha256 is None
    assert result.data.observations[0].status == "not-tested"

"""Framework-independent MCP request, result, and envelope values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Generic, TypeAlias, TypeVar

from binnacle.domain.system import SystemSection


class ProtocolEra(StrEnum):
    MODERN = "modern"
    LEGACY = "legacy"


class CataloguePhase(StrEnum):
    COMPATIBILITY_CORE = "compatibility-core"


class ProbeErrorCase(StrEnum):
    INVALID_INPUT = "invalid_input"
    POLICY_REJECTION = "policy_rejection"
    KNOWN_EXECUTION_FAILURE = "known_execution_failure"
    TIMEOUT = "timeout"
    UNCERTAIN_OUTCOME = "uncertain_outcome"
    BOUNDED_DELAY = "bounded_delay"


@dataclass(frozen=True, slots=True)
class McpCallContext:
    revision: str
    era: ProtocolEra
    request_id: str


@dataclass(frozen=True, slots=True)
class ToolIdentity:
    name: str
    contract_version: str


@dataclass(frozen=True, slots=True)
class DiagnosticFact:
    name: str
    value: str | int | float | bool | None
    classification: str = "normal-result"


@dataclass(frozen=True, slots=True)
class WarningRecord:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class BinnacleError:
    code: str
    message: str
    retryable: bool
    retry_action: str
    operation_id: None = None
    details: tuple[DiagnosticFact, ...] = ()


DataT = TypeVar("DataT", covariant=True)


@dataclass(frozen=True, slots=True)
class SuccessEnvelope(Generic[DataT]):
    schema_version: str
    call_status: str
    tool: ToolIdentity
    request_id: str
    data: DataT
    operation: None = None
    evidence: tuple[object, ...] = ()
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionErrorEnvelope:
    schema_version: str
    call_status: str
    tool: ToolIdentity
    request_id: str
    error: BinnacleError
    operation: None = None
    evidence: tuple[object, ...] = ()
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class BinnacleProbeRequest:
    pass


@dataclass(frozen=True, slots=True)
class SystemInspectRequest:
    sections: tuple[SystemSection, ...] | None = None


@dataclass(frozen=True, slots=True)
class ProbeResultFormatsRequest:
    include_warning: bool = False
    nullable_value: str | None = None
    array_length: int = 3


@dataclass(frozen=True, slots=True)
class ProbeErrorRequest:
    case: ProbeErrorCase
    delay_ms: int | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityReportRequest:
    pass


@dataclass(frozen=True, slots=True)
class ToolManifestIdentity:
    id: str
    version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BinnacleProbeData:
    build_version: str
    build_sha256: str
    device_id: str
    protocol_revision: str
    protocol_era: str
    tool_manifest: ToolManifestIdentity
    catalogue_phase: str
    catalogue_sha256: str
    request_correlation_id: str


@dataclass(frozen=True, slots=True)
class SystemInspectData:
    hostname: str
    returned_sections: tuple[str, ...]
    sections: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProbeResultFormatsData:
    string_value: str
    integer_value: int
    boolean_value: bool
    nullable_value: str | None
    array_values: tuple[int, ...]
    nested: Mapping[str, object]
    warning_included: bool


@dataclass(frozen=True, slots=True)
class ProbeErrorDelayData:
    case: str
    delay_ms: int
    completed: bool


@dataclass(frozen=True, slots=True)
class CompatibilityObservation:
    axis: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class CompatibilityProfileSnapshot:
    profile_version: str
    observed_protocol_revision: str | None
    observations: tuple[CompatibilityObservation, ...]
    evidence_bundle_sha256: str | None
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompatibilityReportData:
    profile_version: str
    observed_protocol_revision: str | None
    observations: tuple[CompatibilityObservation, ...]
    evidence_bundle_sha256: str | None
    limitations: tuple[str, ...]


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def to_json_value(value: object) -> JsonValue:
    """Convert immutable domain values to ordinary JSON-compatible values."""

    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_json_value(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_json_value(child) for child in value]
    raise TypeError(f"unsupported domain serialization type: {type(value).__name__}")


def envelope_to_mapping(
    envelope: SuccessEnvelope[object] | ExecutionErrorEnvelope,
) -> dict[str, JsonValue]:
    value = to_json_value(envelope)
    if not isinstance(value, dict):
        raise TypeError("serialized Tool envelope must be an object")
    return value

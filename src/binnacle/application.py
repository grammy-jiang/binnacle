"""Framework-independent application lifecycle and compatibility use cases."""

from __future__ import annotations

import asyncio
from typing import TypeVar

from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    BinnacleError,
    BinnacleProbeData,
    BinnacleProbeRequest,
    CataloguePhase,
    CompatibilityReportData,
    CompatibilityReportRequest,
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeErrorCase,
    ProbeErrorDelayData,
    ProbeErrorRequest,
    ProbeResultFormatsData,
    ProbeResultFormatsRequest,
    SuccessEnvelope,
    SystemInspectData,
    SystemInspectRequest,
    ToolIdentity,
    ToolManifestIdentity,
    WarningRecord,
)
from binnacle.domain.runtime import BuildIdentity, PackageIdentity
from binnacle.domain.system import (
    DEFAULT_SYSTEM_SECTIONS,
    SYSTEM_SECTION_ORDER,
    InspectionError,
    SystemSection,
    SystemSnapshot,
)
from binnacle.ports.compatibility import CompatibilityProfileReader
from binnacle.ports.device import DeviceIdentityProvider
from binnacle.ports.system import SystemInspector

SuccessDataT = TypeVar("SuccessDataT")


class CompatibilityUseCases:
    """Read-only compatibility-core application behavior."""

    def __init__(
        self,
        *,
        build_identity: BuildIdentity,
        device_identity_provider: DeviceIdentityProvider,
        system_inspector: SystemInspector,
        compatibility_reader: CompatibilityProfileReader,
        contracts: ContractRegistry,
    ) -> None:
        self._build_identity = build_identity
        self._device_identity = device_identity_provider.get_device_identity()
        self._system_inspector = system_inspector
        self._compatibility_reader = compatibility_reader
        self._contracts = contracts

    async def binnacle_probe(
        self,
        request: BinnacleProbeRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[BinnacleProbeData]:
        del request
        return self._success(
            "binnacle_probe",
            context,
            BinnacleProbeData(
                build_version=self._build_identity.version,
                build_sha256=self._build_identity.build_sha256,
                device_id=self._device_identity.device_id,
                protocol_revision=context.revision,
                protocol_era=context.era.value,
                tool_manifest=ToolManifestIdentity(
                    id=self._contracts.manifest_id,
                    version=self._contracts.manifest_version,
                    sha256=self._contracts.manifest_sha256,
                ),
                catalogue_phase=CataloguePhase.COMPATIBILITY_CORE.value,
                catalogue_sha256=self._contracts.catalogue_sha256,
                request_correlation_id=context.request_id,
            ),
        )

    async def system_inspect(
        self,
        request: SystemInspectRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[SystemInspectData] | ExecutionErrorEnvelope:
        requested = request.sections or DEFAULT_SYSTEM_SECTIONS
        sections = tuple(section for section in SYSTEM_SECTION_ORDER if section in requested)
        try:
            snapshot = await self._system_inspector.inspect(sections)
            data = SystemInspectData(
                hostname=snapshot.hostname,
                returned_sections=tuple(section.value for section in snapshot.returned_sections),
                sections=self._snapshot_sections(snapshot),
            )
        except InspectionError as exc:
            return self._error(
                "system_inspect",
                context,
                code="inspection_failed",
                message=str(exc),
            )
        warnings = tuple(
            WarningRecord(code=warning.code, message=warning.message)
            for warning in snapshot.warnings
        )
        return self._success("system_inspect", context, data, warnings=warnings)

    async def probe_result_formats(
        self,
        request: ProbeResultFormatsRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeResultFormatsData]:
        warnings: tuple[WarningRecord, ...] = ()
        if request.include_warning:
            warnings = (
                WarningRecord(
                    code="synthetic_probe_warning",
                    message="Synthetic compatibility warning requested.",
                ),
            )
        return self._success(
            "probe_result_formats",
            context,
            ProbeResultFormatsData(
                string_value="binnacle-result-format-probe",
                integer_value=42,
                boolean_value=True,
                nullable_value=request.nullable_value,
                array_values=tuple(range(request.array_length)),
                nested={"name": "nested", "enabled": True},
                warning_included=request.include_warning,
            ),
            warnings=warnings,
        )

    async def probe_error(
        self,
        request: ProbeErrorRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeErrorDelayData] | ExecutionErrorEnvelope:
        if request.case is ProbeErrorCase.BOUNDED_DELAY:
            if request.delay_ms is None:
                return self._error(
                    "probe_error",
                    context,
                    code="synthetic_invalid_input",
                    message="bounded_delay requires delay_ms",
                )
            await asyncio.sleep(request.delay_ms / 1000)
            return self._success(
                "probe_error",
                context,
                ProbeErrorDelayData(
                    case=request.case.value,
                    delay_ms=request.delay_ms,
                    completed=True,
                ),
            )

        errors = {
            ProbeErrorCase.INVALID_INPUT: (
                "synthetic_invalid_input",
                "Synthetic invalid-input execution error.",
                "none",
            ),
            ProbeErrorCase.POLICY_REJECTION: (
                "policy_rejected",
                "Synthetic policy rejection.",
                "none",
            ),
            ProbeErrorCase.KNOWN_EXECUTION_FAILURE: (
                "known_execution_failure",
                "Synthetic known execution failure.",
                "none",
            ),
            ProbeErrorCase.TIMEOUT: (
                "synthetic_timeout",
                "Synthetic bounded timeout.",
                "none",
            ),
            ProbeErrorCase.UNCERTAIN_OUTCOME: (
                "synthetic_uncertain_outcome",
                "Synthetic uncertain outcome; reconcile before another effect.",
                "reconcile",
            ),
        }
        code, message, retry_action = errors[request.case]
        return self._error(
            "probe_error",
            context,
            code=code,
            message=message,
            retry_action=retry_action,
        )

    async def compatibility_report(
        self,
        request: CompatibilityReportRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[CompatibilityReportData]:
        del request
        profile = self._compatibility_reader.read()
        return self._success(
            "compatibility_report",
            context,
            CompatibilityReportData(
                profile_version=profile.profile_version,
                observed_protocol_revision=profile.observed_protocol_revision,
                observations=profile.observations,
                evidence_bundle_sha256=profile.evidence_bundle_sha256,
                limitations=profile.limitations,
            ),
        )

    def _identity(self, name: str) -> ToolIdentity:
        contract = self._contracts.tools[name]
        return ToolIdentity(name=name, contract_version=contract.contract_version)

    def _success(
        self,
        name: str,
        context: McpCallContext,
        data: SuccessDataT,
        *,
        warnings: tuple[WarningRecord, ...] = (),
    ) -> SuccessEnvelope[SuccessDataT]:
        return SuccessEnvelope(
            schema_version="1.1",
            call_status="succeeded",
            tool=self._identity(name),
            request_id=context.request_id,
            data=data,
            warnings=warnings,
        )

    def _error(
        self,
        name: str,
        context: McpCallContext,
        *,
        code: str,
        message: str,
        retry_action: str = "none",
    ) -> ExecutionErrorEnvelope:
        return ExecutionErrorEnvelope(
            schema_version="1.1",
            call_status="execution_error",
            tool=self._identity(name),
            request_id=context.request_id,
            error=BinnacleError(
                code=code,
                message=message,
                retryable=False,
                retry_action=retry_action,
            ),
        )

    @staticmethod
    def _snapshot_sections(snapshot: SystemSnapshot) -> dict[str, object]:
        values: dict[str, object] = {}
        for section in snapshot.returned_sections:
            if section is SystemSection.OS:
                values[section.value] = snapshot.os_summary
            elif section is SystemSection.KERNEL:
                values[section.value] = snapshot.kernel
            elif section is SystemSection.ARCHITECTURE:
                values[section.value] = snapshot.architecture
            elif section is SystemSection.UPTIME:
                values[section.value] = snapshot.uptime_seconds
            elif section is SystemSection.CPU:
                values[section.value] = snapshot.cpu
            elif section is SystemSection.MEMORY:
                values[section.value] = snapshot.memory
            elif section is SystemSection.FILESYSTEMS:
                values[section.value] = snapshot.filesystems
            elif section is SystemSection.BINNACLE_SERVICE:
                values[section.value] = snapshot.binnacle_service
        if any(value is None for value in values.values()):
            raise InspectionError("system snapshot omitted a requested section")
        return values


class BinnacleApplication:
    """Minimal idempotent lifecycle for the Phase 1 application."""

    def __init__(
        self,
        *,
        identity: PackageIdentity,
        compatibility: CompatibilityUseCases | None = None,
        contracts: ContractRegistry | None = None,
    ) -> None:
        self._identity = identity
        self._compatibility = compatibility
        self._contracts = contracts
        self._started = False
        self._registered_tool_count = 0

    @property
    def identity(self) -> PackageIdentity:
        """Return this process's package identity."""

        return self._identity

    @property
    def is_started(self) -> bool:
        """Return whether the application lifecycle is started."""

        return self._started

    @property
    def is_ready(self) -> bool:
        return (
            self._started
            and self._compatibility is not None
            and self._contracts is not None
            and self._registered_tool_count == 5
        )

    @property
    def compatibility(self) -> CompatibilityUseCases:
        if self._compatibility is None:
            raise RuntimeError("compatibility use cases are not composed")
        return self._compatibility

    @property
    def contracts(self) -> ContractRegistry:
        if self._contracts is None:
            raise RuntimeError("contract registry is not composed")
        return self._contracts

    def set_registered_tool_count(self, count: int) -> None:
        self._registered_tool_count = count

    async def start(self) -> None:
        """Start the application once."""

        self._started = True

    async def stop(self) -> None:
        """Stop the application if it is running."""

        self._registered_tool_count = 0
        self._started = False

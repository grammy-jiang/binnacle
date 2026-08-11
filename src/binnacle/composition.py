"""Explicit application composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import structlog

from binnacle import distribution_version
from binnacle.adapters.audit.journal import FileAuditJournal
from binnacle.adapters.audit.obligations import FileAuditObligationStore
from binnacle.adapters.compatibility import (
    CompiledCompatibilityProfileReader,
    compute_build_identity,
)
from binnacle.adapters.linux import (
    LinuxDeviceIdentityProvider,
    LinuxSystemInspector,
    LinuxTrustedTimeSource,
)
from binnacle.adapters.payload.filesystem import FilesystemPayloadStore
from binnacle.adapters.sqlite.engine import (
    DatabaseRuntime,
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
    verify_database_runtime,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.adapters.sqlite.payload import SqlitePayloadMetadataRepository
from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.application.boundary import ConsequentialBoundaryGate
from binnacle.application.kernel_health import KernelAvailability, KernelHealth
from binnacle.config import BinnacleSettings
from binnacle.contracts import ContractRegistry
from binnacle.domain.audit import AuditRuntimeIdentity
from binnacle.domain.runtime import PackageIdentity
from binnacle.logging import LoggingRuntime, configure_logging

_LOGGER = structlog.get_logger(__name__)


@dataclass(slots=True)
class ComposedApplication:
    """Resources owned by one composed application."""

    settings: BinnacleSettings
    application: BinnacleApplication
    contracts: ContractRegistry
    compatibility: CompatibilityUseCases
    logging_runtime: LoggingRuntime
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        """Stop application and logging resources exactly once."""

        if self._closed:
            return
        self._closed = True
        try:
            await self.application.stop()
        finally:
            self.logging_runtime.close()


def compose_application(*, settings: BinnacleSettings) -> ComposedApplication:
    """Build the trusted read-only application in deterministic dependency order."""

    logging_runtime = configure_logging(settings.logging)
    try:
        identity = PackageIdentity(
            distribution_name="binnacle",
            version=distribution_version(),
        )
        try:
            contracts = ContractRegistry.load()
        except Exception as exc:
            _LOGGER.error(
                "contract_registry_load_failed",
                error_type=type(exc).__name__,
            )
            raise
        _LOGGER.info(
            "contract_registry_loaded",
            manifest_id=contracts.manifest_id,
            manifest_version=contracts.manifest_version,
            manifest_sha256_prefix=contracts.manifest_sha256[:12],
            catalogue_sha256_prefix=contracts.catalogue_sha256[:12],
            registered_tool_count=len(contracts.tools),
        )
        build_identity = compute_build_identity(version=identity.version)
        system_inspector = LinuxSystemInspector(
            filesystem_stat_timeout_seconds=(settings.server.filesystem_stat_timeout_seconds)
        )
        compatibility = CompatibilityUseCases(
            build_identity=build_identity,
            device_identity_provider=LinuxDeviceIdentityProvider(),
            system_inspector=system_inspector,
            compatibility_reader=CompiledCompatibilityProfileReader(contracts),
            contracts=contracts,
        )
        application = BinnacleApplication(
            identity=identity,
            compatibility=compatibility,
            contracts=contracts,
        )
        return ComposedApplication(
            settings=settings,
            application=application,
            contracts=contracts,
            compatibility=compatibility,
            logging_runtime=logging_runtime,
        )
    except Exception:
        logging_runtime.close()
        raise


@dataclass(frozen=True, slots=True)
class KernelCompositionPaths:
    """Explicit test seam; production uses only fixed protected settings roots."""

    database: Path
    audit: Path
    payload: Path
    runtime: Path
    verify_runtime_directory: bool = True


@dataclass(slots=True)
class ComposedOperationKernel:
    database: DatabaseRuntime
    store: SqliteOperationStore
    audit: FileAuditJournal
    obligations: FileAuditObligationStore
    payloads: FilesystemPayloadStore
    gate: ConsequentialBoundaryGate
    health: KernelHealth
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.gate.close()
        try:
            await self.store.set_consequential_admission_enabled(False)
        finally:
            await close_database_runtime(self.database)


async def compose_operation_kernel(
    *,
    settings: BinnacleSettings,
    project_root: Path,
    paths: KernelCompositionPaths | None = None,
) -> ComposedOperationKernel:
    """Verify and compose the internal kernel without exposing an MCP capability."""

    selected_paths = paths or KernelCompositionPaths(
        database=settings.database.path,
        audit=settings.audit.directory,
        payload=settings.payload.directory,
        runtime=Path("/run/binnacle"),
    )
    database = await create_database_runtime(
        DatabaseRuntimeSettings(
            path=selected_paths.database,
            runtime_directory=selected_paths.runtime,
            busy_timeout_ms=settings.database.busy_timeout_ms,
            wal_autocheckpoint_pages=settings.database.wal_autocheckpoint_pages,
            verify_runtime_directory=selected_paths.verify_runtime_directory,
        )
    )
    try:
        database_health = await verify_database_runtime(database)
        if not database_health.healthy:
            raise RuntimeError("database revision or durability pragmas do not match")
        contracts = ContractRegistry.load()
        device = LinuxDeviceIdentityProvider().get_device_identity()
        build = compute_build_identity(version=distribution_version())
        trusted_time = await LinuxTrustedTimeSource().snapshot()
        store = SqliteOperationStore(database)
        await store.initialize_kernel(
            device_id=device.device_id,
            audit_stream_id=f"stream-{device.device_id}",
        )
        audit_identity = AuditRuntimeIdentity(
            stream_id=f"stream-{device.device_id}",
            audit_epoch="epoch-1",
            segment_id="segment-1",
            boot_id=trusted_time.boot_id_digest,
            device_id=device.device_id,
            server_build_sha256=build.build_sha256,
            tool_manifest_sha256=contracts.manifest_sha256,
            schema_registry_sha256=contracts.schema_registry_sha256,
            device_profile_version="phase4-internal-1",
            policy_version="bootstrap-1.0.0",
            redaction_policy_version="1.0.0",
        )
        import json

        schema = json.loads(
            (project_root / "schemas/audit/audit-event.schema.json").read_text(encoding="utf-8")
        )
        audit = FileAuditJournal(
            directory=selected_paths.audit,
            identity=audit_identity,
            schema=schema,
        )
        journal_tail = await audit.open()
        cache_tail = await store.audit_tail_cache()
        if cache_tail.sequence > journal_tail.sequence or (
            cache_tail.sequence == journal_tail.sequence
            and cache_tail.event_hash != journal_tail.event_hash
        ):
            raise RuntimeError("audit tail cache is ahead of or divergent from journal")
        if cache_tail != journal_tail:
            await store.update_audit_tail_cache(journal_tail)
        obligations = FileAuditObligationStore(selected_paths.database.parent / "audit-obligations")
        await obligations.initialize()
        surviving = await obligations.scan()
        if surviving:
            await store.latch_audit_failure("surviving_audit_obligation")
        metadata = SqlitePayloadMetadataRepository(database)
        payloads = FilesystemPayloadStore(
            directory=selected_paths.payload,
            repository=metadata,
            object_bytes_max=settings.payload.object_bytes_max,
            controller_bytes_max=settings.payload.controller_bytes_max,
            append_chunk_bytes_max=settings.payload.append_chunk_bytes_max,
        )
        await payloads.initialize()
        await payloads.verify_all()
        latched, generation, recovered = await store.audit_failure_state()
        gate = ConsequentialBoundaryGate()
        availability = KernelAvailability.AVAILABLE
        reasons: tuple[str, ...] = ()
        if surviving or latched or generation != recovered:
            await store.set_consequential_admission_enabled(False)
            availability = KernelAvailability.UNAVAILABLE
            reasons = ("audit_recovery_required",)
        else:
            await store.set_consequential_admission_enabled(True)
            await gate.open()
        health = KernelHealth(
            availability=availability,
            database_healthy=True,
            audit_healthy=not latched,
            payload_healthy=True,
            obligation_count=len(surviving),
            audit_failure_latched=latched,
            reason_codes=reasons,
        )
        return ComposedOperationKernel(
            database=database,
            store=store,
            audit=audit,
            obligations=obligations,
            payloads=payloads,
            gate=gate,
            health=health,
        )
    except Exception:
        await close_database_runtime(database)
        raise

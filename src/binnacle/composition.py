"""Explicit application composition root."""

from __future__ import annotations

import hashlib
import json
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
from binnacle.adapters.policy.bootstrap import BootstrapPolicyEngine
from binnacle.adapters.privileged_ipc.client import PrivilegedClient, PrivilegedClientSettings
from binnacle.adapters.probe_workspace import (
    LinuxProbeWorkspace,
    ProbeWorkspaceEffectBoundary,
    ProbeWorkspaceReconciler,
)
from binnacle.adapters.sqlite.engine import (
    DatabaseRuntime,
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
    verify_database_runtime,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.adapters.sqlite.payload import SqlitePayloadMetadataRepository
from binnacle.adapters.sqlite.privileged import SqlitePrivilegedApplicationRepository
from binnacle.adapters.sqlite.probe_workspace import SqliteProbeWorkspaceRepository
from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.application.boundary import (
    ConsequentialBoundaryGate,
    DispatchHandoffGate,
    FinalBoundaryService,
    UnavailableOperationBoundaryVerifier,
    UnavailablePreparedStateVerifier,
)
from binnacle.application.kernel_health import KernelAvailability, KernelHealth
from binnacle.application.operations import OperationCoordinator
from binnacle.application.privileged_reconciliation import (
    PrivilegedRestartAuditClosure,
    PrivilegedRestartReconciler,
)
from binnacle.application.probe_workspace import (
    ProbeOperationAuthoriser,
    ProbeOperationBoundaryVerifier,
    ProbePreparedStateVerifier,
    ProbeWorkspaceControllerResolver,
    ProbeWorkspaceEntitlement,
    ProbeWorkspaceService,
    ProbeWorkspaceUseCases,
)
from binnacle.application.reconciliation import (
    CompositeSpecializedOperationReconciler,
    OperationReconciler,
)
from binnacle.application.trusted_time import TrustedTimeGuard
from binnacle.config import BinnacleSettings
from binnacle.contracts import ContractRegistry
from binnacle.domain.audit import AuditRuntimeIdentity
from binnacle.domain.runtime import PackageIdentity
from binnacle.logging import LoggingRuntime, configure_logging
from binnacle.ports.boundary import OperationBoundaryVerifier, PreparedStateVerifier
from binnacle.ports.effect import EffectBoundary, UnavailableEffectBoundary
from binnacle.ports.trusted_time import TrustedTimeSource

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


def compose_application(
    *,
    settings: BinnacleSettings,
    write_catalogue_eligible: bool = False,
) -> ComposedApplication:
    """Build the trusted read-only application in deterministic dependency order."""

    logging_runtime = configure_logging(settings.logging)
    try:
        identity = PackageIdentity(
            distribution_name="binnacle",
            version=distribution_version(),
        )
        try:
            contracts = ContractRegistry.load()
            write_contracts = (
                ContractRegistry.load_phase("compatibility-write-probe")
                if settings.probe_workspace.enabled and write_catalogue_eligible
                else None
            )
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
            write_contracts=write_contracts,
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
    probe: Path | None = None
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
    trusted_time_guard: TrustedTimeGuard
    trusted_time_available: bool
    reconciler: OperationReconciler
    coordinator: OperationCoordinator
    effect_boundary: EffectBoundary
    probe_workspace: ProbeWorkspaceUseCases | None = None
    write_catalogue_available: bool = False
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
    write_catalogue_eligible: bool = False,
    contracts: ContractRegistry | None = None,
    controller_resolver: ProbeWorkspaceControllerResolver | None = None,
    probe_entitlement: ProbeWorkspaceEntitlement | None = None,
    trusted_time_source: TrustedTimeSource | None = None,
) -> ComposedOperationKernel:
    """Verify and compose the internal kernel without exposing an MCP capability."""

    selected_paths = paths or KernelCompositionPaths(
        database=settings.database.path,
        audit=settings.audit.directory,
        payload=settings.payload.directory,
        runtime=Path("/run/binnacle"),
        probe=settings.probe_workspace.root,
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
        runtime_contracts = contracts or ContractRegistry.load()
        device = LinuxDeviceIdentityProvider().get_device_identity()
        build = compute_build_identity(version=distribution_version())
        selected_trusted_time_source = trusted_time_source or LinuxTrustedTimeSource()
        trusted_time = await selected_trusted_time_source.snapshot()
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
            tool_manifest_sha256=runtime_contracts.manifest_sha256,
            schema_registry_sha256=runtime_contracts.schema_registry_sha256,
            device_profile_version="phase4-internal-1",
            policy_version="bootstrap-1.0.0",
            redaction_policy_version="1.0.0",
        )
        schema = json.loads(
            (project_root / "schemas/audit/audit-event.schema.json").read_text(encoding="utf-8")
        )
        audit = FileAuditJournal(
            directory=selected_paths.audit,
            identity=audit_identity,
            schema=schema,
            segment_bytes_max=settings.audit.segment_bytes_max,
            emergency_bytes_max=settings.audit.emergency_bytes_max,
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

        async def probe_closure_health() -> bool:
            latched, generation, recovered = await store.audit_failure_state()
            if latched or generation != recovered:
                return False
            stored = await store.audit_recovery_evidence_sha256()
            if generation == 0:
                return stored is None
            verified = await audit.find_generation_recovery(generation)
            return stored is not None and stored == verified

        probe_filesystem: LinuxProbeWorkspace | None = None
        probe_reconciler: ProbeWorkspaceReconciler | None = None
        probe_state_verifier: ProbePreparedStateVerifier | None = None
        if settings.probe_workspace.enabled:
            probe_path = selected_paths.probe or settings.probe_workspace.root
            probe_filesystem = LinuxProbeWorkspace(
                root=probe_path,
                maximum_file_bytes=settings.probe_workspace.max_file_bytes,
            )
            await probe_filesystem.initialize()
        probe_repository = SqliteProbeWorkspaceRepository(
            database,
            store,
            probe_filesystem,
        )
        await probe_repository.verify_integrity()
        if probe_filesystem is not None:
            probe_reconciler = ProbeWorkspaceReconciler(
                operations=store,
                repository=probe_repository,
                filesystem=probe_filesystem,
                audit=audit,
                obligations=obligations,
                closure_health=probe_closure_health,
            )
            probe_state_verifier = ProbePreparedStateVerifier(
                repository=probe_repository,
                filesystem=probe_filesystem,
            )
        gate = ConsequentialBoundaryGate()
        trusted_time_guard = TrustedTimeGuard(source=selected_trusted_time_source, store=store)
        trusted_time_available = await trusted_time_guard.accept_startup_snapshot(trusted_time)
        privileged_repository = SqlitePrivilegedApplicationRepository(database)
        privileged_audit_closure = PrivilegedRestartAuditClosure(
            audit=audit,
            obligations=obligations,
            store=store,
            closure_health=probe_closure_health,
        )
        privileged_reconciler = PrivilegedRestartReconciler(
            repository=privileged_repository,
            broker=PrivilegedClient(PrivilegedClientSettings()),
            no_accept_audit_closure=privileged_audit_closure,
            accepted_audit_closure=privileged_audit_closure,
        )
        specialized_reconciler = CompositeSpecializedOperationReconciler(
            *(
                (probe_reconciler, privileged_reconciler)
                if probe_reconciler is not None
                else (privileged_reconciler,)
            )
        )
        reconciler = OperationReconciler(
            store=store,
            obligations=obligations,
            gate=gate,
            specialized_reconciler=specialized_reconciler,
        )
        await reconciler.reconcile_startup(open_when_healthy=False)
        privileged_recovery_pending = await privileged_repository.restart_recovery_pending()
        surviving = await obligations.scan()
        latched, generation, recovered = await store.audit_failure_state()
        stored_recovery_evidence = await store.audit_recovery_evidence_sha256()
        verified_recovery_evidence = (
            await audit.find_generation_recovery(recovered) if recovered else None
        )
        recovery_evidence_valid = (
            generation == recovered == 0
            and stored_recovery_evidence is None
            and verified_recovery_evidence is None
        ) or (
            generation == recovered
            and generation > 0
            and stored_recovery_evidence is not None
            and stored_recovery_evidence == verified_recovery_evidence
        )
        audit_available = (
            not surviving and not latched and generation == recovered and recovery_evidence_valid
        )
        reason_values: list[str] = []
        if not audit_available:
            reason_values.append(
                "audit_recovery_evidence_invalid"
                if not latched
                and not surviving
                and generation == recovered
                and not recovery_evidence_valid
                else "audit_recovery_required"
            )
        if not trusted_time_available:
            reason_values.append("trusted_time_unavailable")
        if privileged_recovery_pending:
            reason_values.append("privileged_restart_recovery_required")
        kernel_available = (
            audit_available and trusted_time_available and not privileged_recovery_pending
        )
        availability = (
            KernelAvailability.AVAILABLE if kernel_available else KernelAvailability.UNAVAILABLE
        )
        reasons = tuple(reason_values)
        if not kernel_available:
            await store.set_consequential_admission_enabled(False)
        else:
            await store.set_consequential_admission_enabled(True)
            await gate.open()
        health = KernelHealth(
            availability=availability,
            database_healthy=True,
            audit_healthy=audit_available,
            payload_healthy=True,
            obligation_count=len(surviving),
            audit_failure_latched=latched,
            reason_codes=reasons,
            probe_workspace_healthy=(
                not settings.probe_workspace.enabled or probe_filesystem is not None
            ),
        )
        policy = BootstrapPolicyEngine(
            allowed_contracts=(
                frozenset(
                    {
                        ("probe_workspace_write", "1.1"),
                        ("probe_workspace_cleanup", "1.1"),
                    }
                )
                if settings.probe_workspace.enabled
                else frozenset()
            )
        )
        handoff_gate = DispatchHandoffGate()
        effect_boundary: EffectBoundary
        prepared_state_verifier: PreparedStateVerifier = UnavailablePreparedStateVerifier()
        operation_boundary_verifier: OperationBoundaryVerifier = (
            UnavailableOperationBoundaryVerifier()
        )
        authoriser = None
        if probe_filesystem is not None and probe_state_verifier is not None:
            effect_boundary = ProbeWorkspaceEffectBoundary(
                repository=probe_repository,
                filesystem=probe_filesystem,
            )
            prepared_state_verifier = probe_state_verifier
            operation_boundary_verifier = ProbeOperationBoundaryVerifier(probe_state_verifier)
            authoriser = ProbeOperationAuthoriser(probe_repository, probe_state_verifier)
        else:
            effect_boundary = UnavailableEffectBoundary()

        async def read_health() -> KernelHealth:
            return health

        final_boundary = FinalBoundaryService(
            health_reader=read_health,
            verifier=operation_boundary_verifier,
        )
        coordinator = OperationCoordinator(
            store=store,
            policy=policy,
            audit=audit,
            obligations=obligations,
            handoff_gate=handoff_gate,
            consequential_gate=gate,
            final_boundary=final_boundary,
            effect_boundary=effect_boundary,
            trusted_time_guard=trusted_time_guard,
            prepared_state_verifier=prepared_state_verifier,
            authoriser=authoriser,
        )
        probe_use_cases: ProbeWorkspaceUseCases | None = None
        selected_contracts = runtime_contracts
        if (
            settings.probe_workspace.enabled
            and write_catalogue_eligible
            and selected_contracts is not None
            and selected_contracts.catalogue_phase == "compatibility-write-probe"
            and controller_resolver is not None
            and probe_entitlement is not None
            and probe_filesystem is not None
            and probe_state_verifier is not None
            and probe_reconciler is not None
            and health.consequential_admission_allowed
        ):
            root_identity = await probe_filesystem.root_identity()
            service = ProbeWorkspaceService(
                operation_store=store,
                repository=probe_repository,
                coordinator=coordinator,
                closure=probe_reconciler,
                state_verifier=probe_state_verifier,
                trusted_time=trusted_time_guard,
                device_id=device.device_id,
                device_epoch=1,
                runtime_build_sha256=build.build_sha256,
                runtime_config_sha256=_settings_sha256(settings),
                root_identity=root_identity,
                preparation_ttl_seconds=(settings.probe_workspace.preparation_ttl_seconds),
                maximum_file_bytes=settings.probe_workspace.max_file_bytes,
            )
            probe_use_cases = ProbeWorkspaceUseCases(
                service=service,
                contracts=selected_contracts,
                controller_resolver=controller_resolver,
                entitlement=probe_entitlement,
                maximum_file_bytes=settings.probe_workspace.max_file_bytes,
            )
        return ComposedOperationKernel(
            database=database,
            store=store,
            audit=audit,
            obligations=obligations,
            payloads=payloads,
            gate=gate,
            health=health,
            trusted_time_guard=trusted_time_guard,
            trusted_time_available=trusted_time_available,
            reconciler=reconciler,
            coordinator=coordinator,
            effect_boundary=effect_boundary,
            probe_workspace=probe_use_cases,
            write_catalogue_available=probe_use_cases is not None,
        )
    except Exception:
        await close_database_runtime(database)
        raise


def _settings_sha256(settings: BinnacleSettings) -> str:
    projection = settings.model_dump(mode="json")
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"binnacle.runtime-config.v1\0" + encoded).hexdigest()

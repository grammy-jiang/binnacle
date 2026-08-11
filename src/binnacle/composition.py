"""Explicit application composition root."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from binnacle import distribution_version
from binnacle.adapters.compatibility import (
    CompiledCompatibilityProfileReader,
    compute_build_identity,
)
from binnacle.adapters.linux import LinuxDeviceIdentityProvider, LinuxSystemInspector
from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.config import BinnacleSettings
from binnacle.contracts import ContractRegistry
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

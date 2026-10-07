"""Default deployment-platform composition.

G4 remains Linux-first. Generic callers select host conventions here rather
than constructing Linux paths or adapters directly.
"""

from binnacle.platform.contracts.runtime_path_contracts import RuntimePaths
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceController,
    ManagedServiceInspector,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogSource


def create_runtime_paths() -> RuntimePaths:
    from binnacle.platform.linux.runtime_paths_linux import resolve_runtime_paths

    return resolve_runtime_paths()


def create_service_log_source(
    *, command_timeout_s: float | None = None
) -> ServiceLogSource:
    from binnacle.platform.linux.service_journal import JournalServiceLogSource

    return JournalServiceLogSource(command_timeout_s=command_timeout_s)


def create_service_inspector() -> ManagedServiceInspector:
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()


def create_linux_provisioner(
    *,
    unit_dir=None,
    backup_dir=None,
    run=None,
):
    from binnacle.platform.linux.service_provisioning_linux import (
        DEFAULT_BACKUP_DIR,
        UNIT_DIR,
        LinuxServiceProvisioner,
    )

    return LinuxServiceProvisioner(
        unit_dir=UNIT_DIR if unit_dir is None else unit_dir,
        backup_dir=DEFAULT_BACKUP_DIR if backup_dir is None else backup_dir,
        run=run,
    )


def create_service_controller() -> ManagedServiceController:
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()

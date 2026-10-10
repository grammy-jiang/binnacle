"""Single host-selection boundary for native OS mechanisms.

Stage 1 deliberately supports Linux only. Domain services consume small
platform contracts; they do not select the host or import its implementation.
This module is normal Python composition, not a FastMCP Provider or registry.
"""

import platform
from typing import Literal

from binnacle.platform.contracts.process_contracts import ProcessBackend
from binnacle.platform.contracts.resource_contracts import ResourceAccounting
from binnacle.platform.contracts.runtime_path_contracts import RuntimePaths
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceController,
    ManagedServiceInspector,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogSource


class UnsupportedHostOS(RuntimeError):
    """The host has no installed Binnacle platform implementation."""


def host_os_family(system: str | None = None) -> Literal["linux"]:
    """Resolve the OS once at the boundary, never silently fall back to Linux."""
    name = platform.system() if system is None else system
    if name != "Linux":
        raise UnsupportedHostOS(f"Binnacle has no {name!r} platform adapter")
    return "linux"


def create_process_backend() -> ProcessBackend:
    host_os_family()
    from binnacle.platform.linux.job_process import LinuxProcessBackend

    return LinuxProcessBackend()


def create_resource_accounting() -> ResourceAccounting:
    host_os_family()
    from binnacle.platform.linux.job_cgroup import CgroupResourceAccounting

    return CgroupResourceAccounting()


def create_runtime_paths() -> RuntimePaths:
    host_os_family()
    from binnacle.platform.linux.runtime_paths_linux import resolve_runtime_paths

    return resolve_runtime_paths()


def create_service_log_source(
    *, command_timeout_s: float | None = None
) -> ServiceLogSource:
    host_os_family()
    from binnacle.platform.linux.service_journal import JournalServiceLogSource

    return JournalServiceLogSource(command_timeout_s=command_timeout_s)


def create_service_inspector() -> ManagedServiceInspector:
    host_os_family()
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()


def create_service_controller() -> ManagedServiceController:
    host_os_family()
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()


def create_linux_provisioner(*, unit_dir=None, backup_dir=None, run=None):
    """Linux-only setup compatibility, not a generic cross-OS provisioner."""
    host_os_family()
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


def notify_job_manager_ready(on_error):
    """Linux unit readiness hook; durable RPC remains Core-owned."""
    host_os_family()
    from binnacle.platform.linux.notify_systemd import notify_ready

    notify_ready(on_error)

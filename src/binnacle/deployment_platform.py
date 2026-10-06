"""Default deployment-platform composition.

G4 remains Linux-first. Generic callers select host conventions here rather
than constructing Linux paths or adapters directly.
"""

from binnacle.runtime_path_contracts import RuntimePaths
from binnacle.service_log_contracts import ServiceLogSource


def create_runtime_paths() -> RuntimePaths:
    from binnacle.runtime_paths_linux import resolve_runtime_paths

    return resolve_runtime_paths()


def create_service_log_source(
    *, command_timeout_s: float | None = None
) -> ServiceLogSource:
    from binnacle.service_journal import JournalServiceLogSource

    return JournalServiceLogSource(command_timeout_s=command_timeout_s)

"""Runtime path values independent of host path-selection mechanics."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Ephemeral Binnacle paths selected for the current host/session."""

    binnacle_runtime_dir: Path
    jobs_socket: Path

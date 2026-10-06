"""Default deployment-platform composition.

G4 remains Linux-first. Generic callers select host conventions here rather
than constructing Linux paths or adapters directly.
"""

from binnacle.runtime_path_contracts import RuntimePaths


def create_runtime_paths() -> RuntimePaths:
    from binnacle.runtime_paths_linux import resolve_runtime_paths

    return resolve_runtime_paths()

"""Import every runtime binnacle module once, at process start.

A serving process (the MCP server or a job manager) shares its checkout and
virtual environment with later deploys. A module that such a process imports
lazily after a checkout sync comes from the new revision while the rest of the
process runs the old one (OPS-FOLLOWUP-shared-venv-lazy-import, R-M1-X1: an MCP
that had served no job call imported the synced job client and failed job calls
with "job manager unavailable"). Importing the whole runtime tree at start
closes that window: a running process never reads binnacle source again.

Not imported: entry modules with start-up side effects, the separate companion
CLIs, and the other OS's adapters (which must not load or start owners here).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import platform

import binnacle

log = logging.getLogger("binnacle.startup_imports")

_ALWAYS_EXCLUDED = (
    "binnacle.server",  # builds and starts the ASGI application on import
    "binnacle.cli",
    "binnacle.companions",
)
_EXCLUDED_BY_OS = {
    "Linux": (
        "binnacle.platform.darwin",
        "binnacle.deployment.darwin",
    ),
    "Darwin": (
        "binnacle.platform.linux",
        "binnacle.observability.linux",
        "binnacle.deployment.linux",
        "binnacle.diagnostics.linux_checks",
        # The Linux durable owner composes a process backend on import.
        "binnacle.features.commands.jobs",
        "binnacle.features.commands.job_owner",
        "binnacle.features.commands.job_manager",
    ),
}


def _excluded(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def runtime_module_names(system: str | None = None) -> tuple[str, ...]:
    """The binnacle modules a serving process on ``system`` imports at start."""
    prefixes = _ALWAYS_EXCLUDED + _EXCLUDED_BY_OS.get(
        platform.system() if system is None else system, ()
    )
    names = [
        info.name
        for info in pkgutil.walk_packages(binnacle.__path__, "binnacle.")
        if not _excluded(info.name, prefixes)
    ]
    return tuple(sorted(names))


def import_runtime_modules(system: str | None = None) -> tuple[str, ...]:
    """Import the runtime tree; return the modules that failed to import.

    A failure never stops the process (its module stays lazy, as before) and
    is logged once; the start-up import tests require an empty result.
    """
    failed = []
    for name in runtime_module_names(system):
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - logged and reported
            failed.append(name)
            log.warning(
                "event=startup_import_error module=%s error_class=%s",
                name,
                type(exc).__name__,
            )
    return tuple(failed)

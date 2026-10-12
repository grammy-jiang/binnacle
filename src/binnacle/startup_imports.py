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

A job manager never runs the MCP/tool tree (E1B-R1: the whole tree doubled the
Darwin manager's RSS). Both manager entries import ``MANAGER_MODULES`` instead:
the entry's start-up closure plus every binnacle module it imports lazily while
serving, pinned per OS (derived with an import tracer over the manager suites,
both entries) and held to that by the E1-a3 test, which fails on any binnacle
module a serving manager loads outside the list.
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


# E1-a3: never in a manager set. binnacle.mcp and binnacle.mcp.callctx are the
# one exception: the Linux entry module imports the call-context variable itself.
MANAGER_EXCLUDED = (
    "binnacle.application",
    "binnacle.features.commands.tools",
    "binnacle.features.files",
    "binnacle.features.search",
    "binnacle.mcp",
    *_ALWAYS_EXCLUDED,
)
MANAGER_ENTRY_CLOSURE_ALLOWED = ("binnacle.mcp", "binnacle.mcp.callctx")
_MANAGER_COMMON = (
    "binnacle",
    "binnacle.platform",
    "binnacle.platform.contracts",
    "binnacle.platform.contracts.capability_contracts",
    "binnacle.platform.contracts.darwin_contracts",
    "binnacle.platform.contracts.native_service_contracts",
    "binnacle.platform.contracts.process_contracts",
    "binnacle.platform.contracts.runtime_path_contracts",
    "binnacle.provenance",
    "binnacle.startup_imports",
)
MANAGER_MODULES = {
    # binnacle.features.commands.job_manager.main (binnacle-jobs.service)
    "Linux": tuple(
        sorted(
            _MANAGER_COMMON
            + (
                "binnacle.auto_background_shell",
                "binnacle.config",
                "binnacle.features",
                "binnacle.features.commands",
                "binnacle.features.commands.job_client",
                "binnacle.features.commands.job_manager",
                "binnacle.features.commands.job_output",
                "binnacle.features.commands.job_owner",
                "binnacle.features.commands.job_resource_history",
                "binnacle.features.commands.job_stop",
                "binnacle.features.commands.job_store",
                "binnacle.features.commands.jobs",
                "binnacle.mcp",
                "binnacle.mcp.callctx",
                "binnacle.platform.composition",
                "binnacle.platform.contracts.darwin_release_scope",
                "binnacle.platform.contracts.file_access_contracts",
                "binnacle.platform.contracts.resource_contracts",
                "binnacle.platform.contracts.service_lifecycle_contracts",
                "binnacle.platform.contracts.service_log_contracts",
                "binnacle.platform.job_platform",
                "binnacle.platform.linux",
                "binnacle.platform.linux.job_cgroup",
                "binnacle.platform.linux.job_identity",
                "binnacle.platform.linux.job_process",
                "binnacle.platform.linux.notify_systemd",  # lazy: ready notification
                "binnacle.platform.linux.runtime_paths_linux",
            )
        )
    ),
    # python -m binnacle.platform.darwin.job_manager_service (com.binnacle.jobs)
    "Darwin": tuple(
        sorted(
            _MANAGER_COMMON
            + (
                "binnacle.platform.darwin",
                "binnacle.platform.darwin.generation_publish",
                "binnacle.platform.darwin.generation_runtime",
                "binnacle.platform.darwin.ipc_transport",
                "binnacle.platform.darwin.job_group_fence",
                "binnacle.platform.darwin.job_manager_config",
                "binnacle.platform.darwin.job_manager_entry",
                "binnacle.platform.darwin.job_manager_procinfo",
                "binnacle.platform.darwin.job_manager_records",
                "binnacle.platform.darwin.job_manager_service",
                "binnacle.platform.darwin.job_manager_stopping",
                "binnacle.platform.darwin.job_process_owner",
                "binnacle.platform.darwin.process_authority",
                "binnacle.platform.darwin.process_backend",
            )
        )
    ),
}


def _excluded(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def _walk(path: list[str], prefix: str, prefixes: tuple[str, ...]) -> list[str]:
    # pkgutil.walk_packages imports every package to recurse into it, even an
    # excluded one (the other OS's adapter package); skip those before import.
    names = []
    for info in pkgutil.iter_modules(path, prefix):
        if _excluded(info.name, prefixes):
            continue
        names.append(info.name)
        if info.ispkg:
            package = importlib.import_module(info.name)
            names += _walk(list(package.__path__), info.name + ".", prefixes)
    return names


def runtime_module_names(system: str | None = None) -> tuple[str, ...]:
    """The binnacle modules a serving process on ``system`` imports at start."""
    prefixes = _ALWAYS_EXCLUDED + _EXCLUDED_BY_OS.get(
        platform.system() if system is None else system, ()
    )
    return tuple(sorted(_walk(list(binnacle.__path__), "binnacle.", prefixes)))


def manager_module_names(system: str | None = None) -> tuple[str, ...]:
    """The binnacle modules a job manager on ``system`` imports at start."""
    return MANAGER_MODULES.get(platform.system() if system is None else system, ())


def import_runtime_modules(system: str | None = None) -> tuple[str, ...]:
    """Import the runtime tree; return the modules that failed to import.

    A failure never stops the process (its module stays lazy, as before) and
    is logged once; the start-up import tests require an empty result.
    """
    return _import_all(runtime_module_names(system))


def import_manager_modules(system: str | None = None) -> tuple[str, ...]:
    """Import the job manager's pinned set; failures as ``import_runtime_modules``."""
    return _import_all(manager_module_names(system))


def _import_all(names: tuple[str, ...]) -> tuple[str, ...]:
    failed = []
    for name in names:
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

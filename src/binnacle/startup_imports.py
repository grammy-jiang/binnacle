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

Policy (E1-a4, Supervisor ruling on R-E1 point 5): a REQUIRED module that
raises anything while importing (ImportError, any Exception, SystemExit or
another BaseException, including a package ``__init__`` that raises inside the
name walk) ABORTS start-up. A half-started process that silently lacks a
module fails later, far from the cause. The failing process logs ONE line
(``event=startup_import_failed``: module, exception type and the raising
frame's package-relative file:line, never the message text), writes a durable
record that ``binnacle doctor`` reports, and exits with ``EX_STARTUP_IMPORT``
before it binds a port, takes the jobs lock or binds the jobs socket.
``OPTIONAL_MODULES`` is the pinned allowlist of modules that may fail and
report themselves unavailable at call time instead; no such module exists
today, so it is empty. E1 covers binnacle.* only: third-party and stdlib lazy
imports still come from the shared venv, and the deploy restarts on
pyproject/uv.lock changes.

The durable start-up import record (E1-a5, SD-84): importing this module or
calling ``import_runtime_modules`` / ``import_manager_modules`` never touches
it. Only the real entry points (the serving MCP process, the Linux manager
``main`` and the Darwin manager ``main``) write it, from the ``on_failure``
callback or the failure handler they supply, and clear it only AFTER a
successful start of that same process (the port or socket is bound). The
record lives under the instance's configured state root, which the entry point
passes in (``state_root_of(settings.jobs.dir)``); this library has no HOME
default. It holds no message text.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import pkgutil
import platform
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import binnacle
from binnacle.provenance import runtime_provenance

log = logging.getLogger("binnacle.startup_imports")

# EX_SOFTWARE (sysexits.h): distinct from the Darwin manager's 1/64/75/78.
EX_STARTUP_IMPORT = 70
OPTIONAL_MODULES: tuple[str, ...] = ()  # pinned; empty (no optional module)
RECORD_DIR_NAME = "startup-import"

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


def manager_entry_closure_allowed(system: str) -> tuple[str, ...]:
    """RE1-F4: the closure exception holds for the Linux entry only."""
    return MANAGER_ENTRY_CLOSURE_ALLOWED if system == "Linux" else ()


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
            package = _required_import(info.name)
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


class StartupImportFailed(SystemExit):
    """A required module failed to import; start-up is aborted."""

    def __init__(self, module: str, error_class: str, where: str) -> None:
        super().__init__(EX_STARTUP_IMPORT)
        self.module, self.error_class, self.where = module, error_class, where


def state_root_of(jobs_dir: Path) -> Path:
    """The instance's state root: the parent of its configured ``jobs.dir``."""
    return jobs_dir.parent


def record_dir(state_root: Path) -> Path:
    """Where ``doctor`` looks for a failing process's durable record."""
    return state_root / RECORD_DIR_NAME


def record_path(state_root: Path, process: str) -> Path:
    """The one place a record path is formed (the test suite guards it)."""
    return record_dir(state_root) / f"{process}.json"


def _raising_frame(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown:0"
    frame = frames[-1]
    path = Path(frame.filename)
    package_root = Path(binnacle.__file__).resolve().parent.parent
    roots = [package_root, *(Path(p) for p in sys.path if p.endswith("site-packages"))]
    for root in roots:
        try:
            return f"{path.resolve().relative_to(root.resolve())}:{frame.lineno}"
        except (OSError, ValueError):
            continue
    return f"{path.name}:{frame.lineno}"


def _required_import(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, StartupImportFailed)):
            raise
        raise StartupImportFailed(
            name, type(exc).__name__, _raising_frame(exc)
        ) from None


def record_start_failure(
    process: str, failure: StartupImportFailed, state_root: Path
) -> bool:
    """Entry points only: leave the durable record of a failed start.

    Fields: process, UTC time, revision, module, exception type and raising
    file:line. Never the exception message. Returns whether it was written.
    """
    record = {
        "process": process,
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": runtime_provenance().revision,
        "module": failure.module,
        "error_class": failure.error_class,
        "where": failure.where,
    }
    try:
        target = record_path(state_root, process)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        log.error("event=startup_import_record_error process=%s", process)
        return False
    return True


def clear_record(process: str, state_root: Path) -> None:
    """Entry points only, AFTER a successful start (bound port or socket)."""
    try:
        record_path(state_root, process).unlink(missing_ok=True)
    except OSError:
        log.warning("event=startup_import_record_error process=%s", process)


def _fail_fast(
    process: str,
    names_of: Callable[[str | None], tuple[str, ...]],
    system: str | None,
    on_failure: Callable[[StartupImportFailed], None] | None,
) -> tuple[str, ...]:
    try:
        names = names_of(system)
        for name in names:
            if name in OPTIONAL_MODULES:
                continue
            _required_import(name)
    except StartupImportFailed as failure:
        log.error(
            "event=startup_import_failed process=%s module=%s error_class=%s at=%s "
            "exit=%d",
            process,
            failure.module,
            failure.error_class,
            failure.where,
            EX_STARTUP_IMPORT,
        )
        if on_failure is not None:  # the entry point's record write
            on_failure(failure)
        raise
    return ()


def import_runtime_modules(
    system: str | None = None,
    process: str = "mcp-server",
    on_failure: Callable[[StartupImportFailed], None] | None = None,
) -> tuple[str, ...]:
    """Import the runtime tree or abort start-up (``StartupImportFailed``).

    No record side effect: ``on_failure`` is the entry point's own callback.

    Returns the failed modules, which is always empty: a required failure
    raises ``StartupImportFailed`` (exit ``EX_STARTUP_IMPORT``) instead.
    """
    return _fail_fast(process, runtime_module_names, system, on_failure)


def import_manager_modules(
    system: str | None = None,
    process: str = "job-manager",
    log_format: str | None = None,
    on_failure: Callable[[StartupImportFailed], None] | None = None,
) -> tuple[str, ...]:
    """Import the job manager's pinned set; aborts as ``import_runtime_modules``.

    ``log_format`` configures root logging first, for an entry that must not
    configure it at import time (RE1-F5: the server imports the Linux entry).
    """
    if log_format is not None:
        logging.basicConfig(
            level=logging.INFO, format=log_format, datefmt="%Y-%m-%dT%H:%M:%S"
        )
    return _fail_fast(process, manager_module_names, system, on_failure)

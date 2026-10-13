"""Early, explicit manager entry bootstrap before importing business backends.

This is the sole composition-level code that obtains configured state paths
when the manager is still inside its startup-import failure boundary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from binnacle.startup_imports import (
    EX_STARTUP_IMPORT,
    StartupImportFailed,
    _raising_frame,
    _required_import,
    import_manager_modules,
    record_start_failure,
    state_root_of,
)


def capture_startup_root(*, process: str, system: str) -> Path | None:
    """Load the appropriate configured root under a redacted import boundary.

    Linux MCP and jobs use the same Settings source as production. The Darwin
    job manager instead uses its strict *file-only* ManagerConfig, never the
    frontend's env-override-enabled Settings. Only a successful, one-time
    snapshot is used for subsequent failure receipts.
    """
    manager_darwin = process == "job-manager" and system == "Darwin"
    name = (
        "binnacle.platform.darwin.job_manager_config"
        if manager_darwin
        else "binnacle.config"
    )
    try:
        module = _required_import(name)
        settings = module.read_config() if manager_darwin else module.get_settings()
        return state_root_of(settings.jobs.dir)
    except (ValueError, OSError):
        # Preserve the existing config-invalid path in the serving entry.
        # Without a valid configuration, no failure-receipt path is trusted.
        return None
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        failure = (
            exc
            if isinstance(exc, StartupImportFailed)
            else StartupImportFailed(
                name, type(exc).__name__, _raising_frame(exc, name)
            )
        )
        logging.getLogger("binnacle.startup_imports").error(
            "event=startup_import_failed process=%s module=%s "
            "error_class=%s at=%s exit=%d",
            process,
            failure.module,
            failure.error_class,
            failure.where,
            EX_STARTUP_IMPORT,
        )
        raise failure from None


def record_early_failure(
    process: str, failure: StartupImportFailed, state_root: Path | None
) -> bool:
    """Use only the previously verified state root; NEVER reload configuration.

    A secondary exception, even SystemExit, must not mask the original
    StartupImportFailed or leak its message to stderr.
    """
    if state_root is None:
        logging.getLogger("binnacle.manager_bootstrap").error(
            "event=startup_import_record_error process=%s reason=no_trusted_root",
            process,
        )
        return False
    try:
        return record_start_failure(process, failure, state_root)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        logging.getLogger("binnacle.manager_bootstrap").error(
            "event=startup_import_record_error process=%s error_class=%s",
            process,
            type(exc).__name__,
        )
        return False


def bootstrap_manager_entry(system: str) -> None:
    """Validate the installed -m/console startup before importing backends.

    Library imports remain inert; an invalid manager configuration stays an
    ordinary manager configuration error, not an arbitrary writable path.
    """
    root = capture_startup_root(process="job-manager", system=system)

    def failed(failure: StartupImportFailed) -> None:
        record_early_failure("job-manager", failure, root)

    # Install the SAME timestamped format that the operational Darwin
    # telemetry config uses. basicConfig is inert once an early handler exists.
    output = "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s"
    import_manager_modules(
        system=system,
        process="job-manager",
        log_format=output,
        on_failure=failed,
    )

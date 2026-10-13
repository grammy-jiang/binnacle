"""Early, explicit manager entry bootstrap before importing business backends.

This is the sole composition-level code that obtains configured state paths
when the manager is still inside its startup-import failure boundary.
"""

from __future__ import annotations

import logging
import sys

from binnacle.startup_imports import (
    StartupImportFailed,
    import_manager_modules,
    record_start_failure,
    state_root_of,
)


def record_early_failure(process: str, failure: StartupImportFailed) -> bool:
    """Use only a fully initialized configuration for early failure receipts.

    Never import config while it itself may be failing: if its state root
    cannot be verified, retain the redacted log and exit 70.
    """
    try:
        config = sys.modules.get("binnacle.config")
        settings = getattr(config, "get_settings", None)
        if not callable(settings):
            raise TypeError("configured state root unavailable")
        state = state_root_of(settings().jobs.dir)
        if record_start_failure(process, failure, state):
            return True
    except Exception as exc:  # noqa: BLE001 - no trustworthy config, fail closed
        logging.getLogger("binnacle.manager_bootstrap").error(
            "event=startup_import_record_error process=%s error_class=%s",
            process,
            type(exc).__name__,
        )
        return False
    logging.getLogger("binnacle.manager_bootstrap").error(
        "event=startup_import_record_error process=%s", process
    )
    return False


def bootstrap_manager_entry(system: str) -> None:
    """Guard a real -m manager start before its heavy module imports.

    Called only in the __main__ path. Importing the manager as a library
    remains inert; the canonical module is included in the pinned set.
    """

    def failed(failure: StartupImportFailed) -> None:
        record_early_failure("job-manager", failure)

    output = (
        "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s"
        if system == "Linux"
        else "%(levelname)s %(message)s"
    )
    import_manager_modules(
        system=system,
        process="job-manager",
        log_format=output,
        on_failure=failed,
    )

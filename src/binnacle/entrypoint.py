"""Thin CLI composition: protect serving imports before loading CLI.

Non-serving subcommands preserve the existing lazy command dispatch.
"""

from __future__ import annotations

import logging
import sys
from typing import NoReturn


def _serve_import_failed(exc: BaseException) -> NoReturn:
    from binnacle import startup_imports
    from binnacle.manager_bootstrap import record_early_failure

    failure = startup_imports.StartupImportFailed(
        "binnacle.cli",
        type(exc).__name__,
        startup_imports._raising_frame(exc, "binnacle.cli"),
    )
    logging.getLogger("binnacle.startup_imports").error(
        "event=startup_import_failed process=mcp-server module=%s "
        "error_class=%s at=%s exit=%d",
        failure.module,
        failure.error_class,
        failure.where,
        startup_imports.EX_STARTUP_IMPORT,
    )
    record_early_failure("mcp-server", failure)
    raise failure from None


def main() -> None:
    """Dispatch Cyclopts commands; fail closed before loading serve code."""
    if sys.argv[1:2] != ["serve"]:
        from binnacle.cli import main as cli_main

        cli_main()
        return

    from binnacle import startup_imports
    from binnacle.manager_bootstrap import record_early_failure

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    def on_failure(failure: startup_imports.StartupImportFailed) -> None:
        record_early_failure("mcp-server", failure)

    with startup_imports.serving_entry():
        startup_imports.import_runtime_modules(on_failure=on_failure)
        try:
            from binnacle.cli import main as cli_main
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 - convert import failure safely
            _serve_import_failed(exc)
        cli_main()

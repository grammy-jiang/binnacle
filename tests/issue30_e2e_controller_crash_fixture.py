"""Synthetic maintenance controller subprocess; crash modes SIGKILL ONLY self."""

from __future__ import annotations

import os
import re
import signal
import sys
from pathlib import Path
from typing import Any, cast

from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from tests.issue30_full_transaction_fixture import (
    FixtureProducer,
    run_complete_fixture_transaction,
    setup_fixture,
)
from tests.platform.darwin.test_job_manager_maintenance_fence import _manager

_ROOT = re.compile(r"^issue30-fixture-e2e-[0-9a-f]{32}$")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[1] not in {
        "after-stop",
        "after-canonical",
        "after-raw-unlink",
        "after-restored",
    }:
        return 64
    root, mode = Path(args[0]), args[1]
    if (
        sys.platform != "linux"
        or os.getuid() == 0
        or os.geteuid() != os.getuid()
        or not root.is_absolute()
        or _ROOT.fullmatch(root.name) is None
        or root.exists()
    ):
        return 64
    setup_fixture(root)
    manager, _owner, _fence = _manager(root)
    writer = FixtureProducer(root)
    writer.start_original()

    def crash_only_this_fixture_controller() -> None:
        if _ROOT.fullmatch(root.name) is None or not root.is_dir():
            raise RuntimeError("test fixture path changed")
        os.kill(os.getpid(), signal.SIGKILL)

    opts = {}
    if mode == "after-stop":
        opts["after_stop"] = crash_only_this_fixture_controller
    elif mode == "after-canonical":
        opts["after_canonical_verified"] = crash_only_this_fixture_controller
    elif mode == "after-raw-unlink":
        opts["after_raw_unlink"] = crash_only_this_fixture_controller
    else:
        opts["after_producer_restored"] = crash_only_this_fixture_controller
    run_complete_fixture_transaction(
        root,
        manager=manager,
        mcp=ToolAdmissionDrain(),
        writer=writer,
        **cast(Any, opts),
    )
    return 99  # Any normal return instead of SIGKILL is a failed test.


if __name__ == "__main__":
    sys.exit(main())

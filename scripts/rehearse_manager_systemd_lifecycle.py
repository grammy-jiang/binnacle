#!/usr/bin/env python3
"""Explicit D1 isolated real-systemd rehearsal, outside pytest's host guard.

Run only with BINNACLE_D1_SYSTEMD_REHEARSAL=1 on Linux. It creates and stops
exactly two uniquely named transient test units, never binnacle-jobs.service.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _production_owner() -> tuple[str, str]:
    completed = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            "--property=MainPID,ActiveState",
            "binnacle-jobs.service",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    properties = dict(line.split("=", 1) for line in completed.stdout.splitlines())
    return properties["ActiveState"], properties["MainPID"]


def main() -> None:
    if (
        sys.platform != "linux"
        or os.environ.get("BINNACLE_D1_SYSTEMD_REHEARSAL") != "1"
    ):
        raise SystemExit("explicit opt-in required: BINNACLE_D1_SYSTEMD_REHEARSAL=1")
    if os.geteuid() == 0:
        raise SystemExit("must run as an unprivileged systemd user")
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "src"))
    from scripts.manager_systemd_test_support import (
        check_completed_job_is_preserved_on_owner_stop,
        check_control_group_stop_terminates_active_job,
    )

    before = _production_owner()
    if before[0] != "active" or not before[1].isdigit() or int(before[1]) < 2:
        raise RuntimeError(
            "refusing rehearsal with unexpected production Manager status"
        )
    with tempfile.TemporaryDirectory(prefix="binnacle-d1c-isolated-systemd-") as root:
        sandbox = Path(root)
        active = sandbox / "active-job"
        active.mkdir()
        active_result = check_control_group_stop_terminates_active_job(active)
        drained = sandbox / "drained-job"
        drained.mkdir()
        completed_result = check_completed_job_is_preserved_on_owner_stop(drained)
    after = _production_owner()
    assert after == before, (
        f"production Manager unexpectedly changed: {before}->{after}"
    )
    print(
        json.dumps(
            {
                "scope": "three standalone transient test-only systemd user units across two scenarios; NOT the live Manager",
                "active_job_terminated_by_control_group_stop": True,
                "completed_job_retains_exit_zero_and_output_after_drain": True,
                "real_systemd_delegate_subgroup_verified": True,
                "production_manager_active_and_pid_unchanged": True,
                "production_manager_pid": before[1],
                "production_manager_restarted_or_reconfigured": False,
                "live_manager_active_job_safety_proven": False,
                "decision": "active jobs are killed by control-group stop; pause-admission plus completed-job drain is verified on test units, NOT an approved production rollout",
                "active_job": active_result,
                "completed_job": completed_result,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

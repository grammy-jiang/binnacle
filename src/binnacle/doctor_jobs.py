"""Job-lifecycle diagnostics shared by the CLI doctor and mode gate."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from binnacle import jobs, logstats
from binnacle.deployment_platform import create_service_inspector
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceInspector,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogError


def _job_state_safe(job_id: str) -> dict | None:
    try:
        return jobs.job_state(job_id)
    except (KeyError, OSError):
        return None


def server_uses_manager(
    unit: str,
    inspector: ManagedServiceInspector | None = None,
) -> bool:
    """Whether the currently running MCP process has durable manager ownership.

    The unit file may already have been rewritten during an upgrade while the old
    embedded-owner process is still running, so inspect the live process
    environment through the platform seam. A non-active unit has no embedded
    jobs left to protect.
    """

    services = inspector or create_service_inspector()
    status = services.status(unit)
    if status.state != "active":
        return True
    managed = services.main_process_has_environment(
        unit, "BINNACLE_MANAGED_DEPLOYMENT", "1"
    )
    return managed is True


def server_busy_reasons(
    unit: str,
    jobs_dir: Path,
    window: str = "-30s",
    fetch: Callable[[str, str], str] = lambda u, s: logstats.fetch_journal(u, s),
    *,
    include_jobs: bool = True,
    state_reader: Callable[[str], dict | None] = _job_state_safe,
) -> list[str]:
    """Why restarting the MCP unit now would hurt active work."""
    reasons: list[str] = []
    if include_jobs and jobs_dir.is_dir():
        running = [
            d.name
            for d in sorted(jobs_dir.iterdir())
            if d.is_dir()
            and (state := state_reader(d.name)) is not None
            and state["state"] == "running"
        ]
        if running:
            shown = ", ".join(running[:3]) + (" ..." if len(running) > 3 else "")
            reasons.append(
                f"{len(running)} background job(s) running ({shown}); a unit "
                "restart kills them"
            )
    try:
        calls = fetch(unit, window).count("event=tool_call")
    except (ServiceLogError, OSError, subprocess.SubprocessError) as exc:
        reasons.append(
            f"journal unreadable ({exc}); cannot tell whether calls are in flight"
        )
        return reasons
    if calls:
        reasons.append(
            f"{calls} tool call(s) in the last {window.lstrip('-')}; a restart "
            "fails the calls in flight"
        )
    return reasons

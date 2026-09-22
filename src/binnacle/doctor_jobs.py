"""Job-lifecycle diagnostics shared by the CLI doctor and mode gate."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from binnacle import jobs, logstats


def _job_state_safe(job_id: str) -> dict | None:
    try:
        return jobs.job_state(job_id)
    except (KeyError, OSError):
        return None


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
    except (OSError, subprocess.SubprocessError) as exc:
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

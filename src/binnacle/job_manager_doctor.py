"""Deployment checks for the stable command-owner service."""

from collections.abc import Callable
from pathlib import Path

from binnacle import job_client
from binnacle.doctor_common import (
    Check,
    Systemctl,
    fail,
    ok,
    systemctl,
    unit_property,
    unit_state,
    warn,
)


def check_job_manager(
    unit: str,
    socket_path: Path,
    run: Systemctl = systemctl,
    ping: Callable[[Path], dict] = job_client.ping,
) -> tuple[list[Check], str | None]:
    state = unit_state(unit, run)
    if state != "active":
        return (
            [
                fail(
                    "jobs-service",
                    f"{unit} is {state}",
                    f"systemctl --user start {unit}, or run `binnacle setup`",
                )
            ],
            None,
        )

    checks = [ok("jobs-service", f"{unit} active")]
    restarts = unit_property(unit, "NRestarts", run)
    if restarts.isdigit() and int(restarts) > 0:
        checks.append(
            warn(
                "jobs-service",
                f"{unit} restarted {restarts} time(s) since it was started",
                f"journalctl --user -u {unit} for the crash reason",
            )
        )
    else:
        checks.append(ok("jobs-service", f"{unit} has not crash-restarted"))

    try:
        response = ping(socket_path)
    except (job_client.JobManagerError, OSError) as exc:
        checks.append(
            fail(
                "jobs-service",
                f"manager socket {socket_path} is not responding: {exc}",
                f"journalctl --user -u {unit}",
            )
        )
    else:
        owner = str(response.get("owner_instance_id", "?"))[:12]
        checks.append(ok("jobs-service", f"manager socket responds (owner={owner})"))
    return checks, unit

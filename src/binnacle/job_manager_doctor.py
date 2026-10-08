"""Deployment checks for the stable command-owner service."""

from collections.abc import Callable
from pathlib import Path

from binnacle import job_client
from binnacle.diagnostics.doctor_common import Check, fail, ok, warn
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceInspector,
)
from binnacle.platform.deployment_platform import create_service_inspector


def check_job_manager(
    unit: str,
    socket_path: Path,
    inspector: ManagedServiceInspector | None = None,
    ping: Callable[[Path], dict] = job_client.ping,
    *,
    expected_revision: str | None = None,
) -> tuple[list[Check], str | None]:
    services = inspector or create_service_inspector()
    status = services.status(unit)
    state = status.state
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
    restarts = status.restart_count
    if restarts is not None and restarts > 0:
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
        package = str(response.get("package_version", "?"))
        revision = str(response.get("revision", "?"))
        detail = (
            "manager socket responds "
            f"(owner={owner} package={package} revision={revision})"
        )
        unknown = {"", "?", "unknown"}
        expected_known = expected_revision not in (None, *unknown, "installed")
        revision_known = revision not in unknown
        if package in unknown or not revision_known:
            checks.append(
                warn(
                    "jobs-service",
                    detail,
                    "restart the jobs service at a quiet moment after upgrading Binnacle",
                )
            )
        elif expected_known and revision != expected_revision:
            checks.append(
                warn(
                    "jobs-service",
                    detail,
                    (
                        f"running revision {revision} differs from checkout "
                        f"{expected_revision}; restart binnacle-jobs.service only "
                        "when no jobs are running"
                    ),
                )
            )
        else:
            checks.append(ok("jobs-service", detail))
    return checks, unit

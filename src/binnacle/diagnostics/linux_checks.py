"""Linux managed-service, linger and journal diagnostic checks.

The generic doctor module delegates systemd/procfs/login-specific
diagnostics at call time; this module owns their exact legacy message text.
"""

import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from binnacle.doctor_contracts import Check, fail, ok, warn
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceInspector,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogError


def check_units(
    unit: str,
    inspector: ManagedServiceInspector,
    waits_for_ready: Callable[[str], bool],
    linger: Callable[[], bool | None],
) -> tuple[list[Check], str | None]:
    """Returns the checks and the server unit's name when it is active."""
    services = inspector
    status = services.status(unit)
    state = status.state
    out: list[Check] = []
    if state != "active":
        out.append(
            fail(
                "units",
                f"{unit} is {state}",
                f"systemctl --user start {unit}, or `binnacle setup` if it is missing",
            )
        )
        return out, None
    out.append(ok("units", f"{unit} active"))
    restarts = status.restart_count
    if restarts is not None and restarts > 0:
        out.append(
            warn(
                "units",
                f"{unit} restarted {restarts} time(s) since it was started",
                f"journalctl --user -u {unit} for the crash reason",
            )
        )
    else:
        out.append(ok("units", f"{unit} has not crash-restarted"))
    if waits_for_ready(unit):
        out.append(ok("units", f"{unit} waits for its port before reporting started"))
    else:
        out.append(
            warn(
                "units",
                f"{unit} reports started before it listens",
                "add an ExecStartPost port wait (see `binnacle setup` templates); "
                "without it the tunnel probes a dead port on every restart",
            )
        )
    lg = linger()
    if lg is True:
        out.append(ok("units", "linger enabled (services survive logout)"))
    elif lg is False:
        out.append(warn("units", "linger disabled", "loginctl enable-linger"))
    return out, unit


def check_service_env(
    unit: str,
    rg_bin: str,
    user_bin: Path,
    inspector: ManagedServiceInspector,
) -> list[Check]:
    services = inspector
    status = services.status(unit)
    pid = status.main_pid
    if pid is None:
        return [warn("service-env", f"{unit} has no main PID to inspect")]
    path = services.main_process_path(unit)
    if path is None:
        return [warn("service-env", f"cannot read /proc/{pid}/environ")]
    out: list[Check] = []
    if str(user_bin) in path.split(os.pathsep):
        out.append(ok("service-env", f"{user_bin} is on the service PATH"))
    else:
        out.append(
            fail(
                "service-env",
                f"{user_bin} is not on the service PATH ({path})",
                "add PATH=$HOME/.local/bin:$PATH to ~/.config/environment.d/50-path.conf, "
                "then `systemctl --user daemon-reload` and restart the services; "
                "until then run_command cannot find uv or other user-installed tools",
            )
        )
    for name, tool in (("bash", "run_command"), (rg_bin, "list_files/search_text")):
        found = shutil.which(name, path=path)
        if found:
            out.append(ok("service-env", f"{name} resolves to {found}"))
        else:
            out.append(
                fail(
                    "service-env",
                    f"{name} not found on the service PATH; {tool} will fail",
                    f"install {name} or fix the service PATH",
                )
            )
    return out


def check_boot(
    run: Callable[..., object] | None = None,
    user: str | None = None,
    provisioner_factory: Callable[..., Any] | None = None,
) -> list[Check]:
    """User services only start at boot without a login when lingering is
    on; without it every binnacle unit waits for someone to log in."""
    who = user or os.environ.get("USER") or ""
    runner = None
    if run is not None:
        runner = lambda argv, **kwargs: run(*argv, **kwargs)
    from binnacle.platform.deployment_platform import create_linux_provisioner

    factory = provisioner_factory or create_linux_provisioner
    inspection = factory(run=runner).inspect_persistence(user=who, timeout=15)
    if inspection.error is not None:
        return [warn("boot", f"loginctl could not run: {inspection.error}")]
    if inspection.enabled:
        return [ok("boot", f"lingering is on for {who}: the units start at boot")]
    return [
        fail(
            "boot",
            f"lingering is off for {who}: after a reboot nothing starts until a login",
            f"loginctl enable-linger {who}",
        )
    ]


_JOURNAL_ERROR = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}T\S+\s+)?(?:ERROR|CRITICAL):(?:\s|$)|^(?:\[[^]]+\]\s+)?\s*(?:ERROR|CRITICAL)\s+event="
)


def check_journal(
    unit: str,
    since: str,
    fetch: Callable[[str, str], str],
) -> list[Check]:
    try:
        text = fetch(unit, since)
    except ServiceLogError as e:
        return [warn("journal", f"journal unavailable: {e}")]
    errors = sum(1 for line in text.splitlines() if _JOURNAL_ERROR.match(line))
    tracebacks = sum(1 for line in text.splitlines() if line.startswith("Traceback"))
    if not errors and not tracebacks:
        return [ok("journal", f"no errors in the {unit} journal since {since}")]
    return [
        warn(
            "journal",
            f"{errors} error line(s) and {tracebacks} traceback(s) since {since}",
            f"journalctl --user -u {unit} --since='{since}' --no-pager -o cat",
        )
    ]

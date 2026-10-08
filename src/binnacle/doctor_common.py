"""Shared health-check records and systemd primitives."""

import subprocess
from collections.abc import Callable

from binnacle.diagnostics import doctor_contracts as _contracts

Check = _contracts.Check
Status = _contracts.Status
ok = _contracts.ok
warn = _contracts.warn
fail = _contracts.fail


Systemctl = Callable[..., "subprocess.CompletedProcess[str]"]


def systemctl(*args: str) -> "subprocess.CompletedProcess[str]":
    from binnacle.platform.deployment_platform import create_linux_provisioner

    return create_linux_provisioner().systemctl(*args, check=False)


def unit_state(unit: str, run: Systemctl | None = None) -> str:
    if run is None:
        from binnacle.platform.deployment_platform import create_service_inspector

        return create_service_inspector().status(unit).state
    return run("is-active", unit).stdout.strip() or "unknown"


def unit_property(unit: str, prop: str, run: Systemctl = systemctl) -> str:
    return run("show", unit, "-p", prop, "--value").stdout.strip()

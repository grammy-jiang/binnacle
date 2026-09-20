"""Watchdog inventory and host version rendering."""

import sys
from collections.abc import Collection
from pathlib import Path

from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.hardware import (
    driver_module_of,
    driver_of,
    module_params,
    usb_node_of,
)
from binnacle.ops.watchdog.model import DeviceInfo
from binnacle.ops.watchdog.network import (
    WifiProfile,
    device_mac,
    profile_binding,
    profile_details,
    profile_metric,
)


def inventory_line(
    dev: str,
    info: DeviceInfo,
    profiles: list[WifiProfile],
    run: Run,
    param_names: Collection[str],
) -> str:
    """One line that pins down what a device *is*: bus, id, node, link
    speed, driver, module and its parameters, and every profile bound to
    it with priority and metric. Logged at start and whenever it changes."""
    node, usb_id = usb_node_of(dev)
    _, driver_dir = driver_of(dev)
    driver = Path(driver_dir).name if driver_dir else "?"
    module, _ = driver_module_of(dev)
    params = module_params(module, param_names)
    bound = []
    macs = {dev: device_mac(dev, run)}
    for p in profiles:
        if (
            p.device == dev
            or profile_binding(profile_details(p.name, run), macs) == dev
        ):
            metric = profile_metric(p.name, run)
            bound.append(
                f"{p.name}:prio{p.priority}:metric{metric}:{'auto' if p.autoconnect else 'manual'}"
            )
    kind = f"usb:{usb_id}@{node}:{info.usb_speed or '?'}Mbit" if usb_id else "builtin"
    return (
        f"kind={kind} driver={driver} module={module or '?'}"
        + (
            " params=" + ",".join(f"{k}={v}" for k, v in params.items())
            if params
            else ""
        )
        + f" profiles={';'.join(bound) or '-'}"
    )


def versions(run: Run = _run) -> dict[str, str]:
    """What is running: binnacle, Python, kernel, NetworkManager."""
    out: dict[str, str] = {"python": sys.version.split()[0]}
    try:
        from importlib.metadata import version as pkg_version

        out["binnacle"] = pkg_version("binnacle-mcp")
    except Exception:  # noqa: BLE001 - version is informational
        out["binnacle"] = "?"
    proc = run("uname", "-r")
    out["kernel"] = proc.stdout.strip() if proc.returncode == 0 else "?"
    proc = run("nmcli", "--version")
    out["networkmanager"] = (
        proc.stdout.strip().rsplit(" ", 1)[-1] if proc.returncode == 0 else "?"
    )
    return out

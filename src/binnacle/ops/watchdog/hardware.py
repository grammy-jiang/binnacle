"""Hardware, driver, and USB observations/actions for the watchdog."""

import time
from collections.abc import Callable, Collection
from pathlib import Path

from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import DEFAULT_POLICY, Policy

SYS_MODULE = Path("/sys/module")
USB_DEVICES = Path("/sys/bus/usb/devices")
NET_CLASS = Path("/sys/class/net")
USBDEVFS_RESET = 21780


def usb_speed_of(node: str) -> int | None:
    """Negotiated USB link speed in Mbit/s (sysfs `speed`)."""
    try:
        return int((USB_DEVICES / node / "speed").read_text().strip())
    except (OSError, ValueError):
        return None


def driver_of(dev: str) -> tuple[str | None, str | None]:
    """(sysfs device name, driver directory) behind a network interface."""
    try:
        device_dir = (NET_CLASS / dev / "device").resolve()
        driver_dir = (device_dir / "driver").resolve()
    except OSError:
        return None, None
    if not driver_dir.is_dir():
        return device_dir.name, None
    return device_dir.name, str(driver_dir)


def driver_module_of(dev: str) -> tuple[str | None, list[str]]:
    """(kernel module of the interface's driver, modules that hold it).

    The holders must be unloaded first: on the Pi 5 the built-in radio's
    brcmfmac is held by brcmfmac_cyw.
    """
    _, driver_dir = driver_of(dev)
    if driver_dir is None:
        return None, []
    try:
        module = (Path(driver_dir) / "module").resolve().name
    except OSError:
        return None, []
    holders_dir = SYS_MODULE / module / "holders"
    holders: list[str] = []
    if holders_dir.is_dir():
        holders = sorted(p.name for p in holders_dir.iterdir())
    return module, holders


def driver_reload(dev: str, run: Run = _run) -> tuple[bool, str]:
    """Unload and reload the interface's driver module, as root via
    `sudo -n`: the non-USB cousin of the USB reset. Tested on the Pi 5's
    built-in radio 2026-09-13: a sysfs unbind/bind of the SDIO function
    left the firmware bus down ("bus is down", bind -EIO) and the radio
    gone; `modprobe -r brcmfmac_cyw brcmfmac` then `modprobe brcmfmac`
    brought wlan0 back in about ten seconds. Refuses a USB device -- that
    path has its own, better-tested rung."""
    _, usb_id = usb_node_of(dev)
    if usb_id is not None:
        return False, f"{dev} is a USB device ({usb_id}); use the USB reset"
    module, holders = driver_module_of(dev)
    if module is None:
        return False, f"{dev}: no driver module in sysfs"
    unload = " ".join(holders + [module])
    script = f"modprobe -r {unload} && modprobe {module}"
    proc = run("sudo", "-n", "sh", "-c", script, timeout=120.0)
    if proc.returncode != 0:
        return (
            False,
            f"reload of {module} failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )
    return True, f"reloaded {module}" + (
        f" (after {', '.join(holders)})" if holders else ""
    )


def host_health(run: Run = _run) -> dict[str, str]:
    """Power and thermal flags from the firmware (`vcgencmd`), where
    available: under-voltage is the classic cause of USB adapters going
    quiet. Empty on a host without the tool."""
    out: dict[str, str] = {}
    proc = run("vcgencmd", "get_throttled")
    if proc.returncode == 0 and "=" in proc.stdout:
        raw = proc.stdout.strip().split("=", 1)[1]
        out["throttled"] = raw
        try:
            bits = int(raw, 16)
        except ValueError:
            bits = 0
        flags = []
        for bit, name in (
            (0, "under-voltage now"),
            (1, "arm frequency capped now"),
            (2, "throttled now"),
            (3, "soft temperature limit now"),
            (16, "under-voltage occurred"),
            (17, "arm frequency capped occurred"),
            (18, "throttled occurred"),
            (19, "soft temperature limit occurred"),
        ):
            if bits & (1 << bit):
                flags.append(name)
        out["flags"] = ", ".join(flags) or "none"
    proc = run("vcgencmd", "measure_temp")
    if proc.returncode == 0 and "=" in proc.stdout:
        out["temp"] = proc.stdout.strip().split("=", 1)[1]
    return out


def module_params(module: str | None, names: Collection[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not module:
        return out
    for name in names:
        try:
            out[name] = (SYS_MODULE / module / "parameters" / name).read_text().strip()
        except OSError:
            continue
    return out


def usb_adapters_without_netdev(usb_ids: Collection[str]) -> dict[str, str]:
    """USB nodes carrying a known adapter id that expose no network
    interface: the device is on the bus, the driver is not bound."""
    out: dict[str, str] = {}
    try:
        nodes = list(USB_DEVICES.iterdir())
    except OSError:
        return out
    for node in nodes:
        try:
            vendor = (node / "idVendor").read_text().strip()
            product = (node / "idProduct").read_text().strip()
        except OSError:
            continue
        usb_id = f"{vendor}:{product}"
        if usb_id not in usb_ids:
            continue
        has_net = any(
            (child / "net").is_dir() for child in node.iterdir() if child.is_dir()
        )
        if not has_net:
            out[f"usb:{node.name}"] = (
                f"adapter {usb_id} at {node.name} has no network interface "
                "(driver not bound)"
            )
    return out


def usb_node_of(dev: str) -> tuple[str | None, str | None]:
    """(USB device node like '2-1', 'vendor:product') for a network interface.

    Resolved fresh on every call: across the mode-1 re-enumeration the same
    adapter moves from 1-1 to 2-1 and its device number changes.
    """
    try:
        interface_dir = (NET_CLASS / dev / "device").resolve()
    except OSError:
        return None, None
    node_dir = interface_dir.parent  # '<node>:1.0' -> '<node>'
    try:
        vendor = (node_dir / "idVendor").read_text().strip()
        product = (node_dir / "idProduct").read_text().strip()
    except OSError:
        return None, None
    return node_dir.name, f"{vendor}:{product}"


def usb_devfs_path(node: str) -> Path | None:
    """/dev/bus/usb/BBB/DDD for a sysfs node; the device number changes on
    every re-enumeration, so this is read fresh, never cached."""
    try:
        bus = int((USB_DEVICES / node / "busnum").read_text())
        devnum = int((USB_DEVICES / node / "devnum").read_text())
    except (OSError, ValueError):
        return None
    return Path(f"/dev/bus/usb/{bus:03d}/{devnum:03d}")


def usb_reset_device(
    dev: str,
    policy: Policy = DEFAULT_POLICY,
    run: Run = _run,
    node_of: Callable[[str], tuple[str | None, str | None]] = usb_node_of,
    settle: Callable[[float], None] = time.sleep,
    method: str = "authorized",
    devfs_of: Callable[[str], Path | None] = usb_devfs_path,
) -> tuple[bool, str]:
    """Reset the interface's USB device: the software replug.

    `authorized`: writes 0 then 1 to the node's sysfs attribute -- the
    kernel deconfigures and reconfigures the device in place (same node),
    the driver reloads, NetworkManager reconnects. Proven on a real wedge
    2026-09-12 21:51. `port_reset`: USBDEVFS_RESET on the devfs node -- a
    bus-level port reset that re-enumerates the device, one step closer to
    a physical replug (still no VBUS drop). Both run as root via `sudo -n`,
    which this host grants without a password. Refuses any node whose USB
    id is not in `policy.usb_reset_ids`, and any method not named in
    `policy.usb_reset_methods`.
    """
    node, usb_id = node_of(dev)
    if node is None or usb_id is None:
        return False, f"{dev} has no resolvable USB node"
    if usb_id not in policy.usb_reset_ids:
        return (
            False,
            f"refusing to reset {node}: USB id {usb_id} is not in {policy.usb_reset_ids}",
        )
    if method not in policy.usb_reset_methods:
        return False, f"unknown USB reset method {method!r}"
    if method == "port_reset":
        devfs = devfs_of(node)
        if devfs is None:
            return False, f"{node}: cannot read busnum/devnum for a port reset"
        script = (
            "import fcntl, os; "
            f"fd = os.open({str(devfs)!r}, os.O_WRONLY); "
            f"fcntl.ioctl(fd, {USBDEVFS_RESET}, 0); os.close(fd)"
        )
        proc = run("sudo", "-n", "python3", "-c", script, timeout=30.0)
        if proc.returncode != 0:
            return (
                False,
                f"USBDEVFS_RESET on {devfs} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )
        return True, f"port reset {node} via {devfs} ({usb_id})"
    authorized = USB_DEVICES / node / "authorized"
    for value in ("0", "1"):
        proc = run(
            "sudo", "-n", "sh", "-c", f"echo {value} > {authorized}", timeout=20.0
        )
        if proc.returncode != 0:
            return (
                False,
                f"write {value} to {authorized} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )
        if value == "0":
            settle(2.0)
    return True, f"re-initialised {node} via authorized ({usb_id})"

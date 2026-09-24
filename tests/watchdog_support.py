"""Shared fixtures and fakes for watchdog system tests."""

import json
import subprocess
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any
from unittest import mock

from binnacle import watchdog as wd
from binnacle.ops.watchdog import actions as wd_actions
from binnacle.ops.watchdog import cycle as wd_cycle
from binnacle.ops.watchdog import hardware as wd_hardware
from binnacle.ops.watchdog import inventory as wd_inventory
from binnacle.ops.watchdog import maintenance as wd_maintenance
from binnacle.ops.watchdog import network as wd_network
from binnacle.ops.watchdog import services as wd_services
from binnacle.ops.watchdog import tunnel as wd_tunnel
from binnacle.uplink import ProbeResult, Route

__all__ = [
    "CONNECTIONS",
    "DETAILS",
    "ROUTES",
    "SCHEDULE",
    "SS_ON_WLAN2",
    "THREE",
    "WLAN0",
    "WLAN1",
    "WLAN2",
    "FakeThread",
    "Path",
    "ProbeResult",
    "Route",
    "all_healthy",
    "both_healthy",
    "degraded",
    "demoted_after_reset",
    "demoted_state",
    "dev_info",
    "fake_sudo",
    "fast_env",
    "healthy",
    "json",
    "kinds",
    "link_fake",
    "lossy",
    "mock",
    "nm_fake",
    "obs",
    "outage",
    "pairwise",
    "patch_http_alive",
    "patch_usb_node_of",
    "pref",
    "preference_demotion",
    "recording_nmcli",
    "routes_demoted",
    "socket_fake",
    "subprocess",
    "sys_obs",
    "usb_devices",
    "wd",
    "wd_actions",
    "wd_cycle",
    "wd_hardware",
    "wd_tunnel",
    "wedged",
]

WLAN1 = Route(dev="wlan1", gateway="192.168.50.1", src="192.168.50.197", metric=100)

WLAN0 = Route(dev="wlan0", gateway="192.168.50.1", src="192.168.50.222", metric=600)

ROUTES = [WLAN1, WLAN0]


def patch_http_alive(monkeypatch, func) -> None:
    """Patch HTTP health at the real post-refactor service/tunnel seams."""

    observe = wd_services.observe_services
    monkeypatch.setattr(
        wd_maintenance,
        "observe_services",
        lambda policy, run: observe(policy, run, alive=func),
    )
    monkeypatch.setattr(wd_tunnel, "http_alive", func)
    monkeypatch.setattr(wd, "http_alive", func, raising=False)


def patch_usb_node_of(monkeypatch, func) -> None:
    """Patch the USB-node seam in every companion module that consumes it."""
    monkeypatch.setattr(wd, "usb_node_of", func, raising=False)
    monkeypatch.setattr(wd_hardware, "usb_node_of", func)
    monkeypatch.setattr(wd_network, "usb_node_of", func)
    monkeypatch.setattr(wd_inventory, "usb_node_of", func)


def healthy(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": True, "dns": True, "tcp": True})


def wedged(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": False, "dns": False, "tcp": False})


def degraded(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": True, "dns": False, "tcp": False})


def outage() -> dict[str, ProbeResult]:
    return {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}


def kinds(actions: list[wd.Action]) -> list[str]:
    return [a.kind for a in actions]


def recording_nmcli(profiles: str = "wlan1:Occom-USB\nwlan0:Occom\n", code: int = 0):
    """Records argv; answers `device status` with `profiles`."""
    calls: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        out = profiles if args[:3] == ("nmcli", "-t", "-f") else ""
        if args[:2] == ("systemctl", "is-active") or args[:3] == (
            "systemctl",
            "--user",
            "is-active",
        ):
            out = "active"
        return subprocess.CompletedProcess(list(args), code, stdout=out, stderr="err")

    return run, calls


def lossy(dev: str) -> ProbeResult:
    """Packet loss on the way to the gateway while DNS and TCP still pass."""
    return ProbeResult(dev=dev, layers={"gateway": False, "dns": True, "tcp": True})


def demoted_state() -> wd.State:
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="2026-09-12T01:00:00+00:00",
        reason="wedged",
    )
    return state


SCHEDULE = ((3, 60.0), (3, 180.0), (3, 300.0), (0, 600.0))


def demoted_after_reset(reset_at: float) -> wd.State:
    state = demoted_state()
    state.last_reset["wlan1"] = reset_at
    return state


def routes_demoted() -> list[Route]:
    return [WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]


def fake_sudo(code: int = 0):
    calls: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(list(args), code, stdout="", stderr="denied")

    return run, calls


def pref(dev: str, current: str, target: str | None, visible: bool = True):
    return wd.Preference(dev=dev, current=current, target=target, visible=visible)


def both_healthy() -> dict[str, ProbeResult]:
    return {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}


def preference_demotion(since_ts: float) -> wd.State:
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="2026-09-13T11:00:00+00:00",
        reason="moving to preferred profile",
        kind="preference",
        target="Occom-5G-USB",
        target_metric=100,
        since_ts=since_ts,
    )
    state.last_reset["wlan1"] = since_ts
    return state


def nm_fake(
    profiles: str = "wlan1:Occom-USB\nwlan0:Occom\n",
    connections: str = "",
    details: dict[str, str] | None = None,
    metrics: dict[str, str] | None = None,
    scans: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
    fail: tuple[str, ...] = (),
    devices: str = "",
    infos: dict[str, str] | None = None,
    radio: str = "enabled",
):
    """A NetworkManager that answers the queries the preference code makes."""
    calls: list[tuple[str, ...]] = []
    details = details or {}
    metrics = metrics or {}
    scans = scans or {}
    links = links or {}
    infos = infos or {}

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        out, code = "", 0
        if args[:3] == ("nmcli", "-t", "-f") and args[3] == "DEVICE,CONNECTION":
            out = profiles
        elif args[:3] == ("nmcli", "-t", "-f") and args[3].startswith("DEVICE,TYPE"):
            out = devices
        elif args[:2] == ("iw", "dev") and args[3:] == ("info",):
            out = infos.get(args[2], "")
            code = 0 if args[2] in infos else 1
        elif args[:4] == ("nmcli", "-t", "radio", "wifi"):
            out = radio
        elif args[:2] == ("systemctl", "is-active") or args[:3] == (
            "systemctl",
            "--user",
            "is-active",
        ):
            out = "active"
        elif args[:3] == ("nmcli", "-t", "-f") and args[3].startswith("NAME,TYPE"):
            out = connections
        elif args[:5] == ("nmcli", "-t", "-g", "STATE", "general"):
            out = "connected"
        elif args[:3] == ("nmcli", "-t", "-g"):
            out = details.get(args[-1], "")
            code = 0 if args[-1] in details else 10
        elif args[:3] == ("nmcli", "-g", "ipv4.route-metric"):
            out = metrics.get(args[-1], "")
            code = 0 if args[-1] in metrics else 10
        elif args[:3] == ("nmcli", "-t", "-f") and args[3] == "SSID":
            out = scans.get(args[8], "")
        elif args[:3] == ("sudo", "-n", "iw") and args[5:] == ("scan",):
            out = scans.get("iw:" + args[4], "")
            code = 0 if "iw:" + args[4] in scans else 1
        elif args[:2] == ("iw", "dev"):
            out = links.get(args[2], "")
            code = 0 if args[2] in links else 1
        if args[1:3] in fail or args[:2] in fail:
            code = 1
        return subprocess.CompletedProcess(list(args), code, stdout=out, stderr="err")

    return run, calls


CONNECTIONS = (
    "Occom-USB:802-11-wireless:wlan1:yes:0\n"
    "Occom:802-11-wireless:wlan0:yes:0\n"
    "Occom-5G-USB:802-11-wireless::yes:20\n"
    "Occom-2.4G:802-11-wireless::yes:0\n"
    "Office:802-11-wireless::yes:50\n"
    "Wired connection 1:802-3-ethernet::yes:-999\n"
)

DETAILS = {
    "Occom-5G-USB": "wlan1\nOccom_5G\n",
    "Occom-2.4G": "wlan0\nOccom_2.4G\n",
    "Office": "eth0\nOffice\n",  # bound to another interface: never a candidate
}


def dev_info(dev: str, nm_state: str = "connected", **kw) -> wd.DeviceInfo:
    return wd.DeviceInfo(dev=dev, nm_state=nm_state, **kw)


def usb_devices(speed: int) -> dict[str, wd.DeviceInfo]:
    return {
        "wlan1": dev_info(
            "wlan1", profile="Occom-USB", usb_id="0bda:8812", usb_speed=speed
        ),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }


def obs(**kw: Any) -> wd.ServiceObservation:
    base = wd.ServiceObservation(
        mcp_unit="binnacle-mcp.service",
        endpoint_ok=True,
        tunnel_active=True,
        poll_failures=0,
        poll_failing_since=None,
    )
    return replace(base, **kw)


def sys_obs(**kw: Any) -> wd.SystemObservation:
    return replace(wd.SystemObservation(), **kw)


WLAN2 = Route(dev="wlan2", gateway="192.168.50.1", src="192.168.50.231", metric=300)

THREE = [WLAN1, WLAN2, WLAN0]


def fast_env(monkeypatch, routes=None):
    monkeypatch.setattr(
        wd.uplink, "read_default_routes", lambda run: (routes or ROUTES, True)
    )
    monkeypatch.setitem(wd.uplink._last_address, "api.openai.com", "172.66.0.243")


SS_ON_WLAN2 = (
    '0 0 192.168.50.231:47664 172.66.0.243:443 users:(("tunnel-client",pid=1234,fd=10))\n'
    '0 0 192.168.50.231:5555 10.0.0.1:443 users:(("chrome",pid=99,fd=3))\n'
    '0 0 127.0.0.1:46232 127.0.0.1:8000 users:(("tunnel-client",pid=1234,fd=11))\n'
)


def socket_fake(inner, pid: str = "1234", ss: str = "", addr: str = ""):
    """Wrap a run fake with answers for the tunnel-socket queries."""

    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        if args[:3] == ("systemctl", "--user", "show") and "MainPID" in args:
            return subprocess.CompletedProcess(list(args), 0, stdout=pid, stderr="")
        if args[:2] == ("ss", "-tnpH"):
            return subprocess.CompletedProcess(list(args), 0, stdout=ss, stderr="")
        if args[:4] == ("ip", "-o", "-4", "addr"):
            return subprocess.CompletedProcess(list(args), 0, stdout=addr, stderr="")
        return inner(*args, **kw)

    return run


def link_fake(inner, macs: dict[str, str], permaddr: dict[str, str] | None = None):
    """Wrap a run fake with `ip -o link show dev X` answers: the device's
    address and, for devices in `permaddr`, a differing permanent one (what
    NetworkManager's scan randomization produces on a disconnected radio)."""
    permaddr = permaddr or {}

    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        if args[:5] == ("ip", "-o", "link", "show", "dev"):
            dev = args[5]
            if dev not in macs:
                return subprocess.CompletedProcess(
                    list(args), 1, stdout="", stderr=f'Device "{dev}" does not exist.'
                )
            extra = f" permaddr {permaddr[dev]}" if dev in permaddr else ""
            out = (
                f"3: {dev}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP "
                f"mode DORMANT group default qlen 1000\\    link/ether {macs[dev]} "
                f"brd ff:ff:ff:ff:ff:ff{extra}\n"
            )
            return subprocess.CompletedProcess(list(args), 0, stdout=out, stderr="")
        return inner(*args, **kw)

    return run


def all_healthy() -> dict[str, ProbeResult]:
    return {d: healthy(d) for d in ("wlan1", "wlan2", "wlan0")}


class FakeThread:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive

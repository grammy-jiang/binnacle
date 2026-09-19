"""Host-specific uplink watchdog compatibility facade.

The watchdog is an operational POC, not a Binnacle product feature. Its
implementation lives under binnacle.ops.watchdog and may depend on
Binnacle core; core modules must never depend on this companion. Historical
design notes live in docs/watchdog-poc.md.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from binnacle import uplink
from binnacle.ops.watchdog.actions import (
    _modify_metric,
    _reapply,
    apply_action,
    reset_device,
    set_route_metric,
)
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import (
    DEFAULT_POLICY,
    Policy,
    usb_backoff,
    usb_reset_method,
)
from binnacle.ops.watchdog.cycle import cycle
from binnacle.ops.watchdog.diagnostics import describe_issues
from binnacle.ops.watchdog.fast import (
    _still_safe,
    fast_check,
    fast_loop,
    supervise_fast_path,
)
from binnacle.ops.watchdog.hardware import (
    NET_CLASS,
    SYS_MODULE,
    USB_DEVICES,
    USBDEVFS_RESET,
    driver_module_of,
    driver_of,
    driver_reload,
    host_health,
    module_params,
    usb_adapters_without_netdev,
    usb_devfs_path,
    usb_node_of,
    usb_reset_device,
    usb_speed_of,
)
from binnacle.ops.watchdog.inventory import inventory_line, versions
from binnacle.ops.watchdog.lifecycle import run_forever as _run_forever
from binnacle.ops.watchdog.lock import ACT_LOCK
from binnacle.ops.watchdog.model import (
    Action,
    Demotion,
    DeviceInfo,
    Preference,
    State,
    band_label,
    grade_of,
    grade_rank,
)
from binnacle.ops.watchdog.network import (
    WifiProfile,
    _split_terse,
    bound_profiles,
    device_profiles,
    nm_devices,
    observe_devices,
    preferences,
    profile_details,
    profile_metric,
    profile_never_default,
    stranded_metrics,
    visible_ssids,
    wifi_link_freq,
    wifi_link_info,
    wifi_profiles,
    wifi_radio_enabled,
)
from binnacle.ops.watchdog.policy import evaluate
from binnacle.ops.watchdog.schedule import (
    recent_wedges,
    restore_needed,
)
from binnacle.ops.watchdog.services import (
    ServiceObservation,
    SystemObservation,
    _rfc3339_epoch,
    evaluate_services,
    evaluate_system,
    http_alive,
    nm_answers,
    observe_services,
    observe_system,
    pause_until,
    system_unit_active,
    unit_active,
)
from binnacle.ops.watchdog.tunnel import (
    TunnelSocket,
    _log_decision,
    _log_issues,
    after_failover,
    restart_tunnel,
    tunnel_affinity_check,
    tunnel_main_pid,
    tunnel_sockets,
    tunnel_via,
)

__all__ = [
    "ACT_LOCK",
    "DEFAULT_POLICY",
    "NET_CLASS",
    "SYS_MODULE",
    "USBDEVFS_RESET",
    "USB_DEVICES",
    "Action",
    "Demotion",
    "DeviceInfo",
    "Policy",
    "Preference",
    "ServiceObservation",
    "State",
    "SystemObservation",
    "TunnelSocket",
    "WifiProfile",
    "_log_decision",
    "_log_issues",
    "_modify_metric",
    "_reapply",
    "_rfc3339_epoch",
    "_split_terse",
    "_still_safe",
    "after_failover",
    "apply_action",
    "band_label",
    "bound_profiles",
    "describe_issues",
    "device_profiles",
    "driver_module_of",
    "driver_of",
    "driver_reload",
    "evaluate",
    "evaluate_services",
    "evaluate_system",
    "fast_check",
    "fast_loop",
    "grade_of",
    "grade_rank",
    "host_health",
    "http_alive",
    "inventory_line",
    "module_params",
    "nm_answers",
    "nm_devices",
    "observe_devices",
    "observe_services",
    "observe_system",
    "pause_until",
    "preferences",
    "profile_details",
    "profile_metric",
    "profile_never_default",
    "recent_wedges",
    "reset_device",
    "restart_tunnel",
    "restore_needed",
    "set_route_metric",
    "stranded_metrics",
    "supervise_fast_path",
    "system_unit_active",
    "tunnel_affinity_check",
    "tunnel_main_pid",
    "tunnel_sockets",
    "tunnel_via",
    "unit_active",
    "usb_adapters_without_netdev",
    "usb_backoff",
    "usb_devfs_path",
    "usb_node_of",
    "usb_reset_device",
    "usb_reset_method",
    "usb_speed_of",
    "versions",
    "visible_ssids",
    "wifi_link_freq",
    "wifi_link_info",
    "wifi_profiles",
    "wifi_radio_enabled",
]

log = logging.getLogger("binnacle.watchdog")

#: Held around every decide-and-act section: the full cycle's, and the
#: fast path's, so the two never interleave a demotion.


#: Shared default; Policy is frozen, so one instance is safe to reuse.


#: Grades, best first. `unknown` is a probe that could not run.


# -- decision (pure) ---------------------------------------------------------


# -- NetworkManager side effects ---------------------------------------------


#: USBDEVFS_RESET = _IO('U', 20): a USB port reset through the devfs node.


# -- loop --------------------------------------------------------------------


def run_forever(
    state_file: Path,
    interval_s: float = 30.0,
    policy: Policy = DEFAULT_POLICY,
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    exit_fn: Callable[[int], None] = os._exit,
) -> None:
    """Run the watchdog lifecycle while preserving the compatibility seam."""
    _run_forever(
        state_file,
        interval_s=interval_s,
        policy=policy,
        host=host,
        timeout=timeout,
        run=run,
        sleep=sleep,
        max_cycles=max_cycles,
        exit_fn=exit_fn,
        cycle_fn=cycle,
    )

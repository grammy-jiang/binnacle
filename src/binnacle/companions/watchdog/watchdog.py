"""Host-specific uplink watchdog compatibility facade.

The watchdog is an operational POC, not a Binnacle product feature. Its
implementation lives under binnacle.companions.watchdog.ops and may depend on
Binnacle core; core modules must never depend on this companion. Historical
design notes live in docs/watchdog-poc.md.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from binnacle.companions.watchdog import uplink
from binnacle.companions.watchdog.ops.actions import (
    _modify_metric,
    _reapply,
    apply_action,
    reset_device,
    set_route_metric,
)
from binnacle.companions.watchdog.ops.command import Run, _run
from binnacle.companions.watchdog.ops.config import (
    DEFAULT_POLICY,
    Policy,
    UsbLinkPolicy,
    usb_backoff,
    usb_param_names,
    usb_reset_method,
)
from binnacle.companions.watchdog.ops.cycle import cycle
from binnacle.companions.watchdog.ops.device_identity import (
    DURABLE_FIELDS,
    absent_issues,
    track_identities,
)
from binnacle.companions.watchdog.ops.diagnostics import describe_issues
from binnacle.companions.watchdog.ops.fast import (
    _still_safe,
    fast_check,
    fast_loop,
    supervise_fast_path,
)
from binnacle.companions.watchdog.ops.hardware import (
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
from binnacle.companions.watchdog.ops.inventory import inventory_line, versions
from binnacle.companions.watchdog.ops.lifecycle import run_forever as _run_forever
from binnacle.companions.watchdog.ops.lock import ACT_LOCK
from binnacle.companions.watchdog.ops.model import (
    Action,
    Demotion,
    DeviceInfo,
    Preference,
    State,
    band_label,
    grade_of,
    grade_rank,
)
from binnacle.companions.watchdog.ops.network import (
    ProfileDetails,
    WifiProfile,
    _split_terse,
    bound_profiles,
    device_mac,
    device_profiles,
    nm_devices,
    observe_devices,
    permanent_mac,
    preferences,
    profile_binding,
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
from binnacle.companions.watchdog.ops.policy import evaluate
from binnacle.companions.watchdog.ops.policy_usb import UsbTarget, resolve_usb_target
from binnacle.companions.watchdog.ops.schedule import (
    recent_wedges,
    restore_needed,
)
from binnacle.companions.watchdog.ops.services import (
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
from binnacle.companions.watchdog.ops.tunnel import (
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
    "DURABLE_FIELDS",
    "NET_CLASS",
    "SYS_MODULE",
    "USBDEVFS_RESET",
    "USB_DEVICES",
    "Action",
    "Demotion",
    "DeviceInfo",
    "Policy",
    "Preference",
    "ProfileDetails",
    "ServiceObservation",
    "State",
    "SystemObservation",
    "TunnelSocket",
    "UsbLinkPolicy",
    "UsbTarget",
    "WifiProfile",
    "_log_decision",
    "_log_issues",
    "_modify_metric",
    "_reapply",
    "_rfc3339_epoch",
    "_split_terse",
    "_still_safe",
    "absent_issues",
    "after_failover",
    "apply_action",
    "band_label",
    "bound_profiles",
    "describe_issues",
    "device_mac",
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
    "permanent_mac",
    "preferences",
    "profile_binding",
    "profile_details",
    "profile_metric",
    "profile_never_default",
    "recent_wedges",
    "reset_device",
    "resolve_usb_target",
    "restart_tunnel",
    "restore_needed",
    "set_route_metric",
    "stranded_metrics",
    "supervise_fast_path",
    "system_unit_active",
    "track_identities",
    "tunnel_affinity_check",
    "tunnel_main_pid",
    "tunnel_sockets",
    "tunnel_via",
    "unit_active",
    "usb_adapters_without_netdev",
    "usb_backoff",
    "usb_devfs_path",
    "usb_node_of",
    "usb_param_names",
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

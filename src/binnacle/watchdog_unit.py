"""The watchdog companion's systemd unit: name, template, rendering.

Shared by the companion's `setup` (writes it) and `doctor` (re-renders it
from the marker line and reports drift). May depend on Binnacle core;
core must not import it.
"""

from collections.abc import Mapping

from binnacle import units

WATCHDOG_UNIT = "binnacle-watchdog.service"
OWNER = "binnacle-watchdog"

WATCHDOG_UNIT_TEMPLATE = """\
[Unit]
Description=Binnacle development-host uplink watchdog
After=network.target NetworkManager.service

[Service]
Type=simple
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart={watchdog} run
Restart=always
RestartSec=10
UMask=0077

[Install]
WantedBy=default.target
"""


def watchdog_unit_spec(params: Mapping[str, str]) -> units.UnitSpec:
    """The unit for `params`; `watchdog` is the companion's executable."""
    try:
        binary = params["watchdog"]
    except KeyError as e:
        raise units.UnitError(
            "the watchdog unit needs the `watchdog` parameter (the companion's "
            "executable); run `binnacle-watchdog setup`"
        ) from e
    body = WATCHDOG_UNIT_TEMPLATE.format(watchdog=binary)
    return units.UnitSpec(WATCHDOG_UNIT, OWNER, body, {"watchdog": binary})


def render_watchdog_unit(params: Mapping[str, str]) -> str:
    return units.render(watchdog_unit_spec(params))

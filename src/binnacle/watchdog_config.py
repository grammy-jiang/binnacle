"""Configuration for the host-specific watchdog companion."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from binnacle.config import CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE


class WatchdogSettings(BaseModel):
    """Uplink watchdog (see binnacle/watchdog.py for the policy).

    Defaults come from the 2026-09-12 outage: a wedged radio was invisible
    to every other signal, so the probe interval has to be short enough
    that failover beats a ChatGPT request timing out, and the failure
    threshold high enough that one dropped packet does not move a route.
    """

    interval_s: float = Field(30.0, description="Seconds between probe cycles.")
    failures_before_action: int = Field(
        3, description="Consecutive wedged cycles before the route is demoted."
    )
    successes_before_restore: int = Field(
        3, description="Consecutive healthy cycles before the route is restored."
    )
    demoted_metric: int = Field(
        900, description="Metric applied to a wedged route; must lose to the others."
    )
    reset_after_failover: bool = Field(
        True,
        description="Re-activate the profile (`nmcli connection up`) after failing over.",
    )
    min_reset_interval_s: float = Field(
        300.0, description="Rate limit on resets of one device."
    )
    usb_reset_enabled: bool = Field(
        True,
        description=(
            "Tier 3: re-enumerate the adapter's USB device (the software "
            "replug) when re-association leaves a demoted device unhealthy."
        ),
    )
    usb_reset_schedule: tuple[tuple[int, float], ...] = Field(
        ((3, 60.0), (3, 180.0), (3, 300.0), (0, 600.0)),
        description=(
            "(attempts, seconds) stages for USB resets, counted from the "
            "re-association; 0 attempts = unlimited. Default: 1 min x3, "
            "3 min x3, 5 min x3, then every 10 min (user, 2026-09-12)."
        ),
    )
    usb_reset_ids: tuple[str, ...] = Field(
        ("0bda:8812",),
        description="USB vendor:product ids the watchdog may re-enumerate.",
    )
    usb_reset_methods: tuple[str, ...] = Field(
        ("authorized", "port_reset"),
        description=(
            "USB reset methods in rotation by attempt: sysfs `authorized` "
            "toggle, then USBDEVFS_RESET on /dev/bus/usb (user, 2026-09-13)."
        ),
    )
    standby_repair: bool = Field(
        True,
        description=(
            "Re-activate a wedged standby route on the same threshold and rate "
            "limit as the active one, so the lifeline works when it is needed."
        ),
    )
    prefer_enabled: bool = Field(
        True,
        description=(
            "Move a device to a strictly higher autoconnect-priority "
            "NetworkManager profile whose network is in range (a standby at "
            "once; the active route through a demotion first). NetworkManager "
            "picks the first visible profile and never revisits: after every "
            "reset the adapter came back on the 2.4 GHz profile (2026-09-13)."
        ),
    )
    prefer_check_interval_s: float = Field(
        300.0,
        description="Fresh scan interval for a device not on its best profile.",
    )
    prefer_schedule: tuple[tuple[int, float], ...] = Field(
        ((3, 600.0), (0, 3600.0)),
        description="(attempts, seconds) stages between preference moves: 10 min x3, then hourly.",
    )
    prefer_hold_s: float = Field(
        3600.0, description="Time on the best profile that clears the attempt count."
    )
    prefer_timeout_s: float = Field(
        300.0,
        description="A preference move still unhealthy after this long is undone.",
    )
    down_repair: bool = Field(
        True,
        description=(
            "Re-activate a device that has no route (disconnected, connecting "
            "too long, unavailable) to the best profile in range; USB-reset an "
            "unavailable adapter or one a re-activation did not bring back."
        ),
    )
    connecting_cycles_before_action: int = Field(
        6,
        description="Cycles a device may sit in 'connecting' before it counts as down.",
    )
    usb_speed_repair: bool = Field(
        True,
        description=(
            "Bring a USB adapter back to the best link speed it has shown "
            "(a USB 3 part enumerated at 480 Mbit/s) by re-enumerating it, "
            "through a demotion when it is the active route."
        ),
    )
    usb_speed_schedule: tuple[tuple[int, float], ...] = Field(
        ((3, 600.0), (3, 3600.0), (0, 21600.0)),
        description="(attempts, seconds) stages between link-level resets: 10 min x3, 1 h x3, then 6 h.",
    )
    usb_speed_give_up: int = Field(
        6,
        description="Resets without reaching the best speed after which the lower level is accepted.",
    )
    usb_speed_hold_s: float = Field(
        3600.0, description="Time at the best speed that clears the attempt count."
    )
    upstream_host: str = Field(
        "api.openai.com", description="Host the DNS and TCP layers probe."
    )
    probe_timeout_s: float = Field(
        2.0,
        description=(
            "Per-layer probe timeout (RTTs here are milliseconds; a wedged route "
            "costs every layer's timeout each cycle, so this bounds the cycle)."
        ),
    )
    fast_interval_s: float = Field(
        5.0,
        description=(
            "The fast path: a TCP connect to the upstream through the active "
            "route this often; 0 disables it."
        ),
    )
    fast_failures_before_action: int = Field(
        4,
        description=(
            "Consecutive fast-probe failures (x fast_interval_s) before the "
            "active route is demoted, given a standby with a working TCP path."
        ),
    )
    fast_timeout_s: float = Field(2.0, description="Timeout of one fast probe.")
    restart_tunnel_on_failover: bool = Field(
        True,
        description=(
            "Restart the tunnel right after a failover: its in-flight poll hangs "
            "on the dead path for up to a minute, a restart polls again in ~1 s."
        ),
    )
    reset_floor_s: float = Field(
        60.0,
        description=(
            "The first re-association of a new episode (a demotion, a new failure "
            "streak) only needs this long since the last one; min_reset_interval_s "
            "paces repeats within an episode."
        ),
    )
    flap_window_s: float = Field(
        3600.0,
        description=(
            "Flap damping window: every wedge demotion of a device inside it doubles "
            "the healthy cycles the next restore needs (3, 6, 12, 24 ...)."
        ),
    )
    restore_hold_max_cycles: int = Field(
        40, description="Cap on the healthy cycles a restore may require (20 min)."
    )
    restore_fast_quiet_s: float = Field(
        90.0,
        description=(
            "A demoted route is restored only after the fast path has seen it pass "
            "for this long (it probes demoted routes too)."
        ),
    )
    tunnel_affinity: bool = Field(
        True,
        description=(
            "Keep the tunnel's connection to OpenAI on the active route: off it "
            "without a TCP path, restart at once; off it but usable for "
            "tunnel_affinity_cycles cycles, restart at a quiet moment."
        ),
    )
    tunnel_affinity_cycles: int = Field(
        3,
        description=(
            "Cycles the tunnel's connection may sit on a usable non-active route "
            "before it is moved (a restart at a quiet moment)."
        ),
    )
    tunnel_quiet_s: float = Field(
        30.0,
        description=(
            "An affinity restart waits until no command was forwarded to the server "
            "for this long."
        ),
    )
    failover_restart_floor_s: float = Field(
        15.0,
        description=(
            "Minimum gap between tunnel restarts made for a failover or for a dead "
            "socket path (a second failover 30 s after the first still gets one)."
        ),
    )
    tunnel_ready_timeout_s: float = Field(
        10.0,
        description=(
            "After a tunnel restart, wait this long for its new health server to "
            "answer (logged as ready_ms); a miss logs tunnel_not_ready."
        ),
    )
    flap_log_limit: int = Field(
        3,
        description=(
            "Issue changes per device inside one snapshot interval before the "
            "journal switches to an uplink_issue_flapping summary."
        ),
    )
    dns_fallback: str | None = Field(
        "1.1.1.1",
        description=(
            "Public resolver asked over the same device when the system "
            "resolver fails, to tell a DNS server problem from a dead link. "
            "Diagnostic only: the layer still reflects the system resolver."
        ),
    )
    cycle_timeout_s: float = Field(
        600.0,
        description=(
            "A cycle that runs longer than this means the loop is hung; the "
            "process exits so systemd restarts it (Restart=always)."
        ),
    )
    driver_reload_enabled: bool = Field(
        False,
        description=(
            "Unbind/bind the driver of a wedged or unavailable non-USB radio "
            "(the built-in one) through sysfs, on the USB reset schedule. Off "
            "until proven on the host: a reload that fails leaves the radio "
            "dead until a reboot. `binnacle-watchdog reload-driver --dev wlan0 --apply` "
            "tests it once by hand."
        ),
    )
    service_repair: bool = Field(
        True,
        description=(
            "Restart the tunnel when its poller keeps failing while the uplink "
            "is healthy, and the server when its port stops answering while "
            "the unit is active. A unit the user stopped is left alone."
        ),
    )
    service_failures_before_action: int = Field(
        3, description="Consecutive cycles a service must fail before a restart."
    )
    service_restart_interval_s: float = Field(
        900.0, description="Rate limit on restarts of one service."
    )
    tunnel_restart_after_s: float = Field(
        300.0,
        description="Poll failures must have lasted this long (with a healthy uplink).",
    )
    tunnel_stale_after_s: float = Field(
        1800.0,
        description=(
            "Silence in the tunnel log longer than this is reported as an issue "
            "(a healthy idle tunnel can be quiet for half an hour); the restart "
            "signal is its health server, not the log."
        ),
    )
    tunnel_health_url_file: Path = Field(
        default_factory=lambda: (
            Path.home()
            / ".local"
            / "state"
            / "tunnel-client"
            / "health"
            / "binnacle.url"
        ),
        description=(
            "File holding the URL of the tunnel's health HTTP server (it changes "
            "on every restart); not answering for three cycles restarts the tunnel."
        ),
    )
    tunnel_log: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "tunnel-client" / "logs" / "binnacle.log"
        ),
        description="The tunnel client's own log (what ChatGPT sees).",
    )
    reconcile_interval_s: float = Field(
        600.0,
        description=(
            "How often the loop looks for a profile left at the demoted metric "
            "with no demotion on record (a lost state file) and reports it."
        ),
    )
    snapshot_interval_s: float = Field(
        600.0,
        description=(
            "Journal cadence of the full `snapshot` lines and of re-stated "
            "declined decisions, so any log window has a baseline."
        ),
    )
    system_service_repair: bool = Field(
        True,
        description=(
            "Restart NetworkManager when it is inactive or answers nothing for "
            "three cycles, and wpa_supplicant when it is inactive while a radio "
            "is unavailable (sudo -n systemctl restart; same rate limit)."
        ),
    )
    inventory_params: tuple[str, ...] = Field(
        (),
        description=(
            "Kernel module parameters to record in the `inventory` journal line "
            "(names under /sys/module/<module>/parameters/); host-specific."
        ),
    )
    state_file: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "binnacle" / "watchdog.json"
        ),
        description="Demotions and last cycle summary; read by `doctor`.",
    )
    stale_after_s: float = Field(
        180.0, description="`doctor` warns when the last cycle is older than this."
    )
    stability_log: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "rtl8812au" / "stability.log"
        ),
        description=(
            "Ledger of the daily wlan1 USB 3 stability job "
            "(~/.local/bin/rtl8812au-stability.sh); `doctor` surfaces its last "
            "sample and skips the check when the file is absent."
        ),
    )
    stability_state: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "rtl8812au" / "stability-state.env"
        ),
        description="Promotion and last-break state of that job.",
    )
    stability_stale_after_h: float = Field(
        36.0,
        description="`doctor` warns when the last daily sample is older than this.",
    )


class WatchdogRootSettings(BaseSettings):
    """Read only the watchdog section from the shared deployment TOML."""

    model_config = SettingsConfigDict(
        env_prefix="BINNACLE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    watchdog: WatchdogSettings = Field(default_factory=WatchdogSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_file = Path(os.environ.get(CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE))
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=toml_file),
        )


@lru_cache(maxsize=1)
def get_watchdog_settings() -> WatchdogSettings:
    return WatchdogRootSettings().watchdog

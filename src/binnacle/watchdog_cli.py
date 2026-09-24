"""Host-specific watchdog command line.

This is an operational companion kept in the repository while the watchdog is
still a POC. It may depend on Binnacle core modules; Binnacle core must not
import or otherwise depend on this companion.
"""

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import cyclopts

from binnacle import units
from binnacle.cli import BACKUP_DIR, SERVER_UNIT, UNIT_DIR, _systemctl
from binnacle.config import get_settings
from binnacle.ops.watchdog.config import Policy, UsbLinkPolicy
from binnacle.tunnel_unit import TUNNEL_UNIT
from binnacle.watchdog_config import WatchdogSettings, get_watchdog_settings
from binnacle.watchdog_unit import OWNER, WATCHDOG_UNIT, watchdog_unit_spec

app = cyclopts.App(
    name="binnacle-watchdog",
    help="Host-specific uplink watchdog companion for Binnacle.",
)


def _policy_from(cfg: WatchdogSettings, dry_run: bool) -> Policy:
    """The loop's policy from the TOML settings; `run` and the dry-run
    rehearsal share it."""
    return Policy(
        failures_before_action=cfg.failures_before_action,
        successes_before_restore=cfg.successes_before_restore,
        demoted_metric=cfg.demoted_metric,
        reset_after_failover=cfg.reset_after_failover,
        min_reset_interval_s=cfg.min_reset_interval_s,
        usb_reset_enabled=cfg.usb_reset_enabled,
        usb_reset_schedule=cfg.usb_reset_schedule,
        usb_reset_ids=cfg.usb_reset_ids,
        usb_reset_methods=cfg.usb_reset_methods,
        standby_repair=cfg.standby_repair,
        prefer_enabled=cfg.prefer_enabled,
        prefer_check_interval_s=cfg.prefer_check_interval_s,
        prefer_schedule=cfg.prefer_schedule,
        prefer_hold_s=cfg.prefer_hold_s,
        prefer_timeout_s=cfg.prefer_timeout_s,
        down_repair=cfg.down_repair,
        connecting_cycles_before_action=cfg.connecting_cycles_before_action,
        usb_speed_repair=cfg.usb_speed_repair,
        usb_speed_schedule=cfg.usb_speed_schedule,
        usb_speed_give_up=cfg.usb_speed_give_up,
        usb_speed_hold_s=cfg.usb_speed_hold_s,
        usb_link_policies=_link_policies(cfg),
        dns_fallback=cfg.dns_fallback,
        cycle_timeout_s=cfg.cycle_timeout_s,
        driver_reload_enabled=cfg.driver_reload_enabled,
        service_repair=cfg.service_repair,
        service_failures_before_action=cfg.service_failures_before_action,
        service_restart_interval_s=cfg.service_restart_interval_s,
        tunnel_restart_after_s=cfg.tunnel_restart_after_s,
        tunnel_log=cfg.tunnel_log,
        mcp_units=(SERVER_UNIT,),
        tunnel_unit=TUNNEL_UNIT,
        mcp_url=f"http://{get_settings().serve.host}:{get_settings().serve.port}/mcp",
        reconcile_interval_s=cfg.reconcile_interval_s,
        snapshot_interval_s=cfg.snapshot_interval_s,
        pause_file=cfg.state_file.with_suffix(".pause"),
        system_service_repair=cfg.system_service_repair,
        inventory_params=cfg.inventory_params,
        tunnel_stale_after_s=cfg.tunnel_stale_after_s,
        tunnel_health_url_file=cfg.tunnel_health_url_file,
        fast_interval_s=cfg.fast_interval_s,
        fast_failures_before_action=cfg.fast_failures_before_action,
        fast_timeout_s=cfg.fast_timeout_s,
        restart_tunnel_on_failover=cfg.restart_tunnel_on_failover,
        reset_floor_s=cfg.reset_floor_s,
        flap_window_s=cfg.flap_window_s,
        restore_hold_max_cycles=cfg.restore_hold_max_cycles,
        restore_fast_quiet_s=cfg.restore_fast_quiet_s,
        tunnel_affinity=cfg.tunnel_affinity,
        tunnel_affinity_cycles=cfg.tunnel_affinity_cycles,
        tunnel_quiet_s=cfg.tunnel_quiet_s,
        failover_restart_floor_s=cfg.failover_restart_floor_s,
        tunnel_ready_timeout_s=cfg.tunnel_ready_timeout_s,
        flap_log_limit=cfg.flap_log_limit,
        dry_run=dry_run,
    )


def _link_policies(cfg: WatchdogSettings) -> tuple[UsbLinkPolicy, ...]:
    """The TOML `[[watchdog.usb_link_policies]]` rules as the policy's
    frozen records (`targets` becomes a sorted tuple of pairs)."""
    return tuple(
        UsbLinkPolicy(
            usb_id=rule.usb_id,
            mode=rule.mode,
            target_mbps=rule.target_mbps,
            permanent_mac=rule.permanent_mac,
            param=rule.param,
            targets=tuple(sorted(rule.targets.items())),
        )
        for rule in cfg.usb_link_policies
    )


@app.command
def setup(dry_run: bool = False, adopt: bool = False) -> None:
    """Provision only the host-specific watchdog user service.

    Parameters
    ----------
    dry_run
        Print every action, and the unit diff, instead of performing them.
    adopt
        Take over a unit file no binnacle setup command wrote, after
        reviewing the diff `--dry-run` shows. It is backed up first.
    """
    try:
        binary = units.resolve_executable(OWNER)
    except units.UnitError as e:
        print(e)
        raise SystemExit(1) from None
    spec = watchdog_unit_spec({"watchdog": str(binary)})
    unit_path = UNIT_DIR / WATCHDOG_UNIT
    plan = units.plan_write(unit_path, spec, adopt=adopt)
    if plan.diff:
        print(plan.diff + "\n")
    if plan.action == "refuse":
        print(plan.reason)
        raise SystemExit(1)

    actions: list[tuple[str, object]] = []

    def act(description: str, fn) -> None:
        actions.append((description, fn))
        if not dry_run:
            fn()

    if plan.action == "unchanged":
        actions.append((f"keep {unit_path} (already what setup writes)", None))
    else:
        act(
            f"{'write' if plan.action == 'create' else 'rewrite'} {unit_path}",
            lambda: units.write_unit(unit_path, plan, BACKUP_DIR),
        )
    act("systemctl --user daemon-reload", lambda: _systemctl("daemon-reload"))
    act(
        f"systemctl --user enable --now {WATCHDOG_UNIT}",
        lambda: _systemctl("enable", "--now", WATCHDOG_UNIT),
    )
    act(
        "loginctl enable-linger (service survives logout and reboot)",
        lambda: subprocess.run(["loginctl", "enable-linger"], check=True),
    )

    prefix = "would " if dry_run else ""
    for description, _ in actions:
        print(f"{prefix}{description}")
    if dry_run:
        print("\ndry run: nothing was changed.")
    else:
        print("\nwatchdog service is configured.")


@app.command
def doctor(
    probe: bool = True,
    as_json: Annotated[bool, cyclopts.Parameter(name="--json")] = False,
) -> None:
    """Check the host-specific watchdog and uplink support."""
    from binnacle import doctor as core_doctor
    from binnacle import watchdog_doctor as checks

    results = checks.run_all(probe=probe)
    text, code = (core_doctor.render_json if as_json else core_doctor.render)(results)
    print(text)
    raise SystemExit(code)


@app.command(name="deploy-check")
def deploy_check(window_s: float = 60.0) -> None:
    """Is this a quiet moment to restart the unit? Exit 0 when no demotion
    is in flight, every grade is healthy, the last cycle is recent, and the
    journal shows no fast failure or repair in the last WINDOW-S seconds;
    exit 1 otherwise. The gate for a deploy: `binnacle-watchdog deploy-check
    && systemctl --user restart binnacle-watchdog.service`."""
    from binnacle import watchdog_doctor as checks

    cfg = get_watchdog_settings()
    report = checks.quiet_moment(
        cfg.state_file, window_s, cfg.stale_after_s, WATCHDOG_UNIT
    )
    verdict = "quiet, a restart is safe now" if report.ok else "not quiet, wait"
    print(f"deploy check: {verdict}")
    print("\n".join(report.lines))
    raise SystemExit(0 if report.ok else 1)


@app.command
def run(
    interval: float | None = None,
    once: bool = False,
    cycles: int | None = None,
    dry_run: bool = False,
    state_file: Path | None = None,
) -> None:
    """Probe every default route and fail over a wedged one.

    Runs until stopped; `binnacle-watchdog.service` is the supervised way
    to run it. A wedged active route is demoted so traffic moves to a
    healthy interface, the wedged device is reset, and its original metric
    is restored once it passes the probes again.

    The rehearsal for a new build, before restarting the unit:
    `binnacle-watchdog run --cycles 3 --dry-run --state-file /tmp/wd.json`
    runs the whole observe-decide-log path on the live host, applies
    nothing, and touches no real state.

    Parameters
    ----------
    interval
        Seconds between cycles; defaults to the configured value.
    once
        Run a single cycle and exit (for inspection).
    cycles
        Run this many cycles and exit.
    dry_run
        Observe, decide and log, but apply no action.
    state_file
        Use this state file instead of the configured one.
    """
    import logging

    from binnacle import watchdog as wd

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stdout
    )
    cfg = get_watchdog_settings()
    policy = _policy_from(cfg, dry_run)
    wd.run_forever(
        state_file or cfg.state_file,
        interval_s=interval if interval is not None else cfg.interval_s,
        policy=policy,
        host=cfg.upstream_host,
        timeout=cfg.probe_timeout_s,
        max_cycles=1 if once else cycles,
    )


@app.command(name="usb-reset")
def usb_reset(
    dev: str = "wlan1", apply: bool = False, method: str = "authorized"
) -> None:
    """Reset an interface's USB device (the software replug).

    Plan mode shows the node, its USB id, the devfs path, and the watchdog's
    reset schedule state. `--apply` performs it once, outside the automatic
    schedule: the interface drops for roughly 15 s and NetworkManager
    reconnects it.

    Parameters
    ----------
    dev
        Network interface whose USB device to reset.
    apply
        Perform the reset (default: plan only).
    method
        `authorized` (sysfs toggle) or `port_reset` (USBDEVFS_RESET).
    """
    from binnacle import watchdog as wd

    cfg = get_watchdog_settings()
    policy = wd.Policy(
        usb_reset_ids=cfg.usb_reset_ids,
        usb_reset_schedule=cfg.usb_reset_schedule,
        usb_reset_methods=cfg.usb_reset_methods,
    )
    node, usb_id = wd.usb_node_of(dev)
    devfs = wd.usb_devfs_path(node) if node else None
    state = wd.State.load(cfg.state_file)
    attempts = state.usb_attempts.get(dev, 0)
    print(
        f"usb-reset {dev}: node {node or '?'} id {usb_id or '?'} devfs {devfs or '?'} "
        f"({'allowed' if usb_id in cfg.usb_reset_ids else 'NOT in usb_reset_ids'}); "
        f"method {method}"
    )
    print(
        f"  automatic attempts so far: {attempts}; next automatic wait: "
        f"{wd.usb_backoff(cfg.usb_reset_schedule, attempts + 1):.0f} s; "
        f"schedule {cfg.usb_reset_schedule}"
    )
    if not apply:
        print("  plan only; add --apply to re-enumerate now")
        return
    okay, detail = wd.usb_reset_device(dev, policy, method=method)
    print(f"  {'ok' if okay else 'FAILED'}: {detail}")
    raise SystemExit(0 if okay else 1)


@app.command
def pause(minutes: float = 60.0) -> None:
    """Pause every watchdog action for a while (observation and logging go
    on), e.g. while you rearrange radios or profiles by hand.

    Parameters
    ----------
    minutes
        How long; the pause expires by itself. `resume` ends it early.
    """
    import time

    cfg = get_watchdog_settings()
    pause_file = cfg.state_file.with_suffix(".pause")
    until = time.time() + minutes * 60
    pause_file.parent.mkdir(parents=True, exist_ok=True)
    pause_file.write_text(f"{until:.0f}\n", encoding="utf-8")
    print(
        f"watchdog paused for {minutes:g} min ({pause_file}); `binnacle-watchdog resume` ends it"
    )


@app.command
def resume() -> None:
    """End a pause started with `pause`."""
    cfg = get_watchdog_settings()
    pause_file = cfg.state_file.with_suffix(".pause")
    if pause_file.exists():
        pause_file.unlink()
        print("watchdog resumed")
    else:
        print("watchdog was not paused")


@app.command
def history(
    since: str = "-1 day",
    until: str | None = None,
    verbose: bool = False,
    tunnel_log: Path | None = None,
) -> None:
    """Reconstruct what the watchdog saw and did from its journal, and what
    ChatGPT saw meanwhile from the tunnel's log (failed or timed-out polls,
    in total and per failover).

    Parameters
    ----------
    since
        journalctl time spec (a value starting with a dash needs the equals
        form: --since="-2 days").
    until
        Optional end of the window.
    verbose
        Also list every declined decision and probe error.
    tunnel_log
        The tunnel client's log (default: the configured one); its failed
        polls are matched against the window.
    """
    from binnacle import watchlog

    lines = watchlog.fetch_journal(WATCHDOG_UNIT, since, until)
    events = watchlog.parse(lines)
    log_file = tunnel_log or get_watchdog_settings().tunnel_log
    polls = None
    window = watchlog.window_of(events)
    if log_file is not None and log_file.exists() and window is not None:
        polls = watchlog.tunnel_polls(log_file, *window)
    print(watchlog.render(events, verbose=verbose, polls=polls))


@app.command(name="reload-driver")
def reload_driver(dev: str = "wlan0", apply: bool = False) -> None:
    """Unload and reload a radio's kernel driver module (the non-USB cousin
    of the USB reset; for the built-in radio).

    Plan mode shows the device, driver, module and the modules holding it.
    `--apply` performs it once: the interface disappears for about ten
    seconds and NetworkManager reconnects it. Never run it on the route
    that carries the connector.

    Parameters
    ----------
    dev
        Network interface whose driver module to reload.
    apply
        Perform the reload (default: plan only).
    """
    from binnacle import watchdog as wd

    node, driver = wd.driver_of(dev)
    module, holders = wd.driver_module_of(dev)
    print(
        f"reload-driver {dev}: device {node or '?'} driver {driver or '?'} "
        f"module {module or '?'} held by {', '.join(holders) or '-'}"
    )
    if not apply:
        print("  plan only; add --apply to reload now")
        return
    okay, detail = wd.driver_reload(dev)
    print(f"  {'ok' if okay else 'FAILED'}: {detail}")
    raise SystemExit(0 if okay else 1)


@app.command
def status(rescan: bool = False) -> None:
    """Probe every default route now and print the result.

    Also shows each route's NetworkManager profile and band, and whether a
    higher-priority profile is in range (the preference the loop enforces).

    Parameters
    ----------
    rescan
        Ask each device for a fresh scan before reading the list (a brief
        off-channel gap on a connected device); default reads the cache.
    """
    from binnacle import uplink as up
    from binnacle import watchdog as wd

    cfg = get_watchdog_settings()
    routes = up.default_routes()
    if not routes:
        print("no default route with a gateway and source address")
        raise SystemExit(1)
    probes = up.probe_all(routes, host=cfg.upstream_host, timeout=cfg.probe_timeout_s)
    state = wd.State.load(cfg.state_file)
    active = up.active_route(routes)
    print(f"uplink status (upstream {cfg.upstream_host})")
    for route in routes:
        result = probes[route.dev]
        role = "active " if active and route.dev == active.dev else "standby"
        mark = "ok  " if result.healthy else ("WEDGED" if result.wedged else "degraded")
        note = " [demoted]" if route.dev in state.demoted else ""
        print(f"  [{mark}] {role} {route.label}{note}: {result.summary()}")
        for layer, err in result.errors.items():
            print(f"           {layer}: {err}")
    if state.demoted:
        print(f"demoted: {', '.join(sorted(state.demoted))}")
    devices = wd.observe_devices(usb_ids=cfg.usb_reset_ids)
    devs = sorted({r.dev for r in routes} | set(devices))
    prefs = wd.preferences(devs, rescan_for=set(devs) if rescan else ())
    print("devices (state, profile, band, width, rate, signal, USB link):")
    for dev in devs:
        info = devices.get(dev)
        ident = f" [{info.key}]" if info is not None and info.key else ""
        line = f"  {dev}{ident}: " + (
            info.describe(state.usb_target.get(dev, state.usb_best_speed.get(dev)))
            if info is not None
            else "not a NetworkManager Wi-Fi device"
        )
        pref = prefs.get(dev)
        if pref is not None and pref.target:
            where = "in range" if pref.visible else "not in range"
            if not pref.visible and not rescan:
                where += " (cached scan; --rescan looks again)"
            line += (
                f"; preferred {pref.target} {where}; "
                f"moves so far {state.prefer_attempts.get(dev, 0)}"
            )
        elif pref is not None:
            line += "; highest-priority profile"
        if state.usb_speed_attempts.get(dev):
            line += f"; USB link resets so far {state.usb_speed_attempts[dev]}"
        if dev in state.usb_speed_exhausted:
            line += "; USB link repair exhausted"
        if state.usb_mode.get(dev):
            line += (
                f"; USB policy {state.usb_mode[dev]}, "
                f"max seen {state.usb_max_seen.get(dev, '?')}"
            )
        print(line)
    if state.issues:
        print("below the highest level:")
        for dev, text in state.issues.items():
            print(f"  {dev}: {text}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

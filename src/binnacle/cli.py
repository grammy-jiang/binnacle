"""binnacle command line -- serve, setup, mode, doctor, stats, token.

The server itself lives in binnacle.server; this module only wires it to
subcommands and provisions the deployment pieces that are ours to manage
(token, systemd user units, tunnel config). The tunnel-client binary and
every ChatGPT UI step stay manual by design.
"""

import json
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import cyclopts

from binnacle.config import get_settings

app = cyclopts.App(
    name="binnacle",
    help="MCP server that lets AI agents work on a Raspberry Pi.",
)

TOKEN_FILE = get_settings().auth.token_file
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
PROD_UNIT = "binnacle-mcp.service"
DEV_UNIT = "binnacle-mcp-dev.service"
TUNNEL_UNIT = "binnacle-tunnel.service"
WATCHDOG_UNIT = "binnacle-watchdog.service"
TUNNEL_CONFIG = Path.home() / ".config" / "tunnel-client" / "binnacle.yaml"
# Marks units this CLI generated; setup refuses to overwrite a unit
# without it, so a hand-written unit is never clobbered.
UNIT_MARKER = "# Managed by `binnacle setup`"


def _write_token(path: Path | None = None) -> None:
    """Write a fresh bearer token as the tunnel and server expect it.

    The tunnel forwards the file verbatim as the Authorization header, so
    the value must carry the ``Bearer `` scheme prefix; the server strips
    it before matching. Mode 0600, trailing newline for editors. The
    default is resolved at call time so tests can repoint TOKEN_FILE.
    """
    path = TOKEN_FILE if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"Bearer {secrets.token_urlsafe(32)}\n", encoding="utf-8")
    path.chmod(0o600)


PROD_UNIT_TEMPLATE = """\
{marker}
[Unit]
Description=Binnacle FastMCP server (production)
After=network.target
Conflicts={other}

[Service]
Type=simple
ExecStart={binnacle} serve --host 127.0.0.1 --port {port}
# Hold the unit in "activating" until the port answers, so After= dependents
# (the tunnel) and `systemctl restart` callers see a server that is listening.
ExecStartPost=/bin/bash -c 'for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null && exit 0; sleep 0.1; done; echo "binnacle: port {port} not listening after 30 s" >&2; exit 1'
Restart=always
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
"""

DEV_UNIT_TEMPLATE = """\
{marker}
[Unit]
Description=Binnacle FastMCP server (development, repo + reload)
After=network.target
Conflicts={other}

[Service]
Type=simple
WorkingDirectory={repo}
ExecStart={repo}/.venv/bin/uvicorn binnacle.server:app --host 127.0.0.1 --port {port} --reload
# Hold the unit in "activating" until the port answers, so After= dependents
# (the tunnel) and `systemctl restart` callers see a server that is listening.
ExecStartPost=/bin/bash -c 'for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null && exit 0; sleep 0.1; done; echo "binnacle: port {port} not listening after 30 s" >&2; exit 1'
Restart=on-failure
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
"""


WATCHDOG_UNIT_TEMPLATE = """\
{marker}
[Unit]
Description=Binnacle uplink watchdog (fails a wedged route over)
After=network.target NetworkManager.service

[Service]
Type=simple
# ip lives in /usr/sbin and ping/nmcli in /usr/bin. A user unit started at
# boot inherits only the manager's PATH, which cost us a 127 once already,
# so the three binaries this loop needs are pinned here.
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart={binnacle} watchdog run
Restart=always
RestartSec=10
UMask=0077

[Install]
WantedBy=default.target
"""


def _tunnel_health_url() -> str | None:
    """The tunnel's local health base URL, from its config's health.url_file."""
    try:
        cfg = json.loads(TUNNEL_CONFIG.read_text(encoding="utf-8"))
        url_file = Path(cfg["health"]["url_file"])
        return url_file.read_text(encoding="utf-8").strip() or None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _parse_rfc3339(text: str) -> datetime:
    """fromisoformat that tolerates Go's nanosecond fractions and 'Z'."""
    text = text.replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m:
        frac = (m.group(2) or ".0")[:7].ljust(7, "0")  # exactly 6 digits
        text = f"{m.group(1)}{frac}{m.group(3)}"
    return datetime.fromisoformat(text)


def _wait_tunnel_ready(
    since: float,
    timeout_s: float = 30.0,
    health_url: Callable[[], str | None] = _tunnel_health_url,
) -> str:
    """Block until the restarted tunnel reports ready and its MCP probe is ok.

    Readiness is read from the tunnel's health server: /api/status must
    come from an instance started after `since` (a stale url file still
    points at the old instance) with channel "main" probe_status ok, and
    /readyz must answer 200. Returns a one-line description of the outcome;
    a timeout is reported, not raised, because the restart itself succeeded.
    """
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    last = "health URL file not written yet"
    while time.monotonic() < deadline:
        base = health_url()
        if base:
            try:
                with urllib.request.urlopen(base + "/api/status", timeout=2) as r:  # nosec B310
                    status = json.loads(r.read())
                started = _parse_rfc3339(status["started_at"]).timestamp()
                probe = next(
                    (
                        c.get("probe_status")
                        for c in status.get("channels", [])
                        if c.get("name") == "main"
                    ),
                    None,
                )
                if started < since:
                    last = "health URL still points at the previous tunnel instance"
                elif probe != "ok":
                    last = f"tunnel up, MCP probe status {probe!r}"
                else:
                    with urllib.request.urlopen(base + "/readyz", timeout=2) as r:  # nosec B310
                        if r.status == 200:
                            return f"tunnel ready ({base}, MCP probe ok)"
                    last = "tunnel /readyz not 200"
            except (OSError, ValueError, KeyError, TypeError) as e:
                last = f"tunnel health not answering yet ({e.__class__.__name__})"
        time.sleep(0.25)
    return f"tunnel not ready after {timeout_s:g} s: {last}"


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _unit_state(unit: str) -> str:
    proc = _systemctl("is-active", unit, check=False)
    return proc.stdout.strip() or "unknown"


@app.command
def serve(
    host: str = get_settings().serve.host,
    port: int = get_settings().serve.port,
    reload: bool = False,
) -> None:
    """Run the MCP server in the foreground (what the systemd unit runs)."""
    import uvicorn

    # Explicit, not "auto": startup fails loudly if the uvicorn[standard]
    # performance stack (uvloop event loop, httptools parser) is missing,
    # instead of silently degrading to the stdlib implementations.
    uvicorn.run(
        "binnacle.server:app",
        host=host,
        port=port,
        reload=reload,
        loop="uvloop",
        http="httptools",
    )


@app.command
def setup(
    dev: Path | None = None,
    port: int = get_settings().serve.port,
    dry_run: bool = False,
) -> None:
    """Provision the server side: token, systemd user units, tunnel config.

    Parameters
    ----------
    dev
        Path to a binnacle git checkout; also writes the development unit
        (repo + --reload) pointing at it.
    port
        Local port the server binds; the tunnel forwards to it.
    dry_run
        Print every action instead of performing it.
    """
    actions: list[str] = []

    def act(description: str, fn) -> None:
        actions.append(description)
        if not dry_run:
            fn()

    # 1. Token (0600, referenced by the server and by the tunnel config).
    if not TOKEN_FILE.exists():
        act(f"generate bearer token at {TOKEN_FILE} (mode 0600)", _write_token)
    else:
        actions.append(f"keep existing token at {TOKEN_FILE}")

    # 2. Units. Refuse to overwrite a unit this CLI did not generate.
    binnacle_bin = shutil.which("binnacle") or sys.argv[0]
    units: list[tuple[str, str]] = [
        (
            PROD_UNIT,
            PROD_UNIT_TEMPLATE.format(
                marker=UNIT_MARKER, other=DEV_UNIT, binnacle=binnacle_bin, port=port
            ),
        ),
        (
            WATCHDOG_UNIT,
            WATCHDOG_UNIT_TEMPLATE.format(marker=UNIT_MARKER, binnacle=binnacle_bin),
        ),
    ]
    if dev is not None:
        repo = dev.expanduser().resolve()
        units.append(
            (
                DEV_UNIT,
                DEV_UNIT_TEMPLATE.format(
                    marker=UNIT_MARKER, other=PROD_UNIT, repo=repo, port=port
                ),
            )
        )
    for unit_name, content in units:
        unit_path = UNIT_DIR / unit_name
        if unit_path.exists() and UNIT_MARKER not in unit_path.read_text(
            encoding="utf-8"
        ):
            print(
                f"refusing to overwrite {unit_path}: it was not generated by "
                f"`binnacle setup` (marker missing). Move it away first."
            )
            raise SystemExit(1)

        def write_unit(p: Path = unit_path, c: str = content) -> None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c, encoding="utf-8")

        act(f"write {unit_path}", write_unit)

    # 3. Tunnel config, only when the tunnel-client binary is present.
    tunnel_bin = shutil.which("tunnel-client")
    if tunnel_bin is None:
        actions.append(
            "tunnel-client not found on PATH: skipping tunnel config; install "
            "it and re-run `binnacle setup` to enable the tunnel"
        )
    elif TUNNEL_CONFIG.exists():
        actions.append(f"keep existing tunnel config at {TUNNEL_CONFIG}")
    else:
        actions.append(
            f"tunnel-client found at {tunnel_bin} but {TUNNEL_CONFIG} does not "
            f"exist; write it from your tunnel account settings, then enable "
            f"{TUNNEL_UNIT}"
        )

    # 4. Enable and start.
    act("systemctl --user daemon-reload", lambda: _systemctl("daemon-reload"))
    act(
        f"systemctl --user enable --now {PROD_UNIT}",
        lambda: _systemctl("enable", "--now", PROD_UNIT),
    )
    act(
        f"systemctl --user enable --now {WATCHDOG_UNIT}",
        lambda: _systemctl("enable", "--now", WATCHDOG_UNIT),
    )
    act(
        "loginctl enable-linger (service survives logout and reboot)",
        lambda: subprocess.run(["loginctl", "enable-linger"], check=True),
    )

    prefix = "would " if dry_run else ""
    for a in actions:
        print(f"{prefix}{a}")
    if dry_run:
        print("\ndry run: nothing was changed.")
    else:
        print("\nserver side is configured. Remaining manual steps: install")
        print("tunnel-client (if missing) and add the connector in ChatGPT.")


@app.command
def mode(target: Literal["dev", "prod", "status"] = "status") -> None:
    """Switch which instance owns the port: dev (repo) or prod (installed).

    The two units carry Conflicts= on each other, so starting one stops the
    other; the explicit stop below keeps the outcome the same when the
    Conflicts= line is missing from a hand-written unit. `status` only
    reports. Run `chatgpt-refresh` afterwards when the two instances differ
    in tool surface.
    """
    if target == "status":
        for unit in (PROD_UNIT, DEV_UNIT):
            print(f"{unit}: {_unit_state(unit)}")
        return
    start, stop = (DEV_UNIT, PROD_UNIT) if target == "dev" else (PROD_UNIT, DEV_UNIT)
    _systemctl("stop", stop, check=False)
    proc = _systemctl("start", start, check=False)
    if proc.returncode != 0:
        print(f"failed to start {start}: {proc.stderr.strip()}")
        raise SystemExit(1)
    print(f"{target} mode: {start} is {_unit_state(start)}, {stop} stopped.")


@app.command
def doctor(
    since: str = "-1 hour",
    as_json: Annotated[bool, cyclopts.Parameter(name="--json")] = False,
    probe: bool = True,
) -> None:
    """Check the deployment end to end and exit 1 on any FAIL.

    Checks: config and roots, token file, systemd units (one active, no
    crash restarts, linger), the running server's PATH (~/.local/bin,
    ripgrep, bash), /mcp auth with and without the token, tunnel unit and
    config, the uplink each default route provides, whether the tunnel's
    poller is reaching OpenAI, the watchdog, job spool, and recent journal
    errors. WARN lines are degraded but working and do not change the exit
    code.

    Parameters
    ----------
    since
        journalctl window for the error scan (--since="-2 hours").
    as_json
        Emit the checks as JSON instead of the text report.
    probe
        Run the network probes (--no-probe for a local-only report).
    """
    from binnacle import doctor as checks

    serve_cfg = get_settings().serve
    dep = checks.Deployment(
        prod_unit=PROD_UNIT,
        dev_unit=DEV_UNIT,
        tunnel_unit=TUNNEL_UNIT,
        tunnel_config=TUNNEL_CONFIG,
        token_file=TOKEN_FILE,
        server_url=f"http://{serve_cfg.host}:{serve_cfg.port}/mcp",
        user_bin=Path.home() / ".local" / "bin",
        watchdog_unit=WATCHDOG_UNIT,
    )
    results = checks.run_all(dep, since=since, probe=probe)
    text, code = (checks.render_json if as_json else checks.render)(results)
    print(text)
    raise SystemExit(code)


watchdog_app = cyclopts.App(
    name="watchdog", help="Uplink failover loop (see binnacle/watchdog.py)."
)
app.command(watchdog_app)


@watchdog_app.command
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
    `binnacle watchdog run --cycles 3 --dry-run --state-file /tmp/wd.json`
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
    cfg = get_settings().watchdog
    policy = wd.Policy(
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
        dns_fallback=cfg.dns_fallback,
        cycle_timeout_s=cfg.cycle_timeout_s,
        driver_reload_enabled=cfg.driver_reload_enabled,
        service_repair=cfg.service_repair,
        service_failures_before_action=cfg.service_failures_before_action,
        service_restart_interval_s=cfg.service_restart_interval_s,
        tunnel_restart_after_s=cfg.tunnel_restart_after_s,
        tunnel_log=cfg.tunnel_log,
        mcp_units=(PROD_UNIT, DEV_UNIT),
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
    wd.run_forever(
        state_file or cfg.state_file,
        interval_s=interval if interval is not None else cfg.interval_s,
        policy=policy,
        host=cfg.upstream_host,
        timeout=cfg.probe_timeout_s,
        max_cycles=1 if once else cycles,
    )


@watchdog_app.command(name="usb-reset")
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

    cfg = get_settings().watchdog
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


@watchdog_app.command
def pause(minutes: float = 60.0) -> None:
    """Pause every watchdog action for a while (observation and logging go
    on), e.g. while you rearrange radios or profiles by hand.

    Parameters
    ----------
    minutes
        How long; the pause expires by itself. `resume` ends it early.
    """
    import time

    cfg = get_settings().watchdog
    pause_file = cfg.state_file.with_suffix(".pause")
    until = time.time() + minutes * 60
    pause_file.parent.mkdir(parents=True, exist_ok=True)
    pause_file.write_text(f"{until:.0f}\n", encoding="utf-8")
    print(
        f"watchdog paused for {minutes:g} min ({pause_file}); `binnacle watchdog resume` ends it"
    )


@watchdog_app.command
def resume() -> None:
    """End a pause started with `pause`."""
    cfg = get_settings().watchdog
    pause_file = cfg.state_file.with_suffix(".pause")
    if pause_file.exists():
        pause_file.unlink()
        print("watchdog resumed")
    else:
        print("watchdog was not paused")


@watchdog_app.command
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
    log_file = tunnel_log or get_settings().watchdog.tunnel_log
    polls = None
    window = watchlog.window_of(events)
    if log_file is not None and log_file.exists() and window is not None:
        polls = watchlog.tunnel_polls(log_file, *window)
    print(watchlog.render(events, verbose=verbose, polls=polls))


@watchdog_app.command(name="reload-driver")
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


@watchdog_app.command
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

    cfg = get_settings().watchdog
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
        line = f"  {dev}: " + (
            info.describe(state.usb_best_speed.get(dev))
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
        print(line)
    if state.issues:
        print("below the highest level:")
        for dev, text in state.issues.items():
            print(f"  {dev}: {text}")


@app.command
def stats(
    since: str = "-24 hours",
    until: str | None = None,
    unit: str = "binnacle-mcp",
    system_resources: Annotated[
        bool, cyclopts.Parameter(name="--system-resources")
    ] = False,
) -> None:
    """Usage statistics from the server journal.

    Parameters
    ----------
    since
        journalctl time spec. A value starting with a dash needs the
        equals form (--since="-2 days"); "2 days ago" needs no dash.
    until
        Optional end of the window, same syntax.
    unit
        Systemd user unit whose journal to analyze.
    system_resources
        Also read Webmin system-status history for the same time window.
    """
    from binnacle import logstats

    records, startups = logstats.parse(logstats.fetch_journal(unit, since, until))
    print(
        f"binnacle stats -- unit {unit}, since {since}"
        + (f", until {until}" if until else "")
    )
    print(logstats.render(logstats.analyze(records, startups)))
    if system_resources:
        from binnacle import webminstats

        print("\n" + webminstats.render(webminstats.load(since, until)))


token_app = cyclopts.App(name="token", help="Bearer token operations.")
app.command(token_app)


@token_app.command
def rotate() -> None:
    """Write a new token and restart the server and tunnel services."""
    _write_token()
    print(f"wrote new token to {TOKEN_FILE}")
    for unit in (PROD_UNIT, DEV_UNIT, TUNNEL_UNIT):
        if _unit_state(unit) == "active":
            started = time.time()
            _systemctl("restart", unit, check=False)
            print(f"restarted {unit}")
            if unit == TUNNEL_UNIT:
                # The tunnel caches the token at startup and re-registers its
                # poller with OpenAI; return only once it can reach the server
                # again, so a chatgpt-refresh right after this call has a chance.
                print(_wait_tunnel_ready(started))


def main() -> None:
    app()


if __name__ == "__main__":
    main()

"""Tunnel socket affinity, restart, and decision logging."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from binnacle import uplink
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.model import State
from binnacle.ops.watchdog.services import (
    ServiceObservation,
    http_alive,
    unit_active,
)
from binnacle.uplink import ProbeResult, Route

log = logging.getLogger("binnacle.watchdog")


def _log_decision(
    state: State, policy: Policy, n: int, now: float, dev: str, rung: str, text: str
) -> None:
    """A declined decision: logged on change, re-stated on the snapshot
    cadence, so "why did nothing happen" is answerable from any window."""
    key = f"{dev}/{rung}"
    last_text, last_at = state.last_decision.get(key, ("", 0.0))
    if text != last_text or now - last_at >= policy.snapshot_interval_s:
        log.info("event=decision cycle=%s dev=%s rung=%s note=%s", n, dev, rung, text)
        state.last_decision[key] = (text, now)


def tunnel_main_pid(unit: str, run: Run = _run) -> int | None:
    """The unit's main process id; 0/None when it has none; -1 when the
    answer could not be read (a fake or a failing systemctl)."""
    proc = run("systemctl", "--user", "show", unit, "-p", "MainPID", "--value")
    text = proc.stdout.strip()
    if proc.returncode != 0 or not text:
        return -1
    try:
        return int(text) or None
    except ValueError:
        return -1


@dataclass(frozen=True, slots=True)
class TunnelSocket:
    """One established connection of the tunnel process."""

    #: The device owning the local address; None when it belongs to none.
    dev: str | None
    local: str
    peer: str


def tunnel_sockets(
    unit: str, routes: list[Route], run: Run = _run, port: int = 443
) -> list[TunnelSocket] | None:
    """The tunnel process's established connections to `port`, each with
    the device that owns its local address (the routes' source addresses
    first, then every configured IPv4 address). None when the unit has no
    main process right now (it is restarting); an empty list when there is
    none to see or the answer could not be read.
    """
    pid = tunnel_main_pid(unit, run)
    if pid is None:
        return None
    if pid < 0:
        return []
    proc = run("ss", "-tnpH", "state", "established")
    if proc.returncode != 0:
        return []
    owner = {r.src: r.dev for r in routes}
    addr = run("ip", "-o", "-4", "addr", "show")
    for line in addr.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            owner.setdefault(parts[3].split("/")[0], parts[1])
    tag = f"pid={pid},"
    out: list[TunnelSocket] = []
    for line in proc.stdout.splitlines():
        if tag not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local, peer = parts[2], parts[3]
        if not peer.endswith(f":{port}"):
            continue
        ip = local.rsplit(":", 1)[0]
        if ip.startswith("127."):
            continue
        out.append(TunnelSocket(owner.get(ip), local, peer))
    return out


def tunnel_via(
    sockets: list[TunnelSocket] | None, active_dev: str | None
) -> str | None:
    """The device the tunnel's connection sits on: the active one when any
    connection is on it, else the first connection's ("?" when its address
    belongs to no device); None without a connection."""
    if not sockets:
        return None
    for s in sockets:
        if active_dev is not None and s.dev == active_dev:
            return s.dev
    return sockets[0].dev or "?"


def restart_tunnel(
    state: State,
    policy: Policy,
    run: Run,
    reason: str,
    now: float,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Restart the tunnel unit and wait for its new instance to be up.

    The tunnel rewrites its health URL file on start; a file newer than
    the restart whose URL answers is the new poller (measured 2026-09-14:
    0.6 s). `ready_ms` lands on the service_restart line; not ready within
    `tunnel_ready_timeout_s` logs `tunnel_not_ready` and the health rung
    takes it from there.
    """
    url_file = policy.tunnel_health_url_file
    started = time.time()
    t0 = time.perf_counter()
    state.last_tunnel_restart = now
    proc = run("systemctl", "--user", "restart", policy.tunnel_unit, timeout=60.0)
    okay = proc.returncode == 0
    ready_ms: float | None = None
    if okay and url_file is not None:
        deadline = time.perf_counter() + policy.tunnel_ready_timeout_s
        while True:
            try:
                fresh = url_file.stat().st_mtime >= started - 1.0
                url = url_file.read_text(encoding="utf-8").strip() if fresh else ""
            except OSError:
                url = ""
            if url.startswith("http") and http_alive(url, timeout=1.0):
                ready_ms = (time.perf_counter() - t0) * 1000
                break
            if time.perf_counter() >= deadline:
                break
            sleep(0.5)
    log.warning(
        "event=service_restart cycle=%s unit=%s ok=%s ready_ms=%s reason=%s err=%s",
        state.cycle_n,
        policy.tunnel_unit,
        okay,
        f"{ready_ms:.0f}" if ready_ms is not None else "-",
        reason,
        proc.stderr.strip(),
    )
    if okay and url_file is not None and ready_ms is None:
        log.error(
            "event=tunnel_not_ready cycle=%s unit=%s waited_s=%.0f reason=no new health "
            "server answered; the health rung restarts it again after %s cycles",
            state.cycle_n,
            policy.tunnel_unit,
            policy.tunnel_ready_timeout_s,
            policy.service_failures_before_action,
        )
    return okay


def after_failover(
    state: State, policy: Policy, run: Run, now: float, target: str | None = None
) -> None:
    """Right after traffic moved: put the tunnel's connection on the new
    active route.

    Its socket is bound to the old route's address and would sit on the
    dead path for the rest of its poll deadline (35 s), then reconnect; a
    restart is back polling in about a second (measured 0.6 s on
    2026-09-14). Skipped when the connection is already on the new active
    route (a second failover right after a restart) or while the unit is
    restarting; a floor of `failover_restart_floor_s` between restarts.
    """
    if not policy.restart_tunnel_on_failover:
        return
    if not unit_active(policy.tunnel_unit, run):
        return
    routes, known = uplink.read_default_routes(run)
    active = target or (routes[0].dev if known and routes else None)
    sockets = tunnel_sockets(policy.tunnel_unit, routes if known else [], run)
    if sockets is None:
        log.info(
            "event=tunnel_kept cycle=%s reason=no tunnel process (restarting already)",
            state.cycle_n,
        )
        return
    via = tunnel_via(sockets, active)
    if active is not None and via == active:
        log.info(
            "event=tunnel_kept cycle=%s via=%s reason=connection already on the new active route",
            state.cycle_n,
            via,
        )
        return
    if (
        state.last_tunnel_restart
        and now - state.last_tunnel_restart < policy.failover_restart_floor_s
    ):
        log.warning(
            "event=service_restart_deferred cycle=%s unit=%s via=%s reason=restarted %.0f s ago",
            state.cycle_n,
            policy.tunnel_unit,
            via or "-",
            now - state.last_tunnel_restart,
        )
        return
    state.last_failover_restart = now
    restart_tunnel(
        state,
        policy,
        run,
        f"failover: the poller's connection is on {via or 'the old route'}, "
        f"traffic moved to {active or 'the next route'}",
        now,
    )


def tunnel_affinity_check(
    state: State,
    policy: Policy,
    run: Run,
    routes: list[Route],
    probes: dict[str, ProbeResult],
    obs: "ServiceObservation",
    n: int,
    now: float,
    holding: bool = False,
) -> str:
    """Keep the tunnel's connection on the active route.

    Returns the device it is on for the cycle line ("-" none seen). Off
    the active route and without a TCP path: restart now (the poller is
    stalling on it; `failover_restart_floor_s` between restarts). Off it
    but usable: after `tunnel_affinity_cycles` cycles with the active
    route healthy, at a quiet moment (no command forwarded for
    `tunnel_quiet_s`), one per minute -- waiting those cycles also means
    a route that wedges again right after its restore never costs a
    restart, because the connection is still where traffic goes back to.
    """
    active = uplink.active_route(routes) if routes else None
    if not policy.tunnel_affinity or not obs.tunnel_active or active is None:
        state.tunnel_off_active_cycles = 0
        state.tunnel_via = "-"
        return "-"
    sockets = tunnel_sockets(policy.tunnel_unit, routes, run)
    via = tunnel_via(sockets, active.dev)
    if via is None:
        state.tunnel_off_active_cycles = 0
        state.tunnel_via = "-"
        return "-"
    state.tunnel_via = via
    if via == active.dev:
        state.tunnel_off_active_cycles = 0
        return via
    state.tunnel_off_active_cycles += 1
    count = state.tunnel_off_active_cycles
    via_probe = probes.get(via)
    usable = via_probe is not None and via_probe.layers.get("tcp") is True
    active_probe = probes.get(active.dev)
    active_ok = active_probe is not None and active_probe.layers.get("tcp") is True
    since_restart = (
        now - state.last_tunnel_restart if state.last_tunnel_restart else None
    )
    forwarded_ago = now - obs.forwarded_last if obs.forwarded_last else None
    quiet = forwarded_ago is None or forwarded_ago >= policy.tunnel_quiet_s
    where = f"connection on {via} ({'usable' if usable else 'no TCP path'}), active {active.dev}"
    if holding:
        _log_decision(
            state, policy, n, now, "tunnel", "affinity", f"{where}; paused or dry-run"
        )
        return via
    if not usable:
        if not active_ok:
            why = f"{active.dev} has no TCP path either"
        elif (
            since_restart is not None
            and since_restart < policy.failover_restart_floor_s
        ):
            why = f"restarted {since_restart:.0f} s ago"
        else:
            state.tunnel_off_active_cycles = 0
            restart_tunnel(
                state,
                policy,
                run,
                f"affinity: the poller's connection is on {via}, which has no TCP path; "
                f"{active.dev} is the active route",
                now,
            )
            return via
        _log_decision(state, policy, n, now, "tunnel", "affinity", f"{where}; {why}")
        return via
    if count < policy.tunnel_affinity_cycles:
        why = f"waiting {count}/{policy.tunnel_affinity_cycles} cycles"
    elif active_probe is None or not active_probe.healthy:
        why = f"{active.dev} is not healthy"
    elif not quiet:
        why = f"a command was forwarded {forwarded_ago:.0f} s ago"
    elif since_restart is not None and since_restart < 60.0:
        why = f"restarted {since_restart:.0f} s ago"
    else:
        state.tunnel_off_active_cycles = 0
        restart_tunnel(
            state,
            policy,
            run,
            f"affinity: the poller's connection sat on {via} for {count} cycles while "
            f"{active.dev} is the active route"
            + (
                f" (quiet for {forwarded_ago:.0f} s)"
                if forwarded_ago is not None
                else " (no command forwarded)"
            ),
            now,
        )
        return via
    _log_decision(state, policy, n, now, "tunnel", "affinity", f"{where}; {why}")
    return via


def _log_issues(
    state: State, policy: Policy, issues: dict[str, str], n: int, now: float
) -> None:
    """`uplink_issue` / `uplink_issue_cleared` on change -- up to
    `flap_log_limit` changes per device inside a snapshot interval; past
    that one `uplink_issue_flapping` summary per interval stands for them
    (wlan0's lossy link wrote 56 issue lines in three hours)."""
    window = policy.snapshot_interval_s
    for dev in sorted(set(issues) | set(state.last_logged_issue)):
        current = issues.get(dev, "")
        if current == state.last_logged_issue.get(dev, ""):
            continue
        flips = [t for t in state.issue_flips.get(dev, []) if now - t < window]
        flips.append(now)
        state.issue_flips[dev] = flips
        if len(flips) <= policy.flap_log_limit:
            if current:
                log.warning(
                    "event=uplink_issue cycle=%s dev=%s issue=%s", n, dev, current
                )
            else:
                log.info("event=uplink_issue_cleared cycle=%s dev=%s", n, dev)
            state.last_logged_issue[dev] = current
            continue
        last_summary = state.last_flap_log.get(dev)
        if last_summary is None or now - last_summary >= window:
            state.last_flap_log[dev] = now
            log.warning(
                "event=uplink_issue_flapping cycle=%s dev=%s changes=%s window_s=%.0f current=%s",
                n,
                dev,
                len(flips),
                window,
                current or "clear",
            )
            state.last_logged_issue[dev] = current
    for dev in list(state.last_logged_issue):
        if not state.last_logged_issue[dev] and dev not in issues:
            state.last_logged_issue.pop(dev, None)

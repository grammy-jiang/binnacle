"""Endpoint, tunnel, poller, and uplink health checks."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from binnacle import uplink
from binnacle.doctor_common import (
    Check,
    Systemctl,
    fail,
    ok,
    systemctl,
    unit_property,
    unit_state,
    warn,
)

_INIT = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "binnacle-doctor", "version": "0"},
        },
    }
).encode()

#: Tunnel log messages that decide whether the poller is reaching OpenAI.
#: Both a failed poll and a timed-out poll are the poller backing off: in
#: the log, 132 of 186 timeout runs (2026-09-13/14) end with "poller
#: recovered", and during a wedge of the active route the poller logged
#: only timeouts for five minutes -- ChatGPT saw the connector offline
#: while an earlier version of this check counted nothing.
_POLL_DOWN = ("poll failed; backing off", "poll timed out; backing off")
_POLL_UP = ("poller recovered; polling operational", "🟢 tunnel-client started")
_POLL_WORK = "dispatcher forwarded command to MCP server"


def _post_initialize(url: str, authorization: str | None, timeout: float) -> int | None:
    """HTTP status of an MCP initialize, or None when nothing answers."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if authorization is not None:
        headers["Authorization"] = authorization
    req = urllib.request.Request(url, data=_INIT, headers=headers, method="POST")
    try:
        # url is built from the fixed http:// literal plus local settings, so
        # no file:/ or custom scheme can reach here.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return None


def check_endpoint(url: str, token_file: Path, timeout: float = 5.0) -> list[Check]:
    anon = _post_initialize(url, None, timeout)
    if anon is None:
        return [
            fail("endpoint", f"nothing answers at {url}", "is the server unit running?")
        ]
    out: list[Check] = []
    if anon == 401:
        out.append(ok("endpoint", f"{url} refuses an unauthenticated initialize (401)"))
    elif anon == 200:
        out.append(fail("endpoint", f"{url} accepts an initialize WITHOUT a token"))
    else:
        out.append(warn("endpoint", f"unauthenticated initialize returned HTTP {anon}"))
    try:
        header = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return out  # the token check already reported it
    if not header.startswith("Bearer "):
        header = "Bearer " + header
    auth = _post_initialize(url, header, timeout)
    if auth == 200:
        out.append(ok("endpoint", "initialize with the token file succeeds (200)"))
    elif auth in (401, 403):
        out.append(
            fail(
                "endpoint",
                f"the server rejects the token file (HTTP {auth})",
                "the running server loaded a different token; restart it "
                "(`systemctl --user restart <server unit>`)",
            )
        )
    else:
        out.append(warn("endpoint", f"authenticated initialize returned HTTP {auth}"))
    return out


def check_tunnel(
    unit: str,
    config_file: Path,
    token_file: Path,
    server_url: str,
    run: Systemctl = systemctl,
    timeout: float = 5.0,
    server_unit: str | None = None,
) -> list[Check]:
    out: list[Check] = []
    state = unit_state(unit, run)
    if state == "active":
        out.append(ok("tunnel", f"{unit} active"))
    else:
        out.append(
            fail(
                "tunnel",
                f"{unit} is {state}; ChatGPT cannot reach the server",
                f"systemctl --user start {unit}",
            )
        )
    if server_unit is not None:
        after = unit_property(unit, "After", run).split()
        if server_unit in after:
            out.append(ok("tunnel", f"{unit} starts after {server_unit}"))
        else:
            out.append(
                warn(
                    "tunnel",
                    f"{unit} is not ordered after {server_unit}",
                    f"add After={server_unit} to the tunnel unit",
                )
            )
    if not config_file.exists():
        out.append(
            fail(
                "tunnel",
                f"config missing at {config_file}",
                "write it from the tunnel account",
            )
        )
        return out
    try:
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        out.append(
            warn("tunnel", f"config at {config_file} is not JSON ({e}); not inspected")
        )
        return out
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    urls = [u.get("url") for u in mcp_cfg.get("server_urls", []) if isinstance(u, dict)]
    if server_url in urls:
        out.append(ok("tunnel", f"config forwards to {server_url}"))
    else:
        out.append(
            fail(
                "tunnel",
                f"config forwards to {urls or 'nothing'}, server listens at {server_url}",
                f"set mcp.server_urls[].url to {server_url} in {config_file}",
            )
        )
    expected = f"file:{token_file}"
    for key in ("extra_headers", "discovery_extra_headers"):
        value = (mcp_cfg.get(key) or {}).get("Authorization")
        if value == expected:
            out.append(ok("tunnel", f"mcp.{key} reads the token file"))
        else:
            out.append(
                fail(
                    "tunnel",
                    f"mcp.{key}.Authorization is {value!r}, expected {expected!r}",
                    f"fix {config_file} and restart {unit}",
                )
            )
    url_file = (
        ((cfg.get("health") or {}).get("url_file")) if isinstance(cfg, dict) else None
    )
    if url_file:
        out.append(_check_tunnel_health(Path(url_file), timeout))
    return out


def _check_tunnel_health(url_file: Path, timeout: float) -> Check:
    try:
        url = url_file.read_text(encoding="utf-8").strip()
    except OSError:
        return warn(
            "tunnel", f"health URL file {url_file} unreadable (tunnel not started?)"
        )
    if not url.startswith("http://127.0.0.1") and not url.startswith(
        "http://localhost"
    ):
        return warn("tunnel", f"health URL {url!r} is not local; not probed")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return ok("tunnel", f"health endpoint {url} answers HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        return ok("tunnel", f"health endpoint {url} answers HTTP {e.code}")
    except OSError:
        return warn(
            "tunnel", f"health endpoint {url} does not answer (stale url file?)"
        )


def _tail_lines(path: Path, max_bytes: int = 512 * 1024) -> list[str]:
    """Last lines of a file, without reading all of it.

    The tunnel log runs to megabytes within a day; only the tail says
    anything about the poller's current state.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # A partial first line is likely when we seek into the middle.
    return lines[1:] if size > max_bytes and lines else lines


@dataclass(frozen=True)
class TunnelLogStatus:
    """What the tail of the tunnel's log says right now."""

    #: Trailing failed/timed-out polls, and when the run began.
    trailing: int
    first_failure: str
    #: Time of the last line at all, and of the last command forwarded to
    #: the MCP server.
    last_time: str
    last_forwarded: str


def scan_tunnel_log(log_file: Path) -> TunnelLogStatus:
    """Read the tail of the tunnel's own log. A failed poll and a timed-out
    poll both count (the poller backs off after either); forwarded work or
    a recovery line ends a run. A single timeout is a blip; the callers'
    threshold of three is what makes it an outage."""
    trailing = 0
    first_failure = ""
    last_time = ""
    last_forwarded = ""
    for line in _tail_lines(log_file):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("msg", "")
        stamp = rec.get("time", "")
        if stamp:
            last_time = stamp
        if msg in _POLL_DOWN:
            if not trailing:
                first_failure = stamp
            trailing += 1
        elif msg in _POLL_UP or msg == _POLL_WORK:
            trailing = 0
            first_failure = ""
            if msg == _POLL_WORK and stamp:
                last_forwarded = stamp
    return TunnelLogStatus(trailing, first_failure, last_time, last_forwarded)


def poller_status(log_file: Path) -> tuple[int, str, str]:
    """(trailing poll failures, time of the first one, last log time)."""
    status = scan_tunnel_log(log_file)
    return status.trailing, status.first_failure, status.last_time


def check_tunnel_poller(log_file: Path, min_failures: int = 3) -> list[Check]:
    """Is the tunnel actually reaching OpenAI right now?

    This is the one check that sees what ChatGPT sees. Every other tunnel
    check is local: the unit can be active, the config correct and the
    local health port answering while the poller has been failing for an
    hour because the uplink is wedged. That is exactly the 2026-09-12
    outage, during which `doctor` reported all-ok.

    `poll timed out; backing off` counts like `poll failed`: measured on
    2026-09-14, a run of timeouts is what the tunnel logs while the
    uplink is wedged, and it ends with `poller recovered`.
    """
    if not log_file.exists():
        return [warn("poller", f"tunnel log {log_file} not found; poller not checked")]
    trailing, first_failure, last_time = poller_status(log_file)
    if trailing >= min_failures:
        return [
            fail(
                "poller",
                f"tunnel poll to OpenAI failing: {trailing} consecutive failures "
                f"since {first_failure or 'unknown'}; ChatGPT sees the connector offline",
                "check the uplink (binnacle doctor reports it above); "
                "check the uplink and tunnel path; move traffic to a working route "
                "before restarting the tunnel",
            )
        ]
    if trailing:
        return [
            warn(
                "poller",
                f"tunnel poll to OpenAI failing ({trailing} consecutive, "
                f"below the {min_failures} threshold)",
            )
        ]
    return [ok("poller", f"tunnel poll to OpenAI healthy (last log entry {last_time})")]


def check_uplink(
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: uplink.Run = uplink._run,
    fallback_nameserver: str | None = None,
) -> list[Check]:
    """Does the route traffic takes actually carry traffic?

    Probes every default route end to end. A wedged active route is a
    FAIL: the host is up, the server is up, and nothing can reach it.
    """
    routes = uplink.default_routes(run)
    if not routes:
        return [warn("uplink", "no default route with a gateway and source address")]
    probes = uplink.probe_all(
        routes,
        host=host,
        timeout=timeout,
        run=run,
        fallback_nameserver=fallback_nameserver,
    )
    active = uplink.active_route(routes)
    out: list[Check] = []
    for route in routes:
        probe = probes.get(route.dev)
        if probe is None:
            continue
        is_active = active is not None and route.dev == active.dev
        role = "active" if is_active else "standby"
        if probe.healthy:
            out.append(ok("uplink", f"{role} {route.label}: {probe.summary()}"))
        elif probe.wedged and is_active:
            out.append(
                fail(
                    "uplink",
                    f"active {route.label} carries nothing: {probe.summary()}",
                    "another route must take over; inspect the route and uplink state",
                )
            )
        elif probe.wedged:
            out.append(
                warn(
                    "uplink",
                    f"standby {route.label} carries nothing: {probe.summary()}",
                    f"no impact while {active.dev if active else '?'} is healthy",
                )
            )
        else:
            deepest = probe.deepest_ok or "nothing"
            out.append(
                warn(
                    "uplink",
                    f"{role} {route.label} degraded: {probe.summary()} "
                    f"(deepest layer reached: {deepest})",
                    probe.errors.get(probe.first_failure or "", ""),
                )
            )
    return out

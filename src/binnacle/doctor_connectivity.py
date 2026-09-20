"""Endpoint and uplink health checks, and the log-tail helper they share
with the companions."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from binnacle import uplink
from binnacle.doctor_common import (
    Check,
    fail,
    ok,
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

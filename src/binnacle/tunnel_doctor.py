"""Diagnostics for the tunnel companion: the unit file and its process, the
quiet gate for a restart, the profile config, the health port, and the
poller (the tunnel's own log, the one check that sees what ChatGPT sees).
May depend on core; core must not import it.
"""

import json
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from binnacle import logstats, units
from binnacle.config import get_settings
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
from binnacle.doctor_connectivity import _tail_lines
from binnacle.server_unit import SERVER_UNIT
from binnacle.tunnel_unit import (
    OWNER,
    PROFILE,
    TUNNEL_UNIT,
    profile_config,
    render_tunnel_unit,
)

_POLL_DOWN = ("poll failed; backing off", "poll timed out; backing off")
_POLL_UP = ("poller recovered; polling operational", "🟢 tunnel-client started")
_POLL_WORK = "dispatcher forwarded command to MCP server"


SETUP_HINT = "binnacle-tunnel setup"
RESTART_HINT = "binnacle-tunnel restart (waits for a quiet moment)"


def read_profile(path: Path) -> dict[str, object]:
    """The profile config as a dict; {} when missing or not JSON."""
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def log_file_of(cfg: dict[str, object]) -> Path | None:
    log = cfg.get("log")
    value = log.get("file") if isinstance(log, dict) else None
    return Path(value) if isinstance(value, str) and value else None


def parse_time(text: str) -> datetime | None:
    """RFC 3339 as the tunnel writes it, with Go's nanoseconds
    ('2026-09-20T23:31:30.909439218+10:00'); a naive stamp reads as UTC."""
    text = text.replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m:
        frac = (m.group(2) or ".0")[:7].ljust(7, "0")
        text = f"{m.group(1)}{frac}{m.group(3)}"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def tunnel_busy_reasons(
    window_s: float = 30.0,
    log_file: Path | None = None,
    server_unit: str = SERVER_UNIT,
    fetch: Callable[[str, str], str] = lambda u, s: logstats.fetch_journal(u, s),
    now: Callable[[], datetime] | None = None,
) -> list[str]:
    """Why restarting the tunnel now would hurt: a command it forwarded
    inside `window_s` (its reply would be dropped), or a tool call the
    server saw in the same window (the same call, seen from the other
    end). Empty means a quiet moment."""
    reasons: list[str] = []
    if log_file is not None and log_file.exists():
        stamp = scan_tunnel_log(log_file).last_forwarded
        when = parse_time(stamp) if stamp else None
        if when is not None:
            current = (now or (lambda: datetime.now(timezone.utc)))()
            age = (current - when).total_seconds()
            if age < window_s:
                reasons.append(
                    f"the tunnel forwarded a command {age:.0f} s ago; a restart "
                    "drops its reply"
                )
    try:
        calls = fetch(server_unit, f"-{int(window_s)}s").count("event=tool_call")
    except (OSError, subprocess.SubprocessError) as e:
        reasons.append(
            f"server journal unreadable ({e}); cannot tell whether calls are in flight"
        )
        return reasons
    if calls:
        reasons.append(
            f"{calls} tool call(s) on the server in the last {int(window_s)} s"
        )
    return reasons


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


def run_all(profile: str = PROFILE) -> list[Check]:
    """The unit file against what setup writes, the process it started,
    then the profile config, the health port and the poller."""
    checks: list[Check] = []
    checks += units.check_unit_drift(
        units.UNIT_DIR / TUNNEL_UNIT, OWNER, render_tunnel_unit, "tunnel", SETUP_HINT
    )
    checks += units.check_unit_process(TUNNEL_UNIT, "tunnel", SETUP_HINT, RESTART_HINT)
    settings = get_settings()
    cfg_path = profile_config(profile)
    checks += check_tunnel(
        TUNNEL_UNIT,
        cfg_path,
        settings.auth.token_file,
        f"http://{settings.serve.host}:{settings.serve.port}/mcp",
        server_unit=SERVER_UNIT,
    )
    log = log_file_of(read_profile(cfg_path))
    if log is not None:
        checks += check_tunnel_poller(log)
    return checks

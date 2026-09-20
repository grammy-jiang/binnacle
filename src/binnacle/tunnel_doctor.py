"""Diagnostics for the tunnel companion: the unit file and its process, the
quiet gate for a restart, and, until they move here, the core checks of
the profile config, the health port and the poller. May depend on core;
core must not import it.
"""

import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from binnacle import logstats, units
from binnacle.config import get_settings
from binnacle.doctor_common import Check
from binnacle.doctor_connectivity import (
    check_tunnel,
    check_tunnel_poller,
    scan_tunnel_log,
)
from binnacle.server_unit import SERVER_UNIT
from binnacle.tunnel_unit import (
    OWNER,
    PROFILE,
    TUNNEL_UNIT,
    profile_config,
    render_tunnel_unit,
)

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

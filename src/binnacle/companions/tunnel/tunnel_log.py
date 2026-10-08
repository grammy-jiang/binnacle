"""Public tunnel-log facts shared by tunnel diagnostics and watchdog policy."""

import json
from dataclasses import dataclass
from pathlib import Path

from binnacle.diagnostics.doctor_io import _tail_lines

_POLL_DOWN = ("poll failed; backing off", "poll timed out; backing off")
_POLL_UP = ("poller recovered; polling operational", "🟢 tunnel-client started")
_POLL_WORK = "dispatcher forwarded command to MCP server"


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

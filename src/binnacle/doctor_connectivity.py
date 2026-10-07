"""Local MCP endpoint authentication checks."""

import json
import urllib.error
import urllib.request
from pathlib import Path

from binnacle.doctor_common import (
    Check,
    fail,
    ok,
    warn,
)
from binnacle.doctor_io import _tail_lines

__all__ = ["_tail_lines", "check_endpoint"]

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

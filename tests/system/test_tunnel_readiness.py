"""The tunnel unit's readiness wait, run for real: the ExecStartPost script
rendered into the unit, with systemd's `$$` unescaped, against a local
stand-in for the tunnel's health server."""

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from binnacle import tunnel_unit


class _Health(BaseHTTPRequestHandler):
    probe = "ok"
    ready = 200
    #: tunnel-client writes compact JSON; the unit's grep also tolerates
    #: spaces after the colons.
    compact = True

    def do_GET(self):  # http.server API name
        if self.path == "/readyz":
            self.send_response(self.ready)
            self.end_headers()
            self.wfile.write(b"ready")
        elif self.path == "/api/status":
            body = json.dumps(
                {
                    "channels": [
                        {"name": "main", "enabled": True, "probe_status": self.probe}
                    ]
                },
                separators=(",", ":") if self.compact else (", ", ": "),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):  # silence
        pass


@pytest.fixture()
def health():
    srv = HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Health.probe, _Health.ready, _Health.compact = "ok", 200, True
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def readiness_script(url_file: Path, bound_s: int) -> str:
    """The ExecStartPost script as bash receives it, with a shorter bound."""
    params = {
        "tunnel": "/opt/bin/tunnel-client",
        "profile_dir": "/home/me/.config/tunnel-client",
        "profile": "binnacle",
        "env_file": "/home/me/.config/tunnel-client/binnacle-tunnel.env",
        "url_file": str(url_file),
        "server_unit": "binnacle-mcp.service",
        "home": "/home/me",
    }
    unit = tunnel_unit.render_tunnel_unit(params)
    line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStartPost="))
    script = line.split(" -c ", 1)[1].strip()
    assert script[0] == script[-1] == "'"
    script = script[1:-1].replace("$$", "$")
    return script.replace("SECONDS+10", f"SECONDS+{bound_s}")


def run_wait(
    script: str, write_url: str | None, delay: float = 0.3
) -> tuple[int, float]:
    """Start the script; `write_url` is written to the URL file after `delay`,
    the way a fresh tunnel instance rewrites its URL file after it starts."""
    started = time.monotonic()
    proc = subprocess.Popen(["bash", "-c", script])
    if write_url is not None:
        time.sleep(delay)
        Path(script.split('"')[1]).write_text(write_url + "\n")
    proc.wait(timeout=30)
    return proc.returncode, time.monotonic() - started


def test_ready_once_readyz_and_the_main_probe_are_ok(health, tmp_path):
    script = readiness_script(tmp_path / "binnacle.url", bound_s=8)
    code, elapsed = run_wait(script, health)
    assert code == 0 and elapsed < 5


def test_ready_with_pretty_printed_status_too(health, tmp_path):
    _Health.compact = False
    script = readiness_script(tmp_path / "binnacle.url", bound_s=8)
    code, elapsed = run_wait(script, health)
    assert code == 0 and elapsed < 5


# bash's SECONDS counts whole wall-clock seconds, so a bound of N holds the
# script for N-1 to N seconds; the unit's 10 means 9 to 10.
def test_waits_out_the_bound_but_never_fails_when_the_probe_is_not_ok(health, tmp_path):
    _Health.probe = "error"
    script = readiness_script(tmp_path / "binnacle.url", bound_s=2)
    code, elapsed = run_wait(script, health)
    assert code == 0 and 1 <= elapsed < 4


def test_waits_out_the_bound_when_the_url_file_is_stale(tmp_path):
    url_file = tmp_path / "binnacle.url"
    url_file.write_text("http://127.0.0.1:1\n")  # older than the script's marker
    script = readiness_script(url_file, bound_s=2)
    code, elapsed = run_wait(script, None)
    assert code == 0 and 1 <= elapsed < 4

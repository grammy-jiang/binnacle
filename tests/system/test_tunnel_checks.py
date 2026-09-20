"""The tunnel companion's checks of the profile config, the health port and
the poller (the tunnel's own log), moved here from the core doctor on
2026-09-21 with the code they test."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from binnacle import doctor, tunnel_doctor

BEARER = "Bearer secret-token\n"


def statuses(checks: list[doctor.Check]) -> list[str]:
    return [c.status for c in checks]


def fake_systemctl(states: dict[str, str], props: dict[str, str] | None = None):
    props = props or {}

    def run(*args: str) -> subprocess.CompletedProcess:
        if args[0] == "is-active":
            out = states.get(args[1], "inactive")
        elif args[0] == "show":
            out = props.get(f"{args[1]}.{args[3]}", "")
        else:
            out = ""
        return subprocess.CompletedProcess(list(args), 0, stdout=out + "\n", stderr="")

    return run


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # http.server API name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # silence
        pass


@pytest.fixture()
def http_url():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/mcp"
    srv.shutdown()


@pytest.fixture()
def token_file(tmp_path) -> Path:
    f = tmp_path / "token"
    f.write_text(BEARER)
    return f


def _tunnel_cfg(tmp_path, token_file: Path, url="http://127.0.0.1:8000/mcp", **over):
    cfg = {
        "mcp": {
            "extra_headers": {"Authorization": f"file:{token_file}"},
            "discovery_extra_headers": {"Authorization": f"file:{token_file}"},
            "server_urls": [{"channel": "main", "url": url}],
        },
    }
    cfg.update(over)
    f = tmp_path / "binnacle.yaml"
    f.write_text(json.dumps(cfg))
    return f


def test_tunnel_good(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    checks = tunnel_doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "ok", "ok", "ok"]


def test_tunnel_inactive_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    checks = tunnel_doctor.check_tunnel(
        "t", cfg, token_file, "http://127.0.0.1:8000/mcp", run=fake_systemctl({})
    )
    assert checks[0].status == "fail"


def test_tunnel_wrong_port_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file, url="http://127.0.0.1:9000/mcp")
    checks = tunnel_doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert checks[1].status == "fail" and "9000" in checks[1].detail


def test_tunnel_header_points_elsewhere_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, tmp_path / "other-token")
    checks = tunnel_doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "ok", "fail", "fail"]


def test_tunnel_config_missing_fails(tmp_path, token_file):
    checks = tunnel_doctor.check_tunnel(
        "t",
        tmp_path / "nope.yaml",
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "fail"]


def test_tunnel_unparseable_config_warns(tmp_path, token_file):
    f = tmp_path / "binnacle.yaml"
    f.write_text("mcp:\n  server_urls: [not json]\n")
    checks = tunnel_doctor.check_tunnel(
        "t",
        f,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "warn"]


def test_tunnel_health_probe(tmp_path, token_file, http_url):
    url_file = tmp_path / "health.url"
    url_file.write_text(http_url.removesuffix("/mcp") + "\n")
    cfg = _tunnel_cfg(tmp_path, token_file, health={"url_file": str(url_file)})
    checks = tunnel_doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    # GET on the fake server is unsupported (501) but that is still an answer.
    assert checks[-1].status == "ok" and "health endpoint" in checks[-1].detail


def test_tunnel_health_url_file_missing_warns(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file, health={"url_file": str(tmp_path / "none")})
    checks = tunnel_doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert checks[-1].status == "warn"


def test_tunnel_ordered_after_server_ok(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    run = fake_systemctl({"t": "active"}, {"t.After": "basic.target prod dev"})
    checks = tunnel_doctor.check_tunnel(
        "t", cfg, token_file, "http://127.0.0.1:8000/mcp", run=run, server_unit="prod"
    )
    assert checks[1].status == "ok" and "after prod" in checks[1].detail


def test_tunnel_not_ordered_after_server_warns(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    run = fake_systemctl({"t": "active"}, {"t.After": "basic.target"})
    checks = tunnel_doctor.check_tunnel(
        "t", cfg, token_file, "http://127.0.0.1:8000/mcp", run=run, server_unit="dev"
    )
    assert checks[1].status == "warn" and "After=dev" in checks[1].hint


def poll_log(
    tmp_path: Path, messages: list[str], start: str = "2026-09-12T10:00:00Z"
) -> Path:
    f = tmp_path / "tunnel.log"
    f.write_text(
        "\n".join(
            json.dumps({"time": start, "level": "INFO", "msg": m}) for m in messages
        )
        + "\n"
    )
    return f


def test_poller_ok_when_the_log_ends_with_work(tmp_path):
    log = poll_log(
        tmp_path,
        ["poll failed; backing off", "poller recovered; polling operational"],
    )
    (c,) = tunnel_doctor.check_tunnel_poller(log)
    assert c.status == "ok"


def test_poller_fails_on_a_run_of_failures(tmp_path):
    """The exact outage signature: 146 consecutive poll failures."""
    log = poll_log(tmp_path, ["poll failed; backing off"] * 146)
    (c,) = tunnel_doctor.check_tunnel_poller(log)
    assert c.status == "fail"
    assert "146 consecutive" in c.detail and "offline" in c.detail


def test_poller_warns_below_the_threshold(tmp_path):
    log = poll_log(tmp_path, ["poll failed; backing off"] * 2)
    (c,) = tunnel_doctor.check_tunnel_poller(log, min_failures=3)
    assert c.status == "warn"


def test_poller_counts_timeouts_like_failures(tmp_path):
    """2026-09-14: during a wedge the tunnel logged only timeouts for five
    minutes and then `poller recovered`; an earlier version of this check
    called them the idle long poll and reported ok."""
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"t1","msg":"poll timed out; backing off"}\n'
        '{"time":"t2","msg":"poll timed out; backing off"}\n'
        '{"time":"t3","msg":"poll timed out; backing off"}\n'
    )
    (c,) = tunnel_doctor.check_tunnel_poller(log)
    assert c.status == "fail" and "3 consecutive failures" in c.detail
    log.write_text(
        '{"time":"t1","msg":"poll timed out; backing off"}\n'
        '{"time":"t2","msg":"poller recovered; polling operational"}\n'
    )
    (c,) = tunnel_doctor.check_tunnel_poller(log)
    assert c.status == "ok"


def test_poller_recovery_clears_an_earlier_run(tmp_path):
    log = poll_log(
        tmp_path,
        ["poll failed; backing off"] * 9
        + [
            "poller recovered; polling operational",
            "dispatcher forwarded command to MCP server",
        ],
    )
    (c,) = tunnel_doctor.check_tunnel_poller(log)
    assert c.status == "ok"


def test_poller_missing_log_warns(tmp_path):
    (c,) = tunnel_doctor.check_tunnel_poller(tmp_path / "nope.log")
    assert c.status == "warn"


def test_poller_status_counts_the_trailing_run(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"t1","msg":"poll failed; backing off"}\n'
        '{"time":"t2","msg":"dispatcher forwarded command to MCP server"}\n'
        '{"time":"t3","msg":"poll failed; backing off"}\n'
        '{"time":"t4","msg":"poll failed; backing off"}\n'
        "not json\n"
    )
    assert tunnel_doctor.poller_status(log) == (2, "t3", "t4")


def test_scan_tunnel_log_reports_the_last_forwarded_command(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"t1","msg":"dispatcher forwarded command to MCP server"}\n'
        '{"time":"t2","msg":"poll timed out; backing off"}\n'
        '{"time":"t3","msg":"poll failed; backing off"}\n'
    )
    status = tunnel_doctor.scan_tunnel_log(log)
    assert (
        status.trailing,
        status.first_failure,
        status.last_time,
        status.last_forwarded,
    ) == (
        2,
        "t2",
        "t3",
        "t1",
    )
    assert tunnel_doctor.poller_status(log) == (2, "t2", "t3")

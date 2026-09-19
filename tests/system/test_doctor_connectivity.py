"""Connectivity diagnostics for endpoint, tunnel, poller, and uplink."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from binnacle import doctor, doctor_connectivity, uplink

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


WLAN1 = uplink.Route("wlan1", "192.168.50.1", "192.168.50.197", 100)
WLAN0 = uplink.Route("wlan0", "192.168.50.1", "192.168.50.222", 600)


class _Handler(BaseHTTPRequestHandler):
    accept_anon = False

    def do_POST(self):  # http.server API name
        auth = self.headers.get("Authorization")
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if auth == BEARER.strip() or (auth is None and self.accept_anon):
            self.send_response(200)
        else:
            self.send_response(401)
        self.end_headers()

    def log_message(self, format, *args):  # silence
        pass


@pytest.fixture()
def http_url():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _Handler.accept_anon = False
    yield f"http://127.0.0.1:{srv.server_address[1]}/mcp"
    srv.shutdown()


@pytest.fixture()
def token_file(tmp_path) -> Path:
    f = tmp_path / "token"
    f.write_text(BEARER)
    return f


def test_endpoint_good(http_url, token_file):
    assert statuses(doctor.check_endpoint(http_url, token_file)) == ["ok", "ok"]


def test_endpoint_bare_token_file_gets_prefix(http_url, tmp_path):
    f = tmp_path / "token"
    f.write_text(BEARER.removeprefix("Bearer "))
    assert statuses(doctor.check_endpoint(http_url, f)) == ["ok", "ok"]


def test_endpoint_wrong_token_fails(http_url, tmp_path):
    f = tmp_path / "token"
    f.write_text("Bearer stale\n")
    checks = doctor.check_endpoint(http_url, f)
    assert checks[1].status == "fail" and "restart" in checks[1].hint


def test_endpoint_auth_not_enforced_fails(http_url, token_file):
    _Handler.accept_anon = True
    assert doctor.check_endpoint(http_url, token_file)[0].status == "fail"


def test_endpoint_nothing_answers_fails(token_file):
    # Bind then close a socket to find a port nobody listens on.
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    (c,) = doctor.check_endpoint(f"http://127.0.0.1:{port}/mcp", token_file, timeout=1)
    assert c.status == "fail" and "nothing answers" in c.detail


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
    checks = doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "ok", "ok", "ok"]


def test_tunnel_inactive_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    checks = doctor.check_tunnel(
        "t", cfg, token_file, "http://127.0.0.1:8000/mcp", run=fake_systemctl({})
    )
    assert checks[0].status == "fail"


def test_tunnel_wrong_port_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file, url="http://127.0.0.1:9000/mcp")
    checks = doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert checks[1].status == "fail" and "9000" in checks[1].detail


def test_tunnel_header_points_elsewhere_fails(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, tmp_path / "other-token")
    checks = doctor.check_tunnel(
        "t",
        cfg,
        token_file,
        "http://127.0.0.1:8000/mcp",
        run=fake_systemctl({"t": "active"}),
    )
    assert statuses(checks) == ["ok", "ok", "fail", "fail"]


def test_tunnel_config_missing_fails(tmp_path, token_file):
    checks = doctor.check_tunnel(
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
    checks = doctor.check_tunnel(
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
    checks = doctor.check_tunnel(
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
    checks = doctor.check_tunnel(
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
    checks = doctor.check_tunnel(
        "t", cfg, token_file, "http://127.0.0.1:8000/mcp", run=run, server_unit="prod"
    )
    assert checks[1].status == "ok" and "after prod" in checks[1].detail


def test_tunnel_not_ordered_after_server_warns(tmp_path, token_file):
    cfg = _tunnel_cfg(tmp_path, token_file)
    run = fake_systemctl({"t": "active"}, {"t.After": "basic.target"})
    checks = doctor.check_tunnel(
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
    (c,) = doctor.check_tunnel_poller(log)
    assert c.status == "ok"


def test_poller_fails_on_a_run_of_failures(tmp_path):
    """The exact outage signature: 146 consecutive poll failures."""
    log = poll_log(tmp_path, ["poll failed; backing off"] * 146)
    (c,) = doctor.check_tunnel_poller(log)
    assert c.status == "fail"
    assert "146 consecutive" in c.detail and "offline" in c.detail


def test_poller_warns_below_the_threshold(tmp_path):
    log = poll_log(tmp_path, ["poll failed; backing off"] * 2)
    (c,) = doctor.check_tunnel_poller(log, min_failures=3)
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
    (c,) = doctor.check_tunnel_poller(log)
    assert c.status == "fail" and "3 consecutive failures" in c.detail
    log.write_text(
        '{"time":"t1","msg":"poll timed out; backing off"}\n'
        '{"time":"t2","msg":"poller recovered; polling operational"}\n'
    )
    (c,) = doctor.check_tunnel_poller(log)
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
    (c,) = doctor.check_tunnel_poller(log)
    assert c.status == "ok"


def test_poller_missing_log_warns(tmp_path):
    (c,) = doctor.check_tunnel_poller(tmp_path / "nope.log")
    assert c.status == "warn"


def test_tail_lines_reads_only_the_end(tmp_path):
    f = tmp_path / "big.log"
    f.write_text("".join(f"line{i}\n" for i in range(50_000)))
    lines = doctor._tail_lines(f, max_bytes=1024)
    assert len(lines) < 200 and lines[-1] == "line49999"


def fake_probe_routes(monkeypatch, routes, results):
    monkeypatch.setattr(
        doctor_connectivity.uplink, "default_routes", lambda run: routes
    )
    monkeypatch.setattr(
        doctor_connectivity.uplink, "probe_all", lambda r, **kw: results
    )


def probe_result(dev, gateway, dns, tcp):
    return uplink.ProbeResult(
        dev=dev, layers={"gateway": gateway, "dns": dns, "tcp": tcp}
    )


def test_uplink_ok_when_both_routes_carry_traffic(monkeypatch):
    fake_probe_routes(
        monkeypatch,
        [WLAN1, WLAN0],
        {
            "wlan1": probe_result("wlan1", True, True, True),
            "wlan0": probe_result("wlan0", True, True, True),
        },
    )
    checks = doctor.check_uplink()
    assert statuses(checks) == ["ok", "ok"]
    assert "active" in checks[0].detail


def test_uplink_fails_when_the_active_route_carries_nothing(monkeypatch):
    """Up, addressed, routed -- and nothing gets out. FAIL, not WARN."""
    fake_probe_routes(
        monkeypatch,
        [WLAN1, WLAN0],
        {
            "wlan1": probe_result("wlan1", False, False, False),
            "wlan0": probe_result("wlan0", True, True, True),
        },
    )
    checks = doctor.check_uplink()
    assert statuses(checks) == ["fail", "ok"]
    assert "carries nothing" in checks[0].detail


def test_uplink_only_warns_when_a_standby_is_wedged(monkeypatch):
    fake_probe_routes(
        monkeypatch,
        [WLAN1, WLAN0],
        {
            "wlan1": probe_result("wlan1", True, True, True),
            "wlan0": probe_result("wlan0", False, False, False),
        },
    )
    assert statuses(doctor.check_uplink()) == ["ok", "warn"]


def test_uplink_warns_on_partial_reachability(monkeypatch):
    fake_probe_routes(
        monkeypatch,
        [WLAN1],
        {"wlan1": probe_result("wlan1", True, False, False)},
    )
    (c,) = doctor.check_uplink()
    assert c.status == "warn" and "deepest layer reached: gateway" in c.detail


def test_uplink_warns_without_any_default_route(monkeypatch):
    fake_probe_routes(monkeypatch, [], {})
    (c,) = doctor.check_uplink()
    assert c.status == "warn" and "no default route" in c.detail


def test_poller_status_counts_the_trailing_run(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"t1","msg":"poll failed; backing off"}\n'
        '{"time":"t2","msg":"dispatcher forwarded command to MCP server"}\n'
        '{"time":"t3","msg":"poll failed; backing off"}\n'
        '{"time":"t4","msg":"poll failed; backing off"}\n'
        "not json\n"
    )
    assert doctor.poller_status(log) == (2, "t3", "t4")


def test_scan_tunnel_log_reports_the_last_forwarded_command(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"t1","msg":"dispatcher forwarded command to MCP server"}\n'
        '{"time":"t2","msg":"poll timed out; backing off"}\n'
        '{"time":"t3","msg":"poll failed; backing off"}\n'
    )
    status = doctor.scan_tunnel_log(log)
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
    assert doctor.poller_status(log) == (2, "t2", "t3")

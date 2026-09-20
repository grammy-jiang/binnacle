"""Connectivity diagnostics for the endpoint and the uplink."""

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

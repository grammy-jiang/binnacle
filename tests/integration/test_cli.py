"""Integration tests for Binnacle's command-line control surface.

Host-mutating boundaries such as systemctl, service setup, driver reloads,
and network probes are faked. The tests exercise user-visible command glue:
deployment setup, mode switching, diagnostics, watchdog controls, statistics,
and token rotation without changing the development Raspberry Pi.
"""

import subprocess

from binnacle import cli, doctor


def test_write_token_format_and_mode(tmp_path):
    f = tmp_path / "cfg" / "token"
    cli._write_token(f)
    text = f.read_text()
    assert text.startswith("Bearer ") and text.endswith("\n")
    assert len(text.removeprefix("Bearer ").strip()) >= 32
    assert f.stat().st_mode & 0o777 == 0o600


def test_write_token_satisfies_doctor(tmp_path):
    # The writer and the checker must agree on the file format.
    f = tmp_path / "token"
    cli._write_token(f)
    assert [c.status for c in doctor.check_token(f)] == ["ok", "ok", "ok"]


def test_write_token_matches_server_loader(tmp_path, monkeypatch):
    # server._load_token strips the prefix; the bare token must survive.
    from binnacle import server

    f = tmp_path / "token"
    cli._write_token(f)
    monkeypatch.setattr(server, "TOKEN_FILE", f)
    assert server._load_token() == f.read_text().removeprefix("Bearer ").strip()


def test_write_token_changes_value(tmp_path):
    f = tmp_path / "token"
    cli._write_token(f)
    first = f.read_text()
    cli._write_token(f)
    assert f.read_text() != first


def test_rotate_writes_prefixed_token_and_restarts_active_units(
    tmp_path, monkeypatch, capsys
):
    f = tmp_path / "token"
    f.write_text("old\n")
    monkeypatch.setattr(cli, "TOKEN_FILE", f)
    calls: list[tuple[str, ...]] = []
    states = {cli.SERVER_UNIT: "active", cli.TUNNEL_UNIT: "active"}

    def fake_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(list(args), 0, "", "")

    monkeypatch.setattr(cli, "_systemctl", fake_systemctl)
    monkeypatch.setattr(cli, "_unit_state", lambda u: states[u])
    waited: list[float] = []
    monkeypatch.setattr(
        cli, "_wait_tunnel_ready", lambda since: waited.append(since) or "tunnel ready"
    )

    cli.rotate()
    assert len(waited) == 1  # once, after the tunnel restart

    assert f.read_text().startswith("Bearer ")
    assert f.read_text() != "old\n"
    assert calls == [("restart", cli.SERVER_UNIT), ("restart", cli.TUNNEL_UNIT)]
    out = capsys.readouterr().out
    assert "wrote new token" in out


# -- tunnel readiness wait (token rotate) -----------------------------------

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _TunnelHealth(BaseHTTPRequestHandler):
    started_at = ""
    probe = "ok"
    ready = 200

    def do_GET(self):  # http.server API name
        if self.path == "/api/status":
            body = json.dumps(
                {
                    "started_at": self.started_at,
                    "channels": [{"name": "main", "probe_status": self.probe}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/readyz":
            self.send_response(self.ready)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture()
def tunnel_health():
    srv = HTTPServer(("127.0.0.1", 0), _TunnelHealth)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _TunnelHealth.probe, _TunnelHealth.ready = "ok", 200
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _go_ts(t: float) -> str:
    # Go's RFC 3339 with nanoseconds and a numeric offset, as tunnel-client emits.
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.123456789+00:00"
    )


def test_parse_rfc3339_go_nanoseconds():
    dt = cli._parse_rfc3339("2026-09-03T09:09:23.956036578+10:00")
    assert dt.isoformat() == "2026-09-03T09:09:23.956036+10:00"
    assert cli._parse_rfc3339("2026-09-03T00:00:00Z").utcoffset().total_seconds() == 0


def test_wait_tunnel_ready_fresh_instance(tunnel_health):
    since = time.time()
    _TunnelHealth.started_at = _go_ts(since + 1)
    msg = cli._wait_tunnel_ready(since, timeout_s=5, health_url=lambda: tunnel_health)
    assert msg.startswith("tunnel ready")


def test_wait_tunnel_ready_stale_instance_times_out(tunnel_health):
    since = time.time()
    _TunnelHealth.started_at = _go_ts(since - 100)  # old instance still answering
    msg = cli._wait_tunnel_ready(since, timeout_s=0.6, health_url=lambda: tunnel_health)
    assert "not ready" in msg and "previous tunnel instance" in msg


def test_wait_tunnel_ready_probe_failing_times_out(tunnel_health):
    since = time.time()
    _TunnelHealth.started_at = _go_ts(since + 1)
    _TunnelHealth.probe = "error"
    msg = cli._wait_tunnel_ready(since, timeout_s=0.6, health_url=lambda: tunnel_health)
    assert "probe status 'error'" in msg


def test_wait_tunnel_ready_no_health_url_times_out():
    msg = cli._wait_tunnel_ready(time.time(), timeout_s=0.3, health_url=lambda: None)
    assert "not ready" in msg and "not written" in msg


# -- command glue and safe control paths ------------------------------------


# -- baseline command coverage -----------------------------------------------


def test_serve_uses_explicit_uvicorn_performance_stack(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake)

    cli.serve(host="127.0.0.1", port=8765, reload=True)

    assert calls == [
        (
            ("binnacle.server:app",),
            {
                "host": "127.0.0.1",
                "port": 8765,
                "reload": True,
                "loop": "uvloop",
                "http": "httptools",
            },
        )
    ]


def test_doctor_passes_deployment_and_exit_code(monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(serve=SimpleNamespace(host="127.0.0.1", port=8123)),
    )
    seen = {}

    def fake_run_all(dep, *, since, probe):
        seen.update(dep=dep, since=since, probe=probe)
        return ["check"]

    monkeypatch.setattr(doctor, "run_all", fake_run_all)
    monkeypatch.setattr(doctor, "render", lambda results: ("healthy", 0))

    with pytest.raises(SystemExit) as exc:
        cli.doctor(since="-2 hours", probe=False)

    assert exc.value.code == 0
    assert seen["since"] == "-2 hours"
    assert seen["probe"] is False
    assert seen["dep"].server_url == "http://127.0.0.1:8123/mcp"
    assert capsys.readouterr().out.strip() == "healthy"


def test_stats_only_loads_webmin_history_when_requested(monkeypatch, capsys):
    from binnacle import logstats, webminstats

    monkeypatch.setattr(logstats, "fetch_journal", lambda unit, since, until: "journal")
    monkeypatch.setattr(logstats, "parse", lambda raw: (["record"], ["startup"]))
    monkeypatch.setattr(logstats, "analyze", lambda records, startups: "analysis")
    monkeypatch.setattr(logstats, "render", lambda analysis: "USAGE")
    loads = []
    monkeypatch.setattr(
        webminstats,
        "load",
        lambda since, until: loads.append((since, until)) or "resources",
    )
    monkeypatch.setattr(webminstats, "render", lambda data: "RESOURCES")

    cli.stats(since="-1 hour", until="now", unit="dev", system_resources=False)
    first = capsys.readouterr().out
    assert "USAGE" in first
    assert "RESOURCES" not in first
    assert loads == []

    cli.stats(since="-1 hour", until="now", unit="dev", system_resources=True)
    second = capsys.readouterr().out
    assert "USAGE" in second and "RESOURCES" in second
    assert loads == [("-1 hour", "now")]


def test_tunnel_health_url_reads_current_url_file_and_handles_bad_config(
    tmp_path, monkeypatch
):
    config = tmp_path / "tunnel.json"
    url_file = tmp_path / "health.url"
    url_file.write_text("http://127.0.0.1:1234\n")
    config.write_text(f'{{"health": {{"url_file": "{url_file}"}}}}')
    monkeypatch.setattr(cli, "TUNNEL_CONFIG", config)

    assert cli._tunnel_health_url() == "http://127.0.0.1:1234"

    config.write_text("{}")
    assert cli._tunnel_health_url() is None


def test_parse_rfc3339_accepts_plain_iso_date():
    assert cli._parse_rfc3339("2026-09-03").date().isoformat() == "2026-09-03"


def test_systemctl_wrapper_and_unit_state(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="active\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    proc = cli._systemctl("is-active", "demo.service", check=False)
    assert proc.stdout.strip() == "active"
    assert seen[0][0] == ["systemctl", "--user", "is-active", "demo.service"]
    assert seen[0][1]["check"] is False
    assert cli._unit_state("demo.service") == "active"


def test_main_dispatches_cyclopts_app(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))

    cli.main()

    assert called == [True]

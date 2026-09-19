"""Implementation gate for binnacle/doctor.py (`binnacle doctor`).

Every outside dependency (systemctl, /proc, the journal) is a fake passed
in; the endpoint checks talk to a throwaway http.server so the real
urllib path is exercised.
"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from binnacle import doctor, uplink
from binnacle import jobs as jobstore

BEARER = "Bearer secret-token\n"


def statuses(checks: list[doctor.Check]) -> list[str]:
    return [c.status for c in checks]


def fake_systemctl(states: dict[str, str], props: dict[str, str] | None = None):
    """A systemctl stand-in: is-active from `states`, show -p from `props`."""
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


# -- token -------------------------------------------------------------------


def test_token_missing_fails(tmp_path):
    (c,) = doctor.check_token(tmp_path / "token")
    assert c.status == "fail" and "setup" in c.hint


def test_token_good(tmp_path):
    f = tmp_path / "token"
    f.write_text(BEARER)
    f.chmod(0o600)
    assert statuses(doctor.check_token(f)) == ["ok", "ok", "ok"]


def test_token_wrong_mode_fails(tmp_path):
    f = tmp_path / "token"
    f.write_text(BEARER)
    f.chmod(0o644)
    checks = doctor.check_token(f)
    assert checks[1].status == "fail" and "0644" in checks[1].detail


def test_token_without_prefix_warns(tmp_path):
    # The tunnel forwards the file verbatim as the Authorization header.
    f = tmp_path / "token"
    f.write_text("bare-token\n")
    f.chmod(0o600)
    assert doctor.check_token(f)[2].status == "warn"


def test_token_empty_fails(tmp_path):
    f = tmp_path / "token"
    f.write_text("Bearer \n")
    f.chmod(0o600)
    assert doctor.check_token(f)[2].status == "fail"


# -- units -------------------------------------------------------------------


def test_units_none_active_fails():
    checks, active = doctor.check_units(
        "prod", "dev", run=fake_systemctl({}), linger=lambda: True
    )
    assert active is None
    assert statuses(checks) == ["fail"]


READY = {"NRestarts": "0", "ExecStartPost": "{ path=/bin/bash ; argv[]=... }"}


def _props(unit: str, **over: str) -> dict[str, str]:
    return {f"{unit}.{k}": v for k, v in {**READY, **over}.items()}


def test_units_one_active_ok():
    run = fake_systemctl({"prod": "active"}, _props("prod"))
    checks, active = doctor.check_units("prod", "dev", run=run, linger=lambda: True)
    assert active == "prod"
    assert statuses(checks) == ["ok", "ok", "ok", "ok"]


def test_units_without_readiness_gate_warns():
    # The restart noise of 2026-09-03: tunnel probed a port uvicorn had not
    # opened yet, because Type=simple counts the fork as "started".
    run = fake_systemctl({"prod": "active"}, _props("prod", ExecStartPost=""))
    checks, _ = doctor.check_units("prod", "dev", run=run, linger=lambda: True)
    assert checks[2].status == "warn" and "ExecStartPost" in checks[2].hint


def test_units_both_active_fails():
    run = fake_systemctl({"prod": "active", "dev": "active"}, _props("prod"))
    checks, _ = doctor.check_units("prod", "dev", run=run, linger=lambda: True)
    assert checks[0].status == "fail" and "Conflicts" in checks[0].hint


def test_units_restarts_and_no_linger_warn():
    run = fake_systemctl({"dev": "active"}, _props("dev", NRestarts="3"))
    checks, active = doctor.check_units("prod", "dev", run=run, linger=lambda: False)
    assert active == "dev"
    assert statuses(checks) == ["ok", "warn", "ok", "warn"]
    assert "3 time(s)" in checks[1].detail


def test_units_linger_unknown_is_silent():
    run = fake_systemctl({"prod": "active"}, _props("prod"))
    checks, _ = doctor.check_units("prod", "dev", run=run, linger=lambda: None)
    assert len(checks) == 3


# -- service environment -----------------------------------------------------


def _env_with(path: str):
    return lambda pid: {"PATH": path}


def test_service_env_good(tmp_path):
    user_bin = tmp_path / "bin"
    user_bin.mkdir()
    for name in ("bash", "rg"):
        p = user_bin / name
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "rg", user_bin, run=run, environ=_env_with(str(user_bin))
    )
    assert statuses(checks) == ["ok", "ok", "ok"]


def test_service_env_missing_user_bin_fails(tmp_path):
    # The 2026-09-02 incident: boot-time PATH without ~/.local/bin.
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "rg", tmp_path / "bin", run=run, environ=_env_with("/usr/bin:/bin")
    )
    assert checks[0].status == "fail" and "environment.d" in checks[0].hint
    assert checks[1].status == "ok"  # bash is on /usr/bin or /bin


def test_service_env_missing_rg_fails(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "definitely-not-rg", tmp_path, run=run, environ=_env_with(str(tmp_path))
    )
    assert checks[2].status == "fail" and "search_text" in checks[2].detail


def test_service_env_no_pid_warns(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "0"})
    (c,) = doctor.check_service_env("u", "rg", tmp_path, run=run)
    assert c.status == "warn"


def test_service_env_unreadable_proc_warns(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "42"})
    (c,) = doctor.check_service_env(
        "u", "rg", tmp_path, run=run, environ=lambda pid: None
    )
    assert c.status == "warn"


def test_process_environ_reads_own_process():
    env = doctor.process_environ(os.getpid())
    assert env is not None and "PATH" in env


# -- endpoint ----------------------------------------------------------------


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


# -- tunnel ------------------------------------------------------------------


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


# -- jobs --------------------------------------------------------------------


def _job_dir(root: Path, name: str, meta: dict) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "out.log").write_text("")


def test_jobs_spool_absent_is_ok(tmp_path):
    (c,) = doctor.check_jobs(tmp_path / "jobs")
    assert c.status == "ok"


def test_jobs_counts_running_and_orphaned(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobstore, "JOBS_DIR", store)
    _job_dir(
        store,
        "a" * 12,
        {"command": "x", "workdir": "/tmp", "pid": os.getpid(), "started_at": 1.0},
    )
    _job_dir(
        store,
        "b" * 12,
        {"command": "x", "workdir": "/tmp", "pid": 2**22 - 1, "started_at": 1.0},
    )
    _job_dir(
        store,
        "c" * 12,
        {
            "command": "x",
            "workdir": "/tmp",
            "pid": 1,
            "started_at": 1.0,
            "exit_code": 0,
            "ended_at": 2.0,
        },
    )
    (store / ("d" * 12)).mkdir()  # no meta at all: ignored, not a crash
    checks = doctor.check_jobs(store)
    assert (
        checks[0].status == "ok"
        and "3 job(s), 1 running, 1 orphaned" in checks[0].detail
    )
    assert checks[1].status == "warn"


def test_jobs_unwritable_fails(tmp_path):
    store = tmp_path / "jobs"
    store.mkdir()
    store.chmod(0o500)
    try:
        if os.access(store, os.W_OK):
            pytest.skip("running as root; chmod does not restrict")
        (c,) = doctor.check_jobs(store)
        assert c.status == "fail"
    finally:
        store.chmod(0o700)


# -- journal -----------------------------------------------------------------


def test_journal_clean_ok():
    (c,) = doctor.check_journal(
        "u", "-1 hour", fetch=lambda u, s: "INFO fine\nINFO ok\n"
    )
    assert c.status == "ok"


def test_journal_errors_warn():
    text = "ERROR event=request_error\nTraceback (most recent call last):\n  x\n"
    (c,) = doctor.check_journal("u", "-1 hour", fetch=lambda u, s: text)
    assert c.status == "warn" and "1 error line(s) and 1 traceback(s)" in c.detail


def test_journal_unavailable_warns():
    def boom(u, s):
        raise SystemExit("journalctl failed")

    (c,) = doctor.check_journal("u", "-1 hour", fetch=boom)
    assert c.status == "warn"


# -- render ------------------------------------------------------------------


def test_render_exit_code_and_hints():
    checks = [
        doctor.ok("a", "fine"),
        doctor.warn("b", "meh", "do y"),
        doctor.fail("c", "broken", "do x"),
    ]
    text, code = doctor.render(checks)
    assert code == 1
    assert "[FAIL] c: broken" in text and "hint: do x" in text
    assert "hint: do y" in text
    assert text.endswith("1 ok, 1 warn, 1 fail")


def test_render_warn_only_exits_zero():
    _, code = doctor.render([doctor.warn("a", "meh")])
    assert code == 0


def test_render_json():
    text, code = doctor.render_json([doctor.fail("a", "x")])
    data = json.loads(text)
    assert code == 1 and data["exit_code"] == 1
    assert data["checks"][0] == {
        "group": "a",
        "status": "fail",
        "detail": "x",
        "hint": "",
    }


# -- uplink, poller, watchdog ------------------------------------------------
#
# These three are the checks the 2026-09-12 outage proved were missing:
# everything above them is local, and all of it was green for 48 minutes
# while ChatGPT could not reach the connector at all.


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
    monkeypatch.setattr(doctor.uplink, "default_routes", lambda run: routes)
    monkeypatch.setattr(doctor.uplink, "probe_all", lambda r, **kw: results)


WLAN1 = uplink.Route("wlan1", "192.168.50.1", "192.168.50.197", 100)
WLAN0 = uplink.Route("wlan0", "192.168.50.1", "192.168.50.222", 600)


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


# -- driver stability (external daily job) -----------------------------------


# -- the failure-case review (2026-09-13) ------------------------------------


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


def test_boot_check_wants_lingering():
    def on(*args, **kw):
        return subprocess.CompletedProcess(
            list(args), 0, stdout="Linger=yes\n", stderr=""
        )

    def off(*args, **kw):
        return subprocess.CompletedProcess(
            list(args), 0, stdout="Linger=no\n", stderr=""
        )

    (c,) = doctor.check_boot(on, user="pi")
    assert c.status == "ok" and "start at boot" in c.detail
    (c,) = doctor.check_boot(off, user="pi")
    assert c.status == "fail" and c.hint == "loginctl enable-linger pi"


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

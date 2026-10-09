"""Integration tests for Binnacle's command-line control surface.

Host-mutating boundaries such as systemctl, service setup, driver reloads,
and network probes are faked. The tests exercise user-visible command glue:
deployment setup, mode switching, diagnostics, watchdog controls, statistics,
and token rotation without changing the development Raspberry Pi.
"""

import subprocess

from binnacle import cli, doctor
from binnacle.platform.contracts.service_lifecycle_contracts import ServiceAction
from tests.service_fakes import FakeServiceController


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
    states = {cli.SERVER_UNIT: "active", cli.TUNNEL_UNIT: "active"}
    controller = FakeServiceController()
    monkeypatch.setattr(cli, "create_service_controller", lambda: controller)
    monkeypatch.setattr(cli, "_unit_state", lambda unit: states[unit])

    cli.rotate()

    assert f.read_text().startswith("Bearer ")
    assert f.read_text() != "old\n"
    assert controller.calls == [
        (cli.SERVER_UNIT, None),
        (cli.TUNNEL_UNIT, None),
    ]
    out = capsys.readouterr().out
    assert "wrote new token" in out
    assert f"restarted {cli.SERVER_UNIT}" in out
    assert f"restarted {cli.TUNNEL_UNIT}" in out


def test_rotate_attempts_all_active_units_and_fails_truthfully(
    tmp_path, monkeypatch, capsys
):
    f = tmp_path / "token"
    f.write_text("old\n")
    monkeypatch.setattr(cli, "TOKEN_FILE", f)
    states = {cli.SERVER_UNIT: "active", cli.TUNNEL_UNIT: "active"}
    controller = FakeServiceController(
        results={
            cli.SERVER_UNIT: ServiceAction(1, stderr="server boom"),
            cli.TUNNEL_UNIT: ServiceAction(0),
        }
    )
    monkeypatch.setattr(cli, "create_service_controller", lambda: controller)
    monkeypatch.setattr(cli, "_unit_state", lambda unit: states[unit])

    with pytest.raises(SystemExit) as exc:
        cli.rotate()

    assert exc.value.code == 1
    assert controller.calls == [
        (cli.SERVER_UNIT, None),
        (cli.TUNNEL_UNIT, None),
    ]
    out = capsys.readouterr().out
    assert f"failed to restart {cli.SERVER_UNIT}: server boom" in out
    assert f"restarted {cli.TUNNEL_UNIT}" in out
    assert f"restarted {cli.SERVER_UNIT}" not in out


def test_rotate_tunnel_failure_is_nonzero_after_server_success(
    tmp_path, monkeypatch, capsys
):
    f = tmp_path / "token"
    f.write_text("old\n")
    monkeypatch.setattr(cli, "TOKEN_FILE", f)
    states = {cli.SERVER_UNIT: "active", cli.TUNNEL_UNIT: "active"}
    controller = FakeServiceController(
        results={cli.TUNNEL_UNIT: ServiceAction(1, stderr="tunnel boom")}
    )
    monkeypatch.setattr(cli, "create_service_controller", lambda: controller)
    monkeypatch.setattr(cli, "_unit_state", lambda unit: states[unit])

    with pytest.raises(SystemExit) as exc:
        cli.rotate()

    assert exc.value.code == 1
    assert controller.calls == [
        (cli.SERVER_UNIT, None),
        (cli.TUNNEL_UNIT, None),
    ]
    out = capsys.readouterr().out
    assert f"restarted {cli.SERVER_UNIT}" in out
    assert f"failed to restart {cli.TUNNEL_UNIT}: tunnel boom" in out


# -- tunnel readiness wait (token rotate) -----------------------------------


import pytest

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


def test_doctor_passes_deployment_and_exit_code(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            serve=SimpleNamespace(host="127.0.0.1", port=8123),
            jobs=SimpleNamespace(socket_path=tmp_path / "jobs.sock"),
        ),
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
    assert seen["dep"].jobs_unit == cli.JOBS_UNIT
    assert seen["dep"].jobs_socket is not None
    assert capsys.readouterr().out.strip() == "healthy"


def test_stats_only_loads_webmin_history_when_requested(monkeypatch, capsys):
    from binnacle.observability import logstats
    from binnacle.observability.linux import webminstats

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


def test_stats_default_merges_mcp_and_jobs_journals(monkeypatch, capsys):
    from binnacle.observability import logstats

    seen = []
    monkeypatch.setattr(
        logstats,
        "fetch_journal",
        lambda unit, since, until: seen.append(unit) or "journal",
    )
    monkeypatch.setattr(logstats, "parse", lambda raw: ([], []))
    monkeypatch.setattr(logstats, "analyze", lambda records, startups: "analysis")
    monkeypatch.setattr(logstats, "render", lambda analysis: "USAGE")

    cli.stats(system_resources=False)
    assert seen == [("binnacle-mcp", cli.JOBS_UNIT)]
    assert "binnacle-mcp,binnacle-jobs.service" in capsys.readouterr().out


def test_stats_log_failure_remains_command_failure(monkeypatch):
    import pytest

    from binnacle.observability import logstats
    from binnacle.platform.contracts.service_log_contracts import ServiceLogError

    monkeypatch.setattr(
        logstats,
        "fetch_journal",
        lambda *args: (_ for _ in ()).throw(ServiceLogError("journalctl failed")),
    )

    with pytest.raises(SystemExit, match="journalctl failed"):
        cli.stats()


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

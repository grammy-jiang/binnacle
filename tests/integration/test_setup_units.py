"""`binnacle setup` and `binnacle mode` against a fake host: unit files under
a temporary directory, systemctl and loginctl recorded, the quiet gate faked."""

import subprocess
from types import SimpleNamespace

import pytest

from binnacle import cli, doctor, units


@pytest.fixture
def host(tmp_path, monkeypatch):
    unit_dir = tmp_path / "units"
    token = tmp_path / "config" / "token"
    monkeypatch.setattr(cli, "UNIT_DIR", unit_dir)
    monkeypatch.setattr(cli, "TOKEN_FILE", token)
    monkeypatch.setattr(cli, "TUNNEL_CONFIG", tmp_path / "tunnel.json")
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backups")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *args, **kw: (
            calls.append(args) or subprocess.CompletedProcess(list(args), 0, "", "")
        ),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **kw: (
            calls.append(tuple(argv)) or subprocess.CompletedProcess(argv, 0, "", "")
        ),
    )
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no tunnel-client
    monkeypatch.setattr(cli, "_unit_state", lambda unit: "active")
    exe = tmp_path / "venv" / "bin" / "binnacle"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(units, "resolve_executable", lambda name, **kw: exe)
    return SimpleNamespace(
        unit_dir=unit_dir,
        unit=unit_dir / cli.SERVER_UNIT,
        token=token,
        calls=calls,
        exe=exe,
        repo=tmp_path / "repo",
        tmp=tmp_path,
    )


def test_setup_dev_dry_run_writes_nothing_and_describes_the_plan(host, capsys):
    cli.setup(dev=host.repo, port=9999, dry_run=True)

    out = capsys.readouterr().out
    assert not host.token.exists() and not host.unit_dir.exists()
    assert "would generate bearer token" in out
    assert f"would write {host.unit} (dev mode)" in out
    assert "would systemctl --user daemon-reload" in out
    assert f"would systemctl --user enable --now {cli.SERVER_UNIT}" in out
    assert "dry run: nothing was changed" in out
    assert host.calls == []


def test_setup_dev_writes_a_marked_unit_and_runs_the_safe_boundaries(host, capsys):
    cli.setup(dev=host.repo, port=8123)

    text = host.unit.read_text()
    marker = units.read_marker(text)
    assert marker is not None and marker.owner == "binnacle"
    assert marker.params["mode"] == "dev" and marker.params["port"] == "8123"
    assert marker.params["repo"] == str(host.repo.resolve())
    assert (
        f"ExecStart={host.repo.resolve()}/.venv/bin/uvicorn binnacle.server:app "
        "--host 127.0.0.1 --port 8123 --reload --loop uvloop --http httptools\n"
    ) in text
    assert host.token.read_text().startswith("Bearer ")
    assert ("daemon-reload",) in host.calls
    assert ("enable", "--now", cli.SERVER_UNIT) in host.calls
    assert ("loginctl", "enable-linger") in host.calls
    out = capsys.readouterr().out
    assert "server side is configured" in out and "tunnel-client not found" in out
    drift = units.check_unit_drift(
        host.unit, "binnacle", cli.render_server_unit, "units", "binnacle setup"
    )
    assert drift[0].status == "ok"


def test_setup_prod_uses_the_installed_executable(host):
    cli.setup(port=8000)

    text = host.unit.read_text()
    assert f"ExecStart={host.exe} serve --host 127.0.0.1 --port 8000\n" in text
    assert "Restart=always" in text and "WorkingDirectory" not in text
    marker = units.read_marker(text)
    assert marker is not None and marker.params["mode"] == "prod"


def test_setup_reports_an_unchanged_unit(host, capsys):
    cli.setup(dev=host.repo, port=8000)
    capsys.readouterr()

    cli.setup(dev=host.repo, port=8000, dry_run=True)

    out = capsys.readouterr().out
    assert f"would keep {host.unit} (already what setup writes, dev mode)" in out
    assert "---" not in out


def test_setup_refuses_a_hand_written_unit_and_adopts_it_on_request(host, capsys):
    host.unit_dir.mkdir()
    host.unit.write_text("[Unit]\nDescription=hand written\n")

    with pytest.raises(SystemExit) as exc:
        cli.setup(dev=host.repo, port=8000, dry_run=True)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "refusing to overwrite" in out and "--adopt" in out
    assert "-Description=hand written" in out

    cli.setup(dev=host.repo, port=8000, adopt=True)

    out = capsys.readouterr().out
    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.params["mode"] == "dev"
    backups = list((host.tmp / "backups").iterdir())
    assert len(backups) == 1
    assert backups[0].read_text() == "[Unit]\nDescription=hand written\n"
    assert "restart it at a quiet moment: `binnacle mode dev`" in out


def test_setup_keeps_an_existing_token_and_tunnel_config(host, capsys, monkeypatch):
    host.token.parent.mkdir(parents=True)
    host.token.write_text("Bearer existing\n")
    (host.tmp / "tunnel.json").write_text("{}")
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: "/usr/bin/tunnel-client" if name == "tunnel-client" else None,
    )

    cli.setup(dev=host.repo, dry_run=True)

    out = capsys.readouterr().out
    assert f"would keep existing token at {host.token}" in out
    assert f"would keep existing tunnel config at {host.tmp / 'tunnel.json'}" in out


def test_setup_reports_an_executable_it_cannot_resolve(host, capsys, monkeypatch):
    def refuse(name, **kw):
        raise units.UnitError("cannot resolve the binnacle executable from 'x'")

    monkeypatch.setattr(units, "resolve_executable", refuse)

    with pytest.raises(SystemExit) as exc:
        cli.setup(port=8000, dry_run=True)

    assert exc.value.code == 1
    assert "cannot resolve the binnacle executable" in capsys.readouterr().out


# -- mode ---------------------------------------------------------------------


def quiet(monkeypatch, reasons: list[str] | None = None) -> None:
    monkeypatch.setattr(
        doctor, "server_busy_reasons", lambda unit, jobs_dir: reasons or []
    )


def test_mode_status_reports_the_marker(host, capsys):
    cli.mode("status")
    assert "not managed by `binnacle setup`" in capsys.readouterr().out

    host.unit_dir.mkdir()
    host.unit.write_text("# Managed by `binnacle setup`\n[Unit]\n")
    cli.mode("status")
    assert "pre-2026-09-20 marker" in capsys.readouterr().out

    cli.setup(dev=host.repo, port=8000)
    capsys.readouterr()
    cli.mode("status")
    out = capsys.readouterr().out
    assert (
        f"{cli.SERVER_UNIT}: active; dev mode (mode=dev, host=127.0.0.1, port=8000, repo="
        in out
    )


def test_mode_switch_rewrites_reloads_and_restarts_at_a_quiet_moment(
    host, capsys, monkeypatch
):
    cli.setup(dev=host.repo, port=8000)
    host.calls.clear()
    capsys.readouterr()
    quiet(monkeypatch)

    cli.mode("prod")

    text = host.unit.read_text()
    marker = units.read_marker(text)
    assert marker is not None and marker.params["mode"] == "prod"
    assert marker.params["repo"] == str(host.repo.resolve())
    assert f"{host.exe} serve --host 127.0.0.1 --port 8000" in text
    assert host.calls == [("daemon-reload",), ("restart", cli.SERVER_UNIT)]
    out = capsys.readouterr().out
    assert "-ExecStart=" in out and "+ExecStart=" in out
    assert f"prod mode: {cli.SERVER_UNIT} restarted and active." in out

    host.calls.clear()
    cli.mode("dev")  # the marker remembered the checkout: no --repo needed

    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.params["mode"] == "dev"
    assert host.calls == [("daemon-reload",), ("restart", cli.SERVER_UNIT)]


def test_mode_refuses_a_busy_moment_unless_forced(host, capsys, monkeypatch):
    cli.setup(dev=host.repo, port=8000)
    host.calls.clear()
    capsys.readouterr()
    quiet(
        monkeypatch,
        ["2 tool call(s) in the last 30s; a restart fails the calls in flight"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.mode("prod")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a quiet moment" in out and "2 tool call(s)" in out and "--force" in out
    assert host.calls == []
    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.params["mode"] == "dev"

    cli.mode("prod", force=True)
    assert ("restart", cli.SERVER_UNIT) in host.calls


def test_mode_needs_a_managed_unit_and_a_repo_for_dev(host, capsys, monkeypatch):
    with pytest.raises(SystemExit):
        cli.mode("dev")
    assert "not managed by `binnacle setup`" in capsys.readouterr().out

    cli.setup(port=8000)  # production from the start: no checkout known
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.mode("dev")
    assert "needs the checkout" in capsys.readouterr().out

    quiet(monkeypatch)
    cli.mode("dev", repo=host.repo)
    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.params["mode"] == "dev"


def test_mode_reports_a_failed_restart(host, capsys, monkeypatch):
    cli.setup(dev=host.repo, port=8000)
    capsys.readouterr()
    quiet(monkeypatch)

    def failing(*args, check=True):
        code = 1 if args[0] == "restart" else 0
        return subprocess.CompletedProcess(list(args), code, "", "boom")

    monkeypatch.setattr(cli, "_systemctl", failing)

    with pytest.raises(SystemExit) as exc:
        cli.mode("dev")

    assert exc.value.code == 1
    assert f"failed to restart {cli.SERVER_UNIT}: boom" in capsys.readouterr().out

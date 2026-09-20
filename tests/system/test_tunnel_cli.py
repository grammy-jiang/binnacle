"""The tunnel companion: unit rendering, setup (adopting the hand-written
unit), the gated restart, and the doctor's glue."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from binnacle import tunnel_cli as cli
from binnacle import tunnel_doctor, tunnel_unit, units

PARAMS = {
    "tunnel": "/opt/bin/tunnel-client",
    "profile_dir": "/home/me/.config/tunnel-client",
    "profile": "binnacle",
    "env_file": "/home/me/.config/tunnel-client/binnacle-tunnel.env",
    "url_file": "/home/me/.local/state/tunnel-client/health/binnacle.url",
    "server_unit": "binnacle-mcp.service",
    "home": "/home/me",
}


def test_tunnel_unit_renders_the_profile_and_waits_for_readiness():
    spec = tunnel_unit.tunnel_unit_spec(PARAMS)
    assert spec.name == "binnacle-tunnel.service" and spec.owner == "binnacle-tunnel"
    assert spec.params == PARAMS
    body = spec.body
    assert "Wants=binnacle-mcp.service\nAfter=binnacle-mcp.service\n" in body
    assert "WorkingDirectory=/home/me\n" in body
    assert (
        "EnvironmentFile=/home/me/.config/tunnel-client/binnacle-tunnel.env\n" in body
    )
    assert (
        "ExecStart=/opt/bin/tunnel-client run --profile-dir "
        "/home/me/.config/tunnel-client --profile binnacle\n"
    ) in body
    post = next(line for line in body.splitlines() if line.startswith("ExecStartPost="))
    assert "/readyz" in post and PARAMS["url_file"] in post
    assert "$$SECONDS" in post and post.endswith("exit 0'")  # bounded, never fails
    assert "Restart=always" in body


def test_tunnel_unit_needs_every_parameter_and_round_trips():
    partial = {k: v for k, v in PARAMS.items() if k not in ("env_file", "url_file")}
    with pytest.raises(units.UnitError, match="needs env_file, url_file"):
        tunnel_unit.tunnel_unit_spec(partial)
    text = tunnel_unit.render_tunnel_unit(PARAMS)
    marker = units.read_marker(text)
    assert marker is not None and marker.owner == "binnacle-tunnel"
    assert marker.params == PARAMS
    assert tunnel_unit.render_tunnel_unit(marker.params) == text


def test_profile_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(tunnel_unit.Path, "home", classmethod(lambda cls: tmp_path))
    base = tmp_path / ".config" / "tunnel-client"
    assert tunnel_unit.profile_dir() == base
    assert tunnel_unit.profile_config("x") == base / "x.yaml"
    assert tunnel_unit.profile_env_file("x") == base / "x-tunnel.env"


@pytest.fixture
def host(tmp_path, monkeypatch):
    unit_dir = tmp_path / "units"
    pdir = tmp_path / "profile"
    pdir.mkdir()
    url_file = tmp_path / "health" / "binnacle.url"
    (pdir / "binnacle.yaml").write_text(
        json.dumps(
            {
                "health": {"url_file": str(url_file)},
                "log": {"file": str(tmp_path / "tunnel.log")},
            }
        )
    )
    (pdir / "binnacle-tunnel.env").write_text("CONTROL_PLANE_API_KEY=x\n")
    exe = tmp_path / "bin" / "tunnel-client"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(units, "UNIT_DIR", unit_dir)
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(tunnel_unit, "profile_dir", lambda: pdir)
    monkeypatch.setattr(units, "resolve_executable", lambda name, **kw: exe)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda c: tmp_path))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *a, **k: (
            calls.append(a) or subprocess.CompletedProcess(list(a), 0, "", "")
        ),
    )
    monkeypatch.setattr(cli, "_unit_state", lambda unit: "active")
    return SimpleNamespace(
        unit=unit_dir / cli.TUNNEL_UNIT,
        pdir=pdir,
        exe=exe,
        calls=calls,
        tmp=tmp_path,
        url_file=url_file,
    )


def test_setup_dry_run_then_write(host, capsys):
    cli.setup(dry_run=True)
    out = capsys.readouterr().out
    assert f"would write {host.unit}" in out and "dry run: nothing was changed" in out
    assert not host.unit.exists() and host.calls == []

    cli.setup()

    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.owner == "binnacle-tunnel"
    assert marker.params["tunnel"] == str(host.exe)
    assert marker.params["url_file"] == str(host.url_file)
    assert marker.params["env_file"] == str(host.pdir / "binnacle-tunnel.env")
    assert marker.params["profile_dir"] == str(host.pdir)
    assert marker.params["server_unit"] == "binnacle-mcp.service"
    assert marker.params["home"] == str(host.tmp)
    assert ("daemon-reload",) in host.calls
    assert ("enable", "--now", cli.TUNNEL_UNIT) in host.calls
    assert "tunnel unit is configured" in capsys.readouterr().out
    drift = units.check_unit_drift(
        host.unit, "binnacle-tunnel", tunnel_unit.render_tunnel_unit, "tunnel", "x"
    )
    assert drift[0].status == "ok"


def test_setup_refuses_an_incomplete_profile(host, capsys):
    (host.pdir / "binnacle.yaml").write_text(json.dumps({"log": {"file": "x"}}))
    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    assert "no health.url_file" in capsys.readouterr().out

    (host.pdir / "binnacle.yaml").write_text("not json")
    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    assert "not readable JSON" in capsys.readouterr().out

    (host.pdir / "binnacle.yaml").unlink()
    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    assert "write it from your tunnel account" in capsys.readouterr().out


def test_setup_refuses_without_the_env_file_or_the_binary(host, capsys, monkeypatch):
    (host.pdir / "binnacle-tunnel.env").unlink()
    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    assert "environment file" in capsys.readouterr().out

    def refuse(name, **kw):
        raise units.UnitError("cannot resolve the tunnel-client executable from 'x'")

    monkeypatch.setattr(units, "resolve_executable", refuse)
    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    assert "cannot resolve the tunnel-client executable" in capsys.readouterr().out


def test_setup_adopts_the_hand_written_unit_and_reports_unchanged(host, capsys):
    host.unit.parent.mkdir()
    host.unit.write_text(
        "[Unit]\nDescription=Binnacle OpenAI MCP tunnel client\n"
        "After=binnacle-mcp.service binnacle-mcp-dev.service\n"
    )
    with pytest.raises(SystemExit) as exc:
        cli.setup(dry_run=True)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "refusing to overwrite" in out
    assert "-After=binnacle-mcp.service binnacle-mcp-dev.service" in out
    assert "+ExecStartPost=" in out

    cli.setup(adopt=True)

    out = capsys.readouterr().out
    marker = units.read_marker(host.unit.read_text())
    assert marker is not None and marker.owner == "binnacle-tunnel"
    assert len(list((host.tmp / "backups").iterdir())) == 1
    assert "restart it at a quiet moment: `binnacle-tunnel restart`" in out

    cli.setup(dry_run=True)
    assert (
        f"would keep {host.unit} (already what setup writes)" in capsys.readouterr().out
    )


def test_restart_waits_for_a_quiet_moment_unless_forced(host, capsys, monkeypatch):
    monkeypatch.setattr(
        tunnel_doctor,
        "tunnel_busy_reasons",
        lambda window_s, log_file=None: [
            "the tunnel forwarded a command 3 s ago; a restart drops its reply"
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.restart()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a quiet moment" in out and "3 s ago" in out and "--force" in out
    assert host.calls == []

    cli.restart(force=True)
    assert host.calls == [("restart", cli.TUNNEL_UNIT)]
    assert f"{cli.TUNNEL_UNIT} restarted in" in capsys.readouterr().out

    monkeypatch.setattr(
        tunnel_doctor, "tunnel_busy_reasons", lambda window_s, log_file=None: []
    )
    host.calls.clear()
    cli.restart(window_s=5)
    assert host.calls == [("restart", cli.TUNNEL_UNIT)]


def test_restart_reports_a_failed_restart(host, capsys, monkeypatch):
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *a, **k: subprocess.CompletedProcess(list(a), 1, "", "boom"),
    )
    with pytest.raises(SystemExit) as exc:
        cli.restart(force=True)
    assert exc.value.code == 1
    assert f"failed to restart {cli.TUNNEL_UNIT}: boom" in capsys.readouterr().out


def test_doctor_uses_companion_checks_and_core_renderers(monkeypatch, capsys):
    from binnacle import doctor as core_doctor

    monkeypatch.setattr(tunnel_doctor, "run_all", lambda: ["check"])
    monkeypatch.setattr(core_doctor, "render", lambda checks: ("tunnel healthy", 0))
    with pytest.raises(SystemExit) as exc:
        cli.doctor()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "tunnel healthy"

    monkeypatch.setattr(core_doctor, "render_json", lambda checks: ('{"ok": false}', 1))
    with pytest.raises(SystemExit) as exc:
        cli.doctor(as_json=True)
    assert exc.value.code == 1
    assert capsys.readouterr().out.strip() == '{"ok": false}'


def test_main_dispatches_the_app(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]

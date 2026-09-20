"""Deploy-time checks of the watchdog companion: may the unit be restarted
now (`quiet_moment`, `deploy-check`), and does `setup` write a marked unit
with an absolute path, adopt a hand-written one, and rewrite a legacy one.
The generic unit checks live in tests/unit/core/test_units.py."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import units
from binnacle import watchdog_cli as cli
from binnacle import watchdog_doctor as wdoc

UNIT = wdoc.WATCHDOG_UNIT


def companion(tmp_path: Path) -> Path:
    exe = tmp_path / "venv" / "bin" / "binnacle-watchdog"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def state(tmp_path: Path, **over) -> Path:
    f = tmp_path / "watchdog.json"
    data = {
        "last_cycle": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_grade": {"wlan0": "healthy", "wlan1": "healthy"},
        "demoted": {},
    }
    data.update(over)
    f.write_text(json.dumps(data))
    return f


def no_events(unit: str, since: str) -> list[str]:
    return [
        "2026-09-20T22:14:57+10:00 raspberrypi binnacle[1]: INFO: event=cycle cycle=1"
    ]


def test_quiet_when_nothing_is_in_flight(tmp_path):
    seen = []

    def journal(unit: str, since: str) -> list[str]:
        seen.append((unit, since))
        return no_events(unit, since)

    report = wdoc.quiet_moment(state(tmp_path), window_s=60, journal=journal)
    assert report.ok
    assert len(report.lines) == 4
    assert all(line.startswith("  [ok  ]") for line in report.lines)
    assert seen == [(UNIT, "-60s")]


def test_not_quiet_during_a_demotion(tmp_path):
    demoted = {"wlan1": {"kind": "wedged", "since": "2026-09-20T11:01:11+00:00"}}
    report = wdoc.quiet_moment(state(tmp_path, demoted=demoted), journal=no_events)
    assert not report.ok
    assert "demoted: wlan1 (wedged since 2026-09-20T11:01:11+00:00)" in report.lines[0]


def test_not_quiet_with_an_unhealthy_grade(tmp_path):
    grades = {"wlan1": "wedged", "wlan0": "healthy"}
    report = wdoc.quiet_moment(state(tmp_path, last_grade=grades), journal=no_events)
    assert not report.ok and "not healthy: wlan1=wedged" in report.lines[1]


def test_not_quiet_without_grades(tmp_path):
    report = wdoc.quiet_moment(state(tmp_path, last_grade={}), journal=no_events)
    assert not report.ok and "no grades" in report.lines[1]


def test_not_quiet_when_the_loop_is_stale(tmp_path):
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    f = state(tmp_path, last_cycle=old.isoformat(timespec="seconds"))
    report = wdoc.quiet_moment(f, stale_after_s=180, journal=no_events)
    assert not report.ok and "[wait] last cycle" in report.lines[2]


def test_not_quiet_with_an_unreadable_cycle_stamp(tmp_path):
    f = state(tmp_path, last_cycle="yesterday")
    report = wdoc.quiet_moment(f, journal=no_events)
    assert not report.ok and "unreadable" in report.lines[2]


def test_not_quiet_after_a_fast_failure(tmp_path):
    lines = [
        "... event=cycle cycle=5",
        (
            "2026-09-20T22:12:53+10:00 raspberrypi binnacle[1]: INFO: "
            "event=fast_failure cycle=18784 dev=wlan1 failures=1/4"
        ),
    ]
    report = wdoc.quiet_moment(state(tmp_path), journal=lambda unit, since: lines)
    assert not report.ok
    assert "1 failure or repair event(s)" in report.lines[3]
    assert "event=fast_failure cycle=18784 dev=wlan1" in report.lines[3]


def test_not_quiet_when_the_state_is_unreadable(tmp_path):
    report = wdoc.quiet_moment(tmp_path / "missing.json", journal=no_events)
    assert not report.ok and "unreadable" in report.lines[0]


def test_not_quiet_when_the_journal_cannot_be_read(tmp_path):
    def boom(unit: str, since: str) -> list[str]:
        raise subprocess.TimeoutExpired("journalctl", 120)

    report = wdoc.quiet_moment(state(tmp_path), journal=boom)
    assert not report.ok and "journal unreadable" in report.lines[3]


def test_deploy_check_exits_zero_when_quiet(tmp_path, monkeypatch, capsys):
    settings = SimpleNamespace(state_file=tmp_path / "wd.json", stale_after_s=180.0)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: settings)
    seen = []
    monkeypatch.setattr(
        wdoc,
        "quiet_moment",
        lambda *a: seen.append(a) or wdoc.QuietReport(True, ["  [ok  ] fine"]),
    )

    with pytest.raises(SystemExit) as exc:
        cli.deploy_check(window_s=45)

    assert exc.value.code == 0
    assert seen == [(settings.state_file, 45, 180.0, UNIT)]
    out = capsys.readouterr().out
    assert "quiet, a restart is safe now" in out and "[ok  ] fine" in out


def test_deploy_check_exits_one_when_not_quiet(tmp_path, monkeypatch, capsys):
    settings = SimpleNamespace(state_file=tmp_path / "wd.json", stale_after_s=180.0)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: settings)
    monkeypatch.setattr(
        wdoc,
        "quiet_moment",
        lambda *a: wdoc.QuietReport(False, ["  [wait] demoted: wlan1"]),
    )

    with pytest.raises(SystemExit) as exc:
        cli.deploy_check()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not quiet, wait" in out and "[wait] demoted: wlan1" in out


def test_setup_writes_the_resolved_absolute_path(tmp_path, monkeypatch):
    exe = companion(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(units.shutil, "which", lambda name: None)
    monkeypatch.setattr(units.sys, "argv", ["venv/bin/binnacle-watchdog", "setup"])
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(cli, "_systemctl", lambda *a, **k: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: None)

    cli.setup()

    text = (tmp_path / "units" / cli.WATCHDOG_UNIT).read_text()
    assert f"ExecStart={exe.resolve()} run" in text
    assert "ExecStart=venv/bin" not in text
    assert units.read_marker(text) == units.Marker(
        "binnacle-watchdog", {"watchdog": str(exe.resolve())}
    )


def test_setup_refuses_a_command_it_cannot_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(units.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        units.sys, "argv", [str(tmp_path / "no-such-binnacle-watchdog"), "setup"]
    )
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")

    with pytest.raises(SystemExit) as exc:
        cli.setup(dry_run=True)

    assert exc.value.code == 1
    assert "cannot resolve the binnacle-watchdog executable" in capsys.readouterr().out
    assert not (tmp_path / "units").exists()


def test_setup_adopts_a_hand_written_unit_and_rewrites_a_legacy_one(
    tmp_path, monkeypatch, capsys
):
    exe = companion(tmp_path)
    monkeypatch.setattr(units, "resolve_executable", lambda name, **kw: exe)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    unit = unit_dir / cli.WATCHDOG_UNIT
    unit.write_text("[Unit]\nDescription=hand written\n")
    monkeypatch.setattr(cli, "UNIT_DIR", unit_dir)
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(cli, "_systemctl", lambda *a, **k: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: None)

    with pytest.raises(SystemExit):
        cli.setup(dry_run=True)
    out = capsys.readouterr().out
    assert "refusing to overwrite" in out and "-Description=hand written" in out

    cli.setup(adopt=True)
    assert units.read_marker(unit.read_text()) == units.Marker(
        "binnacle-watchdog", {"watchdog": str(exe)}
    )
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    assert backups[0].read_text() == "[Unit]\nDescription=hand written\n"

    # The pre-2026-09-20 marker is ours: rewritten without --adopt.
    body = unit.read_text().split("\n", 1)[1]
    unit.write_text("# Managed by `binnacle setup`\n" + body)
    capsys.readouterr()
    cli.setup()
    assert units.read_marker(unit.read_text()).params == {"watchdog": str(exe)}
    assert f"rewrite {unit}" in capsys.readouterr().out


def test_watchdog_unit_renders_from_the_marker_parameters_and_needs_its_binary():
    from binnacle import watchdog_unit

    spec = watchdog_unit.watchdog_unit_spec({"watchdog": "/v/bin/binnacle-watchdog"})
    assert (
        spec.name == "binnacle-watchdog.service" and spec.owner == "binnacle-watchdog"
    )
    assert "ExecStart=/v/bin/binnacle-watchdog run\n" in spec.body
    assert "Environment=PATH=" in spec.body and "Restart=always" in spec.body
    text = watchdog_unit.render_watchdog_unit({"watchdog": "/v/bin/binnacle-watchdog"})
    marker = units.read_marker(text)
    assert marker == units.Marker(
        "binnacle-watchdog", {"watchdog": "/v/bin/binnacle-watchdog"}
    )
    assert watchdog_unit.render_watchdog_unit(marker.params) == text
    with pytest.raises(units.UnitError, match="needs the `watchdog` parameter"):
        watchdog_unit.watchdog_unit_spec({})

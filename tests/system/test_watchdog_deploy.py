"""Deploy-time checks of the watchdog companion: does the unit start the
command that exists, is the running process that command, may the unit be
restarted now, and does `setup` write a path systemd accepts."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import watchdog_cli as cli
from binnacle import watchdog_doctor as wdoc

UNIT = wdoc.WATCHDOG_UNIT


def companion(tmp_path: Path) -> Path:
    exe = tmp_path / "venv" / "bin" / "binnacle-watchdog"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def exec_start(*argv: str) -> str:
    return (
        f"{{ path={argv[0]} ; argv[]={' '.join(argv)} ; ignore_errors=no ; "
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
    )


def fake_show(props: dict[str, str]):
    def run(*args: str) -> subprocess.CompletedProcess:
        out = props.get(args[3], "") if args[0] == "show" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout=out + "\n", stderr="")

    return run


def test_exec_start_argv_parses_systemctl_show_output():
    line = exec_start("/v/bin/binnacle-watchdog", "run")
    assert wdoc.exec_start_argv(line) == ["/v/bin/binnacle-watchdog", "run"]
    assert wdoc.exec_start_argv("") == []
    assert wdoc.exec_start_argv("{ path=/x ; ignore_errors=no }") == []


def test_proc_cmdline_reads_this_process():
    argv = wdoc.proc_cmdline(os.getpid())
    assert argv and "python" in Path(argv[0]).name


def test_unit_command_ok_when_the_process_is_the_unit_command(tmp_path):
    exe = companion(tmp_path)
    run = fake_show({"ExecStart": exec_start(str(exe), "run"), "MainPID": "4242"})
    checks = wdoc.check_unit_command(
        UNIT, run=run, cmdline=lambda pid: ["/v/bin/python3", str(exe), "run"]
    )
    assert [c.status for c in checks] == ["ok"]
    assert "pid 4242 is that command" in checks[0].detail


def test_unit_command_warns_when_the_process_predates_the_unit(tmp_path):
    exe = companion(tmp_path)
    run = fake_show({"ExecStart": exec_start(str(exe), "run"), "MainPID": "1196"})
    old = ["/v/bin/python3", "/v/bin/binnacle", "watchdog", "run"]
    checks = wdoc.check_unit_command(UNIT, run=run, cmdline=lambda pid: old)
    assert checks[0].status == "warn"
    assert "binnacle watchdog run" in checks[0].detail
    assert "deploy-check" in checks[0].hint


def test_unit_command_fails_on_the_pre_split_command():
    props = {
        "ExecStart": exec_start("/v/bin/binnacle", "watchdog", "run"),
        "MainPID": "1196",
    }
    checks = wdoc.check_unit_command(UNIT, run=fake_show(props), cmdline=lambda pid: [])
    assert checks[0].status == "fail"
    assert "will not come back after a restart" in checks[0].detail
    assert "setup" in checks[0].hint


def test_unit_command_fails_when_the_executable_is_missing(tmp_path):
    missing = tmp_path / "gone" / "binnacle-watchdog"
    props = {"ExecStart": exec_start(str(missing), "run"), "MainPID": "0"}
    checks = wdoc.check_unit_command(UNIT, run=fake_show(props), cmdline=lambda pid: [])
    assert checks[0].status == "fail"
    assert "missing or not executable" in checks[0].detail


def test_unit_command_fails_without_exec_start():
    props = {
        "ExecStart": "",
        "LoadError": 'org.freedesktop.DBus.Error.FileNotFound "No such file"',
    }
    checks = wdoc.check_unit_command(UNIT, run=fake_show(props), cmdline=lambda pid: [])
    assert checks[0].status == "fail"
    assert "no ExecStart" in checks[0].detail and "No such file" in checks[0].detail


def test_unit_command_ok_when_the_unit_is_not_running(tmp_path):
    exe = companion(tmp_path)
    props = {"ExecStart": exec_start(str(exe), "run"), "MainPID": "0"}

    def no_pid(pid: int) -> list[str]:
        raise AssertionError("no pid to read")

    checks = wdoc.check_unit_command(UNIT, run=fake_show(props), cmdline=no_pid)
    assert [c.status for c in checks] == ["ok"]


def test_unit_command_warns_when_the_cmdline_is_unreadable(tmp_path):
    exe = companion(tmp_path)
    props = {"ExecStart": exec_start(str(exe), "run"), "MainPID": "77"}

    def boom(pid: int) -> list[str]:
        raise OSError("gone")

    checks = wdoc.check_unit_command(UNIT, run=fake_show(props), cmdline=boom)
    assert checks[0].status == "warn" and "pid 77" in checks[0].detail


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
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["venv/bin/binnacle-watchdog", "setup"])
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(cli, "_systemctl", lambda *a: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: None)

    cli.setup()

    text = (tmp_path / "units" / cli.WATCHDOG_UNIT).read_text()
    assert f"ExecStart={exe.resolve()} run" in text
    assert "ExecStart=venv/bin" not in text


def test_setup_refuses_a_command_it_cannot_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        sys, "argv", [str(tmp_path / "no-such-binnacle-watchdog"), "setup"]
    )
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")

    with pytest.raises(SystemExit) as exc:
        cli.setup(dry_run=True)

    assert exc.value.code == 1
    assert "cannot resolve the binnacle-watchdog executable" in capsys.readouterr().out
    assert not (tmp_path / "units").exists()

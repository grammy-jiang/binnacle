"""Tests for the host-specific watchdog companion CLI."""

import time
from types import SimpleNamespace

import pytest

from binnacle import watchdog_cli as cli


def test_pause_and_resume_manage_only_pause_file(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state" / "watchdog.json"
    settings = SimpleNamespace(state_file=state_file)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: settings)
    monkeypatch.setattr(time, "time", lambda: 1_000.0)

    cli.pause(2.5)
    pause_file = state_file.with_suffix(".pause")
    assert pause_file.read_text() == "1150\n"
    assert "paused for 2.5 min" in capsys.readouterr().out

    cli.resume()
    assert not pause_file.exists()
    assert "watchdog resumed" in capsys.readouterr().out


def test_resume_when_not_paused_is_idempotent(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "watchdog.json"
    settings = SimpleNamespace(state_file=state_file)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: settings)

    cli.resume()

    assert "watchdog was not paused" in capsys.readouterr().out


def test_reload_driver_plan_never_calls_mutating_reload(monkeypatch, capsys):
    from binnacle import watchdog as wd

    monkeypatch.setattr(wd, "driver_of", lambda dev: ("mmc1:0001:1", "brcmfmac"))
    monkeypatch.setattr(wd, "driver_module_of", lambda dev: ("brcmfmac", ["brcmutil"]))
    monkeypatch.setattr(
        wd,
        "driver_reload",
        lambda dev: (_ for _ in ()).throw(AssertionError("mutating reload called")),
    )

    cli.reload_driver("wlan0", apply=False)

    out = capsys.readouterr().out
    assert "module brcmfmac" in out
    assert "plan only" in out


def test_status_without_default_route_exits_before_probing(monkeypatch, capsys):
    from binnacle import uplink as up

    monkeypatch.setattr(up, "default_routes", list)
    monkeypatch.setattr(
        up,
        "probe_all",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("probe called")),
    )

    with pytest.raises(SystemExit) as exc:
        cli.status()

    assert exc.value.code == 1
    assert "no default route" in capsys.readouterr().out


def test_setup_dry_run_owns_only_watchdog_unit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: "/usr/bin/binnacle-watchdog",
    )

    cli.setup(dry_run=True)

    out = capsys.readouterr().out
    unit = tmp_path / "units" / cli.WATCHDOG_UNIT
    assert f"would write {unit}" in out
    assert "would systemctl --user daemon-reload" in out
    assert f"would systemctl --user enable --now {cli.WATCHDOG_UNIT}" in out
    assert "dry run: nothing was changed" in out
    assert not (tmp_path / "units").exists()


def test_setup_refuses_foreign_watchdog_unit(tmp_path, monkeypatch, capsys):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    unit = unit_dir / cli.WATCHDOG_UNIT
    unit.write_text("[Service]\nExecStart=/something/else\n")
    monkeypatch.setattr(cli, "UNIT_DIR", unit_dir)

    with pytest.raises(SystemExit) as exc:
        cli.setup(dry_run=True)

    assert exc.value.code == 1
    assert "refusing to overwrite" in capsys.readouterr().out


def test_doctor_uses_companion_checks_and_core_renderer(monkeypatch, capsys):
    from binnacle import doctor as core_doctor
    from binnacle import watchdog_doctor

    seen = []
    monkeypatch.setattr(
        watchdog_doctor,
        "run_all",
        lambda probe=True: seen.append(probe) or ["check"],
    )
    monkeypatch.setattr(core_doctor, "render", lambda checks: ("watchdog healthy", 0))

    with pytest.raises(SystemExit) as exc:
        cli.doctor(probe=False)

    assert exc.value.code == 0
    assert seen == [False]
    assert capsys.readouterr().out.strip() == "watchdog healthy"

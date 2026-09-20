"""Tests for the host-specific watchdog companion CLI."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import watchdog_cli as cli


def companion(tmp_path: Path) -> Path:
    """A stand-in for the installed binnacle-watchdog console script."""
    exe = tmp_path / "venv" / "bin" / "binnacle-watchdog"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


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
        lambda name: str(companion(tmp_path)),
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


def test_setup_real_path_writes_only_watchdog_unit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(companion(tmp_path)))
    systemctl = []
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *args, **kwargs: systemctl.append(args),
    )
    loginctl = []
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **kwargs: loginctl.append(argv),
    )

    cli.setup(dry_run=False)

    unit = tmp_path / "units" / cli.WATCHDOG_UNIT
    assert unit.exists()
    assert "binnacle-watchdog run" in unit.read_text()
    assert ("daemon-reload",) in systemctl
    assert ("enable", "--now", cli.WATCHDOG_UNIT) in systemctl
    assert loginctl == [["loginctl", "enable-linger"]]
    assert "watchdog service is configured" in capsys.readouterr().out


def test_doctor_json_uses_json_renderer(monkeypatch, capsys):
    from binnacle import doctor as core_doctor
    from binnacle import watchdog_doctor

    monkeypatch.setattr(watchdog_doctor, "run_all", lambda probe=True: ["check"])
    monkeypatch.setattr(core_doctor, "render_json", lambda checks: ('{"ok": true}', 1))

    with pytest.raises(SystemExit) as exc:
        cli.doctor(probe=True, as_json=True)

    assert exc.value.code == 1
    assert capsys.readouterr().out.strip() == '{"ok": true}'


def test_run_maps_watchdog_configuration_and_once_to_lifecycle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import watchdog as wd
    from binnacle.watchdog_config import WatchdogSettings

    cfg = WatchdogSettings(state_file=tmp_path / "state.json", interval_s=17.0)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: cfg)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(serve=SimpleNamespace(host="127.0.0.2", port=8123)),
    )
    seen = {}

    def fake_forever(state_file, **kwargs):
        seen.update(state_file=state_file, **kwargs)

    monkeypatch.setattr(wd, "run_forever", fake_forever)

    override = tmp_path / "override.json"
    cli.run(interval=2.5, once=True, dry_run=True, state_file=override)

    assert seen["state_file"] == override
    assert seen["interval_s"] == 2.5
    assert seen["host"] == cfg.upstream_host
    assert seen["timeout"] == cfg.probe_timeout_s
    assert seen["max_cycles"] == 1
    policy = seen["policy"]
    assert policy.dry_run is True
    assert policy.mcp_url == "http://127.0.0.2:8123/mcp"
    assert policy.mcp_units == (cli.PROD_UNIT, cli.DEV_UNIT)
    assert policy.pause_file == cfg.state_file.with_suffix(".pause")


def test_run_uses_configured_interval_cycles_and_state_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import watchdog as wd
    from binnacle.watchdog_config import WatchdogSettings

    cfg = WatchdogSettings(state_file=tmp_path / "state.json", interval_s=19.0)
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: cfg)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(serve=SimpleNamespace(host="127.0.0.1", port=8000)),
    )
    seen = {}
    monkeypatch.setattr(
        wd,
        "run_forever",
        lambda state_file, **kwargs: seen.update(state_file=state_file, **kwargs),
    )

    cli.run(cycles=3)

    assert seen["state_file"] == cfg.state_file
    assert seen["interval_s"] == 19.0
    assert seen["max_cycles"] == 3


def test_usb_reset_plan_and_apply_paths(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from binnacle import watchdog as wd

    cfg = SimpleNamespace(
        usb_reset_ids=("abcd:1234",),
        usb_reset_schedule=((0, 60.0),),
        usb_reset_methods=("authorized",),
        state_file=tmp_path / "state.json",
    )
    state = wd.State()
    state.usb_attempts["wlan9"] = 2
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: cfg)
    monkeypatch.setattr(wd.State, "load", classmethod(lambda cls, path: state))
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: ("1-2", "abcd:1234"))
    monkeypatch.setattr(wd, "usb_devfs_path", lambda node: tmp_path / "usbdev")
    calls = []
    monkeypatch.setattr(
        wd,
        "usb_reset_device",
        lambda dev, policy, method: calls.append((dev, method)) or (True, "reset"),
    )

    cli.usb_reset("wlan9", apply=False)
    assert calls == []
    assert "plan only" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        cli.usb_reset("wlan9", apply=True, method="authorized")
    assert exc.value.code == 0
    assert calls == [("wlan9", "authorized")]
    assert "ok: reset" in capsys.readouterr().out


def test_usb_reset_apply_failure_exits_one(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import watchdog as wd

    cfg = SimpleNamespace(
        usb_reset_ids=(),
        usb_reset_schedule=((0, 60.0),),
        usb_reset_methods=("authorized",),
        state_file=tmp_path / "state.json",
    )
    monkeypatch.setattr(cli, "get_watchdog_settings", lambda: cfg)
    monkeypatch.setattr(wd.State, "load", classmethod(lambda cls, path: wd.State()))
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    monkeypatch.setattr(wd, "usb_reset_device", lambda *a, **k: (False, "denied"))

    with pytest.raises(SystemExit) as exc:
        cli.usb_reset("wlan9", apply=True)

    assert exc.value.code == 1


def test_history_uses_tunnel_poll_window_when_log_exists(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from binnacle import watchlog

    tunnel_log = tmp_path / "tunnel.log"
    tunnel_log.write_text("log")
    monkeypatch.setattr(
        cli,
        "get_watchdog_settings",
        lambda: SimpleNamespace(tunnel_log=tunnel_log),
    )
    monkeypatch.setattr(watchlog, "fetch_journal", lambda *a: "journal")
    monkeypatch.setattr(watchlog, "parse", lambda lines: ["event"])
    monkeypatch.setattr(watchlog, "window_of", lambda events: (10.0, 20.0))
    monkeypatch.setattr(
        watchlog,
        "tunnel_polls",
        lambda path, start, end: ["poll"],
    )
    monkeypatch.setattr(
        watchlog,
        "render",
        lambda events, verbose, polls: f"{events}:{verbose}:{polls}",
    )

    cli.history(verbose=True)

    assert "['event']:True:['poll']" in capsys.readouterr().out


def test_history_skips_poll_matching_without_window(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from binnacle import watchlog

    monkeypatch.setattr(
        cli,
        "get_watchdog_settings",
        lambda: SimpleNamespace(tunnel_log=tmp_path / "missing.log"),
    )
    monkeypatch.setattr(watchlog, "fetch_journal", lambda *a: "")
    monkeypatch.setattr(watchlog, "parse", lambda lines: [])
    monkeypatch.setattr(watchlog, "window_of", lambda events: None)
    monkeypatch.setattr(watchlog, "render", lambda events, verbose, polls: str(polls))

    cli.history()

    assert capsys.readouterr().out.strip() == "None"


def test_reload_driver_apply_success_and_failure(monkeypatch):
    from binnacle import watchdog as wd

    monkeypatch.setattr(wd, "driver_of", lambda dev: ("node", "driver"))
    monkeypatch.setattr(wd, "driver_module_of", lambda dev: ("module", []))
    monkeypatch.setattr(wd, "driver_reload", lambda dev: (True, "done"))

    with pytest.raises(SystemExit) as exc:
        cli.reload_driver("wlan0", apply=True)
    assert exc.value.code == 0

    monkeypatch.setattr(wd, "driver_reload", lambda dev: (False, "failed"))
    with pytest.raises(SystemExit) as exc:
        cli.reload_driver("wlan0", apply=True)
    assert exc.value.code == 1


def test_status_renders_routes_devices_preferences_and_issues(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    from binnacle import uplink as up
    from binnacle import watchdog as wd

    routes = [
        up.Route("wlan1", "gw", "10.0.0.2", 100),
        up.Route("wlan2", "gw", "10.0.0.3", 200),
    ]
    probes = {
        "wlan1": up.ProbeResult(
            "wlan1",
            layers={"gateway": True, "dns": True, "tcp": True},
        ),
        "wlan2": up.ProbeResult(
            "wlan2",
            layers={"gateway": False, "dns": False, "tcp": False},
            errors={"tcp": "dead"},
        ),
    }
    state = wd.State()
    state.demoted["wlan2"] = wd.Demotion(
        "wlan2",
        "slow",
        200,
        "2026-09-20T00:00:00+00:00",
        "wedged",
    )
    state.usb_best_speed["wlan1"] = 5000
    state.usb_speed_attempts["wlan1"] = 2
    state.prefer_attempts["wlan1"] = 1
    state.issues["wlan2"] = "wedged"

    monkeypatch.setattr(
        cli,
        "get_watchdog_settings",
        lambda: SimpleNamespace(
            upstream_host="api.example",
            probe_timeout_s=1.0,
            state_file=tmp_path / "state.json",
            usb_reset_ids=("id",),
        ),
    )
    monkeypatch.setattr(up, "default_routes", lambda: routes)
    monkeypatch.setattr(up, "probe_all", lambda *a, **k: probes)
    monkeypatch.setattr(wd.State, "load", classmethod(lambda cls, path: state))
    monkeypatch.setattr(
        wd,
        "observe_devices",
        lambda **kwargs: {
            "wlan1": wd.DeviceInfo(
                "wlan1",
                "connected",
                profile="slow",
                usb_speed=480,
            )
        },
    )
    monkeypatch.setattr(
        wd,
        "preferences",
        lambda devs, rescan_for=(): {
            "wlan1": wd.Preference("wlan1", "slow", "fast", visible=False),
            "wlan2": wd.Preference("wlan2", "best", None, visible=False),
        },
    )

    cli.status(rescan=False)

    out = capsys.readouterr().out
    assert "uplink status (upstream api.example)" in out
    assert "[ok" in out
    assert "WEDGED" in out
    assert "[demoted]" in out
    assert "cached scan" in out
    assert "highest-priority profile" in out
    assert "USB link resets so far 2" in out
    assert "below the highest level" in out


def test_main_dispatches_watchdog_app(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))

    cli.main()

    assert called == [True]

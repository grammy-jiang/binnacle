"""Diagnostics tests owned by the host-specific watchdog companion."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from binnacle import doctor, watchdog_doctor


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


def watchdog_state(tmp_path, **over) -> Path:
    f = tmp_path / "watchdog.json"
    data = {
        "last_cycle": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_summary": {"wlan1": "gateway=ok dns=ok tcp=ok"},
        "demoted": {},
        "last_reset": {},
    }
    data.update(over)
    f.write_text(json.dumps(data))
    return f


def test_watchdog_ok_when_active_and_recent(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service", watchdog_state(tmp_path), run=run
    )
    assert statuses(checks) == ["ok", "ok"]


def test_watchdog_warns_when_not_running(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "inactive"})
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service", watchdog_state(tmp_path), run=run
    )
    assert checks[0].status == "warn" and "will not fail over" in checks[0].detail


def test_watchdog_warns_on_a_stale_cycle(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(
        timespec="seconds"
    )
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service",
        watchdog_state(tmp_path, last_cycle=old),
        stale_after_s=180,
        run=run,
    )
    assert checks[1].status == "warn" and "may be stuck" in checks[1].detail


def test_watchdog_reports_a_route_it_has_demoted(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    state = watchdog_state(
        tmp_path,
        demoted={
            "wlan1": {
                "dev": "wlan1",
                "profile": "Occom-USB",
                "original_metric": 100,
                "since": "2026-09-12T01:00:00+00:00",
                "reason": "wedged for 3 cycles",
            }
        },
    )
    checks = watchdog_doctor.check_watchdog("binnacle-watchdog.service", state, run=run)
    demoted = [c for c in checks if "demoted" in c.detail]
    assert demoted and demoted[0].status == "warn"
    assert "restored automatically" in demoted[0].hint


def test_watchdog_shows_profiles_and_a_preference_move(tmp_path):
    """2026-09-13: wlan1 sat on its 2.4 GHz profile for 24 h and nothing
    showed it; the state now carries each route's profile and band, and a
    preference move is a demotion of its own kind."""
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    state = watchdog_state(
        tmp_path,
        last_profiles={"wlan1": "Occom-USB (2.4 GHz)", "wlan0": "Occom (5 GHz)"},
        demoted={
            "wlan1": {
                "dev": "wlan1",
                "profile": "Occom-USB",
                "original_metric": 100,
                "since": "2026-09-13T11:00:00+00:00",
                "reason": "moving to preferred profile Occom-5G-USB (attempt 1)",
                "kind": "preference",
                "target": "Occom-5G-USB",
                "target_metric": 100,
                "since_ts": 0.0,
            }
        },
    )
    checks = watchdog_doctor.check_watchdog("binnacle-watchdog.service", state, run=run)
    profiles = [c for c in checks if c.detail.startswith("profiles:")]
    assert profiles and profiles[0].status == "ok"
    assert "wlan1 on Occom-USB (2.4 GHz)" in profiles[0].detail
    move = [c for c in checks if "moves to profile Occom-5G-USB" in c.detail]
    assert move and move[0].status == "warn" and "new profile" in move[0].hint


def test_watchdog_reports_levels_and_warns_on_issues(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    state = watchdog_state(
        tmp_path,
        last_devices={
            "wlan1": "connected Occom-USB 5 GHz 80 MHz 867 Mbit/s usb 480 (best 5000)"
        },
        issues={"wlan1": "USB link 480 Mbit/s, best seen 5000"},
    )
    checks = watchdog_doctor.check_watchdog("binnacle-watchdog.service", state, run=run)
    levels = [c for c in checks if c.detail.startswith("levels:")]
    assert (
        levels
        and levels[0].status == "ok"
        and "usb 480 (best 5000)" in levels[0].detail
    )
    issue = [c for c in checks if "below its highest level" in c.detail]
    assert issue and issue[0].status == "warn" and "best seen 5000" in issue[0].detail


def test_watchdog_warns_without_state(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service", tmp_path / "nope.json", run=run
    )
    assert checks[1].status == "warn" and "no cycle has completed" in checks[1].detail


def stability_ledger(
    tmp_path, *, clean="1", streak="3", baseline="0", age_s=3600.0, now=1_800_000_000.0
):
    log = tmp_path / "stability.log"
    epoch = int(now - age_s)
    log.write_text(
        "2026-09-13 03:30:01 epoch=1799990000 mode=sample clean=1 streak=2 baseline=0 verdict=OK\n"
        f"2026-09-14 03:30:01 epoch={epoch} mode=sample boot=abcd1234 usbmode=1 usb=5000 "
        f"assoc=1 primary=1 rtw_err=0 usb_fault=0 demoted=0 clean={clean} streak={streak} "
        f"baseline={baseline} verdict=OK\n"
    )
    return log


def test_driver_stability_is_skipped_without_the_job(tmp_path):
    assert (
        watchdog_doctor.check_driver_stability(
            tmp_path / "none.log", tmp_path / "s.env"
        )
        == []
    )


def test_driver_stability_ok_reports_the_streak(tmp_path):
    now = 1_800_000_000.0
    log = stability_ledger(tmp_path, now=now)
    (c,) = watchdog_doctor.check_driver_stability(
        log, tmp_path / "s.env", now=lambda: now
    )
    assert c.status == "ok" and "streak 3/7" in c.detail and "mode 0" in c.detail


def test_driver_stability_reports_promotion(tmp_path):
    now = 1_800_000_000.0
    log = stability_ledger(tmp_path, streak="7", baseline="1", now=now)
    state = tmp_path / "s.env"
    state.write_text(
        "PROMOTED_TS=1799999000\nPROMOTED_MODE=1\nLAST_BREAK_TS=0\nLAST_BREAK_REASON=-\n"
    )
    (c,) = watchdog_doctor.check_driver_stability(log, state, now=lambda: now)
    assert c.status == "ok" and "promoted" in c.detail


def test_driver_stability_warns_on_a_broken_sample(tmp_path):
    now = 1_800_000_000.0
    log = stability_ledger(tmp_path, clean="0", streak="0", now=now)
    (c,) = watchdog_doctor.check_driver_stability(
        log, tmp_path / "s.env", now=lambda: now
    )
    assert c.status == "warn" and "broken" in c.detail and "rtw_err=0" in c.detail


def test_driver_stability_warns_when_the_job_stopped_running(tmp_path):
    now = 1_800_000_000.0
    log = stability_ledger(tmp_path, age_s=48 * 3600, now=now)
    checks = watchdog_doctor.check_driver_stability(
        log, tmp_path / "s.env", stale_after_h=36, now=lambda: now
    )
    assert checks[0].status == "warn" and "48 h old" in checks[0].detail
    assert checks[1].status == "ok"  # the sample itself was clean


def test_driver_stability_warns_on_an_empty_ledger(tmp_path):
    log = tmp_path / "stability.log"
    log.write_text("2026-09-13 03:30:01 epoch=1 mode=test clean=1\n")
    (c,) = watchdog_doctor.check_driver_stability(log, tmp_path / "s.env")
    assert c.status == "warn" and "no sample" in c.detail


def test_watchdog_reports_usb_reset_attempts_on_a_demoted_route(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    state = watchdog_state(
        tmp_path,
        demoted={
            "wlan1": {
                "dev": "wlan1",
                "profile": "Occom-USB",
                "original_metric": 100,
                "since": "2026-09-12T10:52:54+00:00",
                "reason": "wedged for 3 cycles",
            }
        },
        usb_attempts={"wlan1": 4},
    )
    checks = watchdog_doctor.check_watchdog("binnacle-watchdog.service", state, run=run)
    demoted = [c for c in checks if "demoted" in c.detail]
    assert demoted and "4 USB re-enumeration(s)" in demoted[0].detail


def test_privileges_ok_when_sudo_n_works():
    def run(*args, **kw):
        return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

    (c,) = watchdog_doctor.check_privileges(run)
    assert c.status == "ok" and "sudo -n works" in c.detail


def test_privileges_fail_when_sudo_n_is_refused():
    def run(*args, **kw):
        return subprocess.CompletedProcess(
            list(args), 1, stdout="", stderr="a password is required"
        )

    (c,) = watchdog_doctor.check_privileges(run)
    assert c.status == "fail" and "NOPASSWD" in c.hint


def test_pause_check_reports_an_active_pause_only(tmp_path):
    pause = tmp_path / "watchdog.pause"
    assert watchdog_doctor.check_pause(pause) == []
    pause.write_text("1\n")
    assert watchdog_doctor.check_pause(pause) == []  # expired
    import time

    pause.write_text(f"{time.time() + 300:.0f}\n")
    (c,) = watchdog_doctor.check_pause(pause)
    assert c.status == "warn" and "paused until" in c.detail


def test_watchdog_warns_when_the_fast_heartbeat_is_stale(tmp_path):
    run = fake_systemctl({"binnacle-watchdog.service": "active"})
    now = datetime.now(timezone.utc).timestamp()
    stale = watchdog_state(tmp_path, fast_last=now - 600)
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service", stale, run=run, fast_interval_s=5.0
    )
    assert any(c.status == "warn" and "fast path heartbeat" in c.detail for c in checks)
    fresh = watchdog_state(tmp_path, fast_last=now - 3)
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service", fresh, run=run, fast_interval_s=5.0
    )
    assert not any("fast path" in c.detail for c in checks)
    # the fast path off, or a state file without a heartbeat: not judged
    checks = watchdog_doctor.check_watchdog("binnacle-watchdog.service", stale, run=run)
    assert not any("fast path" in c.detail for c in checks)
    checks = watchdog_doctor.check_watchdog(
        "binnacle-watchdog.service",
        watchdog_state(tmp_path),
        run=run,
        fast_interval_s=5.0,
    )
    assert not any("fast path" in c.detail for c in checks)


def test_run_all_composes_host_specific_checks(tmp_path, monkeypatch):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        upstream_host="api.example.test",
        probe_timeout_s=1.5,
        dns_fallback="9.9.9.9",
        state_file=tmp_path / "watchdog.json",
        stale_after_s=123.0,
        fast_interval_s=5.0,
        stability_log=tmp_path / "stability.log",
        stability_state=tmp_path / "stability.env",
        stability_stale_after_h=48.0,
    )
    monkeypatch.setattr(watchdog_doctor, "get_watchdog_settings", lambda: settings)

    calls = []
    monkeypatch.setattr(
        watchdog_doctor,
        "check_uplink",
        lambda **kw: calls.append(("uplink", kw)) or [doctor.ok("uplink", "ok")],
    )
    monkeypatch.setattr(
        watchdog_doctor,
        "check_watchdog",
        lambda *args, **kw: (
            calls.append(("watchdog", args, kw)) or [doctor.ok("watchdog", "ok")]
        ),
    )
    monkeypatch.setattr(
        watchdog_doctor,
        "check_pause",
        lambda path: calls.append(("pause", path)) or [],
    )
    monkeypatch.setattr(
        watchdog_doctor,
        "check_privileges",
        lambda: calls.append(("privileges",)) or [doctor.ok("privileges", "ok")],
    )
    monkeypatch.setattr(
        watchdog_doctor,
        "check_driver_stability",
        lambda *args: calls.append(("driver", args)) or [],
    )

    checks = watchdog_doctor.run_all()

    assert [c.group for c in checks] == ["uplink", "watchdog", "privileges"]
    assert calls[0] == (
        "uplink",
        {
            "host": "api.example.test",
            "timeout": 1.5,
            "fallback_nameserver": "9.9.9.9",
        },
    )
    assert calls[1][1][0] == watchdog_doctor.WATCHDOG_UNIT
    assert calls[2] == ("pause", settings.state_file.with_suffix(".pause"))
    assert calls[-1] == (
        "driver",
        (
            settings.stability_log,
            settings.stability_state,
            settings.stability_stale_after_h,
        ),
    )


def test_run_all_can_skip_network_probe(tmp_path, monkeypatch):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        state_file=tmp_path / "watchdog.json",
        stale_after_s=123.0,
        fast_interval_s=5.0,
        stability_log=tmp_path / "stability.log",
        stability_state=tmp_path / "stability.env",
        stability_stale_after_h=48.0,
    )
    monkeypatch.setattr(watchdog_doctor, "get_watchdog_settings", lambda: settings)
    monkeypatch.setattr(
        watchdog_doctor,
        "check_uplink",
        lambda **kw: (_ for _ in ()).throw(AssertionError("uplink called")),
    )
    monkeypatch.setattr(watchdog_doctor, "check_watchdog", lambda *a, **k: [])
    monkeypatch.setattr(watchdog_doctor, "check_pause", lambda *a: [])
    monkeypatch.setattr(watchdog_doctor, "check_privileges", list)
    monkeypatch.setattr(watchdog_doctor, "check_driver_stability", lambda *a: [])

    assert watchdog_doctor.run_all(probe=False) == []

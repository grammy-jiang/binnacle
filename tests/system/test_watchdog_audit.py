"""Audit regressions, dry-run behavior, and no-route safety."""

from tests.watchdog_support import (
    ROUTES,
    SCHEDULE,
    WLAN0,
    WLAN1,
    both_healthy,
    degraded,
    dev_info,
    healthy,
    kinds,
    lossy,
    nm_fake,
    obs,
    outage,
    patch_usb_node_of,
    preference_demotion,
    recording_nmcli,
    routes_demoted,
    subprocess,
    sys_obs,
    wd,
    wd_cycle,
    wedged,
)


def test_demote_reverts_the_active_profile_when_the_reapply_fails():
    """F1: modify landed, reapply failed -> the profile must not sit at 900
    with no demotion on record."""
    run, calls = nm_fake(fail=(("device", "reapply"),))
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("demote", "wlan1", "wedged", metric=900), ROUTES, state, run=run
    )
    modifies = [c[3:6] for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies == [
        ("Occom-USB", "ipv4.route-metric", "900"),
        ("Occom-USB", "ipv4.route-metric", "100"),
    ]
    assert state.demoted == {}


def test_failure_count_restarts_when_a_device_changes_role():
    """F2: two dead-end cycles as a standby must not count towards a
    failover once the device becomes the active route."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=3)
    standby_bad = {"wlan1": healthy("wlan1"), "wlan0": degraded("wlan0")}
    wd.evaluate(ROUTES, standby_bad, state, policy)
    wd.evaluate(ROUTES, standby_bad, state, policy)
    assert state.failures["wlan0"] == 2
    # wlan1 vanishes: wlan0 is the active route now, dead-ending.
    only = [WLAN0]
    active_bad = {"wlan0": degraded("wlan0")}
    assert wd.evaluate(only, active_bad, state, policy) == []
    assert state.failures["wlan0"] == 1


def test_decision_notes_never_say_minus_one_second():
    """F3 (fourth review); the wording follows the episode rule now: a
    re-association from before this failure streak is not one to escalate
    from."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, min_reset_interval_s=300.0)
    probes = {"wlan1": wedged("wlan1"), "wlan0": wedged("wlan0")}
    state.last_reset["wlan1"] = 0.0
    wd.evaluate(ROUTES, probes, state, policy, now=10.0)
    notes = [n for d, r, n in state.decisions if d == "wlan1"]
    assert notes and "-1" not in notes[-1]
    assert "in-place reset in 50 s" in notes[-1]
    assert "USB reset after the first re-association" in notes[-1]
    fresh = wd.State()
    wd.evaluate(ROUTES, probes, fresh, policy, now=10.0)
    # wlan0 (standby, wedged, nothing on record): the wording, not a number
    text = [n for d, r, n in fresh.decisions if d == "wlan0"]
    assert not any("-1" in t for t in text)


def test_networkmanager_restart_waits_for_three_inactive_cycles():
    """F15: an NM that is restarting on its own ("activating") is not
    restarted again on the first look."""
    policy = wd.Policy(service_failures_before_action=3)
    state = wd.State()
    down = sys_obs(nm_active=False)
    assert wd.evaluate_system(down, state, policy, now=0.0) == []
    assert wd.evaluate_system(down, state, policy, now=30.0) == []
    ((unit, reason),) = wd.evaluate_system(down, state, policy, now=60.0)
    assert unit == "NetworkManager.service" and "not active for 3 cycles" in reason
    assert wd.evaluate_system(sys_obs(), state, policy, now=90.0) == []
    assert state.nm_inactive_cycles == 0


def test_nm_answers_is_the_exit_code_not_the_device_count():
    """F4."""
    ok, _ = nm_fake()
    assert wd.nm_answers(ok)
    dead, _ = nm_fake(fail=(("nmcli", "-t"),))
    assert not wd.nm_answers(dead)


def test_a_dead_tunnel_health_server_restarts_the_tunnel_and_silence_does_not():
    """The 2026-09-14 lesson: a healthy idle tunnel can log nothing for half
    an hour (measured gaps up to 1931 s), so silence is only reported; a
    frozen process is caught by its health HTTP server."""
    policy = wd.Policy(service_failures_before_action=3)
    state = wd.State()
    state.uplink_ok_cycles = 9
    silent = obs(poll_failures=0, poll_last=0.0, tunnel_health_ok=True)
    for now in (400.0, 2000.0, 9000.0):
        assert wd.evaluate_services(silent, state, policy, now=now) == []
    frozen = obs(tunnel_health_ok=False)
    assert wd.evaluate_services(frozen, state, policy, now=0.0) == []
    assert wd.evaluate_services(frozen, state, policy, now=30.0) == []
    ((unit, reason),) = wd.evaluate_services(frozen, state, policy, now=60.0)
    assert unit == "binnacle-tunnel.service"
    assert "health server not answering for 3 cycles" in reason
    state.last_service_restart["tunnel"] = 60.0
    assert wd.evaluate_services(frozen, state, policy, now=90.0) == []  # rate limit
    assert (
        wd.evaluate_services(obs(tunnel_health_ok=True), state, policy, now=120.0) == []
    )
    assert state.service_failures["tunnel_health"] == 0


def test_observe_services_reads_the_last_log_time(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"2026-09-13T22:00:00+10:00","level":"INFO","msg":"dispatcher forwarded command to MCP server"}\n'
    )
    policy = wd.Policy(tunnel_log=log)

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(list(args), 0, stdout="active", stderr="")

    seen = wd.observe_services(policy, run, alive=lambda url: True)
    assert seen.poll_last == wd._rfc3339_epoch("2026-09-13T22:00:00+10:00")
    assert seen.poll_failures == 0 and seen.poll_failing_since is None
    assert seen.tunnel_health_ok is None  # no url file configured
    url_file = tmp_path / "binnacle.url"
    url_file.write_text("http://127.0.0.1:46401\n")
    asked: list[str] = []

    def alive(url: str) -> bool:
        asked.append(url)
        return url == "http://127.0.0.1:8000/mcp"  # the tunnel's port: dead

    with_health = wd.Policy(tunnel_log=log, tunnel_health_url_file=url_file)
    seen = wd.observe_services(with_health, run, alive=alive)
    assert seen.tunnel_health_ok is False and "http://127.0.0.1:46401" in asked
    url_file.write_text("garbage")
    assert wd.observe_services(with_health, run, alive=alive).tunnel_health_ok is None


def test_dry_run_decides_and_logs_but_applies_nothing(tmp_path, monkeypatch, caplog):
    import logging as _logging

    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, calls = nm_fake()
    policy = wd.Policy(
        failures_before_action=1,
        dry_run=True,
        service_repair=False,
        system_service_repair=False,
    )
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.cycle(wd.State(), policy, path, run=run) == []
    assert not any(c[1:3] == ("connection", "modify") for c in calls)
    assert (
        "event=dry_run cycle=1 until=- skipped=demote:wlan1,reset:wlan1" in caplog.text
    )
    assert "planned=demote:wlan1,reset:wlan1 actions=-" in caplog.text
    assert "dry_run=yes" in caplog.text


def test_action_lines_carry_the_cycle_the_state_before_and_the_duration(caplog):
    import logging as _logging

    run, _ = nm_fake()
    state = wd.State()
    state.cycle_n = 42
    state.last_grade["wlan1"] = "wedged"
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.apply_action(
            wd.Action("demote", "wlan1", "wedged for 3 cycles", metric=900),
            ROUTES,
            state,
            run=run,
            now=5.0,
        )
        assert wd.apply_action(
            wd.Action("reset", "wlan1", "repair"), ROUTES, state, run=run, now=6.0
        )
        assert wd.apply_action(
            wd.Action("restore", "wlan1", "healthy"), ROUTES, state, run=run, now=99.0
        )
    text = caplog.text
    assert (
        "event=uplink_demoted cycle=42 dev=wlan1 before=wedged trigger=cycle metric=100->900 kind=wedged profile=Occom-USB"
        in text
    )
    assert (
        "event=uplink_reset cycle=42 dev=wlan1 before=wedged trigger=cycle ok=True tag=wedged profile=Occom-USB duration_ms="
        in text
    )
    assert (
        "event=uplink_restored cycle=42 dev=wlan1 before=wedged metric=100 kind=wedged profile=Occom-USB others=- demoted_for_s=94"
        in text
    )


def test_failed_actions_are_named_on_the_cycle(tmp_path, monkeypatch, caplog):
    import logging as _logging

    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, _ = nm_fake(fail=(("connection", "modify"),))
    policy = wd.Policy(
        failures_before_action=1, service_repair=False, system_service_repair=False
    )
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.cycle(wd.State(), policy, path, run=run)
    assert "event=actions_failed cycle=1 failed=demote:wlan1" in caplog.text


def test_pause_transitions_are_logged(tmp_path, monkeypatch, caplog):
    import logging as _logging
    import time as _time

    path = tmp_path / "watchdog.json"
    pause = tmp_path / "watchdog.pause"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: both_healthy())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, _ = nm_fake()
    policy = wd.Policy(
        pause_file=pause, service_repair=False, system_service_repair=False
    )
    state = wd.State()
    pause.write_text(f"{_time.time() + 600:.0f}\n")
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.cycle(state, policy, path, run=run)
        pause.unlink()
        wd.cycle(state, policy, path, run=run)
    assert "event=pause_started cycle=1" in caplog.text
    assert "event=pause_ended cycle=2" in caplog.text


def test_sigterm_ends_the_loop_with_a_stop_line(tmp_path, monkeypatch, caplog):
    import logging as _logging
    import os as _os
    import signal as _signal

    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([], True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: {})
    monkeypatch.setattr(wd_cycle, "observe_devices", lambda run, usb_ids: {})
    calls: list[float] = []

    def sleep_then_signal(seconds: float) -> None:
        calls.append(seconds)
        _os.kill(_os.getpid(), _signal.SIGTERM)

    run, _ = recording_nmcli()
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.run_forever(
            tmp_path / "s.json",
            interval_s=1,
            policy=wd.Policy(service_repair=False, system_service_repair=False),
            sleep=sleep_then_signal,
            max_cycles=5,
            run=run,
        )
    assert calls == [1]  # one sleep, then the signal ended the loop
    assert "event=watchdog_stop signal=SIGTERM cycle=1" in caplog.text


def test_no_route_rung_needs_a_readable_route_table():
    """A failed `ip route` is not every radio losing its route."""
    state = wd.State()
    policy = wd.Policy(connecting_cycles_before_action=1)
    devices = {
        "wlan1": dev_info("wlan1", "connected", profile="Occom-USB"),
        "wlan0": dev_info("wlan0", "connected", profile="Occom"),
    }
    assert wd.evaluate([], {}, state, policy, devices=devices, routes_known=False) == []
    assert (
        "wlan0",
        "down",
        "connected without a default route for 1 cycles; the route table could not be read",
    ) in state.decisions


def test_no_route_rung_touches_one_device_per_cycle_and_reapplies_first():
    state = wd.State()
    policy = wd.Policy(connecting_cycles_before_action=1)
    devices = {
        "wlan1": dev_info("wlan1", "connected", profile="Occom-USB"),
        "wlan0": dev_info("wlan0", "connected", profile="Occom"),
    }
    actions = wd.evaluate([], {}, state, policy, devices=devices)
    assert [(a.kind, a.dev, a.tag) for a in actions] == [("reset", "wlan0", "no_route")]
    assert (
        "wlan1",
        "down",
        "connected without a default route for 1 cycles; one device per cycle",
    ) in state.decisions
    run, calls = nm_fake()
    assert wd.apply_action(actions[0], [], wd.State(), run=run, now=1.0)
    assert ("nmcli", "device", "reapply", "wlan0") in calls
    assert not any(c[1:3] == ("connection", "up") for c in calls)
    failing, calls2 = nm_fake(fail=(("device", "reapply"),))
    assert wd.apply_action(actions[0], [], wd.State(), run=failing, now=1.0)
    assert ("nmcli", "connection", "up", "id", "Occom", "ifname", "wlan0") in calls2


def test_no_route_rung_waits_the_longer_threshold():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, connecting_cycles_before_action=3)
    devices = {"wlan0": dev_info("wlan0", "connected", profile="Occom")}
    probes = {"wlan1": healthy("wlan1")}
    for _ in range(2):
        assert wd.evaluate([WLAN1], probes, state, policy, devices=devices) == []
    assert kinds(wd.evaluate([WLAN1], probes, state, policy, devices=devices)) == [
        "reset"
    ]


def test_the_suite_never_changes_the_host():
    """Classify read-only nmcli as safe and mutating nmcli as forbidden
    without requiring NetworkManager to exist on the test host."""
    from tests.conftest import _is_mutating

    assert not _is_mutating(["nmcli", "-t", "-f", "DEVICE", "device", "status"])
    assert _is_mutating(["nmcli", "connection", "up", "id", "x", "ifname", "wlan1"])
    assert _is_mutating(["sudo", "-n", "sh", "-c", "echo 0 > /sys/x"])
    assert _is_mutating(["systemctl", "--user", "restart", "binnacle-tunnel.service"])
    assert _is_mutating(["iw", "dev", "wlan0", "scan"])
    assert not _is_mutating(["iw", "dev", "wlan0", "link"])
    assert not _is_mutating(
        [
            "nmcli",
            "-t",
            "-f",
            "SSID",
            "device",
            "wifi",
            "list",
            "ifname",
            "wlan0",
            "--rescan",
            "no",
        ]
    )
    assert not _is_mutating(["sudo", "-n", "true"])
    assert not _is_mutating(["ip", "-j", "route", "show", "default"])
    assert _is_mutating(["ip", "route", "del", "default"])


def test_fallback_reset_turns_a_preference_demotion_into_a_wedge():
    """00:27 on 2026-09-14: a preference-demoted wlan1 got wedged; the note
    promised a USB reset that the preference kind never allows. After the
    fallback the demotion escalates like any wedge."""
    run, _ = nm_fake()
    state = preference_demotion(0.0)
    assert wd.apply_action(
        wd.Action("reset", "wlan1", "back", profile="Occom-USB", tag="fallback"),
        routes_demoted(),
        state,
        run=run,
        now=400.0,
    )
    assert state.demoted["wlan1"].kind == "wedged"
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=430.0) == []
    assert kinds(wd.evaluate(routes_demoted(), bad, state, policy, now=461.0)) == [
        "usb_reset"
    ]


def test_preference_demotion_note_names_the_fallback_not_a_usb_reset():
    state = preference_demotion(0.0)
    policy = wd.Policy(prefer_timeout_s=300.0)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    wd.evaluate(routes_demoted(), bad, state, policy, now=100.0)
    notes = [n for d, r, n in state.decisions if d == "wlan1" and r == "restore"]
    assert notes and "no USB escalation for a move" in notes[-1]
    assert "back to Occom-USB in 200 s" in notes[-1]


def test_one_degraded_cycle_is_not_a_transition(tmp_path, monkeypatch, caplog):
    import logging as _logging

    path = tmp_path / "watchdog.json"
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: probes)
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, _ = nm_fake()
    state = wd.State()
    policy = wd.Policy(service_repair=False, system_service_repair=False)
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.cycle(state, policy, path, run=run)
        probes["wlan0"] = lossy("wlan0")
        wd.cycle(state, policy, path, run=run)
        assert state.last_grade["wlan0"] == "healthy"
        wd.cycle(state, policy, path, run=run)
        assert state.last_grade["wlan0"] == "degraded"
        probes["wlan0"] = healthy("wlan0")
        wd.cycle(state, policy, path, run=run)
    assert (
        caplog.text.count("event=transition cycle=3 dev=wlan0 from=healthy to=degraded")
        == 1
    )
    assert "event=transition cycle=2 dev=wlan0" not in caplog.text

"""Recovery concurrency, supervision, and flapping summaries."""

from tests.watchdog_support import (
    ROUTES,
    SCHEDULE,
    SS_ON_WLAN2,
    THREE,
    WLAN0,
    WLAN2,
    FakeThread,
    Route,
    all_healthy,
    demoted_state,
    fast_env,
    healthy,
    json,
    kinds,
    nm_fake,
    patch_usb_node_of,
    routes_demoted,
    socket_fake,
    subprocess,
    wd,
    wedged,
)


def test_fast_path_probes_demoted_routes_for_the_restore(monkeypatch, caplog):
    import logging as _logging

    fast_env(
        monkeypatch,
        routes=[WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)],
    )
    run, _ = nm_fake()
    state = demoted_state()
    policy = wd.Policy()
    alive = {"wlan0": True, "wlan1": False}
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert (
            wd.fast_check(state, policy, run, tcp=lambda r: alive[r.dev], now=10.0)
            == []
        )
    assert state.fast_demoted_last_fail["wlan1"] == 10.0
    assert (
        "event=fast_failure cycle=0 dev=wlan1 role=demoted after_successes=0"
        in caplog.text
    )
    alive["wlan1"] = True
    for t in (15.0, 20.0):
        wd.fast_check(state, policy, run, tcp=lambda r: alive[r.dev], now=t)
    assert state.fast_demoted_streak["wlan1"] == 2
    assert state.fast_demoted_last_fail["wlan1"] == 10.0
    assert state.fast_last == 20.0
    # a restore forgets that view
    assert wd.apply_action(
        wd.Action("restore", "wlan1", "healthy"), ROUTES, state, run=run, now=30.0
    )
    assert (
        "wlan1" not in state.fast_demoted_streak
        and "wlan1" not in state.fast_demoted_last_fail
    )


def test_a_wedge_demotion_starts_a_new_episode_and_is_remembered():
    run, _ = nm_fake()
    state = wd.State()
    state.usb_attempts["wlan1"] = 3
    state.wedge_times["wlan1"] = [1.0, 5000.0]  # 1.0 falls out of the hour window
    assert wd.apply_action(
        wd.Action("demote", "wlan1", "wedged", metric=900),
        ROUTES,
        state,
        run=run,
        now=6000.0,
    )
    assert state.wedge_times["wlan1"] == [5000.0, 6000.0]
    assert "wlan1" not in state.usb_attempts
    # a preference move is not a wedge
    run2, _ = nm_fake(metrics={"Occom-5G-USB": "100"})
    s2 = wd.State()
    assert wd.apply_action(
        wd.Action(
            "demote",
            "wlan1",
            "move",
            metric=900,
            profile="Occom-5G-USB",
            tag="preference",
        ),
        ROUTES,
        s2,
        run=run2,
        now=1.0,
    )
    assert s2.wedge_times == {}


def test_wedge_times_survive_a_restart_and_the_heartbeat_does_not(tmp_path):
    state = wd.State()
    state.wedge_times["wlan1"] = [1.0, 2.0]
    state.fast_last = 99.0
    state.save(tmp_path / "s.json")
    loaded = wd.State.load(tmp_path / "s.json")
    assert loaded.wedge_times == {"wlan1": [1.0, 2.0]} and loaded.fast_last == 0.0
    assert json.loads((tmp_path / "s.json").read_text())["fast_last"] == 99.0


def test_demoted_wedged_route_reassociates_before_the_usb_schedule():
    """The 2026-09-14 15:54 shape: the previous episode's re-association is
    two minutes old, the fast path's own was skipped by the floor."""
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="x",
        reason="wedged",
        since_ts=1000.0,
    )
    state.last_reset["wlan1"] = 900.0  # the previous episode
    state.last_usb_reset["wlan1"] = 800.0
    policy = wd.Policy(
        usb_reset_schedule=SCHEDULE, min_reset_interval_s=300.0, reset_floor_s=60.0
    )
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    (first,) = wd.evaluate(routes_demoted(), bad, state, policy, now=1010.0)
    assert first.kind == "reset" and "before the USB schedule" in first.reason
    state.last_reset["wlan1"] = 1010.0
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=1040.0) == []
    notes = [n for d, r, n in state.decisions if d == "wlan1" and r == "restore"]
    assert "re-association in 270 s, USB reset attempt 1 in 30 s" in notes[-1]
    (second,) = wd.evaluate(routes_demoted(), bad, state, policy, now=1071.0)
    assert (
        second.kind == "usb_reset" and "this episode's re-association" in second.reason
    )


def test_a_repair_in_flight_holds_every_other_rung_for_that_device():
    state = demoted_state()
    state.repair_in_flight["wlan1"] = 1000.0
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=1010.0) == []
    assert any("repair in flight" in n for d, r, n in state.decisions if d == "wlan1")
    # a standby and the active route too
    s2 = wd.State()
    s2.repair_in_flight["wlan0"] = 0.0
    standby_bad = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    assert (
        wd.evaluate(
            ROUTES, standby_bad, s2, wd.Policy(failures_before_action=1), now=10.0
        )
        == []
    )
    assert any("repair in flight" in n for d, r, n in s2.decisions if d == "wlan0")
    # a marker older than any command's timeout is a leftover
    state.repair_in_flight["wlan1"] = 100.0
    assert kinds(wd.evaluate(routes_demoted(), bad, state, policy, now=1010.0)) == [
        "reset"
    ]
    assert state.repair_in_flight == {}


def test_still_safe_skips_a_standby_repair_when_the_device_became_active(monkeypatch):
    state = wd.State()
    now_active = [WLAN2, WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]
    monkeypatch.setattr(
        wd.uplink, "read_default_routes", lambda run: (now_active, True)
    )
    run, _ = nm_fake()
    standby_repair = wd.Action("reset", "wlan2", "standby wedged", tag="standby")
    assert not wd._still_safe(standby_repair, "wlan1", state, run)
    assert wd._still_safe(wd.Action("reset", "wlan1", "in place"), "wlan1", state, run)
    assert wd._still_safe(wd.Action("reset", "wlan0", "standby"), "wlan1", state, run)
    state.demoted["wlan1"] = demoted_state().demoted["wlan1"]
    assert wd._still_safe(wd.Action("usb_reset", "wlan1", "x"), "wlan2", state, run)
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([], False))
    assert wd._still_safe(standby_repair, "wlan1", state, run)  # unreadable: no verdict


def test_repairs_run_outside_the_lock_so_the_fast_path_can_fail_over(
    tmp_path, monkeypatch
):
    """The cycle is inside a 60 s `nmcli connection up` on the standby
    wlan0 when the active route dies: the fast path must not wait for it."""
    import threading as _threading

    path = tmp_path / "s.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (THREE, True))
    monkeypatch.setattr(
        wd.uplink,
        "probe_all",
        lambda rs, **kw: {
            "wlan1": healthy("wlan1"),
            "wlan2": healthy("wlan2"),
            "wlan0": wedged("wlan0"),
        },
    )
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    monkeypatch.setitem(wd.uplink._last_address, "api.openai.com", "172.66.0.243")
    gate = _threading.Event()
    entered = _threading.Event()
    inner, calls = nm_fake()

    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        if args[:3] == ("nmcli", "connection", "up"):
            entered.set()
            assert gate.wait(10)
        return inner(*args, **kw)

    state = wd.State()
    policy = wd.Policy(
        failures_before_action=1,
        fast_failures_before_action=1,
        reset_after_failover=False,
        service_repair=False,
        system_service_repair=False,
    )
    worker = _threading.Thread(target=lambda: wd.cycle(state, policy, path, run=run))
    worker.start()
    try:
        assert entered.wait(10)  # the cycle is inside the wlan0 re-activation
        assert not wd.ACT_LOCK.locked() and "wlan0" in state.repair_in_flight
        alive = {"wlan1": False, "wlan2": True, "wlan0": False}
        done = wd.fast_check(state, policy, run, tcp=lambda r: alive[r.dev], now=1.0)
        assert [a.kind for a in done] == ["demote"] and "wlan1" in state.demoted
    finally:
        gate.set()
        worker.join(10)
    assert not worker.is_alive() and state.repair_in_flight == {}
    assert any(c[:3] == ("nmcli", "connection", "up") and "wlan0" in c for c in calls)


def test_cycle_skips_a_standby_repair_whose_device_became_the_active_route(
    tmp_path, monkeypatch, caplog
):
    import logging as _logging

    path = tmp_path / "s.json"
    # decided with wlan1 active; by the time the repair runs, wlan2 is
    reads = iter(
        [
            (THREE, True),
            (
                [WLAN2, WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)],
                True,
            ),
        ]
    )
    monkeypatch.setattr(
        wd.uplink, "read_default_routes", lambda run: next(reads, ([], False))
    )
    monkeypatch.setattr(
        wd.uplink,
        "probe_all",
        lambda rs, **kw: {
            "wlan1": healthy("wlan1"),
            "wlan2": wedged("wlan2"),
            "wlan0": healthy("wlan0"),
        },
    )
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, calls = nm_fake()
    policy = wd.Policy(
        failures_before_action=1, service_repair=False, system_service_repair=False
    )
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        done = wd.cycle(wd.State(), policy, path, run=run)
    assert done == []
    assert (
        "event=action_skipped cycle=1 kind=reset dev=wlan2 reason=became the active route"
        in caplog.text
    )
    assert "event=actions_failed" not in caplog.text
    assert not any(c[:3] == ("nmcli", "connection", "up") for c in calls)


def test_supervise_fast_path_restarts_dead_logs_stalled_exits_hung(caplog):
    import logging as _logging

    state = wd.State()
    state.fast_last = 1000.0
    policy = wd.Policy(fast_interval_s=5.0, fast_timeout_s=2.0, cycle_timeout_s=600.0)
    started: list[int] = []
    exits: list[int] = []

    def start():
        started.append(1)
        return FakeThread()

    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        _, hung = wd.supervise_fast_path(
            state, policy, FakeThread(alive=False), start, exits.append, now=1010.0
        )
        assert started == [1] and not hung and state.fast_last == 1010.0
        assert "event=fast_path_restarted" in caplog.text
        _, hung = wd.supervise_fast_path(
            state, policy, FakeThread(), start, exits.append, now=1050.0
        )
        assert not hung and "event=fast_path_stalled" in caplog.text and started == [1]
        _, hung = wd.supervise_fast_path(
            state, policy, FakeThread(), start, exits.append, now=2000.0
        )
        assert hung and exits == [3] and "event=fast_path_hung" in caplog.text
        caplog.clear()
        state.fast_last = 3000.0
        _, hung = wd.supervise_fast_path(
            state, policy, FakeThread(), start, exits.append, now=3003.0
        )
    assert not hung and "fast_path" not in caplog.text


def test_cycle_line_carries_the_tunnel_device_and_the_fast_pulse(
    tmp_path, monkeypatch, caplog
):
    import logging as _logging
    import re as _re
    import time as _time

    path = tmp_path / "s.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (THREE, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda rs, **kw: all_healthy())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    monkeypatch.setattr(wd, "http_alive", lambda url, timeout=5.0: True)
    inner, calls = nm_fake()
    run = socket_fake(inner, ss=SS_ON_WLAN2)
    state = wd.State()
    state.fast_last = _time.time() - 3
    policy = wd.Policy(system_service_repair=False)
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.cycle(state, policy, path, run=run)
    assert _re.search(
        r"event=cycle cycle=1 .* tunnel_via=wlan2 fast=0/4@\d+s uplink_ok_cycles=1",
        caplog.text,
    )
    assert (
        "connection on wlan2 (usable), active wlan1; waiting 1/3 cycles" in caplog.text
    )
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)
    assert state.tunnel_via == "wlan2" and state.tunnel_off_active_cycles == 1


def test_issue_lines_switch_to_a_flapping_summary(caplog):
    import logging as _logging

    state = wd.State()
    policy = wd.Policy(snapshot_interval_s=600.0, flap_log_limit=3)
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        for i in range(8):
            issues = {"wlan0": "degraded (gateway=FAIL)"} if i % 2 == 0 else {}
            wd._log_issues(state, policy, issues, i + 1, float(i * 10))
    text = caplog.text
    assert text.count("event=uplink_issue cycle=") == 2
    assert text.count("event=uplink_issue_cleared") == 1
    assert text.count("event=uplink_issue_flapping") == 1
    assert "dev=wlan0 changes=4 window_s=600 current=clear" in text
    # the window passes: individual lines again
    caplog.clear()
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd._log_issues(state, policy, {"wlan0": "degraded (gateway=FAIL)"}, 20, 1000.0)
    assert (
        "event=uplink_issue cycle=20 dev=wlan0 issue=degraded (gateway=FAIL)"
        in caplog.text
    )


def test_observe_services_reads_the_last_forwarded_command(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"2026-09-13T22:00:00+10:00","level":"INFO","msg":"dispatcher forwarded command to MCP server"}\n'
        '{"time":"2026-09-13T22:00:30+10:00","level":"INFO","msg":"poll timed out; backing off"}\n'
    )
    policy = wd.Policy(tunnel_log=log)
    run, _ = nm_fake()
    seen = wd.observe_services(policy, run, alive=lambda url: True)
    assert seen.forwarded_last == wd._rfc3339_epoch("2026-09-13T22:00:00+10:00")
    assert seen.poll_failures == 1

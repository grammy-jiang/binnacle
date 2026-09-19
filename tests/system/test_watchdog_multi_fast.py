"""Three-radio behavior and fast-path failover."""

from tests.watchdog_support import (
    CONNECTIONS,
    DETAILS,
    ROUTES,
    THREE,
    WLAN0,
    WLAN2,
    Route,
    demoted_state,
    dev_info,
    fast_env,
    healthy,
    kinds,
    nm_fake,
    outage,
    patch_usb_node_of,
    subprocess,
    wd,
    wedged,
)


def test_failover_names_the_next_route_by_metric_not_by_name():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {
        "wlan1": wedged("wlan1"),
        "wlan2": healthy("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    actions = wd.evaluate(THREE, probes, state, policy)
    assert kinds(actions) == ["demote", "reset"]
    assert "wlan2 is healthy (metric 300)" in actions[0].reason


def test_second_failover_when_the_second_radio_wedges_too():
    """wlan1 demoted (900), wlan2 now active and wedged, wlan0 fine."""
    state = demoted_state()
    policy = wd.Policy(failures_before_action=1)
    routes = [WLAN2, WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]
    probes = {
        "wlan2": wedged("wlan2"),
        "wlan0": healthy("wlan0"),
        "wlan1": wedged("wlan1"),
    }
    actions = wd.evaluate(routes, probes, state, policy, now=10_000.0)
    demotes = [a for a in actions if a.kind == "demote"]
    assert [a.dev for a in demotes] == [
        "wlan2"
    ] and "wlan0 is healthy (metric 600)" in demotes[0].reason


def test_two_usb_adapters_learn_their_own_link_levels():
    """A USB 2 part (RTL8188EU, 480 Mbit/s) beside the USB 3 one: each
    keeps its own best, and neither is judged by the other's."""
    state = wd.State()
    policy = wd.Policy(usb_reset_ids=("0bda:8812", "0bda:8179"))
    devices = {
        "wlan1": dev_info(
            "wlan1", profile="Occom-USB", usb_id="0bda:8812", usb_speed=5000
        ),
        "wlan2": dev_info(
            "wlan2", profile="Occom-USB2", usb_id="0bda:8179", usb_speed=480
        ),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }
    probes = {
        "wlan1": healthy("wlan1"),
        "wlan2": healthy("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    assert wd.evaluate(THREE, probes, state, policy, devices=devices) == []
    assert state.usb_best_speed == {"wlan1": 5000, "wlan2": 480}
    devices["wlan1"] = dev_info(
        "wlan1", profile="Occom-USB", usb_id="0bda:8812", usb_speed=480
    )
    actions = wd.evaluate(THREE, probes, state, policy, devices=devices)
    assert [(a.kind, a.dev) for a in actions] == [
        ("demote", "wlan1"),
        ("usb_reset", "wlan1"),
    ]


def test_a_wedged_second_standby_is_repaired_on_its_own_counters():
    state = wd.State()
    policy = wd.Policy(failures_before_action=2)
    probes = {
        "wlan1": healthy("wlan1"),
        "wlan2": wedged("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    assert wd.evaluate(THREE, probes, state, policy) == []
    (action,) = wd.evaluate(THREE, probes, state, policy)
    assert action.kind == "reset" and action.dev == "wlan2" and action.tag == "standby"
    assert state.failures.get("wlan0", 0) == 0


def test_no_rescan_while_the_active_route_is_unhealthy(tmp_path, monkeypatch):
    """A scan can cost a minute; during a wedge the failover comes first."""
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, calls = nm_fake(connections=CONNECTIONS, details=DETAILS, scans={"wlan1": ""})
    policy = wd.Policy(
        failures_before_action=9, service_repair=False, system_service_repair=False
    )
    wd.cycle(wd.State(), policy, path, run=run)
    assert not any("wifi" in c and c[-1] == "yes" for c in calls)


def test_fast_path_demotes_after_four_failures_with_a_working_standby(monkeypatch):
    fast_env(monkeypatch)
    run, calls = nm_fake()
    state = wd.State()
    policy = wd.Policy(fast_failures_before_action=4, fast_interval_s=5.0)
    alive = {"wlan1": False, "wlan0": True}
    tcp = lambda route: alive[route.dev]
    for i in range(3):
        assert wd.fast_check(state, policy, run, tcp=tcp, now=float(i * 5)) == []
        assert state.fast_failures == i + 1
    done = wd.fast_check(state, policy, run, tcp=tcp, now=15.0)
    assert [a.kind for a in done] == ["demote", "reset"]
    assert "wlan0 has a TCP path (metric 600)" in done[0].reason
    assert "wlan1" in state.demoted and state.fast_failures == 0
    assert ("systemctl", "--user", "restart", "binnacle-tunnel.service") in calls
    assert state.last_failover_restart == 15.0


def test_fast_path_waits_when_no_standby_has_a_tcp_path(monkeypatch, caplog):
    import logging as _logging

    fast_env(monkeypatch)
    run, calls = nm_fake()
    state = wd.State()
    policy = wd.Policy(fast_failures_before_action=2)
    tcp = lambda route: False
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.fast_check(state, policy, run, tcp=tcp, now=0.0) == []
        assert wd.fast_check(state, policy, run, tcp=tcp, now=5.0) == []
    assert state.demoted == {} and "event=fast_failover_blocked" in caplog.text
    assert not any(c[1:3] == ("connection", "modify") for c in calls)


def test_fast_path_counter_resets_on_success_and_on_a_new_active_route(
    monkeypatch, caplog
):
    import logging as _logging

    fast_env(monkeypatch)
    run, _ = nm_fake()
    state = wd.State()
    policy = wd.Policy(fast_failures_before_action=4)
    state.fast_failures = 3
    state.fast_dev = "wlan1"
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.fast_check(state, policy, run, tcp=lambda r: True, now=0.0) == []
    assert state.fast_failures == 0 and "event=fast_recovered" in caplog.text
    state.fast_failures = 3
    state.fast_dev = "wlan9"  # the route changed underneath: start over
    assert wd.fast_check(state, policy, run, tcp=lambda r: False, now=0.0) == []
    assert state.fast_failures == 1 and state.fast_dev == "wlan1"


def test_fast_path_is_quiet_when_demoted_paused_dry_run_or_unresolved(
    monkeypatch, tmp_path
):
    fast_env(monkeypatch)
    run, _ = nm_fake()
    tcp = lambda route: False
    policy = wd.Policy(fast_failures_before_action=1)
    demoted = demoted_state()
    assert wd.fast_check(demoted, policy, run, tcp=tcp, now=0.0) == []
    assert (
        wd.fast_check(
            wd.State(),
            wd.Policy(fast_failures_before_action=1, dry_run=True),
            run,
            tcp=tcp,
        )
        == []
    )
    pause = tmp_path / "p"
    import time as _time

    pause.write_text(f"{_time.time() + 60:.0f}")
    assert (
        wd.fast_check(
            wd.State(),
            wd.Policy(fast_failures_before_action=1, pause_file=pause),
            run,
            tcp=tcp,
        )
        == []
    )
    monkeypatch.delitem(wd.uplink._last_address, "api.openai.com", raising=False)
    assert wd.fast_check(wd.State(), policy, run, tcp=tcp) == []
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([], False))
    assert wd.fast_check(wd.State(), policy, run, tcp=tcp) == []


def test_fast_path_never_stacks_on_a_demotion_the_cycle_just_made(monkeypatch):
    """The lock: by the time the fast path acts, the cycle may have demoted."""
    fast_env(monkeypatch)
    run, calls = nm_fake()
    state = wd.State()
    policy = wd.Policy(fast_failures_before_action=1)

    def tcp(route):
        if route.dev == "wlan1":
            state.demoted["wlan1"] = demoted_state().demoted[
                "wlan1"
            ]  # a demotion lands meanwhile
            return False
        return True

    assert wd.fast_check(state, policy, run, tcp=tcp, now=0.0) == []
    assert not any(c[1:3] == ("connection", "modify") for c in calls)


def test_slow_path_failover_also_restarts_the_tunnel(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    run, calls = nm_fake()
    policy = wd.Policy(
        failures_before_action=1, service_repair=False, system_service_repair=False
    )
    done = wd.cycle(wd.State(), policy, path, run=run)
    assert "demote" in kinds(done)
    assert ("systemctl", "--user", "restart", "binnacle-tunnel.service") in calls
    calls.clear()
    off = wd.Policy(
        failures_before_action=1,
        service_repair=False,
        system_service_repair=False,
        restart_tunnel_on_failover=False,
    )
    wd.cycle(wd.State(), off, path, run=run)
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)


def test_after_failover_restart_has_a_floor_and_needs_an_active_tunnel():
    run, calls = nm_fake()
    state = wd.State()
    policy = wd.Policy(failover_restart_floor_s=15.0)

    def restarts() -> int:
        return sum(1 for c in calls if c[:3] == ("systemctl", "--user", "restart"))

    wd.after_failover(state, policy, run, now=100.0)
    wd.after_failover(state, policy, run, now=105.0)  # within the floor: deferred
    assert restarts() == 1
    wd.after_failover(state, policy, run, now=130.0)  # a second failover 30 s on
    assert restarts() == 2

    def inactive(*args: str, **kw) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(list(args), 0, stdout="inactive", stderr="")

    fresh = wd.State()
    wd.after_failover(fresh, policy, inactive, now=100.0)
    assert fresh.last_failover_restart == 0.0

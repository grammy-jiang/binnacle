"""Failover, restore, state, actions, and loop policy."""

from tests.watchdog_support import (
    ROUTES,
    WLAN0,
    ProbeResult,
    Route,
    degraded,
    demoted_state,
    healthy,
    json,
    kinds,
    lossy,
    outage,
    recording_nmcli,
    subprocess,
    wd,
    wedged,
)


def test_no_action_while_everything_is_healthy():
    state = wd.State()
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, wd.Policy()) == []


def test_one_wedged_cycle_is_not_enough():
    """A single dropped probe must never move a route."""
    state = wd.State()
    assert wd.evaluate(ROUTES, outage(), state, wd.Policy()) == []
    assert state.failures["wlan1"] == 1


def test_demotes_after_the_threshold_of_consecutive_cycles():
    state = wd.State()
    policy = wd.Policy(failures_before_action=3)
    for _ in range(2):
        assert wd.evaluate(ROUTES, outage(), state, policy) == []
    actions = wd.evaluate(ROUTES, outage(), state, policy)
    assert kinds(actions) == ["demote", "reset"]
    demote = actions[0]
    assert demote.dev == "wlan1" and demote.metric == policy.demoted_metric


def test_a_healthy_cycle_resets_the_failure_counter():
    """Intermittent failures must not accumulate into a failover."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=3)
    wd.evaluate(ROUTES, outage(), state, policy)
    wd.evaluate(ROUTES, outage(), state, policy)
    wd.evaluate(
        ROUTES, {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}, state, policy
    )
    assert state.failures["wlan1"] == 0
    assert wd.evaluate(ROUTES, outage(), state, policy) == []


def test_lossy_but_connected_does_not_fail_over():
    """A lost ping with a working TCP path stays put."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {"wlan1": lossy("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, policy) == []


def test_dead_end_active_route_fails_over_like_a_wedge():
    """Review 2026-09-13: the gateway answers but nothing beyond it does
    while the standby reaches the upstream -- the tunnel is just as dead
    as in a wedge, so the route moves. No in-place reset or USB reset,
    though: those are for a radio that carries nothing at all."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=2)
    probes = {"wlan1": degraded("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, policy) == []
    actions = wd.evaluate(ROUTES, probes, state, policy)
    assert kinds(actions) == ["demote", "reset"]
    assert "no TCP path for 2 cycles" in actions[0].reason


def test_dead_end_on_the_only_route_is_left_alone():
    """Both routes reach the gateway and neither reaches the upstream: that
    is the WAN. Resetting radios would only add an outage."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {"wlan1": degraded("wlan1"), "wlan0": degraded("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, policy, now=0.0) == []
    assert wd.evaluate(ROUTES, probes, state, policy, now=1000.0) == []


def test_never_demotes_the_last_working_route():
    """With no alternative that has a TCP path there is nowhere to go:
    repair in place (and the dead standby gets its own repair)."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {"wlan1": wedged("wlan1"), "wlan0": wedged("wlan0")}
    actions = wd.evaluate(ROUTES, probes, state, policy)
    assert kinds(actions) == ["reset", "reset"]
    assert actions[0].dev == "wlan1" and "no usable alternative" in actions[0].reason
    assert actions[1].dev == "wlan0" and actions[1].tag == "standby"


def test_a_lossy_standby_with_a_tcp_path_is_still_a_failover_target():
    """2026-09-14 00:46: wlan0 had lost a ping and a DNS reply (its 5 GHz
    link in the case) while its TCP layer worked, and the wedged wlan1
    kept the traffic. A TCP path is what the tunnel needs."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    lossy_standby = ProbeResult(
        dev="wlan0", layers={"gateway": False, "dns": False, "tcp": True}
    )
    probes = {"wlan1": wedged("wlan1"), "wlan0": lossy_standby}
    actions = wd.evaluate(ROUTES, probes, state, policy)
    assert kinds(actions) == ["demote", "reset"]
    assert "wlan0 has a TCP path" in actions[0].reason
    # A dead-end standby (no TCP) is not a target.
    probes = {"wlan1": wedged("wlan1"), "wlan0": degraded("wlan0")}
    actions = wd.evaluate(ROUTES, probes, wd.State(), policy)
    assert "demote" not in kinds(actions)


def test_standby_failure_never_moves_traffic():
    """A wedged standby does not affect traffic: no demotion, no failover;
    it is repaired in place (2026-09-13) or, with standby_repair off, left."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    actions = wd.evaluate(ROUTES, probes, state, policy)
    assert kinds(actions) == ["reset"]
    assert actions[0].dev == "wlan0" and actions[0].tag == "standby"
    off = wd.Policy(failures_before_action=1, standby_repair=False)
    assert wd.evaluate(ROUTES, probes, wd.State(), off) == []


def test_reset_is_rate_limited_within_an_episode_and_floored_across():
    """A new failover 30 s after the last re-association: demote, no reset
    yet (the floor); 100 s after: the new episode gets its first one."""
    state = wd.State()
    policy = wd.Policy(
        failures_before_action=1, min_reset_interval_s=300, reset_floor_s=60
    )
    state.last_reset["wlan1"] = 1_000.0
    assert kinds(wd.evaluate(ROUTES, outage(), state, policy, now=1_030.0)) == [
        "demote"
    ]
    state.demoted.clear()
    state.failures.clear()
    later = wd.evaluate(ROUTES, outage(), state, policy, now=1_100.0)
    assert kinds(later) == ["demote", "reset"]


def test_reset_after_failover_can_be_switched_off():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, reset_after_failover=False)
    assert kinds(wd.evaluate(ROUTES, outage(), state, policy)) == ["demote"]


def test_no_routes_means_no_actions():
    assert wd.evaluate([], {}, wd.State(), wd.Policy()) == []


def test_restores_after_enough_healthy_cycles():
    state = demoted_state()
    policy = wd.Policy(successes_before_restore=3)
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    routes = [WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]
    for _ in range(2):
        assert wd.evaluate(routes, probes, state, policy) == []
    actions = wd.evaluate(routes, probes, state, policy)
    assert kinds(actions) == ["restore"]
    assert actions[0].metric == 100


def test_restore_counter_resets_on_a_relapse():
    state = demoted_state()
    policy = wd.Policy(successes_before_restore=3)
    routes = [WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]
    good = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    wd.evaluate(routes, good, state, policy)
    wd.evaluate(routes, good, state, policy)
    wd.evaluate(routes, bad, state, policy)
    assert state.successes["wlan1"] == 0
    assert wd.evaluate(routes, good, state, policy) == []


def test_a_demoted_device_is_not_treated_as_a_failover_target():
    """A demoted interface must not count as the healthy alternative."""
    state = demoted_state()
    policy = wd.Policy(failures_before_action=1)
    routes = [WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]
    probes = {"wlan0": wedged("wlan0"), "wlan1": healthy("wlan1")}
    actions = wd.evaluate(routes, probes, state, policy)
    assert "demote" not in kinds(actions)


def test_state_round_trips_demotions(tmp_path):
    path = tmp_path / "watchdog.json"
    state = demoted_state()
    state.last_reset["wlan1"] = 1234.5
    state.last_cycle = "2026-09-12T01:00:00+00:00"
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.demoted["wlan1"].original_metric == 100
    assert loaded.demoted["wlan1"].profile == "Occom-USB"
    assert loaded.last_reset["wlan1"] == 1234.5
    assert loaded.last_cycle == "2026-09-12T01:00:00+00:00"


def test_counters_do_not_persist(tmp_path):
    """A restarted watchdog must re-observe a fault before acting."""
    path = tmp_path / "watchdog.json"
    state = wd.State()
    state.failures["wlan1"] = 99
    state.successes["wlan1"] = 99
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.failures == {} and loaded.successes == {}


def test_missing_or_corrupt_state_loads_empty(tmp_path):
    assert wd.State.load(tmp_path / "nope.json").demoted == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert wd.State.load(bad).demoted == {}


def test_save_is_atomic(tmp_path):
    path = tmp_path / "nested" / "watchdog.json"
    wd.State().save(path)
    assert path.exists() and not path.with_suffix(".tmp").exists()
    assert json.loads(path.read_text())["demoted"] == {}


def test_demote_sets_the_metric_and_records_the_original():
    run, calls = recording_nmcli()
    state = wd.State()
    action = wd.Action("demote", "wlan1", "wedged", metric=900)
    assert wd.apply_action(action, ROUTES, state, run=run)
    assert (
        "nmcli",
        "connection",
        "modify",
        "Occom-USB",
        "ipv4.route-metric",
        "900",
    ) in calls
    assert ("nmcli", "device", "reapply", "wlan1") in calls
    assert state.demoted["wlan1"].original_metric == 100
    assert state.failures["wlan1"] == 0


def test_demote_is_skipped_when_the_device_has_no_profile():
    run, _ = recording_nmcli(profiles="wlan0:Occom\n")
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("demote", "wlan1", "x", metric=900), ROUTES, state, run=run
    )
    assert state.demoted == {}


def test_demote_does_not_record_when_nmcli_fails():
    """A failed metric change must not leave a phantom demotion behind."""
    run, _ = recording_nmcli(code=1)
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("demote", "wlan1", "x", metric=900), ROUTES, state, run=run
    )
    assert state.demoted == {}


def test_restore_puts_the_original_metric_back_and_clears_state():
    run, calls = recording_nmcli()
    state = demoted_state()
    action = wd.Action("restore", "wlan1", "healthy", metric=100)
    assert wd.apply_action(action, ROUTES, state, run=run)
    assert (
        "nmcli",
        "connection",
        "modify",
        "Occom-USB",
        "ipv4.route-metric",
        "100",
    ) in calls
    assert state.demoted == {}


def test_restore_keeps_the_demotion_when_nmcli_fails():
    run, _ = recording_nmcli(code=1)
    state = demoted_state()
    assert not wd.apply_action(
        wd.Action("restore", "wlan1", "x", metric=100), ROUTES, state, run=run
    )
    assert "wlan1" in state.demoted


def test_reset_reconnects_and_stamps_the_rate_limit():
    run, calls = recording_nmcli()
    state = wd.State()
    assert wd.apply_action(
        wd.Action("reset", "wlan1", "repair"), ROUTES, state, run=run, now=500.0
    )
    assert ("nmcli", "connection", "up", "id", "Occom-USB", "ifname", "wlan1") in calls
    assert state.last_reset["wlan1"] == 500.0


def test_reset_is_stamped_even_when_it_fails():
    """A failing reset must still be rate-limited, or it retries every cycle."""
    run, _ = recording_nmcli(code=1)
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("reset", "wlan1", "x"), ROUTES, state, run=run, now=7.0
    )
    assert state.last_reset["wlan1"] == 7.0


def test_device_profiles_skips_unmanaged_devices():
    run, _ = recording_nmcli(profiles="wlan1:Occom-USB\np2p-dev-wlan1:--\neth0:\n")
    assert wd.device_profiles(run) == {"wlan1": "Occom-USB"}


def test_cycle_writes_state_and_takes_no_action_when_healthy(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(
        wd.uplink,
        "probe_all",
        lambda routes, **kw: {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")},
    )
    run, _ = recording_nmcli()
    state = wd.State()
    assert wd.cycle(state, wd.Policy(), path, run=run) == []
    written = json.loads(path.read_text())
    assert written["last_summary"]["wlan1"] == "gateway=ok dns=ok tcp=ok"
    assert written["last_cycle"]


def test_cycle_fails_over_and_restores_across_cycles(tmp_path, monkeypatch):
    """End to end through the loop: wedge, demote, recover, restore."""
    path = tmp_path / "watchdog.json"
    probes = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: probes)
    run, _ = recording_nmcli()
    state = wd.State()
    policy = wd.Policy(failures_before_action=2, successes_before_restore=2)

    wd.cycle(state, policy, path, run=run)
    done = wd.cycle(state, policy, path, run=run)
    assert "demote" in kinds(done)
    assert "wlan1" in wd.State.load(path).demoted

    probes["wlan1"] = healthy("wlan1")
    wd.cycle(state, policy, path, run=run)
    done = wd.cycle(state, policy, path, run=run)
    assert kinds(done) == ["restore"]
    assert wd.State.load(path).demoted == {}


def test_run_forever_stops_after_max_cycles(tmp_path, monkeypatch):
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([], True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: {})
    slept: list[float] = []
    run, _ = recording_nmcli()
    wd.run_forever(
        tmp_path / "s.json", interval_s=5, sleep=slept.append, max_cycles=3, run=run
    )
    assert slept == [5, 5]  # no sleep after the final cycle


def test_run_forever_survives_a_cycle_exception(tmp_path, monkeypatch):
    """A probe bug must not silently stop the watchdog."""

    def boom(run):
        raise RuntimeError("ip is gone")

    monkeypatch.setattr(wd.uplink, "read_default_routes", boom)
    slept: list[float] = []
    run, _ = recording_nmcli()
    wd.run_forever(
        tmp_path / "s.json", interval_s=1, sleep=slept.append, max_cycles=2, run=run
    )
    assert len(slept) == 1


def test_reset_without_a_profile_fails_cleanly():
    run, calls = recording_nmcli(profiles="wlan0:Occom\n")
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("reset", "wlan1", "x"), ROUTES, state, run=run, now=1.0
    )
    assert not any("up" in c for c in calls)
    assert state.last_reset["wlan1"] == 1.0  # still rate-limited


def test_reset_uses_a_verb_nmcli_actually_has():
    """`nmcli device reconnect` does not exist; this guards the real verb.
    The recording fake accepted the wrong verb happily on 2026-09-12."""
    import shutil

    if shutil.which("nmcli") is None:
        import pytest

        pytest.skip("nmcli not installed")
    proc = subprocess.run(
        ["nmcli", "connection", "--help"], capture_output=True, text=True, check=False
    )
    help_text = proc.stdout + proc.stderr  # nmcli prints usage on stderr
    assert "up" in help_text.split() and "reconnect" not in help_text.split()
    run, calls = recording_nmcli()
    wd.reset_device("wlan1", "Occom-USB", run)
    verb = calls[0][1:3]
    assert verb == ("connection", "up")

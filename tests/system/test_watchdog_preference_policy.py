"""Profile-preference policy and fallback."""

from tests.watchdog_support import (
    ROUTES,
    WLAN1,
    both_healthy,
    degraded,
    demoted_state,
    healthy,
    kinds,
    pairwise,
    pref,
    preference_demotion,
    recording_nmcli,
    routes_demoted,
    wd,
    wedged,
)


def test_standby_repair_waits_for_the_threshold_and_is_rate_limited():
    state = wd.State()
    policy = wd.Policy(failures_before_action=3, min_reset_interval_s=300)
    probes = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, policy, now=0.0) == []
    assert wd.evaluate(ROUTES, probes, state, policy, now=30.0) == []
    actions = wd.evaluate(ROUTES, probes, state, policy, now=60.0)
    assert kinds(actions) == ["reset"] and actions[0].profile is None
    state.last_reset["wlan0"] = 60.0
    assert wd.evaluate(ROUTES, probes, state, policy, now=90.0) == []
    assert kinds(wd.evaluate(ROUTES, probes, state, policy, now=400.0)) == ["reset"]


def test_standby_repair_counter_clears_on_a_healthy_cycle():
    state = wd.State()
    policy = wd.Policy(failures_before_action=2)
    bad = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    wd.evaluate(ROUTES, bad, state, policy)
    wd.evaluate(ROUTES, both_healthy(), state, policy)
    assert state.failures["wlan0"] == 0
    assert wd.evaluate(ROUTES, bad, state, policy) == []


def test_standby_repair_moves_to_the_preferred_profile_when_in_range():
    """Re-activating a dead profile is a guess; a better profile in range
    is the fix (wlan0 at 18:17: the 5 GHz SSID had vanished, 2.4 GHz was
    there)."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    probes = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    prefs = {"wlan0": pref("wlan0", "Occom-5G", "Occom-2.4G", visible=True)}
    (action,) = wd.evaluate(ROUTES, probes, state, policy, preferences=prefs)
    assert action.kind == "reset" and action.profile == "Occom-2.4G"
    assert action.tag == "standby"
    out_of_range = {"wlan0": pref("wlan0", "Occom-5G", "Occom-2.4G", visible=False)}
    (action,) = wd.evaluate(
        ROUTES, probes, wd.State(), policy, preferences=out_of_range
    )
    assert action.profile is None


def test_preference_moves_a_standby_at_once():
    state = wd.State()
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    actions = wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), preferences=prefs)
    assert kinds(actions) == ["reset"]
    assert actions[0].dev == "wlan0" and actions[0].profile == "Occom-5G"
    assert actions[0].tag == "preference" and "attempt 1" in actions[0].reason


def test_preference_moves_the_active_route_through_a_demotion():
    """The link goes down for the switch, so traffic leaves first and the
    new profile's metric is raised too (it earns its way back)."""
    state = wd.State()
    prefs = {"wlan1": pref("wlan1", "Occom-USB", "Occom-5G-USB")}
    actions = wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), preferences=prefs)
    assert kinds(actions) == ["demote", "reset"]
    demote, reset = actions
    assert demote.tag == "preference" and demote.profile == "Occom-5G-USB"
    assert demote.metric == wd.Policy().demoted_metric
    assert reset.profile == "Occom-5G-USB" and reset.tag == "preference"


def test_preference_never_takes_down_the_only_healthy_uplink():
    state = wd.State()
    prefs = {"wlan1": pref("wlan1", "Occom-USB", "Occom-5G-USB")}
    probes = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    policy = wd.Policy(failures_before_action=5)  # keep standby repair quiet
    assert wd.evaluate(ROUTES, probes, state, policy, preferences=prefs) == []


def test_preference_waits_while_the_target_is_out_of_range():
    state = wd.State()
    prefs = {"wlan1": pref("wlan1", "Occom-USB", "Occom-5G-USB", visible=False)}
    assert (
        wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), preferences=prefs) == []
    )


def test_preference_needs_a_healthy_device_and_a_route():
    state = wd.State()
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    probes = {"wlan1": healthy("wlan1"), "wlan0": degraded("wlan0")}
    assert wd.evaluate(ROUTES, probes, state, wd.Policy(), preferences=prefs) == []
    only_wlan1 = {"wlan1": healthy("wlan1")}
    assert wd.evaluate([WLAN1], only_wlan1, state, wd.Policy(), preferences=prefs) == []


def test_preference_never_starts_over_a_demotion_in_flight():
    """While wlan1 is demoted, wlan0 carries the connector: not the moment
    to re-associate it."""
    state = demoted_state()
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    actions = wd.evaluate(
        routes_demoted(), both_healthy(), state, wd.Policy(), preferences=prefs
    )
    assert "reset" not in kinds(actions)


def test_one_preference_move_per_cycle():
    state = wd.State()
    prefs = {
        "wlan1": pref("wlan1", "Occom-USB", "Occom-5G-USB"),
        "wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G"),
    }
    actions = wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), preferences=prefs)
    assert [a.dev for a in actions] == ["wlan0"]  # the standby first, alone


def test_preference_backs_off_on_its_schedule():
    """10 min x3, then hourly: a move that does not stick is not retried
    every cycle."""
    state = wd.State()
    policy = wd.Policy(prefer_schedule=((3, 600.0), (0, 3600.0)))
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    fired: list[float] = []
    now = 0.0
    run, _ = recording_nmcli()
    for _ in range(5):
        while True:
            now += 30.0
            actions = wd.evaluate(
                ROUTES, both_healthy(), state, policy, now=now, preferences=prefs
            )
            if actions:
                break
        wd.apply_action(actions[0], ROUTES, state, run=run, now=now)
        fired.append(now)
    gaps = [b - a for a, b in pairwise(fired)]
    assert gaps == [600, 600, 600, 3600]
    assert state.prefer_attempts["wlan0"] == 5


def test_preference_attempts_clear_after_holding_the_best_profile():
    state = wd.State()
    state.prefer_attempts["wlan1"] = 3
    state.last_prefer["wlan1"] = 0.0
    policy = wd.Policy(prefer_hold_s=3600.0)
    on_best = {"wlan1": pref("wlan1", "Occom-5G-USB", None, visible=False)}
    wd.evaluate(ROUTES, both_healthy(), state, policy, now=10.0, preferences=on_best)
    assert state.prefer_attempts["wlan1"] == 3
    wd.evaluate(ROUTES, both_healthy(), state, policy, now=3700.0, preferences=on_best)
    assert "wlan1" not in state.prefer_attempts and "wlan1" not in state.last_prefer


def test_preference_can_be_disabled():
    state = wd.State()
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    policy = wd.Policy(prefer_enabled=False)
    assert wd.evaluate(ROUTES, both_healthy(), state, policy, preferences=prefs) == []


def test_preference_move_that_stays_unhealthy_falls_back_without_a_usb_reset():
    """A self-inflicted change must not escalate to the software replug;
    after prefer_timeout_s the profile that worked comes back."""
    policy = wd.Policy(prefer_timeout_s=300.0, min_reset_interval_s=300.0)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    state = preference_demotion(0.0)
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=61.0) == []
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=299.0) == []
    (action,) = wd.evaluate(routes_demoted(), bad, state, policy, now=301.0)
    assert action.kind == "reset" and action.tag == "fallback"
    assert action.profile == "Occom-USB" and "did not come up" in action.reason


def test_preference_move_restores_like_any_repair():
    state = preference_demotion(0.0)
    policy = wd.Policy(successes_before_restore=2)
    good = both_healthy()
    assert wd.evaluate(routes_demoted(), good, state, policy, now=100.0) == []
    actions = wd.evaluate(routes_demoted(), good, state, policy, now=130.0)
    assert kinds(actions) == ["restore"]

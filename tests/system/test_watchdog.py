"""Implementation gate for binnacle/watchdog.py.

`evaluate` is pure, so the whole failover policy is tested without a
network: build routes and probe results, assert the actions. The nmcli
side effects use a recording fake.

The scenario throughout is the 2026-09-12 outage: wlan1 (USB, metric 100)
holds the default route and stops carrying traffic while wlan0 (metric
600) is fine.
"""

import json
import subprocess
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any
from unittest import mock

from binnacle import watchdog as wd
from binnacle.uplink import ProbeResult, Route

WLAN1 = Route(dev="wlan1", gateway="192.168.50.1", src="192.168.50.197", metric=100)
WLAN0 = Route(dev="wlan0", gateway="192.168.50.1", src="192.168.50.222", metric=600)
ROUTES = [WLAN1, WLAN0]


def healthy(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": True, "dns": True, "tcp": True})


def wedged(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": False, "dns": False, "tcp": False})


def degraded(dev: str) -> ProbeResult:
    return ProbeResult(dev=dev, layers={"gateway": True, "dns": False, "tcp": False})


def outage() -> dict[str, ProbeResult]:
    return {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}


def kinds(actions: list[wd.Action]) -> list[str]:
    return [a.kind for a in actions]


def recording_nmcli(profiles: str = "wlan1:Occom-USB\nwlan0:Occom\n", code: int = 0):
    """Records argv; answers `device status` with `profiles`."""
    calls: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        out = profiles if args[:3] == ("nmcli", "-t", "-f") else ""
        if args[:2] == ("systemctl", "is-active") or args[:3] == (
            "systemctl",
            "--user",
            "is-active",
        ):
            out = "active"
        return subprocess.CompletedProcess(list(args), code, stdout=out, stderr="err")

    return run, calls


# -- failover policy ---------------------------------------------------------


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


def lossy(dev: str) -> ProbeResult:
    """Packet loss on the way to the gateway while DNS and TCP still pass."""
    return ProbeResult(dev=dev, layers={"gateway": False, "dns": True, "tcp": True})


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


# -- restore policy ----------------------------------------------------------


def demoted_state() -> wd.State:
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="2026-09-12T01:00:00+00:00",
        reason="wedged",
    )
    return state


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


# -- state persistence -------------------------------------------------------


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


# -- applying actions --------------------------------------------------------


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


# -- the loop ----------------------------------------------------------------


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


# -- tier 3: USB re-enumeration on the user's schedule ----------------------
#
# 2026-09-12 21:00: re-association (tier 2) succeeded at the 802.11 level and
# the data path stayed dead; a physical replug revived it. Tier 3 is that
# replug in software, paced 1 min x3, 3 min x3, 5 min x3, then every 10 min.

SCHEDULE = ((3, 60.0), (3, 180.0), (3, 300.0), (0, 600.0))


def test_usb_backoff_follows_the_stages():
    waits = [wd.usb_backoff(SCHEDULE, n) for n in range(1, 13)]
    assert waits == [60, 60, 60, 180, 180, 180, 300, 300, 300, 600, 600, 600]


def test_usb_backoff_unlimited_stage_never_runs_out():
    assert wd.usb_backoff(SCHEDULE, 500) == 600.0
    assert wd.usb_backoff(((2, 30.0),), 99) == 30.0  # last stage repeats
    assert wd.usb_backoff((), 1) == 600.0


def demoted_after_reset(reset_at: float) -> wd.State:
    state = demoted_state()
    state.last_reset["wlan1"] = reset_at
    return state


def routes_demoted() -> list[Route]:
    return [WLAN0, Route("wlan1", "192.168.50.1", "192.168.50.197", 900)]


def test_usb_reset_waits_one_minute_after_the_reassociation():
    state = demoted_after_reset(1000.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=1030.0) == []
    actions = wd.evaluate(routes_demoted(), bad, state, policy, now=1061.0)
    assert kinds(actions) == ["usb_reset"]
    assert "attempt 1" in actions[0].reason


def test_usb_reset_schedule_escalates_across_attempts():
    """Three at 60 s, three at 180 s, three at 300 s, then 600 s forever."""
    state = demoted_after_reset(0.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    run, _ = recording_nmcli()
    fired: list[float] = []
    now = 0.0
    for _ in range(12):
        while True:
            now += 10.0
            actions = wd.evaluate(routes_demoted(), bad, state, policy, now=now)
            if actions:
                break
        assert kinds(actions) == ["usb_reset"]
        with mock.patch.object(wd, "usb_reset_device", return_value=(True, "ok")):
            wd.apply_action(
                actions[0], routes_demoted(), state, run=run, now=now, policy=policy
            )
        fired.append(now)
    gaps = [b - a for a, b in pairwise(fired)]
    assert gaps == [60, 60, 180, 180, 180, 300, 300, 300, 600, 600, 600]
    assert state.usb_attempts["wlan1"] == 12


def test_usb_reset_needs_a_prior_reassociation():
    """Nothing to escalate from: with no tier-2 reset on record the demoted
    wedged route is re-associated first (a state the old rule left stuck
    forever), and the USB schedule counts from that."""
    state = demoted_state()
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    (first,) = wd.evaluate(routes_demoted(), bad, state, policy, now=10_000.0)
    assert first.kind == "reset" and "before the USB schedule" in first.reason
    state.last_reset["wlan1"] = 10_000.0
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=10_030.0) == []
    (second,) = wd.evaluate(routes_demoted(), bad, state, policy, now=10_061.0)
    assert second.kind == "usb_reset"


def test_usb_reset_not_stacked_while_the_device_is_absent():
    """Mid-re-enumeration the interface has no route; do not reset again."""
    state = demoted_after_reset(0.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    only_wlan0 = {"wlan0": healthy("wlan0")}
    assert wd.evaluate([WLAN0], only_wlan0, state, policy, now=5_000.0) == []


def test_usb_reset_can_be_disabled():
    state = demoted_after_reset(0.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE, usb_reset_enabled=False)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=5_000.0) == []


def test_restore_clears_the_usb_attempt_counter():
    run, _ = recording_nmcli()
    state = demoted_state()
    state.usb_attempts["wlan1"] = 7
    assert wd.apply_action(
        wd.Action("restore", "wlan1", "healthy", metric=100), ROUTES, state, run=run
    )
    assert "wlan1" not in state.usb_attempts


def test_usb_attempts_persist_across_a_restart(tmp_path):
    """A restart mid-outage must not begin the schedule again at one minute."""
    path = tmp_path / "watchdog.json"
    state = demoted_state()
    state.usb_attempts["wlan1"] = 5
    state.last_usb_reset["wlan1"] = 4242.0
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.usb_attempts["wlan1"] == 5
    assert loaded.last_usb_reset["wlan1"] == 4242.0


def fake_sudo(code: int = 0):
    calls: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(list(args), code, stdout="", stderr="denied")

    return run, calls


def test_usb_reset_device_writes_zero_then_one_to_authorized():
    run, calls = fake_sudo()
    settled: list[float] = []
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("2-1", "0bda:8812"),
        settle=settled.append,
    )
    assert okay and "2-1" in detail
    assert calls[0][:4] == ("sudo", "-n", "sh", "-c") and "echo 0 > " in calls[0][4]
    assert calls[1][:4] == ("sudo", "-n", "sh", "-c") and "echo 1 > " in calls[1][4]
    assert "/sys/bus/usb/devices/2-1/authorized" in calls[0][4]
    assert settled == [2.0]


def test_usb_reset_device_refuses_a_foreign_usb_id():
    """The keyboard, the NVMe hub, anything else: never touched."""
    run, calls = fake_sudo()
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("4-1.4", "2109:0812"),
        settle=lambda s: None,
    )
    assert not okay and "refusing" in detail and calls == []


def test_usb_reset_device_fails_without_a_node():
    run, calls = fake_sudo()
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: (None, None),
        settle=lambda s: None,
    )
    assert not okay and "no resolvable" in detail and calls == []


def test_usb_reset_device_reports_a_failed_write():
    run, calls = fake_sudo(code=1)
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("2-1", "0bda:8812"),
        settle=lambda s: None,
    )
    assert not okay and "write 0" in detail and len(calls) == 1


def test_usb_reset_action_counts_the_attempt_even_when_it_fails():
    """A failing sudo must still advance the schedule, never storm."""
    run, _ = recording_nmcli()
    state = demoted_after_reset(0.0)
    with mock.patch.object(wd, "usb_reset_device", return_value=(False, "denied")):
        okay = wd.apply_action(
            wd.Action("usb_reset", "wlan1", "x"), ROUTES, state, run=run, now=100.0
        )
    assert not okay
    assert state.usb_attempts["wlan1"] == 1 and state.last_usb_reset["wlan1"] == 100.0


def test_usb_node_of_resolves_the_parent_device(tmp_path, monkeypatch):
    sys_net = tmp_path / "class" / "net" / "wlan1"
    node = tmp_path / "devices" / "usb2" / "2-1"
    iface = node / "2-1:1.0"
    iface.mkdir(parents=True)
    (node / "idVendor").write_text("0bda\n")
    (node / "idProduct").write_text("8812\n")
    sys_net.mkdir(parents=True)
    (sys_net / "device").symlink_to(iface)
    monkeypatch.setattr(wd, "NET_CLASS", tmp_path / "class" / "net")
    assert wd.usb_node_of("wlan1") == ("2-1", "0bda:8812")
    assert wd.usb_node_of("nope0") == (None, None)


# -- second USB reset method: a port reset, in rotation with `authorized` -----


def test_usb_reset_methods_rotate_by_attempt():
    policy = wd.Policy(usb_reset_methods=("authorized", "port_reset"))
    assert [wd.usb_reset_method(policy, n) for n in (1, 2, 3, 4)] == [
        "authorized",
        "port_reset",
        "authorized",
        "port_reset",
    ]
    assert wd.usb_reset_method(wd.Policy(usb_reset_methods=()), 7) == "authorized"


def test_port_reset_issues_usbdevfs_reset_on_the_devfs_node():
    run, calls = fake_sudo()
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("2-1", "0bda:8812"),
        settle=lambda s: None,
        method="port_reset",
        devfs_of=lambda node: Path("/dev/bus/usb/002/003"),
    )
    assert okay and "port reset 2-1" in detail
    assert calls[0][:3] == ("sudo", "-n", "python3")
    script = calls[0][4]
    assert "/dev/bus/usb/002/003" in script and str(wd.USBDEVFS_RESET) in script
    assert "fcntl.ioctl" in script


def test_port_reset_fails_cleanly_without_bus_numbers():
    run, calls = fake_sudo()
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("2-1", "0bda:8812"),
        settle=lambda s: None,
        method="port_reset",
        devfs_of=lambda node: None,
    )
    assert not okay and "busnum/devnum" in detail and calls == []


def test_unknown_reset_method_is_refused():
    run, calls = fake_sudo()
    okay, detail = wd.usb_reset_device(
        "wlan1",
        wd.Policy(),
        run=run,
        node_of=lambda dev: ("2-1", "0bda:8812"),
        settle=lambda s: None,
        method="power_cycle",
    )
    assert not okay and "unknown" in detail and calls == []


def test_usb_devfs_path_reads_bus_and_device_numbers(tmp_path, monkeypatch):
    node = tmp_path / "2-1"
    node.mkdir()
    (node / "busnum").write_text("2\n")
    (node / "devnum").write_text("3\n")
    monkeypatch.setattr(wd, "USB_DEVICES", tmp_path)
    assert wd.usb_devfs_path("2-1") == Path("/dev/bus/usb/002/003")
    assert wd.usb_devfs_path("9-9") is None


def test_second_attempt_uses_the_port_reset(monkeypatch):
    seen: list[str] = []

    def fake_reset(dev, policy, run, method="authorized", **kw):
        seen.append(method)
        return True, method

    monkeypatch.setattr(wd, "usb_reset_device", fake_reset)
    run, _ = recording_nmcli()
    state = demoted_after_reset(0.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    for now in (100.0, 200.0):
        wd.apply_action(
            wd.Action("usb_reset", "wlan1", "x"),
            ROUTES,
            state,
            run=run,
            now=now,
            policy=policy,
        )
    assert seen == ["authorized", "port_reset"]


def test_no_alternative_escalates_to_usb_reset_after_the_reassociation():
    """Both radios dead (2026-09-13 evening: wlan0 in its metal case): the
    in-place reset comes first, then the USB reset on the same schedule."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, usb_reset_schedule=SCHEDULE)
    both_dead = {"wlan1": wedged("wlan1"), "wlan0": wedged("wlan0")}
    devices = {
        "wlan1": dev_info("wlan1", profile="Occom-USB", usb_id="0bda:8812"),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }
    first = wd.evaluate(ROUTES, both_dead, state, policy, now=0.0, devices=devices)
    assert kinds(first) == ["reset", "reset"]  # wlan1 in place, wlan0 standby
    state.last_reset["wlan1"] = 0.0  # what apply_action records
    state.last_reset["wlan0"] = 0.0
    assert (
        wd.evaluate(ROUTES, both_dead, state, policy, now=30.0, devices=devices) == []
    )
    second = wd.evaluate(ROUTES, both_dead, state, policy, now=61.0, devices=devices)
    assert kinds(second) == ["usb_reset"]  # the USB adapter only; wlan0 is built in
    assert second[0].dev == "wlan1" and "no usable alternative" in second[0].reason


def test_in_place_recovery_clears_the_usb_attempt_counter():
    state = wd.State()
    state.usb_attempts["wlan1"] = 4
    good = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    wd.evaluate(ROUTES, good, state, wd.Policy())
    assert "wlan1" not in state.usb_attempts


# -- tier 0: standby repair and profile preference (2026-09-13) --------------
#
# Two findings from the day after the outage. wlan0 sat on a dead 5 GHz link
# at 18:16 and nothing looked at it ("no healthy alternative" waiting to
# happen). And after every reset NetworkManager brought wlan1 up on its
# 2.4 GHz profile (autoconnect-priority 0) although the 5 GHz one (priority
# 20) was in range -- 24 h on the wrong band before anyone noticed.


def pref(dev: str, current: str, target: str | None, visible: bool = True):
    return wd.Preference(dev=dev, current=current, target=target, visible=visible)


def both_healthy() -> dict[str, ProbeResult]:
    return {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}


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


def preference_demotion(since_ts: float) -> wd.State:
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="2026-09-13T11:00:00+00:00",
        reason="moving to preferred profile",
        kind="preference",
        target="Occom-5G-USB",
        target_metric=100,
        since_ts=since_ts,
    )
    state.last_reset["wlan1"] = since_ts
    return state


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


def nm_fake(
    profiles: str = "wlan1:Occom-USB\nwlan0:Occom\n",
    connections: str = "",
    details: dict[str, str] | None = None,
    metrics: dict[str, str] | None = None,
    scans: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
    fail: tuple[str, ...] = (),
    devices: str = "",
    infos: dict[str, str] | None = None,
    radio: str = "enabled",
):
    """A NetworkManager that answers the queries the preference code makes."""
    calls: list[tuple[str, ...]] = []
    details = details or {}
    metrics = metrics or {}
    scans = scans or {}
    links = links or {}
    infos = infos or {}

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        calls.append(args)
        out, code = "", 0
        if args[:3] == ("nmcli", "-t", "-f") and args[3] == "DEVICE,CONNECTION":
            out = profiles
        elif args[:3] == ("nmcli", "-t", "-f") and args[3].startswith("DEVICE,TYPE"):
            out = devices
        elif args[:2] == ("iw", "dev") and args[3:] == ("info",):
            out = infos.get(args[2], "")
            code = 0 if args[2] in infos else 1
        elif args[:4] == ("nmcli", "-t", "radio", "wifi"):
            out = radio
        elif args[:2] == ("systemctl", "is-active") or args[:3] == (
            "systemctl",
            "--user",
            "is-active",
        ):
            out = "active"
        elif args[:3] == ("nmcli", "-t", "-f") and args[3].startswith("NAME,TYPE"):
            out = connections
        elif args[:5] == ("nmcli", "-t", "-g", "STATE", "general"):
            out = "connected"
        elif args[:3] == ("nmcli", "-t", "-g"):
            out = details.get(args[-1], "")
            code = 0 if args[-1] in details else 10
        elif args[:3] == ("nmcli", "-g", "ipv4.route-metric"):
            out = metrics.get(args[-1], "")
            code = 0 if args[-1] in metrics else 10
        elif args[:3] == ("nmcli", "-t", "-f") and args[3] == "SSID":
            out = scans.get(args[8], "")
        elif args[:3] == ("sudo", "-n", "iw") and args[5:] == ("scan",):
            out = scans.get("iw:" + args[4], "")
            code = 0 if "iw:" + args[4] in scans else 1
        elif args[:2] == ("iw", "dev"):
            out = links.get(args[2], "")
            code = 0 if args[2] in links else 1
        if args[1:3] in fail or args[:2] in fail:
            code = 1
        return subprocess.CompletedProcess(list(args), code, stdout=out, stderr="err")

    return run, calls


CONNECTIONS = (
    "Occom-USB:802-11-wireless:wlan1:yes:0\n"
    "Occom:802-11-wireless:wlan0:yes:0\n"
    "Occom-5G-USB:802-11-wireless::yes:20\n"
    "Occom-2.4G:802-11-wireless::yes:0\n"
    "Office:802-11-wireless::yes:50\n"
    "Wired connection 1:802-3-ethernet::yes:-999\n"
)
DETAILS = {
    "Occom-5G-USB": "wlan1\nOccom_5G\n",
    "Occom-2.4G": "wlan0\nOccom_2.4G\n",
    "Office": "eth0\nOffice\n",  # bound to another interface: never a candidate
}


def test_preferences_read_priorities_bindings_and_scan_results():
    run, calls = nm_fake(
        connections=CONNECTIONS,
        details=DETAILS,
        scans={"wlan1": "Occom_2.4G\nOccom_5G\n", "wlan0": "Occom_2.4G\n"},
    )
    prefs = wd.preferences(["wlan1", "wlan0", "eth9"], run)
    assert prefs["wlan1"] == wd.Preference("wlan1", "Occom-USB", "Occom-5G-USB", True)
    # wlan0's alternative has the same priority (0): no preference at all.
    assert prefs["wlan0"] == wd.Preference("wlan0", "Occom", None, False)
    assert "eth9" not in prefs
    assert not any("--rescan" in c and "yes" in c for c in calls)


def test_preferences_report_a_target_out_of_range_and_rescan_on_request():
    run, calls = nm_fake(
        connections=CONNECTIONS, details=DETAILS, scans={"wlan1": "Occom_2.4G\n"}
    )
    prefs = wd.preferences(["wlan1"], run, rescan_for={"wlan1"})
    assert prefs["wlan1"] == wd.Preference("wlan1", "Occom-USB", "Occom-5G-USB", False)
    scan = next(c for c in calls if "wifi" in c)
    assert scan[-2:] == ("--rescan", "yes") and "wlan1" in scan


def test_rescan_also_asks_the_driver_and_merges_the_ssids():
    """2026-09-13: NM's rescan on wlan0 listed only the 5 GHz network twice
    while `iw dev wlan0 scan` saw the 2.4 GHz one; a requested rescan reads
    both. Without `rescan` the driver is not asked."""
    run, calls = nm_fake(
        scans={
            "wlan0": "Occom_1D36_5G\n",
            "iw:wlan0": "BSS aa(on wlan0)\n\tfreq: 2422\n\tSSID: Occom_1D36_2.4G\n",
        }
    )
    assert wd.visible_ssids("wlan0", run) == {"Occom_1D36_5G"}
    assert not any(c[:3] == ("sudo", "-n", "iw") for c in calls)
    assert wd.visible_ssids("wlan0", run, rescan=True) == {
        "Occom_1D36_5G",
        "Occom_1D36_2.4G",
    }
    assert ("sudo", "-n", "iw", "dev", "wlan0", "scan") in calls
    run, _ = nm_fake(scans={"wlan0": "Occom_1D36_5G\n"})  # iw fails: NM list only
    assert wd.visible_ssids("wlan0", run, rescan=True) == {"Occom_1D36_5G"}


def test_preferences_are_empty_when_nmcli_fails():
    run, _ = nm_fake(fail=(("nmcli", "-t"),))
    assert wd.preferences(["wlan1"], run) == {}


def test_split_terse_unescapes_colons_and_backslashes():
    assert wd._split_terse("a\\:b:c") == ["a:b", "c"]
    assert wd._split_terse("plain::x") == ["plain", "", "x"]
    assert wd._split_terse("back\\\\slash:y") == ["back\\slash", "y"]


def test_band_from_the_link_frequency():
    run, _ = nm_fake(links={"wlan1": "Connected to aa:bb (on wlan1)\n\tfreq: 5765.0\n"})
    assert wd.wifi_link_freq("wlan1", run) == 5765
    assert wd.wifi_link_freq("wlan9", run) is None
    assert wd.band_label(5765) == "5 GHz"
    assert wd.band_label(2422) == "2.4 GHz"
    assert wd.band_label(5955) == "6 GHz"
    assert wd.band_label(None) == "?"


def test_preference_demote_raises_both_metrics_and_restore_puts_both_back():
    run, calls = nm_fake(metrics={"Occom-5G-USB": "100"})
    state = wd.State()
    demote = wd.Action(
        "demote",
        "wlan1",
        "moving",
        metric=900,
        profile="Occom-5G-USB",
        tag="preference",
    )
    assert wd.apply_action(demote, ROUTES, state, run=run, now=50.0)
    modifies = [c for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies == [
        ("nmcli", "connection", "modify", "Occom-5G-USB", "ipv4.route-metric", "900"),
        ("nmcli", "connection", "modify", "Occom-USB", "ipv4.route-metric", "900"),
    ]
    d = state.demoted["wlan1"]
    assert d.kind == "preference" and d.target == "Occom-5G-USB"
    assert d.target_metric == 100 and d.since_ts == 50.0

    calls.clear()
    restore = wd.Action("restore", "wlan1", "healthy", metric=100)
    assert wd.apply_action(restore, ROUTES, state, run=run)
    modifies = [c for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies == [
        ("nmcli", "connection", "modify", "Occom-USB", "ipv4.route-metric", "100"),
        ("nmcli", "connection", "modify", "Occom-5G-USB", "ipv4.route-metric", "100"),
    ]
    assert ("nmcli", "device", "reapply", "wlan1") in calls
    assert state.demoted == {}


def test_preference_demote_is_refused_when_the_target_metric_is_unknown():
    """No move without knowing how to undo it."""
    run, calls = nm_fake(metrics={})
    state = wd.State()
    demote = wd.Action(
        "demote",
        "wlan1",
        "moving",
        metric=900,
        profile="Occom-5G-USB",
        tag="preference",
    )
    assert not wd.apply_action(demote, ROUTES, state, run=run)
    assert state.demoted == {}
    assert not any(c[1:3] == ("connection", "modify") for c in calls)


def test_preference_reset_activates_the_target_on_the_device_and_counts():
    run, calls = nm_fake()
    state = wd.State()
    reset = wd.Action("reset", "wlan0", "move", profile="Occom-5G", tag="preference")
    assert wd.apply_action(reset, ROUTES, state, run=run, now=77.0)
    assert ("nmcli", "connection", "up", "id", "Occom-5G", "ifname", "wlan0") in calls
    assert state.prefer_attempts["wlan0"] == 1 and state.last_prefer["wlan0"] == 77.0
    assert state.last_reset["wlan0"] == 77.0
    # A standby or fallback reset with a profile does not count as a move.
    wd.apply_action(
        wd.Action("reset", "wlan0", "x", profile="Occom", tag="fallback"),
        ROUTES,
        state,
        run=run,
        now=99.0,
    )
    assert state.prefer_attempts["wlan0"] == 1


def test_preference_state_persists_and_the_scan_stamp_does_not(tmp_path):
    path = tmp_path / "watchdog.json"
    state = preference_demotion(5.0)
    state.prefer_attempts["wlan1"] = 2
    state.last_prefer["wlan1"] = 4.0
    state.preferred_since["wlan0"] = 3.0
    state.last_scan["wlan1"] = 2.0
    state.last_profiles["wlan1"] = "Occom-USB (2.4 GHz)"
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.prefer_attempts == {"wlan1": 2} and loaded.last_prefer == {
        "wlan1": 4.0
    }
    assert loaded.preferred_since == {"wlan0": 3.0} and loaded.last_scan == {}
    assert loaded.last_profiles == {"wlan1": "Occom-USB (2.4 GHz)"}
    d = loaded.demoted["wlan1"]
    assert d.kind == "preference" and d.target == "Occom-5G-USB" and d.since_ts == 5.0


def test_state_files_from_before_the_preference_tier_still_load(tmp_path):
    path = tmp_path / "watchdog.json"
    path.write_text(
        json.dumps(
            {
                "demoted": {
                    "wlan1": {
                        "dev": "wlan1",
                        "profile": "Occom-USB",
                        "original_metric": 100,
                        "since": "2026-09-12T11:49:51+00:00",
                        "reason": "wedged for 3 cycles",
                    }
                },
                "last_reset": {"wlan1": 1.0},
                "last_cycle": "2026-09-12T11:49:51+00:00",
            }
        )
    )
    loaded = wd.State.load(path)
    assert loaded.demoted["wlan1"].kind == "wedged"
    assert loaded.demoted["wlan1"].target == "" and loaded.prefer_attempts == {}


def test_cycle_reads_preferences_records_profiles_and_moves_the_active_route(
    tmp_path, monkeypatch
):
    """End to end through the loop with a fake NetworkManager: wlan1 is on
    its 2.4 GHz profile, the 5 GHz one (priority 20) is in range."""
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: both_healthy())
    run, calls = nm_fake(
        connections=CONNECTIONS,
        details=DETAILS,
        metrics={"Occom-5G-USB": "100"},
        scans={"wlan1": "Occom_5G\n"},
        links={"wlan1": "\tfreq: 2422.0\n", "wlan0": "\tfreq: 5765.0\n"},
    )
    state = wd.State()
    done = wd.cycle(state, wd.Policy(), path, run=run)
    assert kinds(done) == ["demote", "reset"]
    assert (
        "nmcli",
        "connection",
        "up",
        "id",
        "Occom-5G-USB",
        "ifname",
        "wlan1",
    ) in calls
    written = json.loads(path.read_text())
    assert written["last_profiles"] == {
        "wlan1": "Occom-USB (2.4 GHz)",
        "wlan0": "Occom (5 GHz)",
    }
    assert written["demoted"]["wlan1"]["kind"] == "preference"
    assert written["prefer_attempts"] == {"wlan1": 1}


def test_cycle_rescans_a_device_off_its_best_profile_on_the_interval(
    tmp_path, monkeypatch
):
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: both_healthy())
    run, calls = nm_fake(connections=CONNECTIONS, details=DETAILS, scans={"wlan1": ""})
    state = wd.State()
    policy = wd.Policy(prefer_check_interval_s=300.0)
    assert wd.cycle(state, policy, path, run=run) == []
    rescans = [c for c in calls if "wifi" in c and c[-1] == "yes"]
    assert len(rescans) == 1 and "wlan1" in rescans[0]
    calls.clear()
    assert wd.cycle(state, policy, path, run=run) == []  # within the interval
    assert not any("wifi" in c and c[-1] == "yes" for c in calls)


# -- the reviewed workflow (2026-09-13, user): observe every device, keep the
#    network up first, then bring each radio back to its highest level -------


def dev_info(dev: str, nm_state: str = "connected", **kw) -> wd.DeviceInfo:
    return wd.DeviceInfo(dev=dev, nm_state=nm_state, **kw)


def test_nm_devices_parses_states_and_skips_p2p_entries():
    run, _ = nm_fake(
        devices=(
            "wlan1:wifi:connected:Occom-USB\n"
            "wlan0:wifi:disconnected:\n"
            "lo:loopback:connected (externally):lo\n"
            "p2p-dev-wlan0:wifi-p2p:disconnected:\n"
            "eth0:ethernet:unavailable:\n"
        )
    )
    assert wd.nm_devices(run) == {
        "wlan1": ("connected", "Occom-USB"),
        "wlan0": ("disconnected", ""),
    }


def test_observe_devices_collects_link_and_usb_facts(tmp_path, monkeypatch):
    node = tmp_path / "2-1"
    node.mkdir()
    (node / "speed").write_text("480\n")
    monkeypatch.setattr(wd, "USB_DEVICES", tmp_path)
    monkeypatch.setattr(
        wd,
        "usb_node_of",
        lambda dev: ("2-1", "0bda:8812") if dev == "wlan1" else (None, None),
    )
    run, _ = nm_fake(
        devices="wlan1:wifi:connected:Occom-USB\nwlan0:wifi:disconnected:\n",
        links={
            "wlan1": "\tfreq: 5765.0\n\tsignal: -49 dBm\n\ttx bitrate: 867.0 MBit/s\n"
        },
        infos={"wlan1": "\tchannel 153 (5765 MHz), width: 80 MHz, center1: 5775 MHz\n"},
    )
    devices = wd.observe_devices(run, usb_ids=("0bda:8812",))
    assert devices["wlan1"] == wd.DeviceInfo(
        "wlan1", "connected", "Occom-USB", "0bda:8812", 480, 5765, 80, 867.0, -49
    )
    assert devices["wlan0"] == wd.DeviceInfo("wlan0", "disconnected")
    assert devices["wlan1"].describe(5000) == (
        "connected Occom-USB 5 GHz 80 MHz 867 Mbit/s -49 dBm usb 480 (best 5000)"
    )
    assert devices["wlan0"].describe() == "disconnected"


def test_wifi_link_info_tolerates_a_device_iw_cannot_see():
    run, _ = nm_fake()
    assert wd.wifi_link_info("nope0", run) == (None, None, None, None)


# -- devices without a route


def test_down_device_is_reconnected_to_the_best_profile_in_range():
    """wlan0 fell off at 18:16 and nothing looked; now the standby that is
    not even there is brought back after the threshold, to the profile
    NetworkManager ranks highest among those in range."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=3)
    devices = {"wlan0": dev_info("wlan0", "disconnected")}
    prefs = {"wlan0": pref("wlan0", "", "Occom-5G")}
    probes = {"wlan1": healthy("wlan1")}
    for _ in range(2):
        assert (
            wd.evaluate(
                [WLAN1], probes, state, policy, preferences=prefs, devices=devices
            )
            == []
        )
    (action,) = wd.evaluate(
        [WLAN1], probes, state, policy, preferences=prefs, devices=devices
    )
    assert action.kind == "reset" and action.tag == "down"
    assert action.profile == "Occom-5G" and "disconnected for 3 cycles" in action.reason


def test_down_device_waits_while_nothing_is_in_range():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    devices = {"wlan0": dev_info("wlan0", "disconnected")}
    out_of_range = {"wlan0": pref("wlan0", "", "Occom-5G", visible=False)}
    probes = {"wlan1": healthy("wlan1")}
    assert (
        wd.evaluate(
            [WLAN1], probes, state, policy, preferences=out_of_range, devices=devices
        )
        == []
    )
    assert wd.evaluate([WLAN1], probes, state, policy, devices=devices) == []


def test_connecting_gets_the_longer_threshold():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, connecting_cycles_before_action=3)
    devices = {"wlan0": dev_info("wlan0", "connecting")}
    prefs = {"wlan0": pref("wlan0", "", "Occom-5G")}
    probes = {"wlan1": healthy("wlan1")}
    for _ in range(2):
        assert (
            wd.evaluate(
                [WLAN1], probes, state, policy, preferences=prefs, devices=devices
            )
            == []
        )
    assert kinds(
        wd.evaluate([WLAN1], probes, state, policy, preferences=prefs, devices=devices)
    ) == ["reset"]


def test_down_counter_clears_when_the_device_has_a_route_again():
    state = wd.State()
    policy = wd.Policy(failures_before_action=2)
    down = {"wlan0": dev_info("wlan0", "disconnected")}
    up = {"wlan0": dev_info("wlan0", "connected", profile="Occom")}
    prefs = {"wlan0": pref("wlan0", "", "Occom-5G")}
    wd.evaluate(
        [WLAN1],
        {"wlan1": healthy("wlan1")},
        state,
        policy,
        preferences=prefs,
        devices=down,
    )
    wd.evaluate(ROUTES, both_healthy(), state, policy, devices=up)
    assert state.down_cycles["wlan0"] == 0


def test_unavailable_usb_adapter_gets_a_usb_reset_at_once_after_the_threshold():
    """No radio to speak of (driver, firmware): re-enumerate; it carries
    nothing, so there is nothing to wait for. A built-in radio is left to
    NetworkManager."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    usb_down = {"wlan1": dev_info("wlan1", "unavailable", usb_id="0bda:8812")}
    probes = {"wlan0": healthy("wlan0")}
    (action,) = wd.evaluate([WLAN0], probes, state, policy, devices=usb_down)
    assert action.kind == "usb_reset" and "unavailable" in action.reason
    builtin_down = {"wlan0": dev_info("wlan0", "unavailable")}
    assert (
        wd.evaluate(
            [WLAN1],
            {"wlan1": healthy("wlan1")},
            wd.State(),
            policy,
            devices=builtin_down,
        )
        == []
    )


def test_failed_reconnect_of_a_usb_adapter_escalates_on_the_usb_schedule():
    """2026-09-12 21:51: the 5 GHz profile did not come up after the reset.
    A re-activation that leaves the adapter down is followed by the USB
    schedule, not by another re-activation every five minutes."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, usb_reset_schedule=SCHEDULE)
    devices = {"wlan1": dev_info("wlan1", "disconnected", usb_id="0bda:8812")}
    prefs = {"wlan1": pref("wlan1", "", "Occom-5G-USB")}
    probes = {"wlan0": healthy("wlan0")}
    (first,) = wd.evaluate(
        [WLAN0], probes, state, policy, now=0.0, preferences=prefs, devices=devices
    )
    assert first.kind == "reset" and first.tag == "down"
    state.last_reset["wlan1"] = 0.0
    assert (
        wd.evaluate(
            [WLAN0], probes, state, policy, now=30.0, preferences=prefs, devices=devices
        )
        == []
    )
    (second,) = wd.evaluate(
        [WLAN0], probes, state, policy, now=61.0, preferences=prefs, devices=devices
    )
    assert second.kind == "usb_reset" and "after re-activation" in second.reason


def test_both_radios_down_are_both_repaired():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    devices = {
        "wlan1": dev_info("wlan1", "disconnected", usb_id="0bda:8812"),
        "wlan0": dev_info("wlan0", "disconnected"),
    }
    prefs = {
        "wlan1": pref("wlan1", "", "Occom-5G-USB"),
        "wlan0": pref("wlan0", "", "Occom-5G"),
    }
    actions = wd.evaluate([], {}, state, policy, preferences=prefs, devices=devices)
    assert [(a.kind, a.dev, a.profile) for a in actions] == [
        ("reset", "wlan0", "Occom-5G"),
        ("reset", "wlan1", "Occom-5G-USB"),
    ]


def test_down_repair_can_be_disabled():
    state = wd.State()
    policy = wd.Policy(failures_before_action=1, down_repair=False)
    devices = {"wlan0": dev_info("wlan0", "disconnected")}
    prefs = {"wlan0": pref("wlan0", "", "Occom-5G")}
    assert (
        wd.evaluate(
            [WLAN1],
            {"wlan1": healthy("wlan1")},
            state,
            policy,
            preferences=prefs,
            devices=devices,
        )
        == []
    )


# -- USB link level


def usb_devices(speed: int) -> dict[str, wd.DeviceInfo]:
    return {
        "wlan1": dev_info(
            "wlan1", profile="Occom-USB", usb_id="0bda:8812", usb_speed=speed
        ),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }


def test_usb_level_is_learned_from_what_the_adapter_shows():
    state = wd.State()
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, wd.Policy(), devices=usb_devices(480)
        )
        == []
    )
    assert state.usb_best_speed["wlan1"] == 480
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, wd.Policy(), devices=usb_devices(5000)
        )
        == []
    )
    assert state.usb_best_speed["wlan1"] == 5000


def test_usb_link_below_the_best_level_is_repaired_through_a_demotion():
    """The adapter is the active route: traffic leaves first, every profile
    bound to it is raised, then the re-enumeration."""
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    actions = wd.evaluate(
        ROUTES, both_healthy(), state, wd.Policy(), devices=usb_devices(480)
    )
    assert kinds(actions) == ["demote", "usb_reset"]
    assert actions[0].tag == "usb_speed" and "best seen 5000" in actions[0].reason
    assert actions[1].tag == "usb_speed"


def test_usb_link_repair_on_a_standby_needs_no_demotion():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    routes = [
        Route("wlan0", "192.168.50.1", "192.168.50.222", 100),
        Route("wlan1", "192.168.50.1", "192.168.50.197", 600),
    ]
    actions = wd.evaluate(
        routes, both_healthy(), state, wd.Policy(), devices=usb_devices(480)
    )
    assert kinds(actions) == ["usb_reset"] and actions[0].tag == "usb_speed"


def test_usb_link_repair_never_takes_down_the_only_healthy_route():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    probes = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    policy = wd.Policy(failures_before_action=9)
    assert wd.evaluate(ROUTES, probes, state, policy, devices=usb_devices(480)) == []


def test_usb_link_repair_waits_for_a_healthy_device_and_no_demotion_in_flight():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    probes = {"wlan1": degraded("wlan1"), "wlan0": healthy("wlan0")}
    assert (
        wd.evaluate(ROUTES, probes, state, wd.Policy(), devices=usb_devices(480)) == []
    )
    demoted = demoted_state()
    demoted.usb_best_speed["wlan1"] = 5000
    actions = wd.evaluate(
        routes_demoted(), both_healthy(), demoted, wd.Policy(), devices=usb_devices(480)
    )
    assert "usb_reset" not in kinds(actions)


def test_usb_link_repair_backs_off_and_gives_up():
    """10 min x3, 1 h x3, then the lower level is accepted after six
    attempts -- until the adapter shows the higher one again."""
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    policy = wd.Policy(usb_speed_give_up=6)
    run, _ = recording_nmcli()
    fired: list[float] = []
    now = 0.0
    with mock.patch.object(wd, "usb_reset_device", return_value=(True, "ok")):
        for _ in range(6):
            while True:
                now += 30.0
                actions = wd.evaluate(
                    ROUTES,
                    both_healthy(),
                    state,
                    policy,
                    now=now,
                    devices=usb_devices(480),
                )
                if actions:
                    break
            assert kinds(actions) == ["demote", "usb_reset"]
            wd.apply_action(actions[1], ROUTES, state, run=run, now=now, policy=policy)
            fired.append(now)
    gaps = [b - a for a, b in pairwise(fired)]
    assert gaps == [600, 600, 600, 3600, 3600]
    assert state.usb_speed_attempts["wlan1"] == 6
    # Seventh look: give up, accept 480 as the level, no more resets.
    now += 30_000.0
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, policy, now=now, devices=usb_devices(480)
        )
        == []
    )
    assert (
        state.usb_best_speed["wlan1"] == 480 and "wlan1" not in state.usb_speed_attempts
    )
    # Back at 5000 later: the level is re-learned.
    wd.evaluate(
        ROUTES, both_healthy(), state, policy, now=now + 30, devices=usb_devices(5000)
    )
    assert state.usb_best_speed["wlan1"] == 5000


def test_usb_link_attempts_clear_after_holding_the_best_level():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    state.usb_speed_attempts["wlan1"] = 2
    state.last_usb_speed_reset["wlan1"] = 0.0
    policy = wd.Policy(usb_speed_hold_s=3600.0)
    wd.evaluate(
        ROUTES, both_healthy(), state, policy, now=10.0, devices=usb_devices(5000)
    )
    assert state.usb_speed_attempts["wlan1"] == 2
    wd.evaluate(
        ROUTES, both_healthy(), state, policy, now=3700.0, devices=usb_devices(5000)
    )
    assert "wlan1" not in state.usb_speed_attempts


def test_usb_link_repair_can_be_disabled():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    policy = wd.Policy(usb_speed_repair=False)
    assert (
        wd.evaluate(ROUTES, both_healthy(), state, policy, devices=usb_devices(480))
        == []
    )


def test_usb_level_reset_counts_its_own_attempts():
    run, _ = recording_nmcli()
    state = wd.State()
    with mock.patch.object(wd, "usb_reset_device", return_value=(True, "ok")):
        assert wd.apply_action(
            wd.Action("usb_reset", "wlan1", "level", tag="usb_speed"),
            ROUTES,
            state,
            run=run,
            now=5.0,
        )
    assert (
        state.usb_speed_attempts["wlan1"] == 1
        and state.last_usb_speed_reset["wlan1"] == 5.0
    )
    assert state.usb_attempts == {} and state.last_usb_reset == {}


def test_level_repair_comes_before_the_preference_and_only_one_per_cycle():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G")}
    actions = wd.evaluate(
        ROUTES,
        both_healthy(),
        state,
        wd.Policy(),
        preferences=prefs,
        devices=usb_devices(480),
    )
    assert [(a.kind, a.dev) for a in actions] == [
        ("demote", "wlan1"),
        ("usb_reset", "wlan1"),
    ]


# -- device-level demotion


def test_demotion_raises_every_profile_bound_to_the_device_and_restore_puts_them_back():
    """After the 09-12 21:51 USB reset NetworkManager activated the 2.4 GHz
    profile at metric 100 while the demoted 5 GHz one sat at 900, so the
    fresh link took traffic without passing a single probe."""
    run, calls = nm_fake(
        connections=(
            "Occom-USB:802-11-wireless:wlan1:yes:0\n"
            "Occom-2.4G-USB:802-11-wireless::yes:0\n"
            "Occom:802-11-wireless:wlan0:yes:0\n"
            "Guest:802-11-wireless::yes:0\n"
        ),
        details={
            "Occom-2.4G-USB": "wlan1\nOccom_2.4G\n",
            "Guest": "wlan0\nGuest\n",
            "Occom-USB": "wlan1\nOccom_5G\n",
        },
        metrics={"Occom-2.4G-USB": "100"},
    )
    state = wd.State()
    assert wd.apply_action(
        wd.Action("demote", "wlan1", "wedged", metric=900),
        ROUTES,
        state,
        run=run,
        now=1.0,
    )
    modifies = [c[3:6] for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies == [
        ("Occom-2.4G-USB", "ipv4.route-metric", "900"),
        ("Occom-USB", "ipv4.route-metric", "900"),
    ]
    assert state.demoted["wlan1"].others == {"Occom-2.4G-USB": 100}
    calls.clear()
    assert wd.apply_action(
        wd.Action("restore", "wlan1", "ok", metric=100), ROUTES, state, run=run
    )
    modifies = [c[3:6] for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies == [
        ("Occom-USB", "ipv4.route-metric", "100"),
        ("Occom-2.4G-USB", "ipv4.route-metric", "100"),
    ]
    assert state.demoted == {}


def test_demotion_is_refused_when_a_bound_profile_metric_is_unknown():
    run, calls = nm_fake(
        connections="Occom-USB:802-11-wireless:wlan1:yes:0\nOccom-2.4G-USB:802-11-wireless::yes:0\n",
        details={"Occom-2.4G-USB": "wlan1\nOccom_2.4G\n"},
        metrics={},
    )
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("demote", "wlan1", "x", metric=900), ROUTES, state, run=run
    )
    assert state.demoted == {} and not any(
        c[1:3] == ("connection", "modify") for c in calls
    )


def test_demotion_reverts_raised_profiles_when_the_active_one_fails():
    run, calls = nm_fake(
        connections="Occom-USB:802-11-wireless:wlan1:yes:0\nOccom-2.4G-USB:802-11-wireless::yes:0\n",
        details={"Occom-2.4G-USB": "wlan1\nOccom_2.4G\n"},
        metrics={"Occom-2.4G-USB": "100"},
        fail=(("device", "reapply"),),
    )
    state = wd.State()
    assert not wd.apply_action(
        wd.Action("demote", "wlan1", "x", metric=900), ROUTES, state, run=run
    )
    modifies = [c[3:6] for c in calls if c[1:3] == ("connection", "modify")]
    assert modifies[-1] == ("Occom-2.4G-USB", "ipv4.route-metric", "100")
    assert state.demoted == {}


def test_a_level_demotion_escalates_like_a_wedge_when_the_link_comes_back_dead():
    """After the level reset the link came back dead: the gentle repair
    first (no re-association on record), then the USB schedule from it."""
    state = wd.State()
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="x",
        reason="usb level",
        kind="usb_speed",
        since_ts=0.0,
    )
    state.last_usb_reset["wlan1"] = 0.0
    policy = wd.Policy(usb_reset_schedule=SCHEDULE)
    bad = {"wlan1": wedged("wlan1"), "wlan0": healthy("wlan0")}
    assert kinds(wd.evaluate(routes_demoted(), bad, state, policy, now=30.0)) == [
        "reset"
    ]
    state.last_reset["wlan1"] = 30.0
    assert wd.evaluate(routes_demoted(), bad, state, policy, now=61.0) == []
    assert kinds(wd.evaluate(routes_demoted(), bad, state, policy, now=91.0)) == [
        "usb_reset"
    ]


# -- preferences for a device without an active profile


def test_preferences_list_every_candidate_for_a_down_device():
    run, _ = nm_fake(
        connections=CONNECTIONS.replace(
            "Occom:802-11-wireless:wlan0:yes:0", "Occom:802-11-wireless::yes:0"
        ),
        details={**DETAILS, "Occom": "wlan0\nOccom_5G\n"},
        scans={"wlan0": "Occom_5G\n"},
    )
    prefs = wd.preferences(["wlan0"], run)
    assert prefs["wlan0"] == wd.Preference("wlan0", "", "Occom", True)


# -- persistence, issues, the loop


def test_level_state_persists_and_the_transient_counters_do_not(tmp_path):
    path = tmp_path / "watchdog.json"
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    state.usb_speed_attempts["wlan1"] = 2
    state.last_usb_speed_reset["wlan1"] = 9.0
    state.usb_best_since["wlan1"] = 1.0
    state.down_cycles["wlan0"] = 4
    state.last_devices["wlan1"] = "connected Occom-USB 5 GHz"
    state.issues["wlan1"] = "USB link 480 Mbit/s, best seen 5000"
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1",
        profile="Occom-USB",
        original_metric=100,
        since="x",
        reason="r",
        others={"Occom-2.4G-USB": 100},
    )
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.usb_best_speed == {"wlan1": 5000} and loaded.usb_speed_attempts == {
        "wlan1": 2
    }
    assert loaded.last_usb_speed_reset == {"wlan1": 9.0}
    assert loaded.usb_best_since == {} and loaded.down_cycles == {}
    assert loaded.last_devices == {"wlan1": "connected Occom-USB 5 GHz"}
    assert loaded.issues == {"wlan1": "USB link 480 Mbit/s, best seen 5000"}
    assert loaded.demoted["wlan1"].others == {"Occom-2.4G-USB": 100}


def test_issues_describe_what_is_below_the_highest_level():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    devices = {
        "wlan1": dev_info(
            "wlan1", profile="Occom-2.4G-USB", usb_id="0bda:8812", usb_speed=480
        ),
        "wlan0": dev_info("wlan0", "disconnected"),
    }
    prefs = {"wlan1": pref("wlan1", "Occom-2.4G-USB", "Occom-5G-USB", visible=False)}
    probes = {"wlan1": degraded("wlan1")}
    issues = wd.describe_issues(devices, prefs, probes, state)
    assert issues == {
        "wlan1": (
            "degraded (gateway=ok dns=FAIL tcp=FAIL); USB link 480 Mbit/s, best seen 5000; "
            "on Occom-2.4G-USB, Occom-5G-USB preferred (not in range)"
        ),
        "wlan0": "disconnected",
    }
    assert (
        wd.describe_issues(
            {"wlan1": dev_info("wlan1", profile="x")},
            {},
            {"wlan1": healthy("wlan1")},
            wd.State(),
        )
        == {}
    )


def test_cycle_observes_devices_records_levels_and_issues(tmp_path, monkeypatch):
    """Through the loop with a fake NetworkManager: wlan0 is disconnected
    and its profile is in range -> re-activated; levels and issues land in
    the state file for doctor."""
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([WLAN1], True))
    monkeypatch.setattr(
        wd.uplink, "probe_all", lambda routes, **kw: {"wlan1": healthy("wlan1")}
    )
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    # the service rung is on here: never let it probe the host's real server
    monkeypatch.setattr(wd, "http_alive", lambda url, timeout=5.0: True)
    run, calls = nm_fake(
        profiles="wlan1:Occom-USB\n",
        connections=(
            "Occom-USB:802-11-wireless:wlan1:yes:0\nOccom:802-11-wireless::yes:0\n"
        ),
        details={"Occom": "wlan0\nOccom_5G\n"},
        scans={"wlan0": "Occom_5G\n"},
        devices="wlan1:wifi:connected:Occom-USB\nwlan0:wifi:disconnected:\n",
        links={"wlan1": "\tfreq: 5765.0\n\ttx bitrate: 867.0 MBit/s\n"},
        infos={"wlan1": "\tchannel 153 (5765 MHz), width: 80 MHz\n"},
    )
    state = wd.State()
    policy = wd.Policy(failures_before_action=1)
    done = wd.cycle(state, policy, path, run=run)
    assert [(a.kind, a.dev, a.tag) for a in done] == [("reset", "wlan0", "down")]
    assert ("nmcli", "connection", "up", "id", "Occom", "ifname", "wlan0") in calls
    written = json.loads(path.read_text())
    assert written["last_devices"] == {
        "wlan1": "connected Occom-USB 5 GHz 80 MHz 867 Mbit/s",
        "wlan0": "disconnected",
    }
    assert written["issues"] == {
        "wlan0": "disconnected; on no profile, Occom preferred (in range)"
    }


def test_a_switched_off_wifi_radio_is_switched_back_on_once_per_interval(
    tmp_path, monkeypatch
):
    """Behind a software rfkill every device is 'unavailable' and no rung
    below can help; the loop flips the switch, rate-limited."""
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([], True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: {})
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    run, calls = nm_fake(
        devices="wlan1:wifi:unavailable:\nwlan0:wifi:unavailable:\n", radio="disabled"
    )
    state = wd.State()
    policy = wd.Policy(min_reset_interval_s=300.0)
    wd.cycle(state, policy, path, run=run)
    assert calls.count(("nmcli", "radio", "wifi", "on")) == 1
    assert state.issues["wifi"] == "NetworkManager's Wi-Fi radio is switched off"
    wd.cycle(state, policy, path, run=run)
    assert calls.count(("nmcli", "radio", "wifi", "on")) == 1  # rate-limited
    assert json.loads(path.read_text())["last_radio_on"] == state.last_radio_on > 0
    run_on, calls_on = nm_fake(radio="enabled")
    wd.cycle(wd.State(), policy, path, run=run_on)
    assert not any(c == ("nmcli", "radio", "wifi", "on") for c in calls_on)
    assert wd.wifi_radio_enabled(run_on) is True and wd.wifi_radio_enabled(run) is False


# -- the failure-case review (2026-09-13, user): every scenario we could
#    think of, checked against the code ---------------------------------------


def test_standby_dead_end_is_repaired_only_when_the_active_route_proves_the_upstream():
    """Gateway ok, no TCP: with a healthy active route the standby's problem
    is local (repair it); with the active route dead-ended too it is the
    WAN (leave it)."""
    policy = wd.Policy(failures_before_action=1)
    state = wd.State()
    local = {"wlan1": healthy("wlan1"), "wlan0": degraded("wlan0")}
    (action,) = wd.evaluate(ROUTES, local, state, policy)
    assert action.kind == "reset" and action.tag == "standby"
    assert "no TCP path" in action.reason
    wan = {"wlan1": degraded("wlan1"), "wlan0": degraded("wlan0")}
    assert wd.evaluate(ROUTES, wan, wd.State(), policy) == []


def test_wedged_standby_usb_adapter_escalates_to_the_usb_schedule():
    """Re-association did not revive the standby adapter: the software
    replug, on the schedule, because it carries nothing."""
    routes = [
        Route("wlan0", "192.168.50.1", "192.168.50.222", 100),
        Route("wlan1", "192.168.50.1", "192.168.50.197", 600),
    ]
    devices = {
        "wlan1": dev_info("wlan1", profile="Occom-USB", usb_id="0bda:8812"),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }
    probes = {"wlan0": healthy("wlan0"), "wlan1": wedged("wlan1")}
    policy = wd.Policy(failures_before_action=1, usb_reset_schedule=SCHEDULE)
    state = wd.State()
    (first,) = wd.evaluate(routes, probes, state, policy, now=0.0, devices=devices)
    assert first.kind == "reset" and first.tag == "standby"
    state.last_reset["wlan1"] = 0.0
    assert wd.evaluate(routes, probes, state, policy, now=30.0, devices=devices) == []
    (second,) = wd.evaluate(routes, probes, state, policy, now=61.0, devices=devices)
    assert second.kind == "usb_reset" and "standby still wedged" in second.reason
    # The built-in radio as a wedged standby never gets a USB reset: a new
    # failure streak gets its one re-association (past the floor), no more.
    builtin = {"wlan0": dev_info("wlan0", profile="Occom"), "wlan1": devices["wlan1"]}
    s2 = wd.State()
    s2.last_reset["wlan0"] = 0.0
    p2 = {"wlan1": healthy("wlan1"), "wlan0": wedged("wlan0")}
    assert kinds(wd.evaluate(ROUTES, p2, s2, policy, now=61.0, devices=builtin)) == [
        "reset"
    ]
    s2.last_reset["wlan0"] = 61.0
    assert wd.evaluate(ROUTES, p2, s2, policy, now=200.0, devices=builtin) == []


def test_demoted_dead_end_reassociates_and_never_usb_resets():
    state = demoted_after_reset(0.0)
    policy = wd.Policy(usb_reset_schedule=SCHEDULE, min_reset_interval_s=300.0)
    probes = {"wlan1": degraded("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), probes, state, policy, now=61.0) == []
    (action,) = wd.evaluate(routes_demoted(), probes, state, policy, now=301.0)
    assert action.kind == "reset" and "without a TCP path" in action.reason


def test_probes_unavailable_means_no_action_at_all():
    """A probe that cannot run (SO_BINDTODEVICE refused) is unknown, not a
    dead route: no failover, no reset storm, and a demotion stays put."""
    unknown = {
        "wlan1": ProbeResult(dev="wlan1", errors={"probe": "cannot bind"}),
        "wlan0": ProbeResult(dev="wlan0", errors={"probe": "cannot bind"}),
    }
    policy = wd.Policy(failures_before_action=1)
    assert wd.evaluate(ROUTES, unknown, wd.State(), policy) == []
    assert (
        wd.evaluate(
            routes_demoted(), unknown, demoted_after_reset(0.0), policy, now=999.0
        )
        == []
    )


# -- driver reload (non-USB radio), off by default


def test_driver_reload_is_off_by_default_and_paced_when_on():
    devices = {
        "wlan0": dev_info("wlan0", "unavailable"),
        "wlan1": dev_info("wlan1", profile="Occom-USB", usb_id="0bda:8812"),
    }
    probes = {"wlan1": healthy("wlan1")}
    off = wd.Policy(failures_before_action=1)
    assert wd.evaluate([WLAN1], probes, wd.State(), off, devices=devices) == []
    on = wd.Policy(
        failures_before_action=1,
        driver_reload_enabled=True,
        usb_reset_schedule=SCHEDULE,
    )
    state = wd.State()
    (action,) = wd.evaluate([WLAN1], probes, state, on, now=0.0, devices=devices)
    assert action.kind == "reload" and "unavailable" in action.reason
    state.last_reload["wlan0"] = 0.0
    state.reload_attempts["wlan0"] = 1
    assert wd.evaluate([WLAN1], probes, state, on, now=30.0, devices=devices) == []
    (again,) = wd.evaluate([WLAN1], probes, state, on, now=61.0, devices=devices)
    assert again.kind == "reload" and "attempt 2" in again.reason


def test_driver_reload_never_targets_a_usb_adapter():
    devices = {"wlan1": dev_info("wlan1", "unavailable", usb_id="0bda:8812")}
    on = wd.Policy(
        failures_before_action=1, driver_reload_enabled=True, usb_reset_enabled=False
    )
    assert (
        wd.evaluate(
            [WLAN0], {"wlan0": healthy("wlan0")}, wd.State(), on, devices=devices
        )
        == []
    )


def test_driver_reload_unloads_holders_first_then_reloads_the_module(
    tmp_path, monkeypatch
):
    """Proven on the Pi 5 2026-09-13: sysfs unbind/bind left the built-in
    radio's bus down; `modprobe -r brcmfmac_cyw brcmfmac && modprobe
    brcmfmac` brought it back."""
    net = tmp_path / "class" / "net" / "wlan0"
    device = tmp_path / "devices" / "mmc1:0001:1"
    driver = tmp_path / "bus" / "sdio" / "drivers" / "brcmfmac"
    module = tmp_path / "module" / "brcmfmac"
    (module / "holders").mkdir(parents=True)
    (module / "holders" / "brcmfmac_cyw").symlink_to(
        tmp_path / "module" / "brcmfmac_cyw"
    )
    driver.mkdir(parents=True)
    (driver / "module").symlink_to(module)
    device.mkdir(parents=True)
    (device / "driver").symlink_to(driver)
    net.mkdir(parents=True)
    (net / "device").symlink_to(device)
    monkeypatch.setattr(wd, "NET_CLASS", tmp_path / "class" / "net")
    monkeypatch.setattr(wd, "SYS_MODULE", tmp_path / "module")
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    assert wd.driver_of("wlan0") == ("mmc1:0001:1", str(driver))
    assert wd.driver_module_of("wlan0") == ("brcmfmac", ["brcmfmac_cyw"])
    run, calls = fake_sudo()
    okay, detail = wd.driver_reload("wlan0", run)
    assert okay and "reloaded brcmfmac (after brcmfmac_cyw)" == detail
    assert calls[0][:4] == ("sudo", "-n", "sh", "-c")
    assert calls[0][4] == "modprobe -r brcmfmac_cyw brcmfmac && modprobe brcmfmac"
    failing, _ = fake_sudo(code=1)
    okay, detail = wd.driver_reload("wlan0", failing)
    assert not okay and "reload of brcmfmac failed" in detail
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: ("2-1", "0bda:8812"))
    okay, detail = wd.driver_reload("wlan0", run)
    assert not okay and "USB" in detail
    assert wd.driver_module_of("nope0") == (None, [])
    state = wd.State()
    monkeypatch.setattr(wd, "driver_reload", lambda dev, run: (True, "ok"))
    assert wd.apply_action(
        wd.Action("reload", "wlan0", "x"), ROUTES, state, run=run, now=4.0
    )
    assert state.reload_attempts["wlan0"] == 1 and state.last_reload["wlan0"] == 4.0


# -- services: the two processes between the uplink and ChatGPT


def obs(**kw: Any) -> wd.ServiceObservation:
    base = wd.ServiceObservation(
        mcp_unit="binnacle-mcp.service",
        endpoint_ok=True,
        tunnel_active=True,
        poll_failures=0,
        poll_failing_since=None,
    )
    return replace(base, **kw)


def test_server_is_restarted_when_its_port_stops_answering_while_active():
    policy = wd.Policy(
        service_failures_before_action=3, service_restart_interval_s=900.0
    )
    state = wd.State()
    dead = obs(endpoint_ok=False)
    assert wd.evaluate_services(dead, state, policy, now=0.0) == []
    assert wd.evaluate_services(dead, state, policy, now=30.0) == []
    ((unit, reason),) = wd.evaluate_services(dead, state, policy, now=60.0)
    assert unit == "binnacle-mcp.service" and "not answering for 3 cycles" in reason
    state.last_service_restart["mcp"] = 60.0
    assert wd.evaluate_services(dead, state, policy, now=90.0) == []  # rate limit
    assert wd.evaluate_services(obs(), state, policy, now=120.0) == []
    assert state.service_failures["mcp"] == 0


def test_a_stopped_server_unit_is_never_started():
    policy = wd.Policy(service_failures_before_action=1)
    stopped = obs(mcp_unit=None, endpoint_ok=None)
    assert wd.evaluate_services(stopped, wd.State(), policy, now=0.0) == []


def test_tunnel_is_restarted_only_after_long_failure_on_a_healthy_uplink():
    policy = wd.Policy(service_failures_before_action=3, tunnel_restart_after_s=300.0)
    failing = obs(poll_failures=5, poll_failing_since=0.0)
    state = wd.State()
    state.uplink_ok_cycles = 10
    assert wd.evaluate_services(failing, state, policy, now=200.0) == []  # too short
    ((unit, reason),) = wd.evaluate_services(failing, state, policy, now=400.0)
    assert unit == "binnacle-tunnel.service" and "healthy for 10 cycles" in reason
    bad_uplink = wd.State()
    bad_uplink.uplink_ok_cycles = 1  # the uplink is the problem: leave the tunnel alone
    assert wd.evaluate_services(failing, bad_uplink, policy, now=400.0) == []
    inactive = obs(tunnel_active=False, poll_failures=9, poll_failing_since=0.0)
    assert wd.evaluate_services(inactive, state, policy, now=9000.0) == []


def test_service_repair_can_be_disabled():
    policy = wd.Policy(service_repair=False, service_failures_before_action=1)
    assert (
        wd.evaluate_services(obs(endpoint_ok=False), wd.State(), policy, now=0.0) == []
    )


def test_observe_services_reads_units_endpoint_and_the_tunnel_log(tmp_path):
    log = tmp_path / "binnacle.log"
    log.write_text(
        '{"time":"2026-09-13T22:00:00.123456789+10:00","level":"INFO","msg":"poll failed; backing off"}\n'
        '{"time":"2026-09-13T22:00:30.000+10:00","level":"INFO","msg":"poll failed; backing off"}\n'
    )
    policy = wd.Policy(
        tunnel_log=log, mcp_units=("binnacle-mcp.service", "binnacle-mcp-dev.service")
    )

    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        out = ""
        if args[:3] == ("systemctl", "--user", "is-active"):
            out = (
                "active"
                if args[3] in ("binnacle-mcp-dev.service", "binnacle-tunnel.service")
                else "inactive"
            )
        return subprocess.CompletedProcess(list(args), 0, stdout=out, stderr="")

    seen = wd.observe_services(policy, run, alive=lambda url: url.endswith("/mcp"))
    assert seen.mcp_unit == "binnacle-mcp-dev.service" and seen.endpoint_ok is True
    assert seen.tunnel_active and seen.poll_failures == 2
    assert seen.poll_failing_since == wd._rfc3339_epoch(
        "2026-09-13T22:00:00.123456789+10:00"
    )
    assert wd._rfc3339_epoch(
        "2026-09-13T22:00:00.123456789+10:00"
    ) == wd._rfc3339_epoch("2026-09-13T22:00:00.123456+10:00")
    assert wd._rfc3339_epoch("") is None and wd._rfc3339_epoch("nope") is None


def test_http_alive_treats_any_http_status_as_alive():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(401)
            self.end_headers()

        def log_message(self, *a):  # silence
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert wd.http_alive(f"http://127.0.0.1:{server.server_port}/mcp", timeout=3.0)
    finally:
        server.shutdown()
    assert not wd.http_alive(f"http://127.0.0.1:{server.server_port}/mcp", timeout=1.0)


# -- absent adapters, stranded metrics, self-liveness


def test_stranded_metric_is_reported_when_no_demotion_covers_it():
    run, _ = nm_fake(
        connections="Occom-USB:802-11-wireless:wlan1:yes:0\nOccom:802-11-wireless:wlan0:yes:0\n",
        metrics={"Occom-USB": "900", "Occom": "600"},
    )
    found = wd.stranded_metrics(wd.State(), wd.Policy(demoted_metric=900), run)
    assert (
        list(found) == ["profile:Occom-USB"]
        and "no demotion on record" in found["profile:Occom-USB"]
    )
    covered = demoted_state()  # wlan1's Occom-USB is demoted on record
    assert wd.stranded_metrics(covered, wd.Policy(demoted_metric=900), run) == {}


def test_usb_adapter_on_the_bus_without_a_netdev_is_reported(tmp_path, monkeypatch):
    for node, has_net in (("2-1", False), ("4-1.4", True)):
        d = tmp_path / node
        d.mkdir()
        (d / "idVendor").write_text("0bda\n")
        (d / "idProduct").write_text("8812\n")
        iface = d / f"{node}:1.0"
        iface.mkdir()
        if has_net:
            (iface / "net").mkdir()
    (tmp_path / "usb2").mkdir()  # a hub without ids: skipped
    monkeypatch.setattr(wd, "USB_DEVICES", tmp_path)
    found = wd.usb_adapters_without_netdev(("0bda:8812",))
    assert list(found) == ["usb:2-1"] and "driver not bound" in found["usb:2-1"]
    assert wd.usb_adapters_without_netdev(("ffff:0000",)) == {}


def test_cycle_reports_an_adapter_that_vanished(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([WLAN0], True))
    monkeypatch.setattr(
        wd.uplink, "probe_all", lambda routes, **kw: {"wlan0": healthy("wlan0")}
    )
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    monkeypatch.setattr(wd, "usb_adapters_without_netdev", lambda ids: {})
    state = wd.State()
    state.known_devices["wlan1"] = "0bda:8812"
    run, _ = nm_fake(profiles="wlan0:Occom\n", devices="wlan0:wifi:connected:Occom\n")
    policy = wd.Policy(service_repair=False)
    wd.cycle(state, policy, path, run=run)
    written = json.loads(path.read_text())
    assert written["issues"]["wlan1"].startswith(
        "absent: not seen by NetworkManager (0bda:8812)"
    )
    assert written["last_devices"]["wlan1"] == "absent"
    assert written["known_devices"] == {"wlan1": "0bda:8812", "wlan0": "builtin"}


def test_a_hung_cycle_makes_the_process_exit_for_systemd(tmp_path, monkeypatch):
    """A watchdog that is alive and stuck is the outage shape itself."""
    import threading

    release = threading.Event()

    def hang(*a, **k):
        release.wait(5.0)

    monkeypatch.setattr(wd, "cycle", hang)
    exits: list[int] = []
    run, _ = recording_nmcli()
    wd.run_forever(
        tmp_path / "s.json",
        interval_s=1,
        policy=wd.Policy(cycle_timeout_s=0.2),
        sleep=lambda s: None,
        max_cycles=3,
        exit_fn=exits.append,
        run=run,
    )
    release.set()
    assert exits == [3]


# -- second review + logging (2026-09-13 night): grades, decisions, the
#    journal as the record --------------------------------------------------


def test_grade_of_orders_the_states():
    assert wd.grade_of(healthy("wlan1"), dev_info("wlan1"), True) == "healthy"
    assert wd.grade_of(lossy("wlan1"), dev_info("wlan1"), True) == "degraded"
    assert wd.grade_of(degraded("wlan1"), dev_info("wlan1"), True) == "dead_end"
    assert wd.grade_of(wedged("wlan1"), dev_info("wlan1"), True) == "wedged"
    assert wd.grade_of(None, dev_info("wlan0"), False) == "no_route"
    assert wd.grade_of(None, dev_info("wlan0", "connecting"), False) == "connecting"
    assert wd.grade_of(None, dev_info("wlan0", "disconnected"), False) == "disconnected"
    assert wd.grade_of(None, dev_info("wlan0", "unavailable"), False) == "unavailable"
    assert wd.grade_of(None, None, False) == "absent"
    unknown = ProbeResult(dev="wlan1", errors={"probe": "cannot bind"})
    assert wd.grade_of(unknown, dev_info("wlan1"), True) == "unknown"
    assert (
        wd.grade_rank("healthy") < wd.grade_rank("degraded") < wd.grade_rank("wedged")
    )
    assert wd.grade_rank("nonsense") > wd.grade_rank("unknown")


def test_evaluate_explains_what_it_declined():
    """Every rung that looks at a device and does nothing says why."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=3)
    wd.evaluate(ROUTES, outage(), state, policy)
    assert ("wlan1", "failover", "wedged 1/3 cycles") in state.decisions
    both_dead = {"wlan1": degraded("wlan1"), "wlan0": degraded("wlan0")}
    state = wd.State()
    for _ in range(3):
        wd.evaluate(ROUTES, both_dead, state, wd.Policy(failures_before_action=3))
    notes = [n for d, r, n in state.decisions if d == "wlan1" and r == "failover"]
    assert notes and "WAN is suspected" in notes[-1]
    prefs = {"wlan0": pref("wlan0", "Occom-2.4G", "Occom-5G", visible=False)}
    state = wd.State()
    wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), preferences=prefs)
    assert (
        "wlan0",
        "preference",
        "on Occom-2.4G, Occom-5G preferred; target not in range",
    ) in state.decisions
    state = demoted_state()
    wd.evaluate(
        routes_demoted(), both_healthy(), state, wd.Policy(successes_before_restore=3)
    )
    assert (
        "wlan1",
        "restore",
        "demoted (wedged); healthy 1/3 cycles",
    ) in state.decisions


def test_connected_without_a_default_route_is_reactivated_after_the_threshold():
    """A DHCP offer without a router, or a deleted route: the device is
    'connected' and useless; re-activating the profile re-runs the IP
    configuration."""
    state = wd.State()
    policy = wd.Policy(failures_before_action=2, connecting_cycles_before_action=2)
    devices = {"wlan0": dev_info("wlan0", "connected", profile="Occom")}
    probes = {"wlan1": healthy("wlan1")}
    assert wd.evaluate([WLAN1], probes, state, policy, devices=devices) == []
    assert (
        "wlan0",
        "down",
        "connected without a default route 1/2 cycles",
    ) in state.decisions
    (action,) = wd.evaluate([WLAN1], probes, state, policy, devices=devices)
    assert (
        action.kind == "reset"
        and action.tag == "no_route"
        and action.profile == "Occom"
    )


def test_no_route_reset_leaves_a_never_default_profile_alone():
    run, calls = nm_fake(details={}, metrics={})

    def run2(*args: str, **kw) -> subprocess.CompletedProcess:
        if args[:3] == ("nmcli", "-g", "ipv4.never-default"):
            calls.append(args)
            return subprocess.CompletedProcess(list(args), 0, stdout="yes\n", stderr="")
        return run(*args, **kw)

    state = wd.State()
    okay = wd.apply_action(
        wd.Action("reset", "wlan0", "no route", profile="Occom", tag="no_route"),
        ROUTES,
        state,
        run=run2,
        now=1.0,
    )
    assert not okay and not any(c[1:3] == ("connection", "up") for c in calls)
    assert state.last_reset["wlan0"] == 1.0  # still rate-limited


# -- the system services under the uplink


def sys_obs(**kw: Any) -> wd.SystemObservation:
    return replace(wd.SystemObservation(), **kw)


def test_networkmanager_is_restarted_when_inactive_or_silent():
    policy = wd.Policy(
        service_failures_before_action=3, service_restart_interval_s=900.0
    )
    state = wd.State()
    for now in (0.0, 30.0):
        assert (
            wd.evaluate_system(sys_obs(nm_active=False), state, policy, now=now) == []
        )
    ((unit, reason),) = wd.evaluate_system(
        sys_obs(nm_active=False), state, policy, now=60.0
    )
    assert unit == "NetworkManager.service" and "not active" in reason
    state.last_system_restart["nm"] = 60.0
    assert wd.evaluate_system(sys_obs(nm_active=False), state, policy, now=100.0) == []
    silent = wd.State()
    quiet = sys_obs(nm_responsive=False)
    assert wd.evaluate_system(quiet, silent, policy, now=0.0) == []
    assert wd.evaluate_system(quiet, silent, policy, now=30.0) == []
    ((unit, reason),) = wd.evaluate_system(quiet, silent, policy, now=60.0)
    assert (
        unit == "NetworkManager.service" and "answered nothing for 3 cycles" in reason
    )
    assert wd.evaluate_system(sys_obs(), silent, policy, now=90.0) == []
    assert silent.nm_unresponsive_cycles == 0


def test_supplicant_is_restarted_only_when_a_radio_is_unavailable():
    policy = wd.Policy()
    state = wd.State()
    assert (
        wd.evaluate_system(sys_obs(supplicant_active=False), state, policy, now=0.0)
        == []
    )
    ((unit, _),) = wd.evaluate_system(
        sys_obs(supplicant_active=False, any_unavailable=True), state, policy, now=0.0
    )
    assert unit == "wpa_supplicant.service"
    off = wd.Policy(system_service_repair=False)
    assert wd.evaluate_system(sys_obs(nm_active=False), wd.State(), off, now=0.0) == []


def test_observe_system_reads_the_units_and_the_device_states():
    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        out = ""
        if args[:2] == ("systemctl", "is-active"):
            out = "active" if args[2] == "NetworkManager.service" else "inactive"
        return subprocess.CompletedProcess(list(args), 0, stdout=out, stderr="")

    devices = {"wlan0": dev_info("wlan0", "unavailable")}
    seen = wd.observe_system(wd.Policy(), devices, nm_answered=True, run=run)
    assert seen == wd.SystemObservation(True, True, False, True)


# -- host power and thermal


def test_host_health_decodes_the_throttle_flags():
    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        out = {
            "get_throttled": "throttled=0x50005\n",
            "measure_temp": "temp=61.2'C\n",
        }.get(args[1], "")
        return subprocess.CompletedProcess(
            list(args), 0 if out else 1, stdout=out, stderr=""
        )

    health = wd.host_health(run)
    assert health["throttled"] == "0x50005" and health["temp"] == "61.2'C"
    assert (
        health["flags"]
        == "under-voltage now, throttled now, under-voltage occurred, throttled occurred"
    )
    absent, _ = fake_sudo(code=1)
    assert wd.host_health(absent) == {}


# -- pause switch


def test_pause_file_holds_every_action_and_expires(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    pause = tmp_path / "watchdog.pause"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    run, calls = nm_fake()
    policy = wd.Policy(
        failures_before_action=1,
        pause_file=pause,
        service_repair=False,
        system_service_repair=False,
    )
    import time as _time

    pause.write_text(f"{_time.time() + 600:.0f}\n")
    state = wd.State()
    assert wd.cycle(state, policy, path, run=run) == []
    assert not any(c[1:3] == ("connection", "modify") for c in calls)
    assert state.issues["watchdog"].startswith("paused until")
    assert wd.pause_until(pause) is not None
    pause.write_text("1\n")  # expired long ago
    assert wd.pause_until(pause) is None and not pause.exists()
    assert wd.pause_until(None) is None
    done = wd.cycle(state, policy, path, run=run)
    assert "demote" in kinds(done)


# -- inventory


def test_inventory_line_pins_down_the_device(tmp_path, monkeypatch):
    module = tmp_path / "module" / "rtl8812au"
    (module / "parameters").mkdir(parents=True)
    (module / "parameters" / "rtw_switch_usb_mode").write_text("1\n")
    driver = tmp_path / "drivers" / "rtl8812au"
    driver.mkdir(parents=True)
    (driver / "module").symlink_to(module)
    (driver / "unbind").write_text("")
    device = tmp_path / "devices" / "2-1:1.0"
    device.mkdir(parents=True)
    (device / "driver").symlink_to(driver)
    net = tmp_path / "class" / "net" / "wlan1"
    net.mkdir(parents=True)
    (net / "device").symlink_to(device)
    monkeypatch.setattr(wd, "NET_CLASS", tmp_path / "class" / "net")
    monkeypatch.setattr(wd, "SYS_MODULE", tmp_path / "module")
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: ("2-1", "0bda:8812"))
    run, _ = nm_fake(
        connections="Occom-USB:802-11-wireless:wlan1:yes:20\nOccom-2.4G-USB:802-11-wireless::yes:0\nOccom:802-11-wireless:wlan0:yes:0\n",
        details={
            "Occom-USB": "wlan1\nOccom_5G\n",
            "Occom-2.4G-USB": "wlan1\nOccom_2.4G\n",
            "Occom": "wlan0\nOccom_5G\n",
        },
        metrics={"Occom-USB": "100", "Occom-2.4G-USB": "100"},
    )
    info = dev_info("wlan1", profile="Occom-USB", usb_id="0bda:8812", usb_speed=5000)
    line = wd.inventory_line(
        "wlan1", info, wd.wifi_profiles(run), run, ("rtw_switch_usb_mode",)
    )
    assert line == (
        "kind=usb:0bda:8812@2-1:5000Mbit driver=rtl8812au module=rtl8812au "
        "params=rtw_switch_usb_mode=1 profiles=Occom-USB:prio20:metric100:auto;"
        "Occom-2.4G-USB:prio0:metric100:auto"
    )
    assert wd.module_params(None, ("x",)) == {}


def test_versions_are_collected_without_crashing():
    run, _ = fake_sudo(code=1)
    seen = wd.versions(run)
    assert set(seen) == {"python", "binnacle", "kernel", "networkmanager"}


def test_cycle_logs_transitions_decisions_and_the_summary_line(
    tmp_path, monkeypatch, caplog
):
    """The journal must carry: a `cycle` line every cycle, a `transition`
    when a grade changes, a `decision` while a rung waits, an
    `inventory` line at the start, and a `snapshot`."""
    import logging as _logging

    path = tmp_path / "watchdog.json"
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: probes)
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    monkeypatch.setattr(wd, "usb_adapters_without_netdev", lambda ids: {})
    run, _ = nm_fake(
        devices="wlan1:wifi:connected:Occom-USB\nwlan0:wifi:connected:Occom\n"
    )
    state = wd.State()
    policy = wd.Policy(
        failures_before_action=3, service_repair=False, system_service_repair=False
    )
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.cycle(state, policy, path, run=run)
        probes["wlan0"] = wedged("wlan0")
        wd.cycle(state, policy, path, run=run)
    text = caplog.text
    assert "event=cycle cycle=1 " in text and "event=cycle cycle=2 " in text
    assert "event=transition cycle=1 dev=wlan1 from=- to=healthy" in text
    assert "event=transition cycle=2 dev=wlan0 from=healthy to=wedged" in text
    assert (
        "event=decision cycle=2 dev=wlan0 rung=standby note=wedged 1/3 cycles" in text
    )
    assert "event=inventory cycle=1 dev=wlan1 kind=builtin" in text
    assert "event=snapshot cycle=1 dev=wlan1 grade=healthy" in text
    assert "event=inventory_host cycle=1" in text
    assert (
        state.last_grade == {"wlan1": "healthy", "wlan0": "wedged"}
        and state.cycle_n == 2
    )
    written = json.loads(path.read_text())
    assert written["cycle_n"] == 2 and written["last_grade"]["wlan0"] == "wedged"


# -- the fourth review (2026-09-13 night): the audit's findings --------------


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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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
    monkeypatch.setattr(wd, "observe_devices", lambda run, usb_ids: {})
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


# -- 2026-09-14: the no-route rung must never re-activate the radios en masse


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
    """The conftest guard refuses mutating commands; a real `nmcli
    connection up` from a test fails the test (the 2026-09-13 23:49 lesson)."""
    import subprocess as sp

    proc = sp.run(
        ["nmcli", "-t", "-f", "DEVICE", "device", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "blocked" not in proc.stderr  # a read-only command still runs
    # tests/ is an explicit local package, so this import cannot resolve to
    # a third-party package that also happens to be named tests.
    from tests.conftest import _is_mutating

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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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


# -- three radios (2026-09-14: a second USB adapter, RTL8188EU on wlan2 at
#    metric 300, between wlan1 (100) and the built-in wlan0 (600))

WLAN2 = Route(dev="wlan2", gateway="192.168.50.1", src="192.168.50.231", metric=300)
THREE = [WLAN1, WLAN2, WLAN0]


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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
    run, calls = nm_fake(connections=CONNECTIONS, details=DETAILS, scans={"wlan1": ""})
    policy = wd.Policy(
        failures_before_action=9, service_repair=False, system_service_repair=False
    )
    wd.cycle(wd.State(), policy, path, run=run)
    assert not any("wifi" in c and c[-1] == "yes" for c in calls)


# -- the fast path (2026-09-14, "under one minute") ---------------------------


def fast_env(monkeypatch, routes=None):
    monkeypatch.setattr(
        wd.uplink, "read_default_routes", lambda run: (routes or ROUTES, True)
    )
    monkeypatch.setitem(wd.uplink._last_address, "api.openai.com", "172.66.0.243")


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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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


# -- the fifth review (2026-09-14 night): socket affinity, flap damping,
#    per-episode escalation, the lock, the heartbeat, readiness, the journal


SS_ON_WLAN2 = (
    '0 0 192.168.50.231:47664 172.66.0.243:443 users:(("tunnel-client",pid=1234,fd=10))\n'
    '0 0 192.168.50.231:5555 10.0.0.1:443 users:(("chrome",pid=99,fd=3))\n'
    '0 0 127.0.0.1:46232 127.0.0.1:8000 users:(("tunnel-client",pid=1234,fd=11))\n'
)


def socket_fake(inner, pid: str = "1234", ss: str = "", addr: str = ""):
    """Wrap a run fake with answers for the tunnel-socket queries."""

    def run(*args: str, **kw) -> subprocess.CompletedProcess:
        if args[:3] == ("systemctl", "--user", "show") and "MainPID" in args:
            return subprocess.CompletedProcess(list(args), 0, stdout=pid, stderr="")
        if args[:2] == ("ss", "-tnpH"):
            return subprocess.CompletedProcess(list(args), 0, stdout=ss, stderr="")
        if args[:4] == ("ip", "-o", "-4", "addr"):
            return subprocess.CompletedProcess(list(args), 0, stdout=addr, stderr="")
        return inner(*args, **kw)

    return run


def all_healthy() -> dict[str, ProbeResult]:
    return {d: healthy(d) for d in ("wlan1", "wlan2", "wlan0")}


def test_tunnel_sockets_map_the_local_address_to_a_device():
    run = socket_fake(nm_fake()[0], ss=SS_ON_WLAN2)
    (sock,) = wd.tunnel_sockets("binnacle-tunnel.service", THREE, run)
    assert sock.dev == "wlan2" and sock.peer.endswith(":443")
    assert wd.tunnel_via([sock], "wlan1") == "wlan2"
    assert wd.tunnel_via([sock], "wlan2") == "wlan2"
    # an address the routes do not know but a device holds
    by_addr = socket_fake(
        nm_fake()[0],
        ss=SS_ON_WLAN2.replace("192.168.50.231", "10.9.9.9"),
        addr="7: wlan9    inet 10.9.9.9/24 brd 10.9.9.255 scope global wlan9\n",
    )
    (other,) = wd.tunnel_sockets("binnacle-tunnel.service", THREE, by_addr)
    assert other.dev == "wlan9"
    # an address nobody holds
    orphan_run = socket_fake(
        nm_fake()[0], ss=SS_ON_WLAN2.replace("192.168.50.231", "10.9.9.9")
    )
    (orphan,) = wd.tunnel_sockets("binnacle-tunnel.service", THREE, orphan_run)
    assert orphan.dev is None and wd.tunnel_via([orphan], "wlan1") == "?"
    assert wd.tunnel_sockets("u", THREE, socket_fake(nm_fake()[0], pid="0")) is None
    assert wd.tunnel_sockets("u", THREE, nm_fake()[0]) == []  # unknown pid
    assert wd.tunnel_via(None, "wlan1") is None and wd.tunnel_via([], "wlan1") is None


def test_affinity_restarts_the_tunnel_at_once_when_its_socket_path_is_dead(caplog):
    import logging as _logging

    inner, calls = nm_fake()
    run = socket_fake(inner, ss=SS_ON_WLAN2)
    state = wd.State()
    policy = wd.Policy()
    probes = {
        "wlan1": healthy("wlan1"),
        "wlan2": wedged("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        via = wd.tunnel_affinity_check(
            state, policy, run, THREE, probes, obs(), 7, 100.0
        )
        assert via == "wlan2"
        assert ("systemctl", "--user", "restart", "binnacle-tunnel.service") in calls
        assert (
            "affinity: the poller's connection is on wlan2, which has no TCP path; "
            "wlan1 is the active route" in caplog.text
        )
        assert (
            state.last_tunnel_restart == 100.0 and state.tunnel_off_active_cycles == 0
        )
        calls.clear()
        wd.tunnel_affinity_check(state, policy, run, THREE, probes, obs(), 8, 105.0)
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)
    assert "restarted 5 s ago" in caplog.text
    # both dead: nothing to move to
    both = {
        "wlan1": wedged("wlan1"),
        "wlan2": wedged("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    fresh = wd.State()
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.tunnel_affinity_check(fresh, policy, run, THREE, both, obs(), 9, 200.0)
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)
    assert "wlan1 has no TCP path either" in caplog.text


def test_affinity_moves_a_usable_socket_after_three_quiet_cycles(caplog):
    import logging as _logging

    inner, calls = nm_fake()
    run = socket_fake(inner, ss=SS_ON_WLAN2)
    state = wd.State()
    policy = wd.Policy(tunnel_affinity_cycles=3, tunnel_quiet_s=30.0)

    def restarted() -> bool:
        return ("systemctl", "--user", "restart", "binnacle-tunnel.service") in calls

    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        for n, now in ((1, 0.0), (2, 30.0)):
            assert (
                wd.tunnel_affinity_check(
                    state, policy, run, THREE, all_healthy(), obs(), n, now
                )
                == "wlan2"
            )
        assert not restarted() and "waiting 2/3 cycles" in caplog.text
        # third cycle, but a command was forwarded 10 s ago: not yet
        busy = obs(forwarded_last=50.0)
        wd.tunnel_affinity_check(
            state, policy, run, THREE, all_healthy(), busy, 3, 60.0
        )
        assert not restarted() and "a command was forwarded 10 s ago" in caplog.text
        # the active route must be healthy, not only reachable
        shaky = dict(all_healthy(), wlan1=degraded("wlan1"))
        wd.tunnel_affinity_check(state, policy, run, THREE, shaky, obs(), 4, 90.0)
        assert not restarted() and "wlan1 is not healthy" in caplog.text
        # quiet and healthy: move it
        wd.tunnel_affinity_check(
            state, policy, run, THREE, all_healthy(), busy, 5, 120.0
        )
    assert restarted()
    assert (
        "sat on wlan2 for 5 cycles while wlan1 is the active route (quiet for 70 s)"
        in caplog.text
    )
    assert state.tunnel_off_active_cycles == 0 and state.last_tunnel_restart == 120.0


def test_affinity_is_quiet_on_the_active_route_without_a_socket_or_when_holding(caplog):
    import logging as _logging

    inner, calls = nm_fake()
    on_active = socket_fake(
        inner, ss=SS_ON_WLAN2.replace("192.168.50.231", "192.168.50.197")
    )
    state = wd.State()
    assert (
        wd.tunnel_affinity_check(
            state, wd.Policy(), on_active, THREE, all_healthy(), obs(), 1, 0.0
        )
        == "wlan1"
    )
    assert (
        wd.tunnel_affinity_check(
            state, wd.Policy(), nm_fake()[0], THREE, all_healthy(), obs(), 2, 0.0
        )
        == "-"
    )
    off = wd.Policy(tunnel_affinity=False)
    assert (
        wd.tunnel_affinity_check(
            state, off, on_active, THREE, all_healthy(), obs(), 3, 0.0
        )
        == "-"
    )
    stopped = obs(tunnel_active=False)
    assert (
        wd.tunnel_affinity_check(
            state, wd.Policy(), on_active, THREE, all_healthy(), stopped, 4, 0.0
        )
        == "-"
    )
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)
    # paused or dry-run: observed and decided, never acted
    dead = {
        "wlan1": healthy("wlan1"),
        "wlan2": wedged("wlan2"),
        "wlan0": healthy("wlan0"),
    }
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        via = wd.tunnel_affinity_check(
            wd.State(),
            wd.Policy(),
            socket_fake(inner, ss=SS_ON_WLAN2),
            THREE,
            dead,
            obs(),
            5,
            0.0,
            holding=True,
        )
    assert via == "wlan2" and "paused or dry-run" in caplog.text
    assert not any(c[:3] == ("systemctl", "--user", "restart") for c in calls)


def test_after_failover_keeps_the_tunnel_when_its_socket_is_already_on_the_target(
    monkeypatch, caplog
):
    import logging as _logging

    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (THREE, True))
    inner, calls = nm_fake()
    state = wd.State()

    def restarts() -> int:
        return sum(1 for c in calls if c[:3] == ("systemctl", "--user", "restart"))

    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        wd.after_failover(
            state,
            wd.Policy(),
            socket_fake(inner, ss=SS_ON_WLAN2),
            now=10.0,
            target="wlan2",
        )
        assert restarts() == 0 and "already on the new active route" in caplog.text
        # on the demoted route's address: restart
        on_old = socket_fake(
            inner, ss=SS_ON_WLAN2.replace("192.168.50.231", "192.168.50.197")
        )
        wd.after_failover(state, wd.Policy(), on_old, now=20.0, target="wlan2")
        assert restarts() == 1 and state.last_failover_restart == 20.0
        assert (
            "the poller's connection is on wlan1, traffic moved to wlan2" in caplog.text
        )
        # the unit has no process (restarting already): kept
        wd.after_failover(
            state, wd.Policy(), socket_fake(inner, pid="0"), now=100.0, target="wlan2"
        )
    assert restarts() == 1 and "restarting already" in caplog.text


def test_restart_tunnel_reports_when_the_new_instance_answers(
    tmp_path, monkeypatch, caplog
):
    import logging as _logging
    import re as _re

    url_file = tmp_path / "binnacle.url"
    url_file.write_text("http://127.0.0.1:38335\n")
    monkeypatch.setattr(
        wd, "http_alive", lambda url, timeout=5.0: url == "http://127.0.0.1:38335"
    )
    run, calls = nm_fake()
    state = wd.State()
    state.cycle_n = 5
    policy = wd.Policy(tunnel_health_url_file=url_file)
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.restart_tunnel(
            state, policy, run, "failover: test", now=50.0, sleep=lambda s: None
        )
    assert ("systemctl", "--user", "restart", "binnacle-tunnel.service") in calls
    assert state.last_tunnel_restart == 50.0
    assert _re.search(
        r"event=service_restart cycle=5 unit=binnacle-tunnel.service ok=True ready_ms=\d+ reason=failover: test",
        caplog.text,
    )
    assert "tunnel_not_ready" not in caplog.text


def test_restart_tunnel_logs_when_no_new_instance_answers(
    tmp_path, monkeypatch, caplog
):
    import logging as _logging

    url_file = (
        tmp_path / "binnacle.url"
    )  # never written: the new instance never came up
    monkeypatch.setattr(wd, "http_alive", lambda url, timeout=5.0: False)
    run, _ = nm_fake()
    state = wd.State()
    policy = wd.Policy(tunnel_health_url_file=url_file, tunnel_ready_timeout_s=0.0)
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert wd.restart_tunnel(
            state, policy, run, "affinity: test", now=1.0, sleep=lambda s: None
        )
    assert "ready_ms=- reason=affinity: test" in caplog.text
    assert "event=tunnel_not_ready" in caplog.text
    bad, _ = nm_fake(fail=(("systemctl", "--user"),))
    with caplog.at_level(_logging.INFO, logger="binnacle.watchdog"):
        assert not wd.restart_tunnel(
            wd.State(), policy, bad, "x", now=2.0, sleep=lambda s: None
        )
    assert "ok=False ready_ms=- reason=x" in caplog.text


def test_restore_needed_doubles_per_wedge_in_the_window_and_caps():
    policy = wd.Policy(successes_before_restore=3, restore_hold_max_cycles=40)
    assert [wd.restore_needed(n, policy) for n in (0, 1, 2, 3, 4, 5, 9)] == [
        3,
        3,
        6,
        12,
        24,
        40,
        40,
    ]


def test_restore_holds_down_a_route_that_keeps_wedging():
    state = demoted_state()
    state.demoted["wlan1"].since_ts = 5000.0
    state.wedge_times["wlan1"] = [4000.0, 5000.0]  # the second wedge inside an hour
    policy = wd.Policy(successes_before_restore=3, flap_window_s=3600.0)
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    for i in range(5):
        assert (
            wd.evaluate(routes_demoted(), probes, state, policy, now=5030.0 + 30 * i)
            == []
        )
    notes = [n for d, r, n in state.decisions if d == "wlan1" and r == "restore"]
    assert "healthy 5/6 cycles (hold-down 6: 2 wedges in the last 60 min)" in notes[-1]
    (restore,) = wd.evaluate(routes_demoted(), probes, state, policy, now=5200.0)
    assert restore.kind == "restore" and "hold-down 6" in restore.reason
    # an hour later the wedges are forgotten: back to three cycles
    fresh = demoted_state()
    fresh.wedge_times["wlan1"] = [4000.0]
    for _ in range(2):
        assert wd.evaluate(routes_demoted(), probes, fresh, policy, now=9000.0) == []
    assert kinds(wd.evaluate(routes_demoted(), probes, fresh, policy, now=9000.0)) == [
        "restore"
    ]


def test_restore_waits_for_the_fast_path_to_see_the_route_clean():
    state = demoted_state()
    state.fast_demoted_last_fail["wlan1"] = 1000.0
    policy = wd.Policy(successes_before_restore=1, restore_fast_quiet_s=90.0)
    probes = {"wlan1": healthy("wlan1"), "wlan0": healthy("wlan0")}
    assert wd.evaluate(routes_demoted(), probes, state, policy, now=1030.0) == []
    notes = [n for d, r, n in state.decisions if d == "wlan1" and r == "restore"]
    assert "the fast path saw it fail 30 s ago; restore after 90 s clean" in notes[-1]
    assert kinds(wd.evaluate(routes_demoted(), probes, state, policy, now=1095.0)) == [
        "restore"
    ]
    # with the fast path off, the cycle's word is enough
    off = demoted_state()
    off.fast_demoted_last_fail["wlan1"] = 1000.0
    quiet = wd.Policy(successes_before_restore=1, fast_interval_s=0.0)
    assert kinds(wd.evaluate(routes_demoted(), probes, off, quiet, now=1030.0)) == [
        "restore"
    ]


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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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


class FakeThread:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


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
    monkeypatch.setattr(wd, "usb_node_of", lambda dev: (None, None))
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

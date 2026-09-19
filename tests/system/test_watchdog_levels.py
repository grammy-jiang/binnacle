"""USB link levels, demotion, persistence, and issue reporting."""

from tests.watchdog_support import (
    CONNECTIONS,
    DETAILS,
    ROUTES,
    SCHEDULE,
    WLAN1,
    Route,
    both_healthy,
    degraded,
    demoted_state,
    dev_info,
    healthy,
    json,
    kinds,
    mock,
    nm_fake,
    pairwise,
    patch_http_alive,
    patch_usb_node_of,
    pref,
    recording_nmcli,
    routes_demoted,
    usb_devices,
    wd,
    wd_actions,
    wedged,
)


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
    with mock.patch.object(wd_actions, "usb_reset_device", return_value=(True, "ok")):
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
    with mock.patch.object(wd_actions, "usb_reset_device", return_value=(True, "ok")):
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
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    # the service rung is on here: never let it probe the host's real server
    patch_http_alive(monkeypatch, lambda url, timeout=5.0: True)
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
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
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

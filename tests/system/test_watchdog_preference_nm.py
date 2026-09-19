"""NetworkManager profile discovery and preference integration."""

from tests.watchdog_support import (
    CONNECTIONS,
    DETAILS,
    ROUTES,
    both_healthy,
    json,
    kinds,
    nm_fake,
    preference_demotion,
    wd,
)


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

"""Device observation and no-route recovery."""

from tests.watchdog_support import (
    ROUTES,
    SCHEDULE,
    WLAN0,
    WLAN1,
    both_healthy,
    dev_info,
    healthy,
    kinds,
    nm_fake,
    patch_usb_node_of,
    pref,
    wd,
    wd_hardware,
)


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
    monkeypatch.setattr(wd_hardware, "USB_DEVICES", tmp_path)
    patch_usb_node_of(
        monkeypatch,
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
        "connected Occom-USB 5 GHz 80 MHz 867 Mbit/s -49 dBm usb 480 (target 5000)"
    )
    assert devices["wlan0"].describe() == "disconnected"


def test_wifi_link_info_tolerates_a_device_iw_cannot_see():
    run, _ = nm_fake()
    assert wd.wifi_link_info("nope0", run) == (None, None, None, None)


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

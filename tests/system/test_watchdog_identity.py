"""Physical identity: watchdog state follows the adapter, not the wlanX name.

Regression fixtures from the journal. 2026-09-15 12:24 (boot -6): the
RTL8188EUS came up as wlan1 and the RTL8812AU as wlan2, and the name-keyed
state handed the USB 2-only part the other adapter's learned 5000 Mbit/s
level -- four USB resets that morning, two more that night, six more on
09-16 after a mid-boot rename put it on wlan2. The swap reverted at the
2026-09-17 00:16 boot.
"""

import logging

from tests.watchdog_support import (
    ROUTES,
    WLAN0,
    WLAN1,
    Route,
    all_healthy,
    both_healthy,
    dev_info,
    healthy,
    json,
    link_fake,
    nm_fake,
    patch_http_alive,
    patch_usb_node_of,
    wd,
)

MAC_8812 = "00:0f:00:73:77:7f"
MAC_8179 = "48:8a:d2:05:1a:14"
MAC_PI = "2c:cf:67:c6:73:14"
KEY_8812 = f"usb:0bda:8812@{MAC_8812}"
KEY_8179 = f"usb:0bda:8179@{MAC_8179}"


def usb(dev: str, usb_id: str, mac: str, speed: int = 480) -> wd.DeviceInfo:
    return dev_info(dev, profile="Occom-USB", usb_id=usb_id, usb_speed=speed, mac=mac)


def normal() -> dict[str, wd.DeviceInfo]:
    return {
        "wlan1": usb("wlan1", "0bda:8812", MAC_8812, 5000),
        "wlan2": usb("wlan2", "0bda:8179", MAC_8179, 480),
    }


def swapped() -> dict[str, wd.DeviceInfo]:
    return {
        "wlan1": usb("wlan1", "0bda:8179", MAC_8179, 480),
        "wlan2": usb("wlan2", "0bda:8812", MAC_8812, 5000),
    }


def test_the_device_key_is_usb_id_plus_permanent_mac_and_needs_the_mac():
    assert dev_info("wlan1", usb_id="0bda:8812").key is None
    assert usb("wlan1", "0bda:8812", MAC_8812).key == KEY_8812
    assert dev_info("wlan0", mac=MAC_PI).key == f"builtin@{MAC_PI}"


def test_2026_09_15_name_swap_moves_the_state_with_the_adapter():
    state = wd.State()
    wd.track_identities(state, normal(), 1)
    assert state.identities == {"wlan1": KEY_8812, "wlan2": KEY_8179}
    state.usb_best_speed.update({"wlan1": 5000, "wlan2": 480})
    state.usb_attempts["wlan1"] = 2
    state.wedge_times["wlan1"] = [1.0]
    state.failures["wlan1"] = 2  # transient: re-observed, not carried

    wd.track_identities(state, swapped(), 2)
    assert state.identities == {"wlan1": KEY_8179, "wlan2": KEY_8812}
    assert state.usb_best_speed == {"wlan1": 480, "wlan2": 5000}
    assert state.usb_attempts == {"wlan2": 2}
    assert state.wedge_times == {"wlan2": [1.0]}
    assert state.failures == {} and state.parked == {}
    assert state.known_devices == {"wlan1": "0bda:8179", "wlan2": "0bda:8812"}
    # The rung that cost 12 resets: nothing to repair on either name now.
    routes = [WLAN1, Route("wlan2", "192.168.50.1", "192.168.50.231", 300), WLAN0]
    assert (
        wd.evaluate(routes, all_healthy(), state, wd.Policy(), devices=swapped()) == []
    )


def test_the_legacy_name_keyed_file_is_adopted_when_the_usb_id_matches(caplog):
    """The 2026-09-23 state file: known_devices by name, no identities."""
    caplog.set_level(logging.INFO, logger="binnacle.watchdog")
    state = wd.State()
    state.known_devices = {"wlan1": "0bda:8812", "wlan2": "0bda:8179"}
    state.usb_best_speed = {"wlan1": 480, "wlan2": 480}
    state.last_usb_reset["wlan1"] = 5.0
    wd.track_identities(state, normal(), 7)
    assert state.identities == {"wlan1": KEY_8812, "wlan2": KEY_8179}
    assert state.usb_best_speed == {"wlan1": 480, "wlan2": 480}
    assert state.last_usb_reset == {"wlan1": 5.0}
    seen = [r.getMessage() for r in caplog.records if "identity_seen" in r.getMessage()]
    assert len(seen) == 2 and all("adopted=legacy state" in m for m in seen)


def test_legacy_state_is_discarded_when_another_adapter_holds_the_name(caplog):
    """What should have happened on 2026-09-15 12:25 instead of a USB reset."""
    caplog.set_level(logging.INFO, logger="binnacle.watchdog")
    state = wd.State()
    state.known_devices = {"wlan1": "0bda:8812"}
    state.usb_best_speed["wlan1"] = 5000
    state.usb_attempts["wlan1"] = 3
    devices = {"wlan1": usb("wlan1", "0bda:8179", MAC_8179, 480)}
    wd.track_identities(state, devices, 3)
    assert state.identities == {"wlan1": KEY_8179}
    assert "wlan1" not in state.usb_best_speed and state.usb_attempts == {}
    assert state.known_devices == {"wlan1": "0bda:8179"}
    (line,) = [
        r.getMessage() for r in caplog.records if "identity_mismatch" in r.getMessage()
    ]
    assert "legacy=0bda:8812" in line and "usb_attempts" in line
    assert (
        wd.evaluate(ROUTES, both_healthy(), state, wd.Policy(), devices=devices) == []
    )


def test_an_adapter_back_under_a_new_name_brings_its_state_and_is_not_absent(caplog):
    caplog.set_level(logging.INFO, logger="binnacle.watchdog")
    state = wd.State()
    wd.track_identities(state, {"wlan1": usb("wlan1", "0bda:8812", MAC_8812)}, 1)
    state.usb_attempts["wlan1"] = 4
    state.last_grade["wlan1"] = "healthy"
    devices = {"wlan3": usb("wlan3", "0bda:8812", MAC_8812)}
    wd.track_identities(state, devices, 2)
    assert state.identities == {"wlan3": KEY_8812}
    assert state.usb_attempts == {"wlan3": 4} and state.last_grade == {
        "wlan3": "healthy"
    }
    assert state.known_devices == {"wlan3": "0bda:8812"}
    assert wd.absent_issues(state, devices) == {}
    assert any("identity_renamed" in r.getMessage() for r in caplog.records)


def test_a_replaced_adapter_parks_the_old_state_until_that_adapter_returns(caplog):
    caplog.set_level(logging.INFO, logger="binnacle.watchdog")
    state = wd.State()
    wd.track_identities(state, {"wlan1": usb("wlan1", "0bda:8812", MAC_8812)}, 1)
    state.usb_attempts["wlan1"] = 2
    state.demoted["wlan1"] = wd.Demotion(
        dev="wlan1", profile="Occom-USB", original_metric=100, since="x", reason="r"
    )
    wd.track_identities(state, {"wlan1": usb("wlan1", "0bda:8179", MAC_8179)}, 2)
    assert state.identities == {"wlan1": KEY_8179}
    assert state.usb_attempts == {} and state.demoted == {}
    assert state.parked[KEY_8812]["usb_attempts"] == 2
    assert state.parked[KEY_8812]["demoted"]["profile"] == "Occom-USB"
    assert any("identity_parked" in r.getMessage() for r in caplog.records)
    # The RTL8812AU comes back as wlan2: its demotion is re-addressed to it.
    both = {
        "wlan1": usb("wlan1", "0bda:8179", MAC_8179),
        "wlan2": usb("wlan2", "0bda:8812", MAC_8812),
    }
    wd.track_identities(state, both, 3)
    assert state.parked == {}
    assert state.usb_attempts == {"wlan2": 2}
    assert state.demoted["wlan2"].dev == "wlan2"
    assert state.demoted["wlan2"].profile == "Occom-USB"
    assert any("identity_returned" in r.getMessage() for r in caplog.records)


def test_a_device_without_a_mac_keeps_its_name_keyed_state_and_absence_by_name():
    """A failed `ip link` read must never park anything."""
    state = wd.State()
    state.known_devices["wlan1"] = "0bda:8812"
    state.usb_attempts["wlan1"] = 1
    wd.track_identities(state, {"wlan1": dev_info("wlan1", usb_id="0bda:8812")}, 1)
    assert state.identities == {} and state.usb_attempts == {"wlan1": 1}
    assert wd.absent_issues(state, {}) == {
        "wlan1": "absent: not seen by NetworkManager (0bda:8812); "
        "unplugged, or the driver is not bound"
    }


def test_identity_and_policy_tables_persist(tmp_path):
    path = tmp_path / "watchdog.json"
    state = wd.State()
    state.identities = {"wlan1": KEY_8812}
    state.parked = {KEY_8179: {"usb_attempts": 2, "wedge_times": [1.0]}}
    state.usb_policy_fp = {"wlan1": "param:rtw_switch_usb_mode=0:None"}
    state.usb_target = {"wlan1": None, "wlan2": 480}
    state.usb_mode = {"wlan1": "param", "wlan2": "fixed"}
    state.usb_max_seen = {"wlan1": 5000}
    state.usb_speed_exhausted = {"wlan2": 12}
    state.policy_events = [("wlan1", "a", "b", "-")]  # transient
    state.save(path)
    loaded = wd.State.load(path)
    assert loaded.identities == {"wlan1": KEY_8812}
    assert loaded.parked == {KEY_8179: {"usb_attempts": 2, "wedge_times": [1.0]}}
    assert loaded.usb_policy_fp == {"wlan1": "param:rtw_switch_usb_mode=0:None"}
    assert loaded.usb_target == {"wlan1": None, "wlan2": 480}
    assert loaded.usb_mode == {"wlan1": "param", "wlan2": "fixed"}
    assert loaded.usb_max_seen == {"wlan1": 5000}
    assert loaded.usb_speed_exhausted == {"wlan2": 12}
    assert loaded.policy_events == [] and "policy_events" not in json.loads(
        path.read_text()
    )


def test_permanent_mac_prefers_permaddr_over_a_randomized_address():
    run = link_fake(
        nm_fake()[0],
        {"wlan0": "aa:bb:cc:dd:ee:01", "wlan1": "00:0F:00:73:77:7F"},
        permaddr={"wlan0": MAC_PI},
    )
    assert wd.permanent_mac("wlan0", run) == MAC_PI
    assert wd.permanent_mac("wlan1", run) == MAC_8812
    assert wd.permanent_mac("wlan9", run) == ""


def test_the_cycle_reads_identities_and_logs_them(tmp_path, monkeypatch, caplog):
    """Through the loop with a fake NetworkManager: the state file gains the
    identities, the inventory line carries the id, and a swap on the next
    cycle is logged as a rename, not as new devices."""
    caplog.set_level(logging.INFO, logger="binnacle.watchdog")
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([WLAN1], True))
    monkeypatch.setattr(
        wd.uplink, "probe_all", lambda routes, **kw: {"wlan1": healthy("wlan1")}
    )
    nodes = {"wlan1": ("1-1", "0bda:8812"), "wlan2": ("3-1.4.3", "0bda:8179")}
    patch_usb_node_of(monkeypatch, lambda dev: nodes.get(dev, (None, None)))
    patch_http_alive(monkeypatch, lambda url, timeout=5.0: True)
    inner, _ = nm_fake(
        profiles="wlan1:Occom-USB\nwlan2:Occom-USB2\n",
        connections=(
            "Occom-USB:802-11-wireless:wlan1:yes:0\nOccom-USB2:802-11-wireless:wlan2:yes:0\n"
        ),
        devices="wlan1:wifi:connected:Occom-USB\nwlan2:wifi:connected:Occom-USB2\n",
        links={"wlan1": "\tfreq: 5765.0\n", "wlan2": "\tfreq: 2427.0\n"},
    )
    macs = {"wlan1": MAC_8812, "wlan2": MAC_8179}
    state = wd.State()
    policy = wd.Policy(service_repair=False)
    wd.cycle(state, policy, path, run=link_fake(inner, macs))
    written = json.loads(path.read_text())
    assert written["identities"] == {"wlan1": KEY_8812, "wlan2": KEY_8179}
    assert any(
        "event=inventory" in r.getMessage() and f"id={KEY_8812}" in r.getMessage()
        for r in caplog.records
    )
    caplog.clear()
    nodes.update({"wlan1": ("3-1.4.3", "0bda:8179"), "wlan2": ("1-1", "0bda:8812")})
    macs.update({"wlan1": MAC_8179, "wlan2": MAC_8812})
    wd.cycle(state, policy, path, run=link_fake(inner, macs))
    assert state.identities == {"wlan1": KEY_8179, "wlan2": KEY_8812}
    assert state.known_devices == {"wlan1": "0bda:8179", "wlan2": "0bda:8812"}
    names = {r.getMessage().split()[0] for r in caplog.records}
    assert "event=identity_parked" in names and "event=identity_returned" in names
    assert not any("absent" in r.getMessage() for r in caplog.records)

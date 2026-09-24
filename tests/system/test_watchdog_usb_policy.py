"""USB link targets: what the adapter's policy promises, not the best seen.

Regression fixture from 2026-09-23 10:15-12:47: the RTL8812AU rebooted in
`rtw_switch_usb_mode=0` and enumerated at 480 Mbit/s; the learned level of
5000 (from mode 1) demoted the healthy primary six times, about 100 s each,
and reset its USB device six times for a speed the driver no longer asks for.
"""

from tests.watchdog_support import (
    ROUTES,
    both_healthy,
    dev_info,
    kinds,
    mock,
    recording_nmcli,
    wd,
    wd_actions,
)

PARAM_8812 = wd.UsbLinkPolicy(
    "0bda:8812", mode="param", param="rtw_switch_usb_mode", targets=(("1", 5000),)
)
FIXED_8179 = wd.UsbLinkPolicy("0bda:8179", mode="fixed", target_mbps=480)


def policy(*rules: wd.UsbLinkPolicy, **kw) -> wd.Policy:
    return wd.Policy(usb_link_policies=tuple(rules), **kw)


def rtl8812au(speed: int, mode: str | None) -> dict[str, wd.DeviceInfo]:
    params = (("rtw_switch_usb_mode", mode),) if mode is not None else ()
    return {
        "wlan1": dev_info(
            "wlan1",
            profile="Occom-USB",
            usb_id="0bda:8812",
            usb_speed=speed,
            mac="00:0f:00:73:77:7f",
            params=params,
        ),
        "wlan0": dev_info("wlan0", profile="Occom"),
    }


def notes(state: wd.State, rung: str = "usb_level") -> list[str]:
    return [text for _, r, text in state.decisions if r == rung]


def test_2026_09_23_mode_0_at_480_with_a_learned_5000_is_left_alone():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    state.usb_max_seen["wlan1"] = 5000
    devices = rtl8812au(480, "0")
    assert (
        wd.evaluate(ROUTES, both_healthy(), state, policy(PARAM_8812), devices=devices)
        == []
    )
    assert state.usb_target["wlan1"] is None and state.usb_mode["wlan1"] == "param"
    assert notes(state) == [
        "link 480 Mbit/s, max seen 5000; policy rtw_switch_usb_mode=0: observe, no repair"
    ]
    assert wd.describe_issues(devices, {}, both_healthy(), state) == {}
    assert devices["wlan1"].describe(state.usb_target["wlan1"]).endswith("usb 480")


def test_mode_1_at_480_is_repaired_through_a_demotion_on_the_schedule():
    state = wd.State()
    actions = wd.evaluate(
        ROUTES, both_healthy(), state, policy(PARAM_8812), devices=rtl8812au(480, "1")
    )
    assert kinds(actions) == ["demote", "usb_reset"]
    assert actions[0].tag == "usb_speed"
    assert "target 5000 (rtw_switch_usb_mode=1) (reset attempt 1)" in actions[0].reason
    assert state.usb_target["wlan1"] == 5000
    assert wd.describe_issues(rtl8812au(480, "1"), {}, both_healthy(), state) == {
        "wlan1": "USB link 480 Mbit/s, target 5000 (param)"
    }


def test_mode_1_at_5000_is_satisfied_and_an_unknown_value_observes():
    state = wd.State()
    assert (
        wd.evaluate(
            ROUTES,
            both_healthy(),
            state,
            policy(PARAM_8812),
            devices=rtl8812au(5000, "1"),
        )
        == []
    )
    assert state.usb_target["wlan1"] == 5000 and notes(state) == []
    assert (
        wd.evaluate(
            ROUTES,
            both_healthy(),
            state,
            policy(PARAM_8812),
            devices=rtl8812au(480, "2"),
        )
        == []
    )
    assert state.usb_target["wlan1"] is None


def test_switching_the_driver_mode_clears_the_repair_counters_and_reports_it():
    """The 2026-09-18 experiment: mode 1 -> 0 with attempts on record."""
    state = wd.State()
    wd.evaluate(
        ROUTES, both_healthy(), state, policy(PARAM_8812), devices=rtl8812au(480, "1")
    )
    state.usb_speed_attempts["wlan1"] = 3
    state.last_usb_speed_reset["wlan1"] = 100.0
    old = state.usb_policy_fp["wlan1"]
    assert (
        wd.evaluate(
            ROUTES,
            both_healthy(),
            state,
            policy(PARAM_8812),
            now=200.0,
            devices=rtl8812au(480, "0"),
        )
        == []
    )
    assert state.usb_speed_attempts == {} and state.last_usb_speed_reset == {}
    assert state.policy_events == [
        (
            "wlan1",
            old,
            "param:rtw_switch_usb_mode=0:None",
            "usb_speed_attempts,last_usb_speed_reset",
        )
    ]
    assert old == "param:rtw_switch_usb_mode=1:5000"


def test_a_link_above_a_fixed_target_is_reported_not_forced_down():
    state = wd.State()
    rule = wd.UsbLinkPolicy("0bda:8812", mode="fixed", target_mbps=480)
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, policy(rule), devices=rtl8812au(5000, None)
        )
        == []
    )
    assert notes(state) == [
        "link 5000 Mbit/s above target 480 (fixed); policy drift, no action"
    ]
    assert state.usb_max_seen["wlan1"] == 5000


def test_a_fixed_target_exhausts_without_lowering_itself_and_retries_on_a_new_link():
    state = wd.State()
    rule = wd.UsbLinkPolicy("0bda:8812", mode="fixed", target_mbps=5000)
    pol = policy(rule, usb_speed_give_up=6)
    state.usb_speed_attempts["wlan1"] = 6
    state.last_usb_speed_reset["wlan1"] = 0.0
    devices = rtl8812au(480, None)
    assert (
        wd.evaluate(ROUTES, both_healthy(), state, pol, now=50_000.0, devices=devices)
        == []
    )
    assert state.usb_target["wlan1"] == 5000  # never lowered
    assert state.usb_speed_exhausted == {"wlan1": 480}
    assert notes(state) == [
        (
            "link 480 Mbit/s, target 5000 (fixed); repair exhausted after 6 resets, "
            "waiting for the link to change"
        )
    ]
    assert wd.describe_issues(devices, {}, both_healthy(), state) == {
        "wlan1": "USB link 480 Mbit/s, target 5000 (fixed); repair exhausted"
    }
    # A re-enumeration by other means (a wedge reset, a replug) shows a new
    # speed: the schedule starts over.
    actions = wd.evaluate(
        ROUTES, both_healthy(), state, pol, now=50_030.0, devices=rtl8812au(12, None)
    )
    assert kinds(actions) == ["demote", "usb_reset"]
    assert state.usb_speed_exhausted == {} and state.usb_speed_attempts == {}


def test_learned_mode_still_accepts_the_lower_level_after_giving_up():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    state.usb_speed_attempts["wlan1"] = 6
    state.last_usb_speed_reset["wlan1"] = 0.0
    assert (
        wd.evaluate(
            ROUTES,
            both_healthy(),
            state,
            wd.Policy(),
            now=50_000.0,
            devices=rtl8812au(480, None),
        )
        == []
    )
    assert state.usb_best_speed["wlan1"] == 480 and state.usb_target["wlan1"] == 480
    assert state.usb_max_seen["wlan1"] == 5000 and state.usb_speed_exhausted == {}


def test_learned_mode_relearns_when_the_module_parameter_changes():
    """Without a rule the level is still learned, but the driver's own mode
    is part of what it was learned under."""
    state = wd.State()
    wd.evaluate(
        ROUTES, both_healthy(), state, wd.Policy(), devices=rtl8812au(5000, "1")
    )
    assert state.usb_best_speed["wlan1"] == 5000
    assert state.usb_policy_fp["wlan1"] == "learned|rtw_switch_usb_mode=1"
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, wd.Policy(), devices=rtl8812au(480, "0")
        )
        == []
    )
    assert state.usb_best_speed["wlan1"] == 480 and state.usb_target["wlan1"] == 480
    assert state.usb_max_seen["wlan1"] == 5000
    assert state.policy_events[0][:3] == (
        "wlan1",
        "learned|rtw_switch_usb_mode=1",
        "learned|rtw_switch_usb_mode=0",
    )
    assert "usb_best_speed" in state.policy_events[0][3]


def test_a_rule_bound_to_another_mac_does_not_apply():
    state = wd.State()
    state.usb_best_speed["wlan1"] = 5000
    other = wd.UsbLinkPolicy(
        "0bda:8812", mode="observe", permanent_mac="AA:BB:CC:DD:EE:FF"
    )
    actions = wd.evaluate(
        ROUTES, both_healthy(), state, policy(other), devices=rtl8812au(480, None)
    )
    assert kinds(actions) == ["demote", "usb_reset"]  # learned mode, as before
    mine = wd.UsbLinkPolicy(
        "0bda:8812", mode="observe", permanent_mac="00:0F:00:73:77:7F"
    )
    assert (
        wd.evaluate(
            ROUTES,
            both_healthy(),
            wd.State(),
            policy(mine),
            devices=rtl8812au(480, None),
        )
        == []
    )


def test_the_reset_action_still_counts_and_paces_link_level_attempts():
    run, _ = recording_nmcli()
    state = wd.State()
    pol = policy(PARAM_8812)
    with mock.patch.object(wd_actions, "usb_reset_device", return_value=(True, "ok")):
        (_demote, reset) = wd.evaluate(
            ROUTES, both_healthy(), state, pol, now=10.0, devices=rtl8812au(480, "1")
        )
        assert wd.apply_action(reset, ROUTES, state, run=run, now=10.0, policy=pol)
    assert state.usb_speed_attempts == {"wlan1": 1}
    assert (
        wd.evaluate(
            ROUTES, both_healthy(), state, pol, now=40.0, devices=rtl8812au(480, "1")
        )
        == []
    )
    assert notes(state)[-1].endswith("waiting for the schedule")


def test_link_policies_come_from_the_toml(tmp_path, monkeypatch):
    from binnacle import watchdog_cli as cli
    from binnacle.config import CONFIG_FILE_ENV
    from binnacle.watchdog_config import WatchdogRootSettings

    toml = tmp_path / "config.toml"
    toml.write_text(
        "[watchdog]\n"
        'inventory_params = ["rtw_switch_usb_mode"]\n'
        "[[watchdog.usb_link_policies]]\n"
        'usb_id = "0bda:8812"\n'
        'mode = "param"\n'
        'param = "rtw_switch_usb_mode"\n'
        'targets = { "1" = 5000 }\n'
        "[[watchdog.usb_link_policies]]\n"
        'usb_id = "0bda:8179"\n'
        'mode = "fixed"\n'
        "target_mbps = 480\n"
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(toml))
    cfg = WatchdogRootSettings().watchdog
    rules = cli._link_policies(cfg)
    assert rules == (PARAM_8812, FIXED_8179)
    assert wd.usb_param_names(
        wd.Policy(inventory_params=("zz",), usb_link_policies=rules)
    ) == (
        "rtw_switch_usb_mode",
        "zz",
    )

"""USB re-enumeration and reset escalation."""

from tests.watchdog_support import (
    ROUTES,
    SCHEDULE,
    WLAN0,
    Path,
    demoted_after_reset,
    demoted_state,
    dev_info,
    fake_sudo,
    healthy,
    kinds,
    mock,
    pairwise,
    recording_nmcli,
    routes_demoted,
    wd,
    wd_actions,
    wd_hardware,
    wedged,
)


def test_usb_backoff_follows_the_stages():
    waits = [wd.usb_backoff(SCHEDULE, n) for n in range(1, 13)]
    assert waits == [60, 60, 60, 180, 180, 180, 300, 300, 300, 600, 600, 600]


def test_usb_backoff_unlimited_stage_never_runs_out():
    assert wd.usb_backoff(SCHEDULE, 500) == 600.0
    assert wd.usb_backoff(((2, 30.0),), 99) == 30.0  # last stage repeats
    assert wd.usb_backoff((), 1) == 600.0


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
    with mock.patch.object(
        wd_actions, "usb_reset_device", return_value=(True, "ok")
    ) as reset:
        for _ in range(12):
            while True:
                now += 10.0
                actions = wd.evaluate(routes_demoted(), bad, state, policy, now=now)
                if actions:
                    break
            assert kinds(actions) == ["usb_reset"]
            wd.apply_action(
                actions[0], routes_demoted(), state, run=run, now=now, policy=policy
            )
            fired.append(now)
    assert reset.call_count == 12
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
    with mock.patch.object(
        wd_actions, "usb_reset_device", return_value=(False, "denied")
    ):
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
    monkeypatch.setattr(wd_hardware, "NET_CLASS", tmp_path / "class" / "net")
    assert wd.usb_node_of("wlan1") == ("2-1", "0bda:8812")
    assert wd.usb_node_of("nope0") == (None, None)


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
    monkeypatch.setattr(wd_hardware, "USB_DEVICES", tmp_path)
    assert wd.usb_devfs_path("2-1") == Path("/dev/bus/usb/002/003")
    assert wd.usb_devfs_path("9-9") is None


def test_second_attempt_uses_the_port_reset(monkeypatch):
    seen: list[str] = []

    def fake_reset(dev, policy, run, method="authorized", **kw):
        seen.append(method)
        return True, method

    monkeypatch.setattr(wd_actions, "usb_reset_device", fake_reset)
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

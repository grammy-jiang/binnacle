"""Grades, system services, pause, inventory, and cycle logging."""

from tests.watchdog_support import (
    ROUTES,
    WLAN1,
    ProbeResult,
    both_healthy,
    degraded,
    demoted_state,
    dev_info,
    fake_sudo,
    healthy,
    json,
    kinds,
    lossy,
    nm_fake,
    outage,
    patch_usb_node_of,
    pref,
    routes_demoted,
    subprocess,
    sys_obs,
    wd,
    wd_cycle,
    wd_hardware,
    wedged,
)


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


def test_pause_file_holds_every_action_and_expires(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    pause = tmp_path / "watchdog.pause"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: (ROUTES, True))
    monkeypatch.setattr(wd.uplink, "probe_all", lambda routes, **kw: outage())
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
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
    monkeypatch.setattr(wd_hardware, "NET_CLASS", tmp_path / "class" / "net")
    monkeypatch.setattr(wd_hardware, "SYS_MODULE", tmp_path / "module")
    patch_usb_node_of(monkeypatch, lambda dev: ("2-1", "0bda:8812"))
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
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    monkeypatch.setattr(wd_cycle, "usb_adapters_without_netdev", lambda ids: {})
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

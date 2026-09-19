"""Failure review, driver reload, services, and liveness."""

from tests.watchdog_support import (
    ROUTES,
    SCHEDULE,
    WLAN0,
    WLAN1,
    ProbeResult,
    Route,
    degraded,
    demoted_after_reset,
    demoted_state,
    dev_info,
    fake_sudo,
    healthy,
    json,
    kinds,
    nm_fake,
    obs,
    patch_usb_node_of,
    recording_nmcli,
    routes_demoted,
    subprocess,
    wd,
    wd_actions,
    wd_cycle,
    wd_hardware,
    wedged,
)


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
    monkeypatch.setattr(wd_hardware, "NET_CLASS", tmp_path / "class" / "net")
    monkeypatch.setattr(wd_hardware, "SYS_MODULE", tmp_path / "module")
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
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
    patch_usb_node_of(monkeypatch, lambda dev: ("2-1", "0bda:8812"))
    okay, detail = wd.driver_reload("wlan0", run)
    assert not okay and "USB" in detail
    assert wd.driver_module_of("nope0") == (None, [])
    state = wd.State()
    monkeypatch.setattr(wd_actions, "driver_reload", lambda dev, run: (True, "ok"))
    assert wd.apply_action(
        wd.Action("reload", "wlan0", "x"), ROUTES, state, run=run, now=4.0
    )
    assert state.reload_attempts["wlan0"] == 1 and state.last_reload["wlan0"] == 4.0


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
    monkeypatch.setattr(wd_hardware, "USB_DEVICES", tmp_path)
    found = wd.usb_adapters_without_netdev(("0bda:8812",))
    assert list(found) == ["usb:2-1"] and "driver not bound" in found["usb:2-1"]
    assert wd.usb_adapters_without_netdev(("ffff:0000",)) == {}


def test_cycle_reports_an_adapter_that_vanished(tmp_path, monkeypatch):
    path = tmp_path / "watchdog.json"
    monkeypatch.setattr(wd.uplink, "read_default_routes", lambda run: ([WLAN0], True))
    monkeypatch.setattr(
        wd.uplink, "probe_all", lambda routes, **kw: {"wlan0": healthy("wlan0")}
    )
    patch_usb_node_of(monkeypatch, lambda dev: (None, None))
    monkeypatch.setattr(wd_cycle, "usb_adapters_without_netdev", lambda ids: {})
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

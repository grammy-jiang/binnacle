"""Tunnel socket affinity, restart, and flap damping."""

from tests.watchdog_support import (
    SS_ON_WLAN2,
    THREE,
    all_healthy,
    degraded,
    demoted_state,
    healthy,
    kinds,
    nm_fake,
    obs,
    routes_demoted,
    socket_fake,
    wd,
    wd_tunnel,
    wedged,
)


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
        wd_tunnel,
        "http_alive",
        lambda url, timeout=5.0: url == "http://127.0.0.1:38335",
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
    monkeypatch.setattr(wd_tunnel, "http_alive", lambda url, timeout=5.0: False)
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

"""Implementation gate for binnacle/uplink.py.

`ip` and `ping` are fakes passed in; the socket layers are pointed at
loopback servers so the real socket path runs. The cases mirror the
2026-09-12 outage: an interface that is up, addressed and routed, and
still carries nothing.
"""

import json
import subprocess

from binnacle import uplink

ROUTE_JSON = json.dumps(
    [
        {
            "dst": "default",
            "gateway": "192.168.50.1",
            "dev": "wlan1",
            "protocol": "dhcp",
            "prefsrc": "192.168.50.197",
            "metric": 100,
        },
        {
            "dst": "default",
            "gateway": "192.168.50.1",
            "dev": "wlan0",
            "protocol": "dhcp",
            "prefsrc": "192.168.50.222",
            "metric": 600,
        },
    ]
)


def fake_run(stdout: str = "", code: int = 0):
    def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(list(args), code, stdout=stdout, stderr="")

    return run


# -- route parsing -----------------------------------------------------------


def test_default_routes_sorted_by_metric():
    routes = uplink.default_routes(fake_run(ROUTE_JSON))
    assert [r.dev for r in routes] == ["wlan1", "wlan0"]
    assert routes[0].src == "192.168.50.197" and routes[0].metric == 100


def test_active_route_is_lowest_metric():
    routes = uplink.default_routes(fake_run(ROUTE_JSON))
    assert uplink.active_route(routes).dev == "wlan1"


def test_active_route_none_without_routes():
    assert uplink.active_route([]) is None


def test_routes_without_gateway_or_source_are_skipped():
    raw = json.dumps(
        [
            {"dst": "default", "dev": "tun0", "metric": 50},  # no gateway/prefsrc
            {
                "dst": "default",
                "gateway": "10.0.0.1",
                "dev": "eth0",
                "prefsrc": "10.0.0.5",
                "metric": 100,
            },
        ]
    )
    assert [r.dev for r in uplink.default_routes(fake_run(raw))] == ["eth0"]


def test_default_routes_tolerates_bad_json_and_failure():
    assert uplink.default_routes(fake_run("not json")) == []
    assert uplink.default_routes(fake_run(ROUTE_JSON, code=1)) == []


def test_nameservers_parsed(tmp_path):
    f = tmp_path / "resolv.conf"
    f.write_text("# comment\nnameserver 192.168.50.1\nsearch lan\nnameserver 1.1.1.1\n")
    assert uplink.nameservers(f) == ["192.168.50.1", "1.1.1.1"]


def test_nameservers_missing_file(tmp_path):
    assert uplink.nameservers(tmp_path / "nope") == []


# -- ProbeResult semantics ---------------------------------------------------


def result(gateway: bool, dns: bool, tcp: bool) -> uplink.ProbeResult:
    return uplink.ProbeResult(
        dev="wlan1", layers={"gateway": gateway, "dns": dns, "tcp": tcp}
    )


def test_healthy_only_when_every_layer_passes():
    assert result(True, True, True).healthy
    assert not result(True, True, False).healthy


def test_wedged_only_when_no_layer_passes():
    """The outage signature: up, addressed, and carrying nothing."""
    assert result(False, False, False).wedged
    assert not result(True, False, False).wedged
    assert not result(True, True, True).wedged


def test_empty_result_is_neither_healthy_nor_wedged():
    empty = uplink.ProbeResult(dev="wlan1")
    assert not empty.healthy and not empty.wedged


def test_deepest_ok_and_first_failure_name_the_boundary():
    r = result(True, True, False)
    assert r.deepest_ok == "dns"
    assert r.first_failure == "tcp"
    assert result(False, False, False).deepest_ok is None


def test_summary_lists_layers_in_probe_order():
    assert result(True, False, False).summary() == "gateway=ok dns=FAIL tcp=FAIL"


# -- gateway layer -----------------------------------------------------------


ROUTE = uplink.Route(dev="wlan1", gateway="192.168.50.1", src="127.0.0.1", metric=100)


def test_probe_gateway_ok_on_exit_zero():
    okay, err = uplink.probe_gateway(ROUTE, run=fake_run())
    assert okay and err == ""


def test_probe_gateway_fails_on_nonzero_exit():
    okay, err = uplink.probe_gateway(ROUTE, run=fake_run(code=1))
    assert not okay and "192.168.50.1" in err


def test_probe_gateway_fails_on_timeout():
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(list(args), 1)

    okay, err = uplink.probe_gateway(ROUTE, run=run)
    assert not okay and "timed out" in err


def test_probe_gateway_binds_to_the_device():
    seen: list[tuple] = []

    def run(*args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

    uplink.probe_gateway(ROUTE, run=run)
    assert "-I" in seen[0] and "wlan1" in seen[0]

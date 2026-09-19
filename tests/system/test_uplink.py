"""Implementation gate for binnacle/uplink.py.

`ip` and `ping` are fakes passed in; the socket layers are pointed at
loopback servers so the real socket path runs. The cases mirror the
2026-09-12 outage: an interface that is up, addressed and routed, and
still carries nothing.
"""

import json
import socket
import subprocess
import threading

import pytest

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


# -- dns layer ---------------------------------------------------------------


@pytest.fixture
def dns_server():
    """A UDP responder; `answers` controls the answer-record count."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    state = {"answers": 1, "echo_id": True}

    def serve():
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                return
            qid = data[:2] if state["echo_id"] else b"\xff\xff"
            # A record 93.184.216.34 for the question, name via a pointer to it.
            answer = (
                b"\xc0\x0c"
                + b"\x00\x01"
                + b"\x00\x01"
                + b"\x00\x00\x0e\x10"
                + b"\x00\x04"
                + bytes([93, 184, 216, 34])
            )
            reply = (
                qid
                + b"\x81\x80"
                + b"\x00\x01"
                + state["answers"].to_bytes(2, "big")
                + b"\x00\x00" * 2
                + data[12:]
                + (answer * state["answers"])
            )
            sock.sendto(reply, addr)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1], state
    sock.close()


def test_probe_dns_ok_with_an_answer(dns_server):
    port, _ = dns_server
    okay, err, address = uplink.probe_dns(
        "127.0.0.1", "127.0.0.1", "example.com", timeout=2.0, port=port
    )
    assert okay and err == ""
    assert address == "93.184.216.34"


def test_probe_dns_fails_when_the_reply_has_no_answer_records(dns_server):
    """NXDOMAIN-shaped reply: the resolver answered, the name did not resolve."""
    port, state = dns_server
    state["answers"] = 0
    okay, err, _ = uplink.probe_dns(
        "127.0.0.1", "127.0.0.1", "example.com", timeout=2.0, port=port
    )
    assert not okay and "no answer records" in err


def test_probe_dns_rejects_a_mismatched_transaction_id(dns_server):
    port, state = dns_server
    state["echo_id"] = False
    okay, err, _ = uplink.probe_dns(
        "127.0.0.1", "127.0.0.1", "example.com", timeout=2.0, port=port
    )
    assert not okay and "malformed reply" in err


def test_probe_dns_times_out_against_a_silent_server():
    """The outage signature at the DNS layer: query out, nothing back."""
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    try:
        okay, err, _ = uplink.probe_dns(
            "127.0.0.1",
            "127.0.0.1",
            "example.com",
            timeout=0.2,
            port=silent.getsockname()[1],
        )
    finally:
        silent.close()
    assert not okay and "example.com" in err


def test_probe_dns_rejects_a_bad_source_address():
    okay, err, _ = uplink.probe_dns(
        "203.0.113.9", "127.0.0.1", "example.com", timeout=0.2
    )
    assert not okay and "203.0.113.9" in err


def test_dns_query_is_a_wellformed_a_record_question():
    query, qid = uplink._dns_query("api.openai.com")
    assert query[:2] == qid
    assert query.endswith(b"\x00\x01\x00\x01")
    assert b"\x03api\x06openai\x03com\x00" in query
    assert int.from_bytes(query[4:6], "big") == 1  # exactly one question


# -- tcp layer ---------------------------------------------------------------


@pytest.fixture
def tcp_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    threading.Thread(target=lambda: _accept_forever(srv), daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def _accept_forever(srv):
    while True:
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            return


def test_probe_tcp_connects(tcp_server):
    okay, err = uplink.probe_tcp("127.0.0.1", "127.0.0.1", tcp_server, timeout=2.0)
    assert okay and err == ""


def test_probe_tcp_fails_on_a_closed_port():
    okay, err = uplink.probe_tcp("127.0.0.1", "127.0.0.1", 9, timeout=0.5)
    assert not okay and "127.0.0.1:9" in err


# -- composition -------------------------------------------------------------


def test_probe_runs_every_layer_even_after_one_fails(monkeypatch):
    """A gateway failure must not hide the DNS and TCP verdicts."""
    monkeypatch.setattr(uplink, "probe_dns", lambda *a, **k: (False, "dns down", None))
    uplink._last_address.clear()
    monkeypatch.setattr(uplink, "probe_tcp", lambda *a, **k: (False, "tcp down"))
    res = uplink.probe(ROUTE, run=fake_run(code=1))
    assert set(res.layers) == {"gateway", "dns", "tcp"}
    assert res.wedged
    assert res.errors["dns"] == "dns down"


def test_probe_all_keys_by_device(monkeypatch):
    monkeypatch.setattr(uplink, "probe_dns", lambda *a, **k: (True, "", "127.0.0.1"))
    monkeypatch.setattr(uplink, "probe_tcp", lambda *a, **k: (True, ""))
    routes = uplink.default_routes(fake_run(ROUTE_JSON))
    probes = uplink.probe_all(routes, run=fake_run())
    assert set(probes) == {"wlan0", "wlan1"}
    assert all(p.healthy for p in probes.values())


# -- device binding and DNS-independent TCP ---------------------------------
#
# 2026-09-12 20:31: source-address binding sent "wlan0" probes out wlan1
# (`ip route get ... from <wlan0 addr>` -> dev wlan1), so a degraded wlan1
# made wlan0 look dead too and the watchdog refused to fail over.


def test_probe_dns_binds_the_device(dns_server):
    port, _ = dns_server
    okay, err, address = uplink.probe_dns(
        "127.0.0.1", "127.0.0.1", "example.com", timeout=2.0, port=port, dev="lo"
    )
    assert okay and address == "93.184.216.34", err


def test_probe_dns_reports_an_unknown_device(dns_server):
    port, _ = dns_server
    okay, err, _ = uplink.probe_dns(
        "127.0.0.1", "127.0.0.1", "example.com", timeout=1.0, port=port, dev="nope0"
    )
    assert not okay and "nope0" in err


def test_probe_tcp_binds_the_device_and_uses_the_address(tcp_server):
    okay, err = uplink.probe_tcp(
        "127.0.0.1",
        "example.com",
        tcp_server,
        timeout=2.0,
        dev="lo",
        address="127.0.0.1",
    )
    assert okay, err
    okay, err = uplink.probe_tcp(
        "127.0.0.1", "example.com", 9, timeout=0.5, dev="lo", address="127.0.0.1"
    )
    assert not okay and "example.com (127.0.0.1):9" in err


def test_first_a_record_walks_compressed_names():
    q = b"\x03www\x07example\x03com\x00" + b"\x00\x01\x00\x01"
    cname = b"\xc0\x0c\x00\x05\x00\x01\x00\x00\x00\x3c\x00\x02\xc0\x10"
    a = b"\xc0\x10\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + bytes([10, 1, 2, 3])
    reply = b"\xab\xcd\x81\x80\x00\x01\x00\x02\x00\x00\x00\x00" + q + cname + a
    assert uplink._first_a_record(reply) == "10.1.2.3"
    assert uplink._first_a_record(b"\x00" * 5) is None


def test_probe_uses_the_last_known_address_when_dns_fails(monkeypatch):
    """A dead resolver must not read as a dead path."""
    seen: list[str | None] = []
    monkeypatch.setattr(uplink, "probe_dns", lambda *a, **k: (False, "dns down", None))

    def fake_tcp(src, host, port=443, timeout=5.0, dev=None, address=None):
        seen.append(address)
        return True, ""

    monkeypatch.setattr(uplink, "probe_tcp", fake_tcp)
    uplink._last_address.clear()
    uplink._last_address["api.openai.com"] = "203.0.113.5"
    res = uplink.probe(ROUTE, host="api.openai.com", run=fake_run())
    assert res.layers == {"gateway": True, "dns": False, "tcp": True}
    assert seen == ["203.0.113.5"]
    assert res.deepest_ok == "tcp" and res.first_failure == "dns"


def test_probe_records_a_fresh_address_for_later(monkeypatch):
    monkeypatch.setattr(uplink, "probe_dns", lambda *a, **k: (True, "", "198.51.100.7"))
    monkeypatch.setattr(uplink, "probe_tcp", lambda *a, **k: (True, ""))
    uplink._last_address.clear()
    uplink.probe(ROUTE, host="api.openai.com", run=fake_run())
    assert uplink._last_address["api.openai.com"] == "198.51.100.7"


def test_probe_without_any_address_fails_tcp_explicitly(monkeypatch):
    monkeypatch.setattr(uplink, "probe_dns", lambda *a, **k: (False, "dns down", None))
    uplink._last_address.clear()
    res = uplink.probe(ROUTE, host="api.openai.com", run=fake_run())
    assert res.layers["tcp"] is False and "none cached" in res.errors["tcp"]


def test_source_binding_alone_would_not_select_the_device():
    """Documents the kernel behaviour that forced device binding: with two
    interfaces on one subnet, the route is chosen by metric, not by source."""
    proc = subprocess.run(
        ["ip", "-j", "route", "show", "default"],
        capture_output=True,
        text=True,
        check=False,
    )
    routes = json.loads(proc.stdout or "[]") if proc.returncode == 0 else []
    if len(routes) < 2:
        pytest.skip("needs two default routes to demonstrate")
    lo, hi = sorted(routes, key=lambda r: r.get("metric", 0))[:2]
    got = subprocess.run(
        ["ip", "route", "get", lo["gateway"], "from", hi["prefsrc"]],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert f"dev {lo['dev']}" in got


# -- the failure-case review (2026-09-13) ------------------------------------


def test_dead_end_is_any_result_without_a_tcp_path():
    assert result(True, True, False).dead_end
    assert result(False, False, False).dead_end  # a wedge is a dead end too
    assert not result(False, True, True).dead_end  # lossy ping, path fine
    assert not uplink.ProbeResult(dev="wlan1").dead_end  # nothing probed


def test_probe_reports_unavailable_instead_of_a_dead_route(monkeypatch):
    """SO_BINDTODEVICE refused: layers stay empty (neither healthy nor
    wedged nor a dead end) and the reason is in errors['probe']."""

    def refuse(sock, dev):
        raise uplink.ProbeUnavailable(
            "cannot bind to wlan1: [Errno 1] Operation not permitted"
        )

    monkeypatch.setattr(uplink, "_bind_device", refuse)
    route = uplink.Route("wlan1", "192.168.50.1", "127.0.0.1", 100)
    probe = uplink.probe(
        route,
        host="example.com",
        nameserver="127.0.0.1",
        timeout=0.5,
        run=fake_run("", 0),
    )
    assert probe.layers == {} and "cannot bind" in probe.errors["probe"]
    assert probe.unavailable
    assert not probe.healthy and not probe.wedged and not probe.dead_end


def test_bind_device_turns_a_permission_error_into_unavailable():
    class Sock:
        def setsockopt(self, *a):
            raise PermissionError(1, "Operation not permitted")

    with pytest.raises(uplink.ProbeUnavailable):
        uplink._bind_device(Sock(), "wlan1")  # type: ignore[arg-type]
    uplink._bind_device(Sock(), None)  # type: ignore[arg-type]  # no device: no call


ROUTE = uplink.Route("wlan1", "192.168.50.1", "127.0.0.1", 100)


def probe_with(
    dns_answers,
    tcp_ok: bool,
    fallback: str | None = "1.1.1.1",
    nameserver: str = "silent",
):
    """Run probe() with probe_dns answering per server name and TCP fixed."""
    import unittest.mock as um

    def fake_dns(
        src, server, host=uplink.UPSTREAM_HOST, timeout=3.0, port=53, dev=None
    ):
        return dns_answers[server]

    with (
        um.patch.object(uplink, "probe_dns", side_effect=fake_dns) as pd,
        um.patch.object(
            uplink,
            "probe_tcp",
            return_value=(tcp_ok, "" if tcp_ok else "TCP: timed out"),
        ),
    ):
        probe = uplink.probe(
            ROUTE,
            host="example.com",
            nameserver=nameserver,
            timeout=0.5,
            run=fake_run("", 0),
            fallback_nameserver=fallback,
        )
    return probe, pd.call_count


def test_dns_fallback_classifies_a_dead_resolver():
    """The system resolver is silent, the public one answers over the same
    device: the note says 'resolver' and TCP still gets an address."""
    probe, calls = probe_with(
        {
            "silent": (False, "DNS example.com at silent via wlan1: timed out", None),
            "1.1.1.1": (True, "", "93.184.216.34"),
        },
        tcp_ok=True,
    )
    assert calls == 2
    assert probe.layers == {"gateway": True, "dns": False, "tcp": True}
    assert probe.notes["dns"] == "resolver"
    assert "the resolver, not the link" in probe.errors["dns"]


def test_dns_fallback_classifies_a_dead_link():
    probe, calls = probe_with(
        {"silent": (False, "timed out", None), "1.1.1.1": (False, "timed out", None)},
        tcp_ok=False,
    )
    assert calls == 2
    assert probe.notes["dns"] == "link" and "too: the link" in probe.errors["dns"]
    assert probe.layers["dns"] is False


def test_dns_fallback_is_skipped_when_it_is_the_system_resolver():
    probe, calls = probe_with(
        {"1.1.1.1": (False, "timed out", None)}, tcp_ok=False, nameserver="1.1.1.1"
    )
    assert calls == 1 and "dns" not in probe.notes


def test_probe_records_layer_timings_and_detail_shows_them():
    probe, _ = probe_with({"silent": (True, "", "93.184.216.34")}, tcp_ok=True)
    assert set(probe.timings) == {"gateway", "dns", "tcp"}
    assert all(ms >= 0 for ms in probe.timings.values())
    detail = probe.detail()
    assert (
        detail.startswith("gateway=ok(") and "dns=ok(" in detail and "tcp=ok(" in detail
    )
    assert probe.summary() == "gateway=ok dns=ok tcp=ok"  # unchanged for the state file
    assert (
        uplink.ProbeResult(dev="x", errors={"probe": "no"}).detail()
        == "probe=unavailable"
    )
    assert result(True, False, True).detail() == "gateway=ok dns=FAIL tcp=ok"


def test_read_default_routes_tells_an_empty_table_from_a_failed_read():
    assert uplink.read_default_routes(fake_run("[]", 0)) == ([], True)
    assert uplink.read_default_routes(fake_run("", 1)) == ([], False)
    assert uplink.read_default_routes(fake_run("not json", 0)) == ([], False)

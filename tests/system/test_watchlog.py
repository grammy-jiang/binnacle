"""The journal reader: what the richer watchdog logging is for."""

from binnacle import watchlog

LINES = """\
2026-09-13T23:00:00+10:00 pi binnacle[1]: INFO: event=watchdog_start interval_s=30.0 host=api.openai.com state_file=/x cycle=10 demoted=[] counters=usb{}/prefer{}/level{}/reload{} versions={"kernel": "6.18"} policy={"a": 1}
2026-09-13T23:00:01+10:00 pi binnacle[1]: INFO: event=inventory cycle=11 dev=wlan1 kind=usb:0bda:8812@2-1:5000Mbit driver=rtl8812au module=rtl8812au params=rtw_switch_usb_mode=1 profiles=Occom-USB:prio20:metric100:auto
2026-09-13T23:00:01+10:00 pi binnacle[1]: INFO: event=transition cycle=11 dev=wlan1 from=- to=healthy after_s=- detail=gateway=ok(3ms) dns=ok(2ms) tcp=ok(20ms)
2026-09-13T23:00:01+10:00 pi binnacle[1]: INFO: event=cycle cycle=11 duration_ms=812 active=wlan1 routes=wlan1:100,wlan0:600 grades=wlan0:healthy,wlan1:healthy demoted=- issues=0 actions=- services=mcp=ok,tunnel=ok
2026-09-13T23:05:01+10:00 pi binnacle[1]: WARNING: event=transition cycle=21 dev=wlan1 from=healthy to=wedged after_s=300 detail=gateway=FAIL(2001ms) dns=FAIL(3000ms) tcp=FAIL(5000ms)
2026-09-13T23:05:01+10:00 pi binnacle[1]: INFO: event=decision cycle=21 dev=wlan1 rung=failover note=wedged 1/3 cycles
2026-09-13T23:06:01+10:00 pi binnacle[1]: WARNING: event=uplink_demoted cycle=23 dev=wlan1 metric=100->900 kind=wedged others=Occom-2.4G-USB reason=wedged for 3 cycles; wlan0 is healthy
2026-09-13T23:06:02+10:00 pi binnacle[1]: WARNING: event=uplink_reset cycle=23 dev=wlan1 ok=True tag=wedged profile=Occom-USB reason=repair after failover
2026-09-13T23:07:05+10:00 pi binnacle[1]: WARNING: event=uplink_usb_reset cycle=25 dev=wlan1 attempt=1 method=authorized ok=True tag=wedged next_in_s=60 detail=re-initialised 2-1 via authorized (0bda:8812)
2026-09-13T23:09:31+10:00 pi binnacle[1]: INFO: event=transition cycle=30 dev=wlan1 from=wedged to=healthy after_s=270 detail=gateway=ok(4ms) dns=ok(3ms) tcp=ok(25ms)
2026-09-13T23:10:31+10:00 pi binnacle[1]: WARNING: event=uplink_restored cycle=32 dev=wlan1 metric=100 kind=wedged reason=healthy for 3 cycles
2026-09-13T23:10:31+10:00 pi binnacle[1]: INFO: event=cycle cycle=32 duration_ms=900 active=wlan1 routes=wlan1:100,wlan0:600 grades=wlan0:healthy,wlan1:healthy demoted=- issues=0 actions=restore:wlan1 services=mcp=ok,tunnel=ok
some unrelated line
"""


def test_parse_reads_timestamp_level_name_and_fields():
    events = watchlog.parse(LINES.splitlines())
    assert [e.name for e in events][:4] == [
        "watchdog_start",
        "inventory",
        "transition",
        "cycle",
    ]
    demoted = next(e for e in events if e.name == "uplink_demoted")
    assert demoted.level == "WARNING" and demoted.ts.startswith("2026-09-13T23:06:01")
    assert demoted.fields["metric"] == "100->900"
    assert demoted.fields["reason"] == "wedged for 3 cycles; wlan0 is healthy"
    start = events[0]
    assert (
        start.fields["versions"] == '{"kernel": "6.18"}'
        and start.fields["policy"] == '{"a": 1}'
    )
    assert watchlog.parse(["nothing here"]) == []


def test_render_tells_the_story_and_sums_it_up():
    out = watchlog.render(watchlog.parse(LINES.splitlines()))
    assert "wlan1: healthy -> wedged (after 300 s)" in out
    assert (
        "wlan1: demoted metric 100->900 kind=wedged: wedged for 3 cycles; wlan0 is healthy"
        in out
    )
    assert "USB reset attempt 1 method=authorized ok=True" in out
    assert "restored metric 100" in out
    assert "cycles: 2, mean 856 ms, max 900 ms" in out
    assert "failovers (wedge/dead end demotions): 1, restores: 1" in out
    assert "wlan1: healthy" in out and "wedged 4 min" in out
    assert "decision" not in out  # declined decisions only with --verbose
    verbose = watchlog.render(watchlog.parse(LINES.splitlines()), verbose=True)
    assert "failover declined: wedged 1/3 cycles" in verbose


def test_render_with_nothing_says_so():
    assert "(no watchdog events in this window)" in watchlog.render([])


FIFTH = """\
2026-09-14T15:51:56+10:00 pi binnacle[1]: WARNING: event=fast_failover cycle=1745 dev=wlan1 failures=4 window_s=20 target=wlan2 metric=300
2026-09-14T15:51:56+10:00 pi binnacle[1]: WARNING: event=uplink_demoted cycle=1745 dev=wlan1 before=healthy trigger=fast metric=100->900 kind=wedged profile=Occom-USB others=- reason=no TCP path for 4 fast probes (20 s); wlan2 has a TCP path (metric 300)
2026-09-14T15:51:56+10:00 pi binnacle[1]: WARNING: event=service_restart cycle=1745 unit=binnacle-tunnel.service ok=True ready_ms=612 reason=failover: the poller's connection is on wlan1, traffic moved to wlan2 err=
2026-09-14T15:53:46+10:00 pi binnacle[1]: WARNING: event=uplink_restored cycle=1749 dev=wlan1 metric=100 kind=wedged reason=healthy for 3 cycles
2026-09-14T15:55:00+10:00 pi binnacle[1]: WARNING: event=uplink_issue_flapping cycle=1751 dev=wlan0 changes=5 window_s=600 current=clear
2026-09-14T15:56:00+10:00 pi binnacle[1]: WARNING: event=service_restart cycle=1753 unit=binnacle-tunnel.service ok=True ready_ms=- reason=affinity: the poller's connection sat on wlan2 for 3 cycles while wlan1 is the active route err=
2026-09-14T15:56:00+10:00 pi binnacle[1]: ERROR: event=tunnel_not_ready cycle=1753 unit=binnacle-tunnel.service waited_s=10 reason=no new health server answered
2026-09-14T15:57:00+10:00 pi binnacle[1]: WARNING: event=fast_failover_blocked cycle=1755 dev=wlan1 reason=no standby with a TCP path
"""


def test_render_sums_up_the_fifth_review_events():
    events = watchlog.parse(FIFTH.splitlines())
    out = watchlog.render(events)
    assert "wlan1: fast failover after 4 misses (20 s) -> wlan2 (metric 300)" in out
    assert "restart binnacle-tunnel.service ok=True ready in 612 ms: failover" in out
    assert "wlan0: issue flapping, 5 changes in 600 s; now clear" in out
    assert "not ready 10 s after its restart" in out
    assert "wlan1: fast failover blocked: no standby with a TCP path" in out
    assert (
        "failovers (wedge/dead end demotions): 1 (1 by the fast path), restores: 1, "
        "fast failovers blocked: 1" in out
    )
    assert "tunnel restarts: affinity 1, failover 1" in out
    assert "issue flapping summaries: 1" in out


def test_tunnel_polls_and_the_chatgpt_summary(tmp_path):
    log = tmp_path / "binnacle.log"
    lines = [
        '{"time":"2026-09-14T15:40:00.123456789+10:00","msg":"poll timed out; backing off"}',
        '{"time":"2026-09-14T15:52:10.000000000+10:00","msg":"poll timed out; backing off"}',
        '{"time":"2026-09-14T15:52:40.5+10:00","msg":"poll failed; backing off"}',
        '{"time":"2026-09-14T15:53:00+10:00","msg":"poller recovered; polling operational"}',
        '{"time":"2026-09-14T15:55:30+10:00","msg":"dispatcher forwarded command to MCP server"}',
        '{"time":"garbage","msg":"poll failed; backing off"}',
        "not json {",
    ]
    log.write_text("".join(line + "\n" for line in lines))
    events = watchlog.parse(FIFTH.splitlines())
    window = watchlog.window_of(events)
    assert window is not None and window[0].strftime("%H:%M:%S") == "15:51:56"
    polls = watchlog.tunnel_polls(log, *window)
    assert [(w.strftime("%H:%M:%S"), k) for w, k in polls] == [
        ("15:52:10", "down"),
        ("15:52:40", "down"),
        ("15:53:00", "up"),
    ]
    out = watchlog.render(events, polls=polls)
    assert "ChatGPT (tunnel log): 2 polls failed or timed out, 1 recoveries" in out
    assert (
        "failed polls per failover (from a minute before to the restore): 15:51:56 wlan1 2"
        in out
    )
    assert watchlog.window_of([]) is None
    assert watchlog.tunnel_polls(tmp_path / "missing.log", *window) == []

"""Classification rules for Chat-mode async probe journals."""

from scripts.analyze_chat_async_probe import analyze

BASE = """\
2026-09-23T00:00:00.000 INFO: event=tool_call call=w tool=async_probe_wait client=openai-mcp session=s request_id=0 turn=turn1/a args={"delay_s":10,"label":"long","probe_id":"P"}
2026-09-23T00:00:00.001 INFO: event=async_probe phase=start tool=wait probe_id=P label=long token=- call=w monotonic_ns=100
2026-09-23T00:00:00.010 INFO: event=tool_call call=s tool=async_probe_seed client=openai-mcp session=s request_id=0 turn=turn1/b args={"probe_id":"P"}
2026-09-23T00:00:00.011 INFO: event=async_probe phase=start tool=seed probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=s monotonic_ns=110
2026-09-23T00:00:00.012 INFO: event=async_probe phase=end tool=seed probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=s monotonic_ns=120
"""


def test_true_async_requires_dependent_echo_before_wait_end():
    text = (
        BASE
        + """\
2026-09-23T00:00:00.020 INFO: event=tool_call call=e tool=async_probe_echo client=openai-mcp session=s request_id=0 turn=turn1/c args={"probe_id":"P","token":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
2026-09-23T00:00:00.021 INFO: event=async_probe phase=start tool=echo probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=e monotonic_ns=130
2026-09-23T00:00:00.022 INFO: event=async_probe phase=end tool=echo probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=e monotonic_ns=140
2026-09-23T00:00:00.100 INFO: event=async_probe phase=end tool=wait probe_id=P label=long token=- call=w monotonic_ns=1000
"""
    )
    result = analyze(text, "P")
    assert result["classification"] == "true_async"
    assert result["same_turn"] is True


def test_batch_barrier_when_echo_waits_for_long_call():
    text = (
        BASE
        + """\
2026-09-23T00:00:00.100 INFO: event=async_probe phase=end tool=wait probe_id=P label=long token=- call=w monotonic_ns=1000
2026-09-23T00:00:00.110 INFO: event=tool_call call=e tool=async_probe_echo client=openai-mcp session=s request_id=0 turn=turn1/c args={"probe_id":"P","token":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
2026-09-23T00:00:00.111 INFO: event=async_probe phase=start tool=echo probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=e monotonic_ns=1100
2026-09-23T00:00:00.112 INFO: event=async_probe phase=end tool=echo probe_id=P label=- token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx call=e monotonic_ns=1110
"""
    )
    result = analyze(text, "P")
    assert result["classification"] == "parallel_batch_barrier"
    assert result["seed_finished_while_wait_running"] is True
    assert result["echo_started_before_wait_end"] is False


def test_parallel_waits_overlap():
    text = """\
2026-09-23T00:00:00 INFO: event=tool_call call=a tool=async_probe_wait client=openai-mcp session=s request_id=0 turn=t/a args={"probe_id":"P"}
2026-09-23T00:00:00 INFO: event=tool_call call=b tool=async_probe_wait client=openai-mcp session=s request_id=0 turn=t/b args={"probe_id":"P"}
2026-09-23T00:00:00 INFO: event=async_probe phase=start tool=wait probe_id=P label=a token=- call=a monotonic_ns=100
2026-09-23T00:00:00 INFO: event=async_probe phase=start tool=wait probe_id=P label=b token=- call=b monotonic_ns=110
2026-09-23T00:00:01 INFO: event=async_probe phase=end tool=wait probe_id=P label=a token=- call=a monotonic_ns=1000
2026-09-23T00:00:01 INFO: event=async_probe phase=end tool=wait probe_id=P label=b token=- call=b monotonic_ns=1010
"""
    assert analyze(text, "P")["classification"] == "parallel_dispatch"

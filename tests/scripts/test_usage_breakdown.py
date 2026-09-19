"""Gate for scripts/usage_breakdown.py's era-aware counting.

The old era (rich-wrapped ``request_start`` with the arguments in the
payload) and the new era (single-line ``tool_call`` / ``tool_result``
records, 2026-09-13 on) must count one call once, and only the new era
yields result metrics. The tunnel-log attribution is fed as a set of
dispatch times, as the script does.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

from binnacle import logstats

_SPEC = importlib.util.spec_from_file_location(
    "usage_breakdown",
    Path(__file__).resolve().parents[2] / "scripts" / "usage_breakdown.py",
)
assert _SPEC is not None
ub = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(ub)

# One old-era call (09/12), then a new-era call that has BOTH its
# request_start record and its tool_call record (same session and
# request_id), then a new-era error and a job that exits later.
SAMPLE = """\
[09/12/26 10:00:00] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"run_co
                             mmand","arguments":{"command":"git s
                             tatus | tail -n 5","workdir":"/tmp"}}
                             payload_type=CallToolRequestParams
                             request_id=0 session=aaaa
                             client=openai-mcp tool=run_command
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=120.00 request_id=0
                             session=aaaa
                             client=openai-mcp tool=run_command
[09/13/26 23:00:00] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"read_f
                             ile","arguments":{"path":"/tmp/a.py"}}
                             payload_type=CallToolRequestParams
                             request_id=0 session=bbbb
                             client=openai-mcp tool=read_file
2026-09-13T23:00:00.010 INFO: event=tool_call call=c1 tool=read_file client=openai-mcp session=bbbb request_id=0 turn=wfr_turn1/x1 args_chars=20 args={"path":"/tmp/a.py","start_line":1,"end_line":40}
2026-09-13T23:00:00.020 INFO: event=tool_result call=c1 tool=read_file client=openai-mcp session=bbbb request_id=0 duration_ms=4.00 is_error=False content_chars=100 structured_bytes=1900 est_tokens=500 truncated=true total_lines=90 start_line=1 end_line=40 kind=text bytes=3000
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=5.00 request_id=0
                             session=bbbb
                             client=openai-mcp tool=read_file
2026-09-13T23:00:05.000 INFO: event=tool_call call=c2 tool=run_command client=openai-mcp session=cccc request_id=0 turn=wfr_turn1/x2 args_chars=40 args={"wait_seconds":1,"workdir":"/tmp","command":"sleep 5"}
2026-09-13T23:00:05.001 INFO: event=job_start job_id=j1 pid=5 command='sleep 5' workdir=/tmp call=c2
2026-09-13T23:00:06.002 INFO: event=tool_result call=c2 tool=run_command client=openai-mcp session=cccc request_id=0 duration_ms=1001.00 is_error=False content_chars=90 structured_bytes=220 est_tokens=77 job_id=j1 state=running background_job=true truncated=false output_bytes=0
2026-09-13T23:00:07.000 INFO: event=tool_call call=c3 tool=read_file client=openai-mcp session=dddd request_id=0 turn=wfr_turn2/y1 args_chars=22 args={"path":"/etc/passwd"}
2026-09-13T23:00:07.002 WARNING: event=tool_result call=c3 tool=read_file client=openai-mcp session=dddd request_id=0 duration_ms=2.00 is_error=True error_class=ToolError error=Path outside allowed roots (/tmp): /etc/passwd
2026-09-13T23:00:08.000 INFO: event=tool_call call=c4 tool=run_command client=claude-code session=eeee request_id=3 args_chars=30 args={"workdir":"/tmp","command":"ls"}
2026-09-13T23:00:08.010 INFO: event=tool_result call=c4 tool=run_command client=claude-code session=eeee request_id=3 duration_ms=9.00 is_error=False content_chars=90 structured_bytes=200 est_tokens=72 job_id=j2 state=exited exit_code=0 background_job=false truncated=false output_bytes=3
2026-09-13T23:00:10.000 INFO: event=job_exit job_id=j1 exit_code=0 signal=None runtime_s=5.001 log_bytes=0
2026-09-13T23:00:11.000 INFO: event=tool_call call=c5 tool=run_command client=openai-mcp session=ffff request_id=0 turn=wfr_turn2/y2 args_chars=30 args={"workdir":"/tmp","command":"false"}
2026-09-13T23:00:11.001 INFO: event=job_start job_id=j3 pid=7 command='false' workdir=/tmp call=c5
2026-09-13T23:00:11.003 INFO: event=job_exit job_id=j3 exit_code=1 signal=None runtime_s=0.002 log_bytes=0
2026-09-13T23:00:11.004 INFO: event=tool_result call=c5 tool=run_command client=openai-mcp session=ffff request_id=0 turn=wfr_turn2/y2 duration_ms=9.00 is_error=False content_chars=90 structured_bytes=200 est_tokens=50 job_id=j3 state=exited exit_code=1 background_job=false truncated=false output_bytes=0
"""

DISPATCH = {datetime(2026, 9, 12, 10, 0, 0)}  # noqa: DTZ001 - the tunnel time of the old call only


def _report(**kw):
    records, _ = logstats.parse(SAMPLE)
    return ub.build_report(records, SAMPLE, DISPATCH, "2026-09-12", None, **kw)


def test_each_call_counted_once_across_both_eras():
    rep = _report()
    # old-era run_command (tunnel-matched), new-era read_file x2 (turn=), new-era
    # run_command (turn=); the claude-code call has no turn and no dispatch time.
    assert rep["tool_calls"] == 5
    assert rep["tools"] == {"run_command": 3, "read_file": 2}
    assert rep["days"] == {"09/12/26": 1, "09/13/26": 4}


def test_old_era_traits_still_come_from_the_payload():
    rep = _report()
    assert rep["run_command"]["traits"]["hand-tail"] == 1
    assert rep["git_subcommands"] == {"status": 1}


def test_read_file_spans_from_new_era_args():
    rep = _report()
    assert rep["read_file"]["calls"] == 2
    assert rep["read_file"]["span_median"] == 40


def test_result_metrics_only_for_attributed_calls():
    rep = _report()
    res = rep["results"]
    assert res["calls_with_sizes"] == 3  # c1, c2, c5; c3 errored, c4 is claude-code
    assert res["est_tokens_total"] == 627
    assert res["by_tool"]["read_file"] == {
        "calls": 1,
        "est_tokens_median": 500,
        "est_tokens_p90": 500,
        "est_tokens_max": 500,
        "est_tokens_total": 500,
        "truncated": 1,
        "errors": 1,
    }
    assert res["errors_by_class"] == {"read_file: ToolError": 1}
    assert res["became_jobs"] == 1
    # j1 exited after its result line, j3 (synchronous) before it: both count
    assert res["job_exits"] == {"0": 1, "1": 1}
    assert res["latency_ms"]["run_command"] == {"median": 1001.0, "p90": 1001.0}


def test_turns_from_the_journal():
    rep = _report()
    assert rep["turns_journal"] == {
        "turns": 2,
        "calls": 4,
        "calls_per_turn_median": 2,
        "calls_per_turn_max": 2,
    }


def test_all_clients_includes_the_local_agent():
    rep = _report(all_clients=True)
    assert rep["tool_calls"] == 6
    assert rep["results"]["calls_with_sizes"] == 4


def test_test_traffic_is_dropped_by_its_call_id():
    sample = (
        SAMPLE.replace('"command":"ls"', '"command":"echo e2e-1234"')
        .replace("client=claude-code", "client=openai-mcp")
        .replace("session=eeee request_id=3", "session=eeee request_id=3 turn=wfr_t3/z")
    )
    records, _ = logstats.parse(sample)
    rep = ub.build_report(records, sample, DISPATCH, "2026-09-12", None)
    assert rep["tools"]["run_command"] == 3  # the e2e- probe is not counted
    assert rep["results"]["calls_with_sizes"] == 3  # nor is its result
    kept = ub.build_report(
        records, sample, DISPATCH, "2026-09-12", None, keep_tests=True
    )
    assert kept["tools"]["run_command"] == 4

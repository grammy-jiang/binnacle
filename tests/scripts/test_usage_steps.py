"""Gate for the model-step and job-polling metrics (scripts/usage_steps.py).

ChatGPT sends several tool calls in one model step, so the 2026-09-27 usage
round counts steps: calls of one turn that start less than 2 s apart are one
step. A job_status poll alone in its step costs one step; the realistic
minimum per job is ceil(max(0, runtime - initial wait) / 61), with the
initial wait 1 s for a background launch.
"""

import importlib.util
from pathlib import Path

import pytest

from binnacle import logstats

_SPEC = importlib.util.spec_from_file_location(
    "usage_breakdown",
    Path(__file__).resolve().parents[2] / "scripts" / "usage_breakdown.py",
)
assert _SPEC is not None
ub = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(ub)
us = ub.usage_steps

_HEAD = "client=openai-mcp session=s request_id=0"


def _call(ts: str, call: str, tool: str, turn: str, args: str) -> str:
    return (
        f"2026-09-27T{ts} INFO: event=tool_call call={call} tool={tool} {_HEAD} "
        f"turn={turn} args_chars={len(args)} args={args}"
    )


def _exit(ts: str, job: str, runtime: float, call: str) -> str:
    return (
        f"2026-09-27T{ts} INFO: event=job_exit job_id={job} exit_code=0 signal=None "
        f"reason=normal_exit runtime_s={runtime} log_bytes=10 call={call} owner=manager"
    )


SAMPLE = "\n".join(
    [
        # Turn T1: two reads in one step, a serial read, a command that
        # becomes job aa01 (wait 30 s, runtime 140 s), two solo polls, and a
        # poll that shares its step with a read.
        _call("10:00:00.000", "a1", "read_file", "T1/1", '{"path":"/tmp/a.py"}'),
        _call("10:00:00.300", "a2", "read_file", "T1/2", '{"path":"/tmp/b.py"}'),
        _call("10:00:10.000", "a3", "read_file", "T1/3", '{"path":"/tmp/c.py"}'),
        _call(
            "10:00:20.000",
            "r1",
            "run_command",
            "T1/4",
            '{"wait_seconds":30,"workdir":"/tmp","command":"pytest -q"}',
        ),
        _call(
            "10:00:50.500",
            "p1",
            "job_status",
            "T1/5",
            '{"job_id":"aa01","wait_seconds":10}',
        ),
        _call(
            "10:01:10.000",
            "p2",
            "job_status",
            "T1/6",
            '{"job_id":"aa01","wait_seconds":50}',
        ),
        _call(
            "10:02:10.000",
            "p3",
            "job_status",
            "T1/7",
            '{"job_id":"aa01","wait_seconds":0}',
        ),
        _call("10:02:10.500", "a4", "read_file", "T1/8", '{"path":"/tmp/a.py"}'),
        _exit("10:02:40.000", "aa01", 140.0, "r1"),
        # Turn T2: a background launch (initial wait 1 s) of a 70 s job
        # with three solo polls.
        _call(
            "11:00:00.000",
            "r2",
            "run_command",
            "T2/1",
            '{"wait_seconds":30,"background":true,"workdir":"/tmp","command":"sleep 70"}',
        ),
        _call(
            "11:00:40.000",
            "p4",
            "job_status",
            "T2/2",
            '{"job_id":"bb02","wait_seconds":5}',
        ),
        _call(
            "11:01:00.000",
            "p5",
            "job_status",
            "T2/3",
            '{"job_id":"bb02","wait_seconds":5}',
        ),
        _exit("11:01:10.000", "bb02", 70.0, "r2"),
        _call(
            "11:01:20.000",
            "p6",
            "job_status",
            "T2/4",
            '{"job_id":"bb02","wait_seconds":50}',
        ),
        # A local agent (no turn), a nonce-marked probe and a listing in T3.
        (
            "2026-09-27T12:00:00.000 INFO: event=tool_call call=l1 tool=read_file "
            'client=claude-code session=l request_id=1 args_chars=16 args={"path":"/tmp/z"}'
        ),
        _call(
            "12:00:01.000", "e1", "run_command", "T3/1", '{"command":"echo e2e-1234"}'
        ),
        _call("12:00:05.000", "p7", "job_status", "T3/2", "{}"),
    ]
)


def _report(**kw):
    records, _ = logstats.parse(SAMPLE)
    return ub.build_report(records, SAMPLE, set(), "2026-09-27", None, **kw)


def test_attribution_counts_turn_ids_only():
    rep = _report()
    assert rep["attribution"] == {"turn_attributed_calls": 13, "tool_calls": 13}


def test_parallel_calls_form_one_step():
    st = _report()["steps"]
    assert (st["turns"], st["calls"], st["steps"]) == (3, 13, 11)
    assert st["calls_per_step"] == 1.18
    assert (st["steps_per_turn_median"], st["steps_per_turn_p90"]) == (4, 6)
    assert st["steps_per_turn_max"] == 6
    assert st["read_after_other_read"] == {"parallel": 1, "serial": 1}


def test_solo_polls_and_their_waits():
    jp = _report()["job_polling"]
    assert (jp["polls"], jp["listings"], jp["solo_polls"]) == (6, 1, 5)
    assert jp["solo_share_of_steps"] == round(5 / 11, 4)
    assert jp["solo_wait_seconds"] == {"5": 2, "10": 1, "50": 2}
    assert jp["solo_at_max_share"] == 0.4
    assert jp["polled_jobs"] == 2
    assert (jp["polls_per_polled_job_median"], jp["polls_per_polled_job_max"]) == (3, 3)


def test_minimum_uses_the_initial_wait_and_the_background_rule():
    jp = _report()["job_polling"]
    # aa01: ceil((140 - 30) / 61) = 2, two solo polls -> no excess.
    # bb02: background, ceil((70 - 1) / 61) = 2, three solo polls -> one excess.
    assert jp["jobs_with_runtime"] == 2
    assert jp["realistic_minimum"] == 4
    assert jp["excess_over_minimum"] == 1
    assert jp["poll_cycle_s"] == 61


def test_keep_tests_keeps_the_probe():
    rep = _report(keep_tests=True)
    assert rep["attribution"]["turn_attributed_calls"] == 14
    assert rep["steps"]["steps"] == 12


def test_polls_on_a_probe_job_are_dropped():
    sample = (
        SAMPLE
        + "\n"
        + "\n".join(
            [
                (
                    "2026-09-27T12:00:02.000 INFO: event=job_start job_id=cc03 pid=9 "
                    "command='echo e2e-1234' workdir=/tmp call=e1"
                ),
                _call("12:00:30.000", "p8", "job_status", "T3/3", '{"job_id":"cc03"}'),
            ]
        )
    )
    records, _ = logstats.parse(sample)
    rep = ub.build_report(records, sample, set(), "2026-09-27", None)
    assert rep["job_polling"]["polls"] == 6


@pytest.mark.parametrize("stamp", [None, "", "not-a-time"])
def test_a_call_without_a_usable_timestamp_is_skipped(stamp):
    assert us._epoch(stamp) is None


def test_empty_window():
    out = us.measure([], 0)
    assert out["steps"]["steps"] == 0 and out["steps"]["calls_per_step"] == 0
    assert out["job_polling"]["solo_share_of_steps"] == 0
    assert out["job_polling"]["solo_at_max_share"] == 0

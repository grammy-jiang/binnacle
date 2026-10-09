"""Model steps and job-polling efficiency of ChatGPT turns.

Added in the 2026-09-27 usage round (docs/usage-analysis-2026-09-27.md).
ChatGPT sends several tool calls in one model step, so a call count
over-states round trips: 86% of the reads of a different file right after
a read were parallel calls in the same step.

Attribution is exact: a ``tool_call`` record that carries the tunnel's
``turn=<id>/<call>`` came from ChatGPT. Inside one turn, a call that starts
less than ``STEP_GAP_S`` after the previous call belongs to the same step.

A ``job_status`` poll that is alone in its step costs one model step. The
realistic minimum of such polls for a job is
``ceil(max(0, runtime_s - initial_wait) / POLL_CYCLE_S)``: ``runtime_s``
from the job's ``job_exit`` record, ``initial_wait`` the spawning
run_command's ``wait_seconds`` (1 when ``background`` is true), and
``POLL_CYCLE_S`` one 50 s wait plus about 11 s of model time.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any

from binnacle.observability import logstats

STEP_GAP_S = 2.0
POLL_CYCLE_S = 61
WAIT_MAX_S = 50
RUN_WAIT_DEFAULT_S = 30  # RunCommandSettings.wait_default_s, repository default
_PATH = re.compile(r'"path":"([^"]*)"')
_JOB = re.compile(r'"job_id":"([0-9a-f]+)"')
_WAIT = re.compile(r'"wait_seconds":(\d+)')


@dataclass(frozen=True)
class Call:
    turn: str
    ts: float
    call: str
    tool: str
    args: str


def _median(xs: list[int]) -> int:
    return sorted(xs)[len(xs) // 2] if xs else 0


def _p90(xs: list[int]) -> int:
    return sorted(xs)[int(len(xs) * 0.9)] if xs else 0


def _epoch(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def collect(
    records: Iterable[Any],
    test_jobs: frozenset[str] | set[str] = frozenset(),
    is_test: Callable[[str], bool] | None = None,
) -> tuple[list[Call], dict[str, tuple[float, str]]]:
    """Turn-attributed calls (test traffic dropped) and job runtimes by job id."""
    calls: list[Call] = []
    exits: dict[str, tuple[float, str]] = {}
    for r in records:
        if r.event == "tool_call":
            f = logstats.plain_fields(r.body)
            turn, ts, args = f.get("turn"), _epoch(r.timestamp), f.get("args", "")
            if not turn or ts is None:
                continue
            if is_test and (
                is_test(args) or any(j in test_jobs for j in _JOB.findall(args))
            ):
                continue
            calls.append(
                Call(
                    turn.split("/")[0], ts, f.get("call", ""), f.get("tool", "?"), args
                )
            )
        elif r.event == "job_exit":
            f = logstats.plain_fields(r.body)
            try:
                runtime = float(f["runtime_s"])
            except (KeyError, ValueError):
                continue
            if f.get("job_id") and f.get("call"):
                exits[f["job_id"]] = (runtime, f["call"])
    return calls, exits


def steps_by_turn(calls: Iterable[Call]) -> dict[str, list[list[Call]]]:
    """Each turn's calls in time order, grouped into model steps."""
    turns: dict[str, list[Call]] = defaultdict(list)
    for c in calls:
        turns[c.turn].append(c)
    out: dict[str, list[list[Call]]] = {}
    for turn, seq in turns.items():
        seq.sort(key=lambda c: c.ts)
        steps: list[list[Call]] = []
        prev: float | None = None
        for c in seq:
            if prev is None or c.ts - prev >= STEP_GAP_S:
                steps.append([c])
            else:
                steps[-1].append(c)
            prev = c.ts
        out[turn] = steps
    return out


def _read_after_other_read(by_turn: dict[str, list[list[Call]]]) -> dict[str, int]:
    parallel = serial = 0
    for steps in by_turn.values():
        seq = [c for s in steps for c in s]
        for a, b in pairwise(seq):
            pa, pb = _PATH.search(a.args), _PATH.search(b.args)
            if a.tool == b.tool == "read_file" and pa and pb and pa[1] != pb[1]:
                if b.ts - a.ts < STEP_GAP_S:
                    parallel += 1
                else:
                    serial += 1
    return {"parallel": parallel, "serial": serial}


def _polling(
    by_turn: dict[str, list[list[Call]]],
    exits: dict[str, tuple[float, str]],
    n_steps: int,
) -> dict[str, Any]:
    run: dict[str, tuple[int, bool]] = {}
    polls: list[tuple[str, int, bool]] = []  # (job id, wait, alone in its step)
    listings = 0
    for steps in by_turn.values():
        for s in steps:
            for c in s:
                w = _WAIT.search(c.args)
                if c.tool == "run_command":
                    wait = int(w[1]) if w else RUN_WAIT_DEFAULT_S
                    run[c.call] = (wait, '"background":true' in c.args)
                elif c.tool == "job_status":
                    j = _JOB.search(c.args)
                    if j:
                        polls.append((j[1], int(w[1]) if w else 0, len(s) == 1))
                    else:
                        listings += 1
    solo = [p for p in polls if p[2]]
    waits = Counter(p[1] for p in solo)
    per_job = Counter(p[0] for p in polls)
    jobs = minimum = excess = 0
    for job, n in Counter(p[0] for p in solo).items():
        runtime, call = exits.get(job, (0.0, ""))
        if call not in run:
            continue
        wait, background = run[call]
        initial = 1 if background else wait
        need = math.ceil(max(0.0, runtime - initial) / POLL_CYCLE_S)
        jobs += 1
        minimum += min(n, need)
        excess += max(0, n - need)
    return {
        "polls": len(polls),
        "listings": listings,
        "solo_polls": len(solo),
        "solo_share_of_steps": round(len(solo) / n_steps, 4) if n_steps else 0,
        "solo_wait_seconds": {str(k): v for k, v in sorted(waits.items())},
        "solo_at_max_share": round(waits[WAIT_MAX_S] / len(solo), 4) if solo else 0,
        "polled_jobs": len(per_job),
        "polls_per_polled_job_median": _median(list(per_job.values())),
        "polls_per_polled_job_max": max(per_job.values(), default=0),
        "jobs_with_runtime": jobs,
        "realistic_minimum": minimum,
        "excess_over_minimum": excess,
    }


def measure(
    records: Iterable[Any],
    tool_calls: int,
    test_jobs: frozenset[str] | set[str] = frozenset(),
    is_test: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """The ``attribution``, ``steps`` and ``job_polling`` report sections."""
    calls, exits = collect(records, test_jobs, is_test)
    by_turn = steps_by_turn(calls)
    per_turn = [len(s) for s in by_turn.values()]
    n_steps = sum(per_turn)
    return {
        "attribution": {"turn_attributed_calls": len(calls), "tool_calls": tool_calls},
        "steps": {
            "turns": len(by_turn),
            "calls": len(calls),
            "steps": n_steps,
            "calls_per_step": round(len(calls) / n_steps, 2) if n_steps else 0,
            "steps_per_turn_median": _median(per_turn),
            "steps_per_turn_p90": _p90(per_turn),
            "steps_per_turn_max": max(per_turn, default=0),
            "read_after_other_read": _read_after_other_read(by_turn),
            "step_gap_s": STEP_GAP_S,
        },
        "job_polling": _polling(by_turn, exits, n_steps)
        | {"poll_cycle_s": POLL_CYCLE_S},
    }

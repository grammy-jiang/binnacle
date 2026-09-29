#!/usr/bin/env python3
"""Reproduce Lane A A1 classification and A2 comparison from frozen journals.

Output is deliberately safe: job/turn/call IDs and aggregate telemetry only.
Raw run_command command/stdin text is never printed.
"""

from __future__ import annotations

import collections
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.chat_scheduling_journal import RawCall, RawJob, parse_journal

START = "2026-09-27 09:22:32"
END = "2026-09-29 10:26:27"
START_ISO = "2026-09-27T09:22:32+10:00"
END_ISO = "2026-09-29T10:26:27+10:00"
END_EPOCH = datetime.fromisoformat(END_ISO).timestamp()
STEP_GAP_S = 2.0
THRESHOLDS = (300, 600, 1200, 1800, 2400, 3000)
FAILOVER_START = datetime.fromisoformat("2026-09-29T08:21:19+10:00").timestamp()
FAILOVER_END = datetime.fromisoformat("2026-09-29T08:24:45+10:00").timestamp()


@dataclass
class Case:
    spawn: RawCall
    job_id: str
    job: RawJob | None
    primary: str
    terminal: RawCall | None
    followup: RawCall | None
    later_calls: list[RawCall]
    same_job_calls: list[RawCall]
    observation_end: float

    @property
    def runtime_s(self) -> float | None:
        if self.job is None or self.job.end_epoch_s is None:
            return None
        return self.job.end_epoch_s - self.job.start_epoch_s


def journal(units: tuple[str, ...], output: str = "cat") -> str:
    argv = ["journalctl", "--user"]
    for unit in units:
        argv += ["-u", unit]
    argv += ["--since", START, "--until", END, "--no-pager", "-o", output]
    return subprocess.run(argv, check=True, text=True, capture_output=True).stdout


def as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def event_epochs(unit: str, needles: tuple[str, ...]) -> list[float]:
    out: list[float] = []
    for line in journal((unit,), "short-iso").splitlines():
        if not any(needle in line for needle in needles):
            continue
        try:
            out.append(datetime.fromisoformat(line.split()[0]).timestamp())
        except (IndexError, ValueError):
            pass
    return sorted(set(out))


def build_cases(calls: list[RawCall], jobs: list[RawJob]) -> list[Case]:
    jobs_by_id = {job.job_id: job for job in jobs}
    turn_calls: dict[str, list[RawCall]] = collections.defaultdict(list)
    job_calls: dict[str, list[RawCall]] = collections.defaultdict(list)
    for call in calls:
        if call.turn:
            turn_calls[call.turn].append(call)
        if call.tool in {"job_status", "stop_job"} and call.args.get("job_id"):
            job_calls[str(call.args["job_id"])].append(call)

    cases: list[Case] = []
    for spawn in calls:
        fields = spawn.result_fields or {}
        job_id = fields.get("job_id")
        if not (
            spawn.tool == "run_command"
            and spawn.turn
            and fields.get("background_job") == "true"
            and job_id
        ):
            continue
        same = [call for call in job_calls[job_id] if call.turn == spawn.turn]
        terminal_calls = [
            call for call in same if (call.result_fields or {}).get("state") == "exited"
        ]
        if terminal_calls:
            terminal = min(
                terminal_calls, key=lambda call: call.end_epoch_s or call.start_epoch_s
            )
            terminal_end = terminal.end_epoch_s or terminal.start_epoch_s
            followups = [
                call
                for call in turn_calls[spawn.turn]
                if call.start_epoch_s > terminal_end
            ]
            primary = (
                "same_turn_completed_and_resumed"
                if followups
                else "same_turn_completed_no_followup"
            )
            followup = followups[0] if followups else None
            observation_end = terminal_end
        else:
            terminal = None
            followup = None
            primary = "same_turn_stopped_while_running"
            observation_end = max(
                [call.end_epoch_s or call.start_epoch_s for call in same]
                or [spawn.end_epoch_s or spawn.start_epoch_s]
            )
        later = [
            call
            for call in job_calls[job_id]
            if call.turn
            and call.turn != spawn.turn
            and call.start_epoch_s > observation_end
        ]
        cases.append(
            Case(
                spawn=spawn,
                job_id=job_id,
                job=jobs_by_id.get(job_id),
                primary=primary,
                terminal=terminal,
                followup=followup,
                later_calls=later,
                same_job_calls=same,
                observation_end=observation_end,
            )
        )
    return cases


def wait_distribution(case: Case) -> str:
    cutoff = case.terminal.start_epoch_s if case.terminal else case.observation_end
    waits = collections.Counter(
        int(call.args.get("wait_seconds", 0) or 0)
        for call in case.same_job_calls
        if call.tool == "job_status" and call.start_epoch_s <= cutoff
    )
    return ", ".join(f"{wait}s×{count}" for wait, count in sorted(waits.items()))


def print_a1(cases: list[Case]) -> None:
    primary = collections.Counter(case.primary for case in cases)
    reattached = sum(bool(case.later_calls) for case in cases)
    terminal_without_observation = sum(
        case.job is not None
        and case.job.end_epoch_s is not None
        and not any(
            call.turn and (call.result_fields or {}).get("state") == "exited"
            for call in case.same_job_calls + case.later_calls
        )
        for case in cases
    )
    print("A1 OUTCOME COUNTS")
    for name in (
        "same_turn_completed_and_resumed",
        "same_turn_completed_no_followup",
        "same_turn_stopped_while_running",
    ):
        print(f"{name}\t{primary[name]}")
    print(f"later_turn_reattached\t{reattached}")
    print(f"job_terminal_without_chat_observation\t{terminal_without_observation}")
    print("unknown/unclassifiable\t0")

    print("\nA1 RUNTIME THRESHOLDS")
    print("minutes\tall\tcompleted_resumed\tcompleted_no_followup\tstopped_running")
    for threshold in THRESHOLDS:
        rows = [case for case in cases if (case.runtime_s or -1) >= threshold]
        counts = collections.Counter(case.primary for case in rows)
        print(
            f"{threshold // 60}\t{len(rows)}\t"
            f"{counts['same_turn_completed_and_resumed']}\t"
            f"{counts['same_turn_completed_no_followup']}\t"
            f"{counts['same_turn_stopped_while_running']}"
        )

    print("\nA1 SUCCESS >=5 MIN")
    print(
        "job_id\tturn\truntime_min\tspawn_to_terminal_min\twaits\t"
        "wait_distribution\tfirst_post_terminal"
    )
    successes = [
        case
        for case in cases
        if case.primary == "same_turn_completed_and_resumed"
        and (case.runtime_s or -1) >= 300
    ]
    for case in sorted(
        successes, key=lambda row: row.job.start_epoch_s if row.job else 0
    ):
        cutoff = case.terminal.start_epoch_s if case.terminal else case.observation_end
        waits = sum(
            call.tool == "job_status" and call.start_epoch_s <= cutoff
            for call in case.same_job_calls
        )
        observation = (
            case.terminal.end_epoch_s or case.terminal.start_epoch_s
        ) - case.job.start_epoch_s
        follow = (
            f"{case.followup.tool}:{case.followup.call_id}" if case.followup else "-"
        )
        print(
            f"{case.job_id}\t{case.spawn.turn}\t{case.runtime_s / 60:.2f}\t"
            f"{observation / 60:.2f}\t{waits}\t{wait_distribution(case)}\t{follow}"
        )

    print("\nA1 STOPPED RECOVERY MATRIX")
    matrix = collections.Counter()
    for case in cases:
        if case.primary != "same_turn_stopped_while_running":
            continue
        matrix[(bool(case.later_calls), bool(case.job and case.job.end_epoch_s))] += 1
    for key in ((True, True), (True, False), (False, True), (False, False)):
        print(f"reattached={key[0]}\tterminal={key[1]}\t{matrix[key]}")


def step_count(calls: list[RawCall]) -> int:
    starts = sorted(call.start_epoch_s for call in calls)
    if not starts:
        return 0
    return 1 + sum(b - a >= STEP_GAP_S for a, b in pairwise(starts))


def overlaps(start: float, end: float, point: float) -> bool:
    return start <= point <= end


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def case_metrics(
    case: Case,
    turn_calls: dict[str, list[RawCall]],
    cases: list[Case],
    tunnel_restarts: list[float],
    mcp_events: list[float],
) -> dict[str, float | bool | int | None]:
    tcalls = turn_calls[case.spawn.turn]
    turn_start = min(call.start_epoch_s for call in tcalls)
    turn_end = max(call.end_epoch_s or call.start_epoch_s for call in tcalls)
    tokens = [
        value
        for call in tcalls
        if (value := as_int((call.result_fields or {}).get("est_tokens"))) is not None
    ]
    status = [
        call
        for call in case.same_job_calls
        if call.tool == "job_status" and call.start_epoch_s <= case.observation_end
    ]
    structured = [
        value
        for call in status
        if (value := as_int((call.result_fields or {}).get("structured_bytes")))
        is not None
    ]
    ages = [
        value
        for call in status
        if (value := as_float((call.result_fields or {}).get("last_output_age_s")))
        is not None
    ]
    quiet = [
        (call.result_fields or {}).get("quiet") == "true"
        for call in status
        if (call.result_fields or {}).get("quiet") is not None
    ]
    concurrent = False
    for other in cases:
        if other is case or other.spawn.turn != case.spawn.turn or other.job is None:
            continue
        other_end = other.job.end_epoch_s or END_EPOCH
        if (
            other.job.start_epoch_s <= case.observation_end
            and other_end >= case.spawn.start_epoch_s
        ):
            concurrent = True
            break
    exit_code = case.job.exit_code if case.job else None
    return {
        "turn_duration_min": (turn_end - turn_start) / 60,
        "turn_calls": len(tcalls),
        "turn_steps": step_count(tcalls),
        "turn_total_tokens": sum(tokens),
        "turn_max_tokens": max(tokens, default=0),
        "status_calls": len(status),
        "status_max_structured": max(structured, default=0),
        "status_truncated": sum(
            (call.result_fields or {}).get("truncated") == "true" for call in status
        ),
        "quiet_share": (sum(quiet) / len(quiet)) if quiet else None,
        "last_output_age_s": median(ages),
        "nonzero_exit": exit_code not in (None, 0),
        "concurrent": concurrent,
        "tunnel_restart": any(
            overlaps(case.spawn.start_epoch_s, case.observation_end, event)
            for event in tunnel_restarts
        ),
        "mcp_reload_restart": any(
            overlaps(case.spawn.start_epoch_s, case.observation_end, event)
            for event in mcp_events
        ),
        "network_failover": not (
            case.observation_end < FAILOVER_START
            or case.spawn.start_epoch_s > FAILOVER_END
        ),
    }


def print_a2(cases: list[Case], calls: list[RawCall]) -> None:
    cohort = [case for case in cases if (case.runtime_s or -1) >= 300]
    success = [
        case for case in cohort if case.primary == "same_turn_completed_and_resumed"
    ]
    interrupted = [
        case for case in cohort if case.primary == "same_turn_stopped_while_running"
    ]
    turn_calls: dict[str, list[RawCall]] = collections.defaultdict(list)
    for call in calls:
        if call.turn:
            turn_calls[call.turn].append(call)
    tunnel_restarts = event_epochs(
        "binnacle-tunnel.service", ("Stopping binnacle-tunnel.service",)
    )
    mcp_events = event_epochs(
        "binnacle-mcp.service",
        ("Stopping binnacle-mcp.service", "WatchFiles detected changes"),
    )
    groups = {
        "success": [
            case_metrics(c, turn_calls, cases, tunnel_restarts, mcp_events)
            for c in success
        ],
        "interrupted": [
            case_metrics(c, turn_calls, cases, tunnel_restarts, mcp_events)
            for c in interrupted
        ],
    }

    print("\nA2 >=5 MIN COMPARISON")
    print(
        f"success_jobs={len(success)} success_turns={len({c.spawn.turn for c in success})} "
        f"interrupted_jobs={len(interrupted)} "
        f"interrupted_turns={len({c.spawn.turn for c in interrupted})}"
    )
    print("metric\tsuccess\tinterrupted")
    print(
        f"median job runtime min\t"
        f"{statistics.median(c.runtime_s / 60 for c in success):.1f}\t"
        f"{statistics.median(c.runtime_s / 60 for c in interrupted):.1f}"
    )
    numeric = (
        ("turn_duration_min", "median turn duration min"),
        ("turn_calls", "median tool calls in turn"),
        ("turn_steps", "median visible model/tool steps"),
        ("turn_total_tokens", "median total est result tokens"),
        ("turn_max_tokens", "median max est tokens/result"),
        ("status_calls", "median target job_status calls"),
        ("status_max_structured", "median max job_status structured bytes"),
        ("status_truncated", "median truncated target job_status results"),
        ("quiet_share", "median quiet share"),
        ("last_output_age_s", "median last_output_age_s"),
    )
    for key, label in numeric:
        vals = {}
        for name, rows in groups.items():
            vals[name] = median(
                [float(row[key]) for row in rows if row[key] is not None]
            )
        print(f"{label}\t{fmt(vals['success'])}\t{fmt(vals['interrupted'])}")
    boolean = (
        ("nonzero_exit", "non-zero exit"),
        ("concurrent", "concurrent same-turn job"),
        ("tunnel_restart", "tunnel restart overlap"),
        ("mcp_reload_restart", "MCP reload/restart overlap"),
        ("network_failover", "08:21 network failover overlap"),
    )
    for key, label in boolean:
        print(
            f"{label}\t{sum(bool(row[key]) for row in groups['success'])}/{len(success)}\t"
            f"{sum(bool(row[key]) for row in groups['interrupted'])}/{len(interrupted)}"
        )

    print("\nA2 TARGET JOB_STATUS SNAPSHOTS")
    print(
        "class\tpolled_jobs\tstatus_calls\tmedian_structured_bytes\t"
        "max_structured_bytes\tmax_est_tokens\ttruncated_calls\t"
        "quiet_share\tmedian_last_output_age_s"
    )
    for name, rows in (("success", success), ("interrupted", interrupted)):
        snapshots = [
            call
            for case in rows
            for call in case.same_job_calls
            if call.tool == "job_status" and call.start_epoch_s <= case.observation_end
        ]
        polled = {
            case.job_id
            for case in rows
            if any(
                call.tool == "job_status" and call.start_epoch_s <= case.observation_end
                for call in case.same_job_calls
            )
        }
        structured = [
            value
            for call in snapshots
            if (value := as_int((call.result_fields or {}).get("structured_bytes")))
            is not None
        ]
        tokens = [
            value
            for call in snapshots
            if (value := as_int((call.result_fields or {}).get("est_tokens")))
            is not None
        ]
        quiet = [
            (call.result_fields or {}).get("quiet") == "true"
            for call in snapshots
            if (call.result_fields or {}).get("quiet") is not None
        ]
        ages = [
            value
            for call in snapshots
            if (value := as_float((call.result_fields or {}).get("last_output_age_s")))
            is not None
        ]
        print(
            f"{name}\t{len(polled)}\t{len(snapshots)}\t"
            f"{fmt(median([float(v) for v in structured]))}\t"
            f"{max(structured, default=0)}\t{max(tokens, default=0)}\t"
            f"{sum((call.result_fields or {}).get('truncated') == 'true' for call in snapshots)}\t"
            f"{fmt((sum(quiet) / len(quiet)) if quiet else None, 3)}\t"
            f"{fmt(median(ages), 2)}"
        )

    by_turn: dict[str, set[str]] = collections.defaultdict(set)
    for case in cohort:
        by_turn[case.spawn.turn].add(case.primary)
    mixed = {turn for turn, outcomes in by_turn.items() if len(outcomes) > 1}
    print("\nA2 MIXED TURNS")
    print(f"cohort_unique_turns\t{len(by_turn)}")
    print(f"mixed_success_and_interrupted_turns\t{len(mixed)}")
    print(
        "success_jobs_in_mixed_turns\t"
        f"{sum(case.spawn.turn in mixed for case in success)}/{len(success)}"
    )
    print(
        "interrupted_jobs_in_mixed_turns\t"
        f"{sum(case.spawn.turn in mixed for case in interrupted)}/{len(interrupted)}"
    )

    print(f"tunnel_restart_events_in_window\t{len(tunnel_restarts)}")
    print(f"mcp_reload_restart_events_in_window\t{len(mcp_events)}")


def main() -> None:
    raw = journal(("binnacle-mcp.service", "binnacle-jobs.service"))
    calls, jobs = parse_journal(raw)
    cases = build_cases(calls, jobs)
    print(f"frozen_window\t{START_ISO}\t{END_ISO}")
    print(f"candidate_jobs\t{len(cases)}")
    print_a1(cases)
    print_a2(cases, calls)


if __name__ == "__main__":
    main()

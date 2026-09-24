"""Deterministic Phase-3 replay engine for cumulative and H10 wait policies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ALGORITHM_ID = "phase3-replay-v1"
SCHEMA_VERSION = 1
PER_CALL_CAP_S = 50.0
EPSILON = 1e-9


def _nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and >= 0")
    return result


def _optional_nonnegative(value: Any, field: str) -> float | None:
    return None if value is None else _nonnegative(value, field)


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _percent(before: float, after: float) -> float | None:
    return None if before <= EPSILON else _rounded((before - after) * 100.0 / before)


def _merged_intervals(
    intervals: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    ordered = sorted(
        (float(start), float(end))
        for start, end in intervals
        if float(end) - float(start) > EPSILON
    )
    merged: list[tuple[float, float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def interval_union_seconds(intervals: Iterable[tuple[float, float]]) -> float:
    return sum(end - start for start, end in _merged_intervals(intervals))


def _union_before(intervals: Sequence[tuple[float, float]], offset: float) -> float:
    return interval_union_seconds(
        (start, min(end, offset))
        for start, end in intervals
        if start < offset and end > start
    )


def _time_at_union_duration(
    intervals: Sequence[tuple[float, float]], target: float
) -> float | None:
    consumed = 0.0
    for start, end in _merged_intervals(intervals):
        width = end - start
        if consumed + width + EPSILON >= target:
            return start + max(target - consumed, 0.0)
        consumed += width
    return None


def _historical_interval(wait: Mapping[str, Any]) -> tuple[float, float, float]:
    requested = _nonnegative(wait.get("requested_wait_s"), "requested_wait_s")
    waited = _nonnegative(wait.get("waited_s"), "waited_s")
    call_start = _nonnegative(wait.get("call_start_offset_s"), "call_start_offset_s")
    call_end = _nonnegative(wait.get("call_end_offset_s"), "call_end_offset_s")
    block_start = _optional_nonnegative(
        wait.get("blocking_start_offset_s"), "blocking_start_offset_s"
    )
    block_end = _optional_nonnegative(
        wait.get("blocking_end_offset_s"), "blocking_end_offset_s"
    )
    if call_end + EPSILON < call_start:
        raise ValueError("call_end_offset_s precedes call_start_offset_s")
    start = call_start if block_start is None else block_start
    if start + EPSILON < call_start or start > call_end + EPSILON:
        raise ValueError("blocking_start_offset_s is outside the call interval")
    if waited > EPSILON and (block_start is None or block_end is None):
        raise ValueError("positive observed wait is missing blocking interval timing")
    reported_end = start + waited if block_end is None else block_end
    if reported_end + EPSILON < start or reported_end > call_end + EPSILON:
        raise ValueError("blocking_end_offset_s is outside the call interval")
    return start, max(min(reported_end, start + waited, call_end), start), requested


def _wait_sort_key(wait: Mapping[str, Any]) -> tuple[float, int]:
    start = wait.get("blocking_start_offset_s")
    start = wait.get("call_start_offset_s") if start is None else start
    index = wait.get("wait_index", 0)
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("wait_index must be an integer")
    return _nonnegative(start, "wait start"), index


def _required_observed_completion(wait: Mapping[str, Any]) -> bool:
    return bool(wait.get("required_completion")) and bool(
        wait.get("observed_completion")
    )


def _validate_row(row: Mapping[str, Any]) -> None:
    required = {
        "source_id",
        "source_sha256",
        "trial_id",
        "scenario",
        "arm",
        "base_turn",
        "observed_blocking_wall_s",
        "waits",
        "observed_required_completions",
        "terminal_state",
        "correct",
        "same_prompt",
    }
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"replay row is missing fields: {', '.join(missing)}")
    if not isinstance(row["waits"], list):
        raise TypeError("waits must be a list")
    _nonnegative(row["observed_blocking_wall_s"], "observed_blocking_wall_s")
    count = row["observed_required_completions"]
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("observed_required_completions must be an integer")
    if count < 0:
        raise ValueError("observed_required_completions must be >= 0")


def replay_turn(
    row: Mapping[str, Any], *, policy: str, budget_s: float
) -> dict[str, Any]:
    """Replay one normalized historical turn under a frozen Phase-3 policy."""

    _validate_row(row)
    budget = _nonnegative(budget_s, "budget_s")
    if budget <= 0:
        raise ValueError("budget_s must be > 0")
    if policy not in {"cumulative", "historical-one-shot"}:
        raise ValueError(f"unsupported replay policy: {policy}")
    if policy == "historical-one-shot" and abs(budget - 10.0) > EPSILON:
        raise ValueError("historical-one-shot policy is the frozen H10 budget (10 s)")

    waits = sorted(row["waits"], key=_wait_sort_key)
    candidate_intervals: list[tuple[float, float]] = []
    positive_waits = clipped_count = nonblocking_count = 0
    preserved = 0
    exhaustion_offset: float | None = None
    h10_positive_seen = False

    for wait in waits:
        if not isinstance(wait, Mapping):
            raise TypeError("each wait must be an object")
        start, historical_end, requested = _historical_interval(wait)
        observed_duration = max(historical_end - start, 0.0)
        positive_request = requested > EPSILON
        positive_waits += int(positive_request)
        clipped = converted = False
        effective_end = start

        if policy == "cumulative":
            remaining = max(budget - _union_before(candidate_intervals, start), 0.0)
            if positive_request and remaining < 1.0 - EPSILON:
                converted = True
                clipped = observed_duration > EPSILON
                exhaustion_offset = (
                    start if exhaustion_offset is None else exhaustion_offset
                )
            elif positive_request and observed_duration > EPSILON:
                duration = min(observed_duration, PER_CALL_CAP_S, remaining)
                effective_end = start + duration
                clipped = duration + EPSILON < observed_duration
                if duration > EPSILON:
                    candidate_intervals.append((start, effective_end))
        elif positive_request and not h10_positive_seen:
            h10_positive_seen = True
            duration = min(observed_duration, requested, budget, PER_CALL_CAP_S)
            effective_end = start + duration
            clipped = duration + EPSILON < observed_duration
            if duration > EPSILON:
                candidate_intervals.append((start, effective_end))
            exhaustion_offset = effective_end
        elif positive_request:
            converted = True
            clipped = observed_duration > EPSILON
            exhaustion_offset = (
                start if exhaustion_offset is None else exhaustion_offset
            )

        clipped_count += int(clipped)
        nonblocking_count += int(converted)
        if _required_observed_completion(wait):
            exit_offset = _optional_nonnegative(
                wait.get("job_exit_offset_s"), "job_exit_offset_s"
            )
            if exit_offset is None:
                raise ValueError(
                    "required observed completion is missing job_exit_offset_s"
                )
            preserved += int(exit_offset <= effective_end + EPSILON)

    candidate_union = interval_union_seconds(candidate_intervals)
    if policy == "cumulative" and candidate_union + EPSILON >= budget:
        reached = _time_at_union_duration(candidate_intervals, budget)
        if reached is not None:
            exhaustion_offset = (
                reached
                if exhaustion_offset is None
                else min(exhaustion_offset, reached)
            )

    observed_union = _nonnegative(
        row["observed_blocking_wall_s"], "observed_blocking_wall_s"
    )
    observed_required = int(row["observed_required_completions"])
    derived_required = sum(_required_observed_completion(wait) for wait in waits)
    if observed_required != derived_required:
        raise ValueError(
            "observed_required_completions does not match required observed wait markers"
        )
    return {
        "source_id": row["source_id"],
        "source_sha256": row["source_sha256"],
        "trial_id": row["trial_id"],
        "scenario": row["scenario"],
        "historical_arm": row["arm"],
        "base_turn": row["base_turn"],
        "observed_blocking_wall_s": _rounded(observed_union),
        "candidate_blocking_wall_s": _rounded(candidate_union),
        "burden_reduction_percent": _percent(observed_union, candidate_union),
        "candidate_exhaustion_offset_s": (
            None if exhaustion_offset is None else _rounded(exhaustion_offset)
        ),
        "positive_waits_observed": positive_waits,
        "waits_clipped": clipped_count,
        "waits_converted_to_nonblocking": nonblocking_count,
        "observed_required_completions": observed_required,
        "required_completions_preserved": preserved,
        "completion_at_risk": observed_required - preserved,
        "terminal_state": row["terminal_state"],
        "correct": row["correct"],
        "same_prompt": row["same_prompt"],
    }


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observed_wall = sum(float(row["observed_blocking_wall_s"]) for row in rows)
    candidate_wall = sum(float(row["candidate_blocking_wall_s"]) for row in rows)
    positive_turns = sum(int(row["positive_waits_observed"]) > 0 for row in rows)
    exhausted = sum(row["candidate_exhaustion_offset_s"] is not None for row in rows)
    observed_required = sum(int(row["observed_required_completions"]) for row in rows)
    preserved = sum(int(row["required_completions_preserved"]) for row in rows)
    return {
        "turns": len(rows),
        "turns_with_positive_waits": positive_turns,
        "observed_blocking_wall_s": _rounded(observed_wall),
        "candidate_blocking_wall_s": _rounded(candidate_wall),
        "burden_reduction_percent": _percent(observed_wall, candidate_wall),
        "positive_waits_observed": sum(
            int(row["positive_waits_observed"]) for row in rows
        ),
        "waits_clipped": sum(int(row["waits_clipped"]) for row in rows),
        "waits_converted_to_nonblocking": sum(
            int(row["waits_converted_to_nonblocking"]) for row in rows
        ),
        "observed_required_completions": observed_required,
        "required_completions_preserved": preserved,
        "completion_at_risk": observed_required - preserved,
        "completion_preservation_percent": (
            None
            if observed_required == 0
            else _rounded(preserved * 100.0 / observed_required)
        ),
        "turns_exhausted": exhausted,
        "exhaustion_percent": (
            None
            if positive_turns == 0
            else _rounded(exhausted * 100.0 / positive_turns)
        ),
    }


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def replay_corpus(
    corpus: Mapping[str, Any],
    *,
    policy: str,
    budget_s: float,
    corpus_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay all corpus rows and return a canonical policy-report object."""

    if corpus.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported replay corpus schema_version")
    rows = corpus.get("rows")
    if not isinstance(rows, list):
        raise TypeError("replay corpus rows must be a list")
    replayed = [replay_turn(row, policy=policy, budget_s=budget_s) for row in rows]
    replayed.sort(
        key=lambda row: (
            str(row["source_id"]),
            str(row["trial_id"]),
            str(row["base_turn"]),
        )
    )
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in replayed:
        grouped[str(row["scenario"])].append(row)
    per_scenario = [
        {"scenario": scenario, **_aggregate(scenario_rows)}
        for scenario, scenario_rows in sorted(grouped.items())
    ]
    if corpus_sha256 is None:
        corpus_sha256 = hashlib.sha256(
            canonical_json(corpus).encode("utf-8")
        ).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm_id": ALGORITHM_ID,
        "corpus_sha256": corpus_sha256,
        "policy": policy,
        "budget_s": _rounded(float(budget_s)),
        "summary": _aggregate(replayed),
        "per_scenario": per_scenario,
        "rows": replayed,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render deterministic Markdown from a replay-report JSON object."""

    summary = report["summary"]
    lines = [
        "# Phase-3 policy replay",
        "",
        f"- Algorithm: {report['algorithm_id']}",
        f"- Policy: {report['policy']}",
        f"- Budget: {report['budget_s']} s",
        f"- Corpus SHA-256: {report['corpus_sha256']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    summary_keys = (
        "turns",
        "turns_with_positive_waits",
        "observed_blocking_wall_s",
        "candidate_blocking_wall_s",
        "burden_reduction_percent",
        "positive_waits_observed",
        "waits_clipped",
        "waits_converted_to_nonblocking",
        "observed_required_completions",
        "required_completions_preserved",
        "completion_at_risk",
        "completion_preservation_percent",
        "turns_exhausted",
        "exhaustion_percent",
    )
    lines.extend(f"| {key} | {summary[key]} |" for key in summary_keys)
    lines.extend(
        [
            "",
            "## Per scenario",
            "",
            (
                "| Scenario | Turns | Observed wall (s) | Candidate wall (s) | "
                "Preserved / observed | Exhausted turns |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {item['scenario']} | {item['turns']} | "
        f"{item['observed_blocking_wall_s']} | {item['candidate_blocking_wall_s']} | "
        f"{item['required_completions_preserved']} / "
        f"{item['observed_required_completions']} | {item['turns_exhausted']} |"
        for item in report["per_scenario"]
    )
    return "\n".join([*lines, ""])


def write_report(
    corpus_path: Path, *, policy: str, budget_s: float, output_path: Path
) -> dict[str, Any]:
    raw = corpus_path.read_bytes()
    corpus = json.loads(raw)
    if not isinstance(corpus, dict):
        raise TypeError("replay corpus root must be an object")
    report = replay_corpus(
        corpus,
        policy=policy,
        budget_s=budget_s,
        corpus_sha256=hashlib.sha256(raw).hexdigest(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report), encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="chat-scheduling-replay")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--policy", choices=("cumulative", "historical-one-shot"), required=True
    )
    parser.add_argument("--budget-s", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_report(
        args.corpus,
        policy=args.policy,
        budget_s=args.budget_s,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()

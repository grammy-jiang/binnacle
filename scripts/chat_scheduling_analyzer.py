"""Compute correctness, scheduling, efficiency, and UX metrics from TrialTrace."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.chat_scheduling_manifest import Node, Scenario
from scripts.chat_scheduling_oracle import evaluate_oracles
from scripts.chat_scheduling_trace import (
    ToolInterval,
    TrialMetrics,
    TrialTrace,
    calls_by_node,
    exact_call_key,
    intersection_seconds,
    interval_union_seconds,
    peak_inflight,
)

READ_ONLY_TOOLS = {"read_file", "list_files", "search_text", "job_status"}


def _node_map(scenario: Scenario) -> dict[str, Node]:
    return {node.id: node for node in scenario.dag}


def _successful(call: ToolInterval) -> bool:
    return not call.is_error and not bool(call.result.get("is_error"))


def _completion_times(scenario: Scenario, trace: TrialTrace) -> dict[str, float]:
    grouped = calls_by_node(trace)
    completed: dict[str, float] = {}
    for node in scenario.dag:
        calls = grouped.get(node.id, [])
        if node.kind == "tool":
            if node.allow_repeats and node.completion_condition == "job_state=exited":
                final = next(
                    (
                        call
                        for call in calls
                        if _successful(call) and call.result.get("state") == "exited"
                    ),
                    None,
                )
                if final is not None:
                    completed[node.id] = final.end_s
            else:
                first = next((call for call in calls if _successful(call)), None)
                if first is not None:
                    completed[node.id] = first.end_s

    changed = True
    horizon = trace.wall_s or max((call.end_s for call in trace.tools), default=0.0)
    while changed:
        changed = False
        for node in scenario.dag:
            if node.id in completed:
                continue
            if node.kind == "reasoning" and all(
                dep in completed for dep in node.depends_on
            ):
                completed[node.id] = max(
                    (completed[dep] for dep in node.depends_on), default=0.0
                )
                changed = True
            elif node.kind == "control" and node.id in trace.explicit_completed_nodes:
                completed[node.id] = horizon
                changed = True
    for node_id in trace.explicit_completed_nodes:
        completed.setdefault(node_id, horizon)
    return completed


def _ready_time(node: Node, completion: dict[str, float]) -> float | None:
    if not node.depends_on:
        return 0.0
    if not all(dep in completion for dep in node.depends_on):
        return None
    return max(completion[dep] for dep in node.depends_on)


def _descendants(scenario: Scenario) -> dict[str, set[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for node in scenario.dag:
        for dep in node.depends_on:
            children[dep].append(node.id)
    out: dict[str, set[str]] = {}
    for node in scenario.dag:
        seen: set[str] = set()
        stack = list(children[node.id])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(children[current])
        out[node.id] = seen
    return out


def _independent(a: str, b: str, descendants: dict[str, set[str]]) -> bool:
    return b not in descendants[a] and a not in descendants[b]


def _eligible_read_nodes(scenario: Scenario) -> set[str]:
    nodes = [
        node
        for node in scenario.dag
        if node.kind == "tool" and node.tool in READ_ONLY_TOOLS
    ]
    groups: dict[tuple[str, ...], list[Node]] = defaultdict(list)
    for node in nodes:
        groups[tuple(sorted(node.depends_on))].append(node)
    return {node.id for group in groups.values() if len(group) >= 2 for node in group}


def _overlap(a: ToolInterval, b: ToolInterval) -> bool:
    return a.start_s < b.end_s and b.start_s < a.end_s


def _eligible_overlap(scenario: Scenario, trace: TrialTrace) -> tuple[int, int]:
    eligible_nodes = _eligible_read_nodes(scenario)
    calls = [
        call
        for call in trace.tools
        if call.node_id in eligible_nodes and call.tool in READ_ONLY_TOOLS
    ]
    descendants = _descendants(scenario)
    overlapped = 0
    for call in calls:
        if call.node_id is None:
            continue
        if any(
            other.call_id != call.call_id
            and other.node_id is not None
            and _independent(call.node_id, other.node_id, descendants)
            and _overlap(call, other)
            for other in calls
        ):
            overlapped += 1
    return len(calls), overlapped


def _avoidable_idle(scenario: Scenario, trace: TrialTrace) -> float:
    completion = _completion_times(scenario, trace)
    grouped = calls_by_node(trace)
    descendants = _descendants(scenario)
    blocking = [
        (call, (call.blocking_start_s, call.blocking_end_s))
        for call in trace.tools
        if call.node_id is not None
        and call.blocking_start_s is not None
        and call.blocking_end_s is not None
    ]
    pending_intervals: list[tuple[float, float]] = []
    for status_call, block in blocking:
        if block[0] is None or block[1] is None:
            continue
        for node in scenario.dag:
            if (
                node.kind != "tool"
                or node.tool not in READ_ONLY_TOOLS
                or node.id == status_call.node_id
                or status_call.node_id is None
                or not _independent(status_call.node_id, node.id, descendants)
            ):
                continue
            ready = _ready_time(node, completion)
            if ready is None:
                continue
            node_calls = grouped.get(node.id, [])
            start = node_calls[0].start_s if node_calls else (trace.wall_s or block[1])
            if start > ready:
                pending_intervals.append((ready, start))
    block_intervals = [
        (float(start), float(end))
        for _, (start, end) in blocking
        if start is not None and end is not None
    ]
    return intersection_seconds(block_intervals, pending_intervals)


def _derived_relations(scenario: Scenario, trace: TrialTrace) -> dict[str, bool]:
    relations = dict(trace.relations)
    grouped = calls_by_node(trace)

    if "peak_read_only_inflight_observed" not in relations:
        relations["peak_read_only_inflight_observed"] = (
            peak_inflight(
                [
                    (call.start_s, call.end_s)
                    for call in trace.tools
                    if call.tool in READ_ONLY_TOOLS
                ]
            )
            >= 2
        )

    def one(node_id: str) -> ToolInterval | None:
        calls = grouped.get(node_id, [])
        return calls[0] if calls else None

    slow = one("slow_status")
    reads = [
        call
        for node_id, calls in grouped.items()
        if node_id.startswith("read_")
        for call in calls[:1]
    ]
    if slow is not None and reads:
        relations.setdefault(
            "later_read_starts_before_slow_status_ends",
            any(slow.start_s < call.start_s < slow.end_s for call in reads),
        )

    token = one("read_token")
    search = one("dependent_search")
    if slow is not None and token is not None:
        relations.setdefault(
            "token_returns_while_status_running",
            slow.start_s < token.end_s < slow.end_s,
        )
    if slow is not None and search is not None:
        relations.setdefault(
            "dependent_search_vs_status_end",
            search.start_s < slow.end_s,
        )

    stop_calls = [
        call
        for node_id, calls in grouped.items()
        if node_id.startswith("stop_")
        for call in calls
    ]
    if stop_calls:
        relations.setdefault(
            "non_read_only_serialization_observed",
            peak_inflight([(call.start_s, call.end_s) for call in stop_calls]) <= 1,
        )

    jobs = {job.job_id: job for job in trace.jobs}
    for start_node, relation in (
        ("start_job", "read_occurs_while_background_job_running"),
        ("start_validation", "reads_overlap_background_job"),
    ):
        starter = one(start_node)
        if starter is None:
            continue
        job_id = starter.result.get("job_id")
        job = jobs.get(job_id) if isinstance(job_id, str) else None
        if job is None:
            continue
        job_end = job.end_s if job.end_s is not None else (trace.wall_s or float("inf"))
        candidate_reads = [
            call
            for call in trace.tools
            if call.node_id is not None and call.node_id.startswith("read_")
        ]
        relations.setdefault(
            relation,
            any(
                call.start_s < job_end and call.end_s > job.start_s
                for call in candidate_reads
            ),
        )
    return relations


def analyze_trace(scenario: Scenario, trace: TrialTrace) -> TrialMetrics:
    if scenario.id != trace.scenario_id:
        raise ValueError("scenario id does not match trace")

    completion = _completion_times(scenario, trace)
    relations = _derived_relations(scenario, trace)
    failures = evaluate_oracles(scenario, trace, completion, relations)
    correctness = not failures
    terminal = all(node.id in completion for node in scenario.dag)
    interrupted = (
        trace.interruption_kind is not None or trace.timing_status == "timeout"
    )
    same_prompt = (
        terminal
        and correctness
        and trace.assistant_complete
        and trace.user_messages == 1
        and not interrupted
    )
    premature = (
        not terminal
        and trace.assistant_complete
        and not interrupted
        and not trace.budget_exhausted
        and not trace.external_input_required
        and not trace.unrecoverable_error
    )
    budget_handoff = (
        not terminal
        and trace.assistant_complete
        and trace.budget_exhausted
        and not interrupted
    )
    continuations = max(
        max(trace.user_messages - 1, 0),
        1 if (premature or budget_handoff) else 0,
    )

    node_map = _node_map(scenario)
    duplicates = 0
    for node_id, calls in calls_by_node(trace).items():
        node = node_map.get(node_id)
        if node is not None and not node.allow_repeats and len(calls) > 1:
            duplicates += len(calls) - 1

    exact_counts: Counter[tuple[str, str]] = Counter()
    for call in trace.tools:
        node = node_map.get(call.node_id or "")
        if node is not None and node.allow_repeats:
            continue
        exact_counts[exact_call_key(call)] += 1
    redundant_exact = sum(max(count - 1, 0) for count in exact_counts.values())

    blocking = [
        (float(call.blocking_start_s), float(call.blocking_end_s))
        for call in trace.tools
        if call.blocking_start_s is not None and call.blocking_end_s is not None
    ]
    read_calls = [call for call in trace.tools if call.tool in READ_ONLY_TOOLS]
    eligible, overlapped = _eligible_overlap(scenario, trace)

    return TrialMetrics(
        scenario_id=trace.scenario_id,
        run_id=trace.run_id,
        arm=trace.arm,
        wall_s=trace.wall_s,
        correctness_passed=correctness,
        oracle_failures=failures,
        same_prompt_completion=same_prompt,
        premature_handoff=premature,
        budget_exhaustion_handoff=budget_handoff,
        manual_continuations_required=continuations,
        interrupted=interrupted,
        interruption_kind=trace.interruption_kind
        or ("timeout" if trace.timing_status == "timeout" else None),
        tool_calls=len(trace.tools),
        duplicate_calls=duplicates,
        redundant_exact_calls=redundant_exact,
        job_status_calls=sum(call.tool == "job_status" for call in trace.tools),
        positive_job_status_calls=sum(
            call.tool == "job_status"
            and float(call.args.get("wait_seconds", 0) or 0) > 0
            for call in trace.tools
        ),
        blocking_wall_s=interval_union_seconds(blocking),
        avoidable_idle_wall_s=_avoidable_idle(scenario, trace),
        read_only_peak_inflight=peak_inflight(
            [(call.start_s, call.end_s) for call in read_calls]
        ),
        eligible_read_only_calls=eligible,
        overlapped_eligible_read_only_calls=overlapped,
        eligible_read_only_overlap_ratio=(
            round(overlapped / eligible, 6) if eligible else None
        ),
        tool_result_tokens=sum(call.tokenizer_tokens for call in trace.tools),
        tool_result_bytes=sum(call.result_bytes for call in trace.tools),
        tool_errors=sum(call.is_error for call in trace.tools),
    )


def metrics_json(metrics: TrialMetrics) -> str:
    return json.dumps(metrics.model_dump(), indent=2, sort_keys=True) + "\n"


def analyze_state_dir(state_dir: Path) -> TrialMetrics:
    from scripts.chat_scheduling_evidence import load_trial_trace
    from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
    from scripts.chat_scheduling_manifest import load_scenario

    record = json.loads((state_dir / "trial.json").read_text(encoding="utf-8"))
    scenario_id = record.get("scenario_id")
    if not isinstance(scenario_id, str):
        raise TypeError("trial.json has no scenario_id")
    scenario = load_scenario(SCENARIO_ROOT / f"{scenario_id}.json")
    trace = load_trial_trace(state_dir, scenario)
    (state_dir / "trace.json").write_text(
        json.dumps(trace.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics = analyze_trace(scenario, trace)
    (state_dir / "metrics.json").write_text(metrics_json(metrics), encoding="utf-8")
    return metrics


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="chat-scheduling-analyzer")
    parser.add_argument("state_dir", type=Path)
    args = parser.parse_args()
    metrics = analyze_state_dir(args.state_dir)
    print(metrics_json(metrics), end="")


if __name__ == "__main__":
    main()

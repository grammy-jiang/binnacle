"""Cross-event run_command workflow analysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from binnacle.logstats_models import Record, RunCommandWorkflowStats
from binnacle.logstats_run_command_groups import populate_auto_background_groups

Fields = dict[str, str]
FieldParser = Callable[[str], Fields]


@dataclass
class RunCommandEventIndex:
    """Small join indexes built from one journal pass."""

    tool_calls: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    all_tool_calls: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    tool_results: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    dispatches: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    dispatch_errors: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    auto_markers: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    output_shaping: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    run_command_configs: list[tuple[int, Fields]] = field(default_factory=list)
    job_starts: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    owner_starts: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    job_exits: dict[str, tuple[int, Fields]] = field(default_factory=dict)
    job_status: dict[str, list[tuple[int, Fields]]] = field(default_factory=dict)
    tool_call_sequence: list[tuple[int, str, Fields]] = field(default_factory=list)
    tool_calls_by_turn: dict[str, list[tuple[int, str, Fields]]] = field(
        default_factory=dict
    )
    timestamps: dict[int, str] = field(default_factory=dict)


def build_run_command_index(
    records: list[Record], fields: FieldParser
) -> RunCommandEventIndex:
    """Index correlation-bearing events without parsing command text."""

    out = RunCommandEventIndex()
    relevant_events = {
        "tool_call",
        "tool_result",
        "run_command_dispatch",
        "run_command_dispatch_error",
        "run_command_auto_background",
        "run_command_output_shaping",
        "tool_config",
        "job_start",
        "job_owner_timing",
        "job_exit",
        "job_status_timing",
    }
    for seq, record in enumerate(records):
        if record.event not in relevant_events:
            continue
        if record.event == "tool_result" and " tool=run_command " not in record.body:
            continue
        if record.event == "tool_config" and " tool=run_command " not in record.body:
            continue
        if record.timestamp is not None:
            out.timestamps[seq] = record.timestamp
        f = fields(record.body)
        if record.event == "tool_call":
            call = f.get("call")
            if call:
                out.all_tool_calls[call] = (seq, f)
                out.tool_call_sequence.append((seq, call, f))
                turn = (f.get("turn") or "-").split("/", 1)[0]
                if turn != "-":
                    out.tool_calls_by_turn.setdefault(turn, []).append((seq, call, f))
                if f.get("tool") == "run_command":
                    out.tool_calls[call] = (seq, f)
        elif record.event == "tool_result" and f.get("tool") == "run_command":
            if call := f.get("call"):
                out.tool_results[call] = (seq, f)
        elif record.event == "run_command_dispatch":
            if call := f.get("call"):
                out.dispatches[call] = (seq, f)
        elif record.event == "run_command_dispatch_error":
            if call := f.get("call"):
                out.dispatch_errors[call] = (seq, f)
        elif record.event == "run_command_auto_background":
            if call := f.get("call"):
                out.auto_markers[call] = (seq, f)
        elif record.event == "run_command_output_shaping":
            if call := f.get("call"):
                out.output_shaping[call] = (seq, f)
        elif record.event == "tool_config" and f.get("tool") == "run_command":
            out.run_command_configs.append((seq, f))
        elif record.event == "job_start":
            if job_id := f.get("job_id"):
                out.job_starts[job_id] = (seq, f)
        elif record.event == "job_owner_timing" and f.get("op") == "start":
            if job_id := f.get("job_id"):
                out.owner_starts[job_id] = (seq, f)
        elif record.event == "job_exit":
            if job_id := f.get("job_id"):
                out.job_exits[job_id] = (seq, f)
        elif record.event == "job_status_timing":
            if job_id := f.get("job_id"):
                out.job_status.setdefault(job_id, []).append((seq, f))
    return out


def policy_mode(fields: Fields) -> str:
    """Classify policy selection independently from execution outcome."""

    if fields.get("auto_background") == "true":
        return "auto_background"
    background_arg = fields.get("background_arg")
    if background_arg == "true":
        return "explicit_background"
    if background_arg == "false":
        return "explicit_foreground_override"
    if background_arg == "omitted":
        return "foreground_default"
    return "unknown_legacy"


def dispatch_outcome(fields: Fields) -> str:
    """Classify what happened during the selected dispatch wait policy."""

    mode = policy_mode(fields)
    state = fields.get("state")
    if mode in {"auto_background", "explicit_background"}:
        if state == "exited":
            return "warmup_finished"
        if state == "running":
            return "handed_off"
    elif mode in {"explicit_foreground_override", "foreground_default"}:
        if state == "exited":
            return "synchronous"
        if state == "running":
            return "wait_expired"
    return "unknown_legacy"


def _number(fields: Fields, key: str) -> float | None:
    try:
        return float(fields[key])
    except (KeyError, TypeError, ValueError):
        return None


def _base_turn(value: str | None) -> str | None:
    if not value or value == "-":
        return None
    return value.split("/", 1)[0]


def _status_turn(index: RunCommandEventIndex, status: Fields) -> str | None:
    """Resolve a status call's base turn from its tool_call, then timing fields."""

    call = status.get("call")
    if call and call in index.all_tool_calls:
        return _base_turn(index.all_tool_calls[call][1].get("turn"))
    return _base_turn(status.get("turn"))


def _not_dispatched_reason(result: Fields) -> str:
    return result.get("error_code") or result.get("error_class") or "unknown"


def _timestamp_seconds(index: RunCommandEventIndex, seq: int) -> datetime | None:
    value = index.timestamps.get(seq)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def analyze_run_command_workflow(
    records: list[Record], fields: FieldParser
) -> RunCommandWorkflowStats:
    """Join existing records into run_command policy/lifecycle statistics."""

    index = build_run_command_index(records, fields)
    out = RunCommandWorkflowStats(
        tool_calls=len(index.tool_calls),
        tool_results=len(index.tool_results),
        successful_dispatches=len(index.dispatches),
        dispatch_errors=len(index.dispatch_errors),
    )
    out.result_errors = sum(
        f.get("is_error") == "True" for _, f in index.tool_results.values()
    )
    out.result_without_call = len(set(index.tool_results) - set(index.tool_calls))
    out.dispatch_without_call = len(set(index.dispatches) - set(index.tool_calls))
    out.call_without_result = len(set(index.tool_calls) - set(index.tool_results))

    auto_dispatch_calls = {
        call
        for call, (_, dispatch) in index.dispatches.items()
        if dispatch.get("auto_background") == "true"
    }
    out.auto_dispatches = len(auto_dispatch_calls)
    out.auto_marker_dispatch_linked = len(auto_dispatch_calls & set(index.auto_markers))
    out.auto_dispatches_without_marker = len(
        auto_dispatch_calls - set(index.auto_markers)
    )
    out.auto_markers_without_dispatch_or_error = len(
        set(index.auto_markers) - set(index.dispatches) - set(index.dispatch_errors)
    )

    for call, (_, marker) in index.auto_markers.items():
        rule_hash = marker.get("rule_hash")
        if not rule_hash or rule_hash == "-":
            continue
        out.auto_rule_matches[rule_hash] += 1
        dispatch_row = index.dispatches.get(call)
        if (
            dispatch_row is not None
            and dispatch_outcome(dispatch_row[1]) == "handed_off"
        ):
            out.auto_rule_handoffs[rule_hash] += 1
    for _, shaping in index.output_shaping.values():
        out.output_shaping_reasons[shaping.get("reason", "?")] += 1
        if (dropped := _number(shaping, "dropped_lines")) is not None:
            out.output_shaping_dropped_lines.append(int(dropped))
        if (omitted := _number(shaping, "omitted_chars")) is not None:
            out.output_shaping_omitted_chars.append(int(omitted))

    for call, (_, result) in index.tool_results.items():
        if result.get("truncated") == "true" and call not in index.output_shaping:
            out.output_shaping_legacy_unclassified += 1

    for call, (_, dispatch) in index.dispatches.items():
        mode = policy_mode(dispatch)
        outcome = dispatch_outcome(dispatch)
        out.policy_modes[mode] += 1
        out.outcomes[outcome] += 1

        job_id = dispatch.get("job_id")
        if call in index.tool_results:
            out.dispatch_result_linked += 1
        if job_id and job_id in index.job_starts:
            out.dispatch_job_start_linked += 1
        if job_id and job_id in index.owner_starts:
            out.dispatch_owner_timing_linked += 1
        if dispatch.get("state") == "exited":
            out.synchronous_exit_expected += 1
            if job_id and job_id in index.job_exits:
                out.synchronous_exit_linked += 1

        if mode != "auto_background":
            continue
        out.auto_matches += 1
        if outcome == "warmup_finished":
            out.auto_warmup_finished += 1
            continue
        if outcome != "handed_off":
            continue

        out.auto_handed_off += 1
        if not job_id:
            continue
        exit_row = index.job_exits.get(job_id)
        if exit_row is not None:
            out.auto_terminal_observed += 1
            exit_fields = exit_row[1]
            runtime = _number(exit_fields, "runtime_s")
            bounded = _number(dispatch, "bounded_wait_s")
            effective = _number(dispatch, "effective_wait_s")
            if runtime is not None and bounded is not None and effective is not None:
                out.auto_terminal_analysis_eligible += 1
                if runtime <= bounded:
                    out.auto_would_finish_within_original_wait += 1
                else:
                    out.auto_would_timeout_anyway += 1
                out.auto_initial_wait_released_s += max(
                    0.0, min(runtime, bounded) - effective
                )

        statuses = index.job_status.get(job_id, [])
        if not statuses:
            continue
        out.auto_jobs_with_status += 1
        out.auto_status_calls += len(statuses)
        for _, status in statuses:
            if (state_ms := _number(status, "state_ms")) is not None:
                out.auto_status_state_ms.append(state_ms)
            if (waited_s := _number(status, "waited_s")) is not None:
                out.auto_status_waited_s.append(waited_s)

        first_seq, first_status = statuses[0]
        out.auto_first_status_states[first_status.get("state", "?")] += 1

        if exit_row is not None:
            terminal_status = next(
                (
                    (seq, status)
                    for seq, status in statuses
                    if status.get("state") == "exited"
                ),
                None,
            )
            if terminal_status is not None:
                exit_time = _timestamp_seconds(index, exit_row[0])
                status_time = _timestamp_seconds(index, terminal_status[0])
                if exit_time is not None and status_time is not None:
                    lag_s = (status_time - exit_time).total_seconds()
                    if lag_s >= 0:
                        out.auto_terminal_collection_lag_s.append(lag_s)
        origin_turn = None
        origin_call = index.all_tool_calls.get(call)
        if origin_call is not None:
            origin_turn = _base_turn(origin_call[1].get("turn"))
        status_turn = _status_turn(index, first_status)
        if origin_turn is None or status_turn is None:
            out.auto_first_status_unknown_turn += 1
        elif origin_turn == status_turn:
            out.auto_first_status_same_turn += 1
        else:
            out.auto_first_status_different_turn += 1

        if origin_call is None:
            continue
        origin_seq = origin_call[0]
        intervening_tools: list[str] = []
        turn_calls = (
            index.tool_calls_by_turn.get(origin_turn, [])
            if origin_turn is not None
            else index.tool_call_sequence
        )
        for seq, other_call, tool_fields in turn_calls:
            if seq <= origin_seq or seq >= first_seq or other_call == call:
                continue
            tool = tool_fields.get("tool", "?")
            if tool != "job_status":
                intervening_tools.append(tool)
        if intervening_tools:
            out.auto_jobs_with_intervening_non_status_calls += 1
            out.auto_intervening_tools.update(intervening_tools)

    populate_auto_background_groups(out, index)

    for call, (_, result) in index.tool_results.items():
        if result.get("is_error") != "True":
            continue
        if call in index.dispatches or call in index.dispatch_errors:
            continue
        if call not in index.tool_calls:
            continue
        out.not_dispatched_errors += 1
        out.not_dispatched_error_reasons[_not_dispatched_reason(result)] += 1

    return out

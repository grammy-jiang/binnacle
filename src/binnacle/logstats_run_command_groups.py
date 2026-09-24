"""Detailed automatic-background groups for Phase-5 analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from binnacle.logstats_models import AutoBackgroundGroupStats, RunCommandWorkflowStats


def _number(fields: dict[str, str], key: str) -> float | None:
    try:
        return float(fields[key])
    except (KeyError, TypeError, ValueError):
        return None


def _base_turn(value: str | None) -> str | None:
    if not value or value == "-":
        return None
    return value.split("/", 1)[0]


def _timestamp(index: Any, seq: int) -> datetime | None:
    value = index.timestamps.get(seq)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _status_turn(index: Any, status: dict[str, str]) -> str | None:
    call = status.get("call")
    if call and call in index.all_tool_calls:
        return _base_turn(index.all_tool_calls[call][1].get("turn"))
    return _base_turn(status.get("turn"))


def _group(
    table: dict[str, AutoBackgroundGroupStats],
    key: str,
    marker: dict[str, str],
    *,
    rule_hash: str | None,
) -> AutoBackgroundGroupStats:
    group = table.get(key)
    if group is None:
        group = AutoBackgroundGroupStats(
            policy_hash=marker.get("policy_hash"),
            behavior_hash=marker.get("behavior_hash"),
            rule_hash=rule_hash,
            semantics_version=marker.get("semantics_version"),
            auto_warmup_s=_number(marker, "auto_warmup_s"),
        )
        table[key] = group
    return group


def _accumulate(
    group: AutoBackgroundGroupStats,
    *,
    call: str,
    index: Any,
) -> None:
    group.matches += 1
    if call in index.dispatch_errors:
        group.dispatch_errors += 1
        return
    dispatch_row = index.dispatches.get(call)
    if dispatch_row is None:
        group.dispatch_missing += 1
        return

    _, dispatch = dispatch_row
    state = dispatch.get("state")
    job_id = dispatch.get("job_id")
    if state == "exited":
        group.warmup_finished += 1
    elif state == "running":
        group.handed_off += 1

    exit_row = index.job_exits.get(job_id) if job_id else None
    if exit_row is not None:
        group.terminal_observed += 1
        runtime = _number(exit_row[1], "runtime_s")
        if runtime is not None:
            group.runtime_s.append(runtime)

    if state != "running" or not job_id:
        return

    if exit_row is not None:
        group.handoff_terminal_observed += 1
        runtime = _number(exit_row[1], "runtime_s")
        bounded = _number(dispatch, "bounded_wait_s")
        effective = _number(dispatch, "effective_wait_s")
        if runtime is not None and bounded is not None and effective is not None:
            group.handoff_analysis_eligible += 1
            if runtime <= bounded:
                group.handoff_would_finish_within_original_wait += 1
            else:
                group.handoff_would_timeout_anyway += 1
            group.initial_wait_released_s += max(0.0, min(runtime, bounded) - effective)

    statuses = index.job_status.get(job_id, [])
    if not statuses:
        return
    group.jobs_with_status += 1
    group.status_calls += len(statuses)
    first_seq, first_status = statuses[0]
    group.first_status_states[first_status.get("state", "?")] += 1

    origin = index.all_tool_calls.get(call)
    origin_turn = _base_turn(origin[1].get("turn")) if origin is not None else None
    status_turn = _status_turn(index, first_status)
    if origin_turn is None or status_turn is None:
        group.first_status_unknown_turn += 1
    elif origin_turn == status_turn:
        group.first_status_same_turn += 1
    else:
        group.first_status_different_turn += 1

    if exit_row is not None:
        terminal = next(
            (
                (seq, status)
                for seq, status in statuses
                if status.get("state") == "exited"
            ),
            None,
        )
        if terminal is not None:
            exit_time = _timestamp(index, exit_row[0])
            status_time = _timestamp(index, terminal[0])
            if exit_time is not None and status_time is not None:
                lag_s = (status_time - exit_time).total_seconds()
                if lag_s >= 0:
                    group.terminal_collection_lag_s.append(lag_s)

    if origin is None:
        return
    turn_calls = (
        index.tool_calls_by_turn.get(origin_turn, [])
        if origin_turn is not None
        else index.tool_call_sequence
    )
    intervening = []
    for seq, other_call, tool_fields in turn_calls:
        if seq <= origin[0] or seq >= first_seq or other_call == call:
            continue
        tool = tool_fields.get("tool", "?")
        if tool != "job_status":
            intervening.append(tool)
    if intervening:
        group.jobs_with_intervening_non_status_calls += 1
        group.intervening_tools.update(intervening)


def populate_auto_background_groups(
    stats: RunCommandWorkflowStats,
    index: Any,
) -> None:
    """Populate behavior and behavior-scoped rule slices from config/marker joins."""

    for _, config in index.run_command_configs:
        policy_hash = config.get("auto_background_policy_hash")
        behavior_hash = config.get("auto_background_behavior_hash") or policy_hash
        if not behavior_hash:
            continue
        marker = {
            "policy_hash": policy_hash or "-",
            "behavior_hash": behavior_hash,
            "semantics_version": config.get("auto_background_semantics_version", "-"),
            "auto_warmup_s": config.get("auto_background_warmup_s", "-"),
        }
        group = _group(
            stats.auto_behavior_groups,
            behavior_hash,
            marker,
            rule_hash=None,
        )
        group.startups += 1

    for call, (_, marker) in index.auto_markers.items():
        policy_hash = marker.get("policy_hash") or "legacy"
        behavior_hash = marker.get("behavior_hash") or policy_hash
        behavior = _group(
            stats.auto_behavior_groups,
            behavior_hash,
            marker,
            rule_hash=None,
        )
        _accumulate(behavior, call=call, index=index)

        rule_hash = marker.get("rule_hash")
        if not rule_hash or rule_hash == "-":
            continue
        rule_key = f"{behavior_hash}/{rule_hash}"
        rule = _group(
            stats.auto_rule_groups,
            rule_key,
            marker,
            rule_hash=rule_hash,
        )
        _accumulate(rule, call=call, index=index)


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _identity(group: AutoBackgroundGroupStats) -> str:
    behavior = group.behavior_hash or group.policy_hash or "legacy"
    parts = [f"behavior={behavior}"]
    if group.policy_hash:
        parts.append(f"policy={group.policy_hash}")
    if group.semantics_version:
        parts.append(f"semantics={group.semantics_version}")
    if group.auto_warmup_s is not None:
        parts.append(f"warmup_s={group.auto_warmup_s:g}")
    if group.rule_hash:
        parts.append(f"rule={group.rule_hash}")
    return " ".join(parts)


def _render_group(group: AutoBackgroundGroupStats, indent: str) -> list[str]:
    out = [
        (
            f"{indent}{_identity(group)} startups={group.startups} "
            f"matches={group.matches} warmup_finished={group.warmup_finished} "
            f"handed_off={group.handed_off} "
            f"dispatch_errors={group.dispatch_errors} "
            f"dispatch_missing={group.dispatch_missing}"
        )
    ]
    if group.runtime_s:
        out.append(
            f"{indent}  runtime_s: n={len(group.runtime_s)} "
            f"p50={_pct(group.runtime_s, 0.5):.3f} "
            f"p90={_pct(group.runtime_s, 0.9):.3f} max={max(group.runtime_s):.3f}"
        )
    if group.handed_off:
        out.append(
            f"{indent}  handoff: terminal={group.handoff_terminal_observed}/"
            f"{group.handed_off} eligible={group.handoff_analysis_eligible} "
            f"would_finish_within_original_wait="
            f"{group.handoff_would_finish_within_original_wait} "
            f"would_timeout_anyway={group.handoff_would_timeout_anyway} "
            f"initial_wait_released_s={group.initial_wait_released_s:.1f}"
        )
        out.append(
            f"{indent}  follow-up: jobs_with_status={group.jobs_with_status} "
            f"status_calls={group.status_calls} "
            f"first_status_exited={group.first_status_states.get('exited', 0)} "
            f"first_status_running={group.first_status_states.get('running', 0)} "
            f"same_turn={group.first_status_same_turn} "
            f"intervening_jobs={group.jobs_with_intervening_non_status_calls}"
        )
        if group.terminal_collection_lag_s:
            out.append(
                f"{indent}  collection_lag_s: n={len(group.terminal_collection_lag_s)} "
                f"p50={_pct(group.terminal_collection_lag_s, 0.5):.3f} "
                f"p90={_pct(group.terminal_collection_lag_s, 0.9):.3f} "
                f"max={max(group.terminal_collection_lag_s):.3f}"
            )
    return out


def render_auto_background_groups(stats: RunCommandWorkflowStats) -> list[str]:
    """Render behavior-segmented and behavior-scoped per-rule Phase-5 metrics."""

    if not stats.auto_behavior_groups:
        return []
    out = ["    auto behavior groups:"]
    for _, group in sorted(stats.auto_behavior_groups.items()):
        out.extend(_render_group(group, "      "))

    if stats.auto_rule_groups:
        out.append("    auto rule groups:")
        for _, group in sorted(
            stats.auto_rule_groups.items(),
            key=lambda item: (
                item[1].behavior_hash or item[1].policy_hash or "",
                item[1].rule_hash or "",
            ),
        ):
            out.extend(_render_group(group, "      "))
    return out

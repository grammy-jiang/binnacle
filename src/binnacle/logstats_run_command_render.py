"""Rendering for cross-event run_command workflow statistics."""

from binnacle.logstats_models import RunCommandWorkflowStats
from binnacle.logstats_run_command_groups import render_auto_background_groups


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _coverage(num: int, den: int) -> str:
    if den <= 0:
        return "-"
    return f"{100 * num / den:.2f}%"


def render_run_command_workflow(stats: RunCommandWorkflowStats) -> list[str]:
    """Render cross-event run_command workflow analysis."""

    if not (
        stats.tool_calls
        or stats.tool_results
        or stats.successful_dispatches
        or stats.auto_behavior_groups
    ):
        return []

    out = ["\nrun_command workflow:"]
    out.append(
        "  calls/results: "
        f"calls={stats.tool_calls} results={stats.tool_results} "
        f"result_errors={stats.result_errors} "
        f"not_dispatched_errors={stats.not_dispatched_errors}"
    )
    out.append(
        "  dispatch: "
        f"successful={stats.successful_dispatches} owner_errors={stats.dispatch_errors} "
        f"result_without_call={stats.result_without_call} "
        f"dispatch_without_call={stats.dispatch_without_call} "
        f"call_without_result={stats.call_without_result}"
    )
    if stats.policy_modes:
        out.append(
            "  policy: "
            + ", ".join(f"{k}={v}" for k, v in stats.policy_modes.most_common())
        )
    if stats.outcomes:
        out.append(
            "  outcome: "
            + ", ".join(f"{k}={v}" for k, v in stats.outcomes.most_common())
        )
    if stats.not_dispatched_error_reasons:
        out.append(
            "  not-dispatched errors: "
            + ", ".join(
                f"{k}={v}" for k, v in stats.not_dispatched_error_reasons.most_common()
            )
        )

    if stats.successful_dispatches:
        out.append(
            "  in-window linkage: "
            f"dispatch->result={stats.dispatch_result_linked}/{stats.successful_dispatches}"
            f" ({_coverage(stats.dispatch_result_linked, stats.successful_dispatches)}), "
            f"job_start={stats.dispatch_job_start_linked}/{stats.successful_dispatches}"
            f" ({_coverage(stats.dispatch_job_start_linked, stats.successful_dispatches)}), "
            f"owner_timing={stats.dispatch_owner_timing_linked}/{stats.successful_dispatches}"
            f" ({_coverage(stats.dispatch_owner_timing_linked, stats.successful_dispatches)}), "
            f"sync_exit={stats.synchronous_exit_linked}/{stats.synchronous_exit_expected}"
            f" ({_coverage(stats.synchronous_exit_linked, stats.synchronous_exit_expected)})"
        )

    if stats.output_shaping_reasons or stats.output_shaping_legacy_unclassified:
        reasons = ", ".join(
            f"{key}={value}"
            for key, value in stats.output_shaping_reasons.most_common()
        )
        out.append(
            "  output shaping: "
            + (reasons if reasons else "classified=0")
            + f", legacy_unclassified={stats.output_shaping_legacy_unclassified}"
        )
        if stats.output_shaping_dropped_lines:
            out.append(
                f"    dropped_lines_total={sum(stats.output_shaping_dropped_lines)} "
                f"(n={len(stats.output_shaping_dropped_lines)})"
            )
        if stats.output_shaping_omitted_chars:
            out.append(
                f"    omitted_chars_total={sum(stats.output_shaping_omitted_chars)} "
                f"(n={len(stats.output_shaping_omitted_chars)})"
            )

    if stats.auto_matches or stats.auto_dispatches:
        auto_label = (
            "  auto-background (aggregate across behavior groups):"
            if len(stats.auto_behavior_groups) > 1
            else "  auto-background:"
        )
        out.append(auto_label)
        out.append(
            f"    marker/dispatch linkage={stats.auto_marker_dispatch_linked}/"
            f"{stats.auto_dispatches} dispatches_without_marker="
            f"{stats.auto_dispatches_without_marker} markers_without_dispatch_or_error="
            f"{stats.auto_markers_without_dispatch_or_error}"
        )
        out.append(
            f"    matches={stats.auto_matches} warmup_finished={stats.auto_warmup_finished} "
            f"handed_off={stats.auto_handed_off} terminal_observed={stats.auto_terminal_observed}"
        )
        out.append(
            "    counterfactual: "
            f"eligible={stats.auto_terminal_analysis_eligible} "
            f"would_finish_within_original_wait="
            f"{stats.auto_would_finish_within_original_wait} "
            f"would_timeout_anyway={stats.auto_would_timeout_anyway} "
            f"initial_wait_released_s={stats.auto_initial_wait_released_s:.1f}"
        )
        out.append(
            f"    follow-up: jobs_with_status={stats.auto_jobs_with_status} "
            f"status_calls={stats.auto_status_calls} "
            f"first_status_same_turn={stats.auto_first_status_same_turn} "
            f"different_turn={stats.auto_first_status_different_turn} "
            f"unknown_turn={stats.auto_first_status_unknown_turn}"
        )
        if stats.auto_first_status_states:
            out.append(
                "    first status: "
                + ", ".join(
                    f"{k}={v}" for k, v in stats.auto_first_status_states.most_common()
                )
            )
        out.append(
            "    observable overlap: "
            f"jobs_with_intervening_non_status_tools="
            f"{stats.auto_jobs_with_intervening_non_status_calls}"
        )
        if stats.auto_intervening_tools:
            out.append(
                "    intervening tools: "
                + ", ".join(
                    f"{k}={v}" for k, v in stats.auto_intervening_tools.most_common()
                )
            )
        if stats.auto_terminal_collection_lag_s:
            values = stats.auto_terminal_collection_lag_s
            out.append(
                "    terminal collection lag s: "
                f"n={len(values)} p50={_pct(values, 0.5):.2f} "
                f"p90={_pct(values, 0.9):.2f} p95={_pct(values, 0.95):.2f} "
                f"max={max(values):.2f}"
            )
        if stats.auto_status_state_ms:
            out.append(
                f"    status state-phase total s="
                f"{sum(stats.auto_status_state_ms) / 1000:.2f} "
                f"(n={len(stats.auto_status_state_ms)})"
            )
        if stats.auto_status_waited_s:
            out.append(
                f"    status waited total s={sum(stats.auto_status_waited_s):.2f} "
                f"(coverage={len(stats.auto_status_waited_s)}/{stats.auto_status_calls})"
            )
        if stats.auto_rule_matches and len(stats.auto_behavior_groups) <= 1:
            out.append("    auto rules:")
            for rule_hash, matches in stats.auto_rule_matches.most_common():
                out.append(
                    f"      {rule_hash}: matches={matches} "
                    f"handed_off={stats.auto_rule_handoffs.get(rule_hash, 0)}"
                )

    out.extend(render_auto_background_groups(stats))
    return out

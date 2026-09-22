"""Formatting and report summaries for usage statistics."""

from collections.abc import Sequence
from typing import Any

from binnacle.logstats_jobs import render_job_telemetry
from binnacle.logstats_models import AdaptiveDiscoveryStats, IndexedContextStats, Stats


def _pct(values: Sequence[int | float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "mean": sum(values) / len(values),
        "p50": _pct(values, 0.5),
        "p90": _pct(values, 0.9),
        "max": max(values),
    }


def adaptive_discovery_report(adaptive: AdaptiveDiscoveryStats) -> dict[str, Any]:
    """JSON-friendly adaptive-discovery pilot summary."""
    return {
        "adaptive_calls": adaptive.calls,
        "budget_trimmed": adaptive.budget_trimmed,
        "candidate_open_conversion": (
            adaptive.candidate_opened / adaptive.calls if adaptive.calls else 0.0
        ),
        "detailed_open_conversion": (
            adaptive.detailed_opened / adaptive.calls if adaptive.calls else 0.0
        ),
        "candidate_reads": adaptive.candidate_reads,
        "candidate_file_searches": adaptive.candidate_file_searches,
        "detailed_reads": adaptive.detailed_reads,
        "detailed_file_searches": adaptive.detailed_file_searches,
        "trigger_bytes": _distribution([float(x) for x in adaptive.trigger_bytes]),
        "result_bytes": _distribution([float(x) for x in adaptive.result_bytes]),
        "result_tokens": _distribution([float(x) for x in adaptive.result_tokens]),
        "total_matches": _distribution([float(x) for x in adaptive.total_matches]),
        "matching_files": _distribution([float(x) for x in adaptive.matching_files]),
        "detailed_files": _distribution([float(x) for x in adaptive.detailed_files]),
        "candidate_files": _distribution([float(x) for x in adaptive.candidate_files]),
        "representative_entries": _distribution(
            [float(x) for x in adaptive.representative_entries]
        ),
        "tail_entries": _distribution([float(x) for x in adaptive.tail_entries]),
        "followup_calls": _distribution([float(x) for x in adaptive.followup_calls]),
        "followup_exact_searches": _distribution(
            [float(x) for x in adaptive.followup_exact_searches]
        ),
        "followup_reads": _distribution([float(x) for x in adaptive.followup_reads]),
        "followup_result_tokens": _distribution(
            [float(x) for x in adaptive.followup_result_tokens]
        ),
        "investigation_result_tokens": _distribution(
            [float(x) for x in adaptive.investigation_result_tokens]
        ),
        "rows": adaptive.rows,
    }


def indexed_context_report(idx: IndexedContextStats) -> dict[str, Any]:
    """JSON-friendly summary used by the CLI section and detailed pilot script."""
    return {
        "indexed_successes": idx.successes,
        "indexed_errors": idx.errors,
        "error_phases": dict(idx.error_phases),
        "pilot_versions": dict(idx.pilot_versions),
        "schema_versions": dict(idx.schema_versions),
        "parser_versions": dict(idx.parser_versions),
        "cold_opens": idx.cold_opens,
        "changed_files": idx.changed_files,
        "evidence_open_conversion": (
            idx.evidence_opened / idx.successes if idx.successes else 0.0
        ),
        "evidence_reads": idx.evidence_reads,
        "evidence_file_searches": idx.evidence_file_searches,
        "result_tokens": _distribution([float(x) for x in idx.result_tokens]),
        "package_est_tokens": _distribution([float(x) for x in idx.package_est_tokens]),
        "package_bytes": _distribution([float(x) for x in idx.package_bytes]),
        "package_items": _distribution([float(x) for x in idx.package_items]),
        "latency_total_ms": _distribution(idx.total_ms),
        "latency_reconcile_ms": _distribution(idx.reconcile_ms),
        "latency_query_ms": _distribution(idx.query_ms),
        "followup_calls": _distribution([float(x) for x in idx.followup_calls]),
        "followup_exact_searches": _distribution(
            [float(x) for x in idx.followup_exact_searches]
        ),
        "followup_reads": _distribution([float(x) for x in idx.followup_reads]),
        "followup_result_tokens": _distribution(
            [float(x) for x in idx.followup_result_tokens]
        ),
        "investigation_result_tokens": _distribution(
            [float(x) for x in idx.investigation_result_tokens]
        ),
        "rows": idx.rows,
    }


def render(st: Stats) -> str:
    out: list[str] = []
    starts = st.events.get("request_start", 0)
    errors = st.events.get("request_error", 0)
    if starts:
        out.append(
            f"requests: {starts}   errors: {errors} ({100 * errors / starts:.2f}%)"
        )
    else:
        out.append("requests: 0")
    out.append(f"server startups in window: {st.startups}")
    out.append("\ntools/call by tool:")
    for name, n in st.tools.most_common():
        out.append(f"  {name:24s} {n}")

    out.append("\nrequests by method:")
    for name, n in st.methods.most_common():
        out.append(f"  {name:28s} {n}")

    out.append("\nduration_ms (n / p50 / p90 / max):")
    for name, values in sorted(st.durations.items(), key=lambda kv: -len(kv[1])):
        if len(values) >= 3:
            out.append(
                f"  {name:24s} n={len(values):5d}  p50={_pct(values, 0.5):9.1f}"
                f"  p90={_pct(values, 0.9):9.1f}  max={max(values):10.1f}"
            )

    out.append("\nclients (per-request clientInfo where present):")
    for name, n in st.clients.most_common():
        out.append(f"  {name:32s} {n}")

    if st.commands:
        out.append("\nrun_command first words (top 15):")
        for name, n in st.commands.most_common(15):
            out.append(f"  {name:24s} {n}")

    if st.areas:
        out.append("\nfile-tool target areas (top 12):")
        for name, n in st.areas.most_common(12):
            out.append(f"  {name:48s} {n}")

    out.append("\nrequests per day:")
    for day in sorted(st.per_day):
        out.append(f"  {day}  {st.per_day[day]}")

    out.append("\nbusiest hours (top 8):")
    for hour, n in st.per_hour.most_common(8):
        out.append(f"  {hour}  {n}")

    if st.errors:
        out.append("\nrequest_error details:")
        out.extend(f"  {e}" for e in st.errors)

    if st.results:
        out.append(
            "\nresult size by tool, est_tokens = chars/4 (n / p50 / p90 / max / total):"
        )
        for name, values in sorted(
            st.result_tokens.items(), key=lambda kv: -sum(kv[1])
        ):
            out.append(
                f"  {name:24s} n={len(values):5d}  p50={_pct(values, 0.5):7.0f}"
                f"  p90={_pct(values, 0.9):7.0f}  max={max(values):8.0f}"
                f"  total={sum(values):9d}"
            )
        out.append("\ntruncated results by tool (truncated / sized results):")
        for name, n in st.results.most_common():
            out.append(f"  {name:24s} {st.truncated.get(name, 0)} / {n}")
    if st.tool_errors:
        out.append("\ntool errors by class:")
        for name, n in st.tool_errors.most_common():
            out.append(f"  {name:40s} {n}")
    if st.job_exits:
        exits = ", ".join(f"{k}: {v}" for k, v in st.job_exits.most_common())
        out.append(f"\njob exits by code (job_exit lines): {exits}")
    if st.results:
        out.append(
            f"run_command results that became background jobs: {st.background_jobs}"
        )
    out.extend(render_job_telemetry(st.jobs))
    if st.turn_calls:
        per_turn = sorted(st.turn_calls.values())
        out.append(
            f"\nChatGPT turns (tunnel X-Request-Id): {len(per_turn)} turns, "
            f"{sum(per_turn)} tool calls; calls per turn median="
            f"{per_turn[len(per_turn) // 2]} max={per_turn[-1]}"
        )
    if st.adaptive.calls:
        adaptive = st.adaptive
        out.append("\nadaptive search discovery pilot:")
        out.append(
            f"  calls={adaptive.calls} budget_trimmed={adaptive.budget_trimmed} "
            f"candidate_opened={adaptive.candidate_opened} "
            f"detailed_opened={adaptive.detailed_opened}"
        )
        out.append(
            f"  candidate evidence: reads={adaptive.candidate_reads} "
            f"file_searches={adaptive.candidate_file_searches}; "
            f"detailed reads={adaptive.detailed_reads} "
            f"file_searches={adaptive.detailed_file_searches}"
        )
        for label, values in (
            ("trigger bytes", adaptive.trigger_bytes),
            ("result bytes", adaptive.result_bytes),
            ("result tokens", adaptive.result_tokens),
            ("matching files", adaptive.matching_files),
            ("candidate files", adaptive.candidate_files),
            ("follow-up calls", adaptive.followup_calls),
            ("follow-up exact", adaptive.followup_exact_searches),
            ("follow-up reads", adaptive.followup_reads),
            ("follow-up tokens", adaptive.followup_result_tokens),
            ("investigation tokens", adaptive.investigation_result_tokens),
        ):
            if values:
                out.append(
                    f"  {label:20s} n={len(values):4d} p50={_pct(values, 0.5):8.1f} "
                    f"p90={_pct(values, 0.9):8.1f} max={max(values):9.1f}"
                )

    if st.indexed.successes or st.indexed.errors:
        idx = st.indexed
        out.append("\nindexed context pilot:")
        out.append(
            f"  success={idx.successes} errors={idx.errors} cold_opens={idx.cold_opens} "
            f"changed_files={idx.changed_files}"
        )
        if idx.pilot_versions:
            versions = ", ".join(
                f"{k}:{v}" for k, v in idx.pilot_versions.most_common()
            )
            out.append(f"  pilot versions: {versions}")
        if idx.error_phases:
            phases = ", ".join(f"{k}:{v}" for k, v in idx.error_phases.most_common())
            out.append(f"  error phases: {phases}")
        if idx.successes:
            conversion = 100 * idx.evidence_opened / idx.successes
            out.append(
                f"  evidence opened: {idx.evidence_opened}/{idx.successes} ({conversion:.1f}%) "
                f"reads={idx.evidence_reads} file_searches={idx.evidence_file_searches}"
            )
            for label, values in (
                ("result tokens", idx.result_tokens),
                ("package bytes", idx.package_bytes),
                ("total ms", idx.total_ms),
                ("reconcile ms", idx.reconcile_ms),
                ("query ms", idx.query_ms),
                ("follow-up calls", idx.followup_calls),
                ("follow-up exact", idx.followup_exact_searches),
                ("follow-up reads", idx.followup_reads),
                ("follow-up tokens", idx.followup_result_tokens),
                ("investigation tokens", idx.investigation_result_tokens),
            ):
                if values:
                    out.append(
                        f"  {label:20s} n={len(values):4d} p50={_pct(values, 0.5):8.1f} "
                        f"p90={_pct(values, 0.9):8.1f} max={max(values):9.1f}"
                    )
    return "\n".join(out)

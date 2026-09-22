"""Exact-search Phase B telemetry aggregation and report rendering."""

from collections.abc import Callable, Sequence

from binnacle.logstats_models import ExactSearchStats, Record


def _float(fields: dict[str, str], key: str) -> float | None:
    try:
        return float(fields[key])
    except (KeyError, ValueError):
        return None


def _int(fields: dict[str, str], key: str) -> int | None:
    try:
        return int(fields[key])
    except (KeyError, ValueError):
        return None


def _pct(values: Sequence[int | float], q: float) -> float:
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int(q * len(ordered)))])


def analyze_exact_search(
    records: list[Record], fields: Callable[[str], dict[str, str]]
) -> ExactSearchStats:
    out = ExactSearchStats()
    for record in records:
        f = fields(record.body)
        if record.event == "search_dispatch" and f.get("mode") == "exact":
            out.dispatches += 1
            continue
        if record.event != "search_exact":
            continue
        out.summaries += 1
        pipeline = f.get("pipeline", "materialized")
        out.pipelines[pipeline] += 1
        if f.get("outcome") == "error":
            out.errors += 1
            out.error_codes[f.get("error_code", "-")] += 1
        out.strategies[f.get("strategy", "?")] += 1
        out.budget_outcomes[f.get("budget_outcome", "?")] += 1
        calls = _int(f, "rg_calls")
        if calls is not None:
            out.rg_calls_total += calls
        out.auto_context += int(f.get("auto_context") == "true")
        float_targets: list[tuple[str, list[float]]] = [
            ("impl_ms", out.impl_ms),
            ("context_attach_ms", out.context_attach_ms),
            ("adaptive_ms", out.adaptive_ms),
            ("budget_ms", out.budget_ms),
        ]
        if pipeline == "streaming":
            float_targets += [
                ("rg_wall_ms", out.rg_wall_ms),
                ("stream_cpu_ms", out.stream_cpu_ms),
            ]
        else:
            float_targets += [
                ("rg_subprocess_ms", out.rg_subprocess_ms),
                ("rg_parse_ms", out.rg_parse_ms),
                ("collect_ms", out.collect_ms),
            ]
        for key, target in float_targets:
            if (value := _float(f, key)) is not None:
                target.append(value)
        int_targets: list[tuple[str, list[int]]] = [
            ("rg_events", out.rg_events),
            ("rg_match_events", out.rg_match_events),
            ("rg_context_events", out.rg_context_events),
            ("accepted_matches", out.accepted_matches),
            ("accepted_files", out.accepted_files),
            ("returned_entries", out.returned_entries),
            ("adaptive_match_events", out.adaptive_match_events),
            ("adaptive_glob_checks", out.adaptive_glob_checks),
        ]
        if pipeline == "streaming":
            int_targets += [
                ("rg_stdout_bytes", out.rg_stdout_bytes),
                ("glob_cache_hits", out.glob_cache_hits),
                ("glob_cache_misses", out.glob_cache_misses),
                ("glob_rejected_files", out.glob_rejected_files),
                ("glob_rejected_events", out.glob_rejected_events),
                (
                    "adaptive_retained_match_events",
                    out.adaptive_retained_match_events,
                ),
            ]
        else:
            int_targets += [
                ("rg_stdout_chars", out.rg_stdout_chars),
                ("collect_glob_checks", out.collect_glob_checks),
                ("collect_glob_rejected", out.collect_glob_rejected),
            ]
        for key, int_target in int_targets:
            if (int_value := _int(f, key)) is not None:
                int_target.append(int_value)
        events = _int(f, "rg_events")
        accepted = _int(f, "accepted_matches")
        if events is not None and accepted:
            out.events_per_accepted_match.append(events / accepted)
        returned = _int(f, "returned_entries")
        if pipeline == "streaming":
            raw_bytes = _int(f, "rg_stdout_bytes")
            if raw_bytes is not None and returned:
                out.bytes_per_returned_entry.append(raw_bytes / returned)
        else:
            chars = _int(f, "rg_stdout_chars")
            if chars is not None and returned:
                out.chars_per_returned_entry.append(chars / returned)
    return out


def _metric_line(
    label: str, values: Sequence[int | float], unit: str = ""
) -> str | None:
    if not values:
        return None
    suffix = f" {unit}" if unit else ""
    return (
        f"  {label:24s} n={len(values):4d} p50={_pct(values, 0.5):10.2f}"
        f" p90={_pct(values, 0.9):10.2f} p95={_pct(values, 0.95):10.2f}"
        f" max={max(values):11.2f}{suffix}"
    )


def render_exact_search(exact: ExactSearchStats) -> list[str]:
    if not exact.dispatches and not exact.summaries:
        return []
    coverage = 100 * exact.summaries / exact.dispatches if exact.dispatches else 0.0
    out = [
        "\nexact search telemetry:",
        (
            f"  dispatches={exact.dispatches} summaries={exact.summaries} "
            f"coverage={coverage:.1f}% errors={exact.errors}"
        ),
    ]
    if exact.pipelines:
        out.append(
            "  pipeline: "
            + ", ".join(f"{k}={v}" for k, v in exact.pipelines.most_common())
        )
    if exact.strategies:
        out.append(
            "  strategy: "
            + ", ".join(f"{k}={v}" for k, v in exact.strategies.most_common())
        )
    if exact.budget_outcomes:
        out.append(
            "  budget outcomes: "
            + ", ".join(f"{k}={v}" for k, v in exact.budget_outcomes.most_common())
        )
    out.append(
        f"  rg calls total={exact.rg_calls_total} "
        f"auto_context_second_rg={exact.auto_context}"
    )
    if exact.error_codes:
        out.append(
            "  errors: "
            + ", ".join(f"{k}={v}" for k, v in exact.error_codes.most_common())
        )
    out.append("  latency:")
    latency_metrics: tuple[tuple[str, list[float]], ...] = (
        ("exact impl", exact.impl_ms),
        ("rg subprocess", exact.rg_subprocess_ms),
        ("rg JSON parse", exact.rg_parse_ms),
        ("collect/filter", exact.collect_ms),
        ("rg stream wall", exact.rg_wall_ms),
        ("stream CPU", exact.stream_cpu_ms),
        ("context attach", exact.context_attach_ms),
        ("adaptive build", exact.adaptive_ms),
        ("budget shaping", exact.budget_ms),
    )
    for label, values in latency_metrics:
        if line := _metric_line(label, values, "ms"):
            out.append(line)
    out.append("  work:")
    work_metrics: tuple[tuple[str, list[int]], ...] = (
        ("rg stdout chars", exact.rg_stdout_chars),
        ("rg stdout bytes", exact.rg_stdout_bytes),
        ("rg events", exact.rg_events),
        ("match events", exact.rg_match_events),
        ("context events", exact.rg_context_events),
        ("glob checks", exact.collect_glob_checks),
        ("glob rejects", exact.collect_glob_rejected),
        ("accepted matches", exact.accepted_matches),
        ("accepted files", exact.accepted_files),
        ("returned entries", exact.returned_entries),
        ("adaptive match scan", exact.adaptive_match_events),
        ("adaptive glob checks", exact.adaptive_glob_checks),
        ("glob cache hits", exact.glob_cache_hits),
        ("glob cache misses", exact.glob_cache_misses),
        ("glob rejected files", exact.glob_rejected_files),
        ("glob rejected events", exact.glob_rejected_events),
        ("adaptive retained", exact.adaptive_retained_match_events),
    )
    for label, work_values in work_metrics:
        if line := _metric_line(label, work_values):
            out.append(line)
    out.append("  amplification:")
    if line := _metric_line("rg events / accepted", exact.events_per_accepted_match):
        out.append(line)
    if line := _metric_line("rg chars / returned", exact.chars_per_returned_entry):
        out.append(line)
    if line := _metric_line("rg bytes / returned", exact.bytes_per_returned_entry):
        out.append(line)
    return out

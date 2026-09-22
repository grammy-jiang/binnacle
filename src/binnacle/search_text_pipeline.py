"""Materialized/streaming exact-search scan selection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from binnacle.search_text_stream import RgJsonStream
from binnacle.search_text_stream_reduce import ExactScanResult, ExactStreamReducer
from binnacle.search_text_telemetry import ExactSearchMetrics

RunRg = Callable[
    [Path, str, bool, int, ExactSearchMetrics | None], tuple[list[dict], bool]
]
Collect = Callable[
    [list[dict], Path, str | None, int, ExactSearchMetrics | None],
    tuple[list[dict], dict[str, dict[int, str]], int, bool],
]
MatchGlob = Callable[[str, Path, str | None], bool]


def scan_exact(
    mode: str,
    resolved: Path,
    pattern: str,
    glob: str | None,
    fixed_strings: bool,
    context: int,
    max_results: int,
    metrics: ExactSearchMetrics,
    *,
    run_rg: RunRg,
    collect: Collect,
    matches_glob: MatchGlob,
    rg_bin: str,
    timeout_s: float,
    max_line_chars: int,
    clip_mark: str,
) -> ExactScanResult:
    if mode == "streaming":
        return _scan_streaming(
            resolved,
            pattern,
            glob,
            fixed_strings,
            context,
            max_results,
            metrics,
            matches_glob=matches_glob,
            rg_bin=rg_bin,
            timeout_s=timeout_s,
            max_line_chars=max_line_chars,
            clip_mark=clip_mark,
        )
    events, _ = run_rg(resolved, pattern, fixed_strings, context, metrics)
    matches, line_map, total, truncated = collect(
        events, resolved, glob, max_results, metrics
    )
    return ExactScanResult(matches, line_map, total, truncated, events, glob)


def _scan_streaming(
    resolved: Path,
    pattern: str,
    glob: str | None,
    fixed_strings: bool,
    context: int,
    max_results: int,
    metrics: ExactSearchMetrics,
    *,
    matches_glob: MatchGlob,
    rg_bin: str,
    timeout_s: float,
    max_line_chars: int,
    clip_mark: str,
) -> ExactScanResult:
    metrics.pipeline = "streaming"
    metrics.rg_calls += 1
    reducer = ExactStreamReducer(
        resolved,
        glob,
        max_results,
        max_line_chars=max_line_chars,
        clip_mark=clip_mark,
        matches_glob=matches_glob,
    )
    stream = RgJsonStream(
        resolved,
        pattern,
        fixed_strings,
        context,
        rg_bin=rg_bin,
        timeout_s=timeout_s,
    )
    try:
        with stream:
            for event in stream:
                reducer.consume(event)
    finally:
        _update_stream_metrics(metrics, stream)
    result = reducer.result()
    _update_reducer_metrics(metrics, reducer, result)
    return ExactScanResult(
        result.matches,
        result.line_map,
        result.total,
        result.truncated,
        result.accepted_match_events,
        None,
    )


def _update_stream_metrics(metrics, stream) -> None:
    metrics.rg_events += stream.stats.events
    metrics.rg_match_events += stream.stats.match_events
    metrics.rg_context_events += stream.stats.context_events
    metrics.rg_begin_events += stream.stats.begin_events
    metrics.rg_bad_json += stream.stats.bad_json
    metrics.rg_stdout_bytes += stream.stats.stdout_bytes
    metrics.rg_wall_ms += stream.stats.wall_ms
    metrics.stream_cpu_ms += stream.stats.stream_cpu_ms


def _update_reducer_metrics(metrics, reducer, result) -> None:
    metrics.glob_cache_hits += reducer.glob_cache_hits
    metrics.glob_cache_misses += reducer.glob_cache_misses
    metrics.glob_rejected_files += reducer.glob_rejected_files
    metrics.glob_rejected_events += reducer.glob_rejected_events
    metrics.adaptive_retained_match_events += len(result.accepted_match_events)
    metrics.collect_event_candidates += reducer.event_candidates
    metrics.collect_glob_checks += reducer.glob_cache_misses
    metrics.collect_glob_rejected += reducer.glob_rejected_events
    metrics.accepted_matches = result.total
    metrics.accepted_files = reducer.accepted_files
    metrics.retained_matches = len(result.matches)
    metrics.match_cap_hit = result.truncated

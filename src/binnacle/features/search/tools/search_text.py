"""Regex search with ripgrep plus adaptive discovery (see docs/tools/search_text.md)."""

import hashlib
import logging
import subprocess as _subprocess
import time
from functools import partial
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult

from binnacle.config import RootsSettings, SearchTextSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files.paths import full_match, nearby_hint, resolve_path
from binnacle.features.search.search_text_adaptive import (
    build_adaptive_result,
    log_adaptive_result,
)
from binnacle.features.search.search_text_budget import (
    enforce_result_budget as _fit_result_budget,
)
from binnacle.features.search.search_text_budget import (
    entry_count as _budget_entry_count,
)
from binnacle.features.search.search_text_budget import (
    structured_bytes as _budget_structured_bytes,
)
from binnacle.features.search.search_text_collect import (
    attach_context as _attach_context_impl,
)
from binnacle.features.search.search_text_collect import (
    collect as _collect_impl,
)
from binnacle.features.search.search_text_collect import (
    matches_glob as _matches_glob_impl,
)
from binnacle.features.search.search_text_pipeline import scan_exact as _scan_exact_impl
from binnacle.features.search.search_text_rg import run_rg as _run_rg_impl
from binnacle.features.search.search_text_telemetry import (
    AdaptiveWork,
    ExactSearchMetrics,
)
from binnacle.features.search.search_text_telemetry import (
    fit_budget_with_metrics as _fit_budget_metrics,
)
from binnacle.features.search.search_text_telemetry import (
    timed_attach_context as _timed_attach_context_impl,
)
from binnacle.mcp.callctx import current_call

LINE_CLIP_MARK = "… [line truncated]"
log = logging.getLogger("binnacle.search_text")
subprocess = _subprocess  # compatibility seam for existing tests/extensions
from binnacle.features.search.search_text_schema import OUTPUT_SCHEMA

_structured_bytes = _budget_structured_bytes
_entry_count = _budget_entry_count


def _enforce_result_budget_rich(
    payload: dict[str, Any],
    *,
    names_only: bool,
    max_bytes: int,
    initial_bytes: int | None = None,
):
    return _fit_result_budget(
        payload,
        names_only=names_only,
        max_bytes=max_bytes,
        initial_bytes=initial_bytes,
    )


def _enforce_result_budget(
    payload: dict[str, Any], *, names_only: bool, max_bytes: int
) -> tuple[dict[str, Any], bool]:
    outcome = _enforce_result_budget_rich(
        payload, names_only=names_only, max_bytes=max_bytes
    )
    return outcome.payload, outcome.hit


def _run_rg(
    root: Path,
    pattern: str,
    fixed_strings: bool,
    context: int,
    metrics: ExactSearchMetrics | None = None,
    *,
    rg_bin: str,
    timeout_s: int,
) -> tuple[list[dict], bool]:
    return _run_rg_impl(
        root,
        pattern,
        fixed_strings,
        context,
        rg_bin=rg_bin,
        timeout_s=timeout_s,
        metrics=metrics,
    )


def _matches_glob(file_path: str, root: Path, glob: str | None) -> bool:
    return _matches_glob_impl(file_path, root, glob, matcher=full_match)


def _collect(
    events: list[dict],
    root: Path,
    glob: str | None,
    max_results: int,
    metrics: ExactSearchMetrics | None = None,
    *,
    max_line_chars: int,
) -> tuple[list[dict], dict[str, dict[int, str]], int, bool]:
    return _collect_impl(
        events,
        root,
        glob,
        max_results,
        metrics,
        max_line_chars=max_line_chars,
        clip_mark=LINE_CLIP_MARK,
    )


def _attach_context(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    span: int,
    line_numbers: bool = False,
    *,
    max_line_chars: int,
) -> None:
    _attach_context_impl(
        matches,
        line_map,
        span,
        line_numbers,
        max_line_chars=max_line_chars,
        clip_mark=LINE_CLIP_MARK,
    )


def _scan_exact(
    resolved: Path,
    pattern: str,
    glob: str | None,
    fixed_strings: bool,
    context: int,
    max_results: int,
    metrics: ExactSearchMetrics,
    *,
    settings: SearchTextSettings,
    rg_bin: str,
):
    return _scan_exact_impl(
        settings.exact_execution,
        resolved,
        pattern,
        glob,
        fixed_strings,
        context,
        max_results,
        metrics,
        run_rg=partial(_run_rg, rg_bin=rg_bin, timeout_s=settings.timeout_s),
        collect=partial(_collect, max_line_chars=settings.max_line_chars),
        matches_glob=_matches_glob,
        rg_bin=rg_bin,
        timeout_s=settings.timeout_s,
        max_line_chars=settings.max_line_chars,
        clip_mark=LINE_CLIP_MARK,
    )


def _fit_budget_with_metrics(
    payload: dict[str, Any],
    *,
    names_only: bool,
    metrics: ExactSearchMetrics,
    max_bytes: int,
    pre_bytes: int | None = None,
):
    return _fit_budget_metrics(
        payload,
        names_only=names_only,
        metrics=metrics,
        structured_bytes=_structured_bytes,
        enforce=partial(_enforce_result_budget_rich, max_bytes=max_bytes),
        pre_bytes=pre_bytes,
    )


def _search_exact_impl(
    pattern: str,
    resolved: Path,
    glob: str | None,
    fixed_strings: bool,
    context_lines: int | None,
    names_only: bool,
    max_results: int,
    line_numbers: bool,
    metrics: ExactSearchMetrics,
    *,
    settings: SearchTextSettings,
    rg_bin: str,
) -> ToolResult:
    attach_context = partial(_attach_context, max_line_chars=settings.max_line_chars)
    explicit_context = context_lines if context_lines is not None else 0
    metrics.effective_context = explicit_context
    scan = _scan_exact(
        resolved,
        pattern,
        glob,
        fixed_strings,
        explicit_context,
        max_results,
        metrics,
        settings=settings,
        rg_bin=rg_bin,
    )
    matches, line_map, total, truncated = (
        scan.matches,
        scan.line_map,
        scan.total,
        scan.truncated,
    )

    if (
        not names_only
        and context_lines is None
        and 1 <= len(matches) <= 3
        and not truncated
    ):
        metrics.auto_context = True
        span = (
            settings.auto_context_single
            if len(matches) == 1
            else settings.auto_context_few
        )
        metrics.effective_context = span
        scan = _scan_exact(
            resolved,
            pattern,
            glob,
            fixed_strings,
            span,
            max_results,
            metrics,
            settings=settings,
            rg_bin=rg_bin,
        )
        matches, line_map, total, truncated = (
            scan.matches,
            scan.line_map,
            scan.total,
            scan.truncated,
        )
        _timed_attach_context_impl(
            attach_context, matches, line_map, span, line_numbers, metrics
        )
    elif explicit_context > 0:
        _timed_attach_context_impl(
            attach_context, matches, line_map, explicit_context, line_numbers, metrics
        )

    where = f"{resolved}" + (f" (glob {glob!r})" if glob else "")
    if names_only:
        counts: dict[str, int] = {}
        for match in matches:
            counts[match["file"]] = counts.get(match["file"], 0) + 1
        entries = [
            {"file": file, "count": count} for file, count in sorted(counts.items())
        ]
        payload = {
            "path": str(resolved),
            "pattern": pattern,
            "entries": entries,
            "count": total,
            "truncated": truncated,
        }
        summary = (
            f"Found {total} matches for {pattern!r} in {len(entries)} files under {where}."
            if entries
            else f"No matches for {pattern!r} under {where}."
        )
        outcome = _fit_budget_with_metrics(
            payload,
            names_only=True,
            metrics=metrics,
            max_bytes=settings.result_max_bytes,
        )
        payload = outcome.payload
        if outcome.hit:
            log.info(
                "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
                "returned_entries=%s total_matches=%s names_only=true",
                current_call.get(),
                outcome.result_bytes,
                settings.result_max_bytes,
                _entry_count(payload),
                total,
            )
            summary = (
                f"Found {total} matches for {pattern!r} under {where}; "
                f"showing {_entry_count(payload)} within the response budget."
            )
        metrics.mark_result(payload, strategy="names_only")
        return ToolResult(content=summary, structured_content=payload)

    payload = {
        "path": str(resolved),
        "pattern": pattern,
        "entries": matches,
        "count": total,
        "truncated": truncated,
    }
    if not matches:
        payload["note"] = (
            "No matches (gitignored and hidden files are not searched; "
            "use run_command rg --no-ignore to include them)."
        )
        summary = f"No matches for {pattern!r} under {where}."
    elif truncated:
        payload["note"] = (
            f"Showing first {len(matches)} of {total} matches; narrow the "
            f"pattern, add a glob, or raise max_results."
        )
        summary = (
            f"Found {total} matches for {pattern!r} under {where}; "
            f"showing first {len(matches)}."
        )
    else:
        summary = f"Found {total} matches for {pattern!r} under {where}."

    pre_budget_bytes = _structured_bytes(payload)
    metrics.pre_budget_bytes = pre_budget_bytes
    if (
        settings.adaptive_discovery_enabled
        and pre_budget_bytes > settings.result_max_bytes
    ):
        metrics.adaptive_attempted = True
        adaptive_work = AdaptiveWork()
        started_ns = time.perf_counter_ns()
        try:
            adaptive = build_adaptive_result(
                scan.adaptive_events,
                root=resolved,
                pattern=pattern,
                glob=scan.adaptive_glob,
                fixed_strings=fixed_strings,
                max_match_entries=max_results,
                settings=settings,
                matches_glob=_matches_glob,
                result_max_bytes=settings.result_max_bytes,
                work=adaptive_work,
            )
        finally:
            metrics.adaptive_ms += ExactSearchMetrics.elapsed_ms(started_ns)
            metrics.adaptive_match_events += adaptive_work.match_events_scanned
            metrics.adaptive_glob_checks += adaptive_work.glob_checks
            metrics.adaptive_glob_rejected += adaptive_work.glob_rejected
        if adaptive is not None:
            metrics.adaptive_selected = True
            metrics.adaptive_budget_trimmed = adaptive.budget_trimmed
            metrics.result_bytes = adaptive.result_bytes
            payload = adaptive.payload
            log_adaptive_result(
                log,
                call=current_call.get(),
                trigger_bytes=pre_budget_bytes,
                total_matches=total,
                result=adaptive,
                result_budget_bytes=settings.result_max_bytes,
            )
            summary = (
                f"Found {total} matches for {pattern!r} under {where}; "
                f"adaptive discovery shows {adaptive.candidate_files} ranked files."
            )
            metrics.mark_result(payload, strategy="adaptive")
            return ToolResult(content=summary, structured_content=payload)

    outcome = _fit_budget_with_metrics(
        payload,
        names_only=False,
        metrics=metrics,
        pre_bytes=pre_budget_bytes,
        max_bytes=settings.result_max_bytes,
    )
    payload = outcome.payload
    if outcome.hit:
        log.info(
            "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
            "returned_entries=%s total_matches=%s names_only=false",
            current_call.get(),
            outcome.result_bytes,
            settings.result_max_bytes,
            _entry_count(payload),
            total,
        )
        summary = (
            f"Found {total} matches for {pattern!r} under {where}; "
            f"showing {_entry_count(payload)} within the response budget."
        )
    metrics.mark_result(payload, strategy="normal")
    return ToolResult(content=summary, structured_content=payload)


def search_text_impl(
    pattern: str,
    path: str,
    glob: str | None,
    fixed_strings: bool,
    context_lines: int | None,
    names_only: bool,
    max_results: int,
    line_numbers: bool = False,
    *,
    roots: RootsSettings | None = None,
    settings: SearchTextSettings | None = None,
    rg_bin: str | None = None,
) -> ToolResult:
    if roots is None or settings is None or rg_bin is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        settings = defaults.search_text if settings is None else settings
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
    if not pattern:
        raise CodedToolError(
            "empty_pattern", "The 'pattern' parameter must be non-empty."
        )
    resolved = resolve_path(path, roots=roots)
    if not resolved.exists():
        raise CodedToolError(
            "path_not_found",
            f"Path not found: {resolved}.{nearby_hint(resolved.parent, roots=roots)}",
        )
    max_results = max(1, min(max_results, settings.max_results_cap))

    # mode stays in the line for journal readers; since the removal of the
    # indexed-context pilot (2026-09-28) every search is exact.
    log.info(
        "event=search_dispatch call=%s mode=exact path_hash=%s pattern_chars=%s",
        current_call.get(),
        hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12],
        len(pattern),
    )

    metrics = ExactSearchMetrics(
        call=current_call.get(),
        scope="file" if resolved.is_file() else "dir",
        context_requested="omitted" if context_lines is None else str(context_lines),
    )
    metrics.start()
    try:
        result = _search_exact_impl(
            pattern,
            resolved,
            glob,
            fixed_strings,
            context_lines,
            names_only,
            max_results,
            line_numbers,
            metrics,
            settings=settings,
            rg_bin=rg_bin,
        )
    except Exception as exc:
        metrics.log_terminal(log, exc)
        raise
    metrics.log_terminal(log)
    return result


def register(
    mcp: FastMCP,
    *,
    roots: RootsSettings,
    settings: SearchTextSettings,
    rg_bin: str,
) -> None:
    from binnacle.features.search.search_text_register import register_search_text

    roots, settings = roots.model_copy(deep=True), settings.model_copy(deep=True)
    register_search_text(
        mcp,
        partial(search_text_impl, roots=roots, settings=settings, rg_bin=rg_bin),
        output_schema=OUTPUT_SCHEMA,
        max_results_default=settings.max_results_default,
        max_results_cap=settings.max_results_cap,
    )

"""Regex search with ripgrep plus indexed/adaptive discovery (see docs/tools/search_text.md)."""

import hashlib
import logging
import subprocess as _subprocess
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult

from binnacle.callctx import current_call
from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.indexed_context import PREFIX as INDEXED_CONTEXT_PREFIX
from binnacle.indexed_context import get_indexed_context_service
from binnacle.paths import full_match, nearby_hint, resolve_path
from binnacle.search_text_adaptive import (
    build_adaptive_result,
    log_adaptive_result,
)
from binnacle.search_text_budget import (
    enforce_result_budget as _fit_result_budget,
)
from binnacle.search_text_budget import (
    entry_count as _budget_entry_count,
)
from binnacle.search_text_budget import (
    structured_bytes as _budget_structured_bytes,
)
from binnacle.search_text_collect import (
    attach_context as _attach_context_impl,
)
from binnacle.search_text_collect import (
    collect as _collect_impl,
)
from binnacle.search_text_collect import matches_glob as _matches_glob_impl
from binnacle.search_text_pipeline import scan_exact as _scan_exact_impl
from binnacle.search_text_rg import run_rg as _run_rg_impl
from binnacle.search_text_telemetry import (
    AdaptiveWork,
    ExactSearchMetrics,
)
from binnacle.search_text_telemetry import (
    fit_budget_with_metrics as _fit_budget_metrics,
)
from binnacle.search_text_telemetry import (
    timed_attach_context as _timed_attach_context_impl,
)

SEARCH_SETTINGS = get_settings().search_text
SEARCH_MAX_RESULTS_DEFAULT = SEARCH_SETTINGS.max_results_default
SEARCH_MAX_RESULTS_CAP = SEARCH_SETTINGS.max_results_cap
SEARCH_TIMEOUT_S = SEARCH_SETTINGS.timeout_s
EXACT_EXECUTION = SEARCH_SETTINGS.exact_execution
SEARCH_MAX_LINE_CHARS = SEARCH_SETTINGS.max_line_chars
SEARCH_RESULT_MAX_BYTES = SEARCH_SETTINGS.result_max_bytes
LINE_CLIP_MARK = "… [line truncated]"
log = logging.getLogger("binnacle.search_text")
AUTO_CONTEXT_SINGLE = get_settings().search_text.auto_context_single
AUTO_CONTEXT_FEW = get_settings().search_text.auto_context_few
RG_BIN = get_settings().rg_bin
subprocess = _subprocess  # compatibility seam for existing tests/extensions
from binnacle.search_text_schema import OUTPUT_SCHEMA

_structured_bytes = _budget_structured_bytes
_entry_count = _budget_entry_count


def _enforce_result_budget_rich(
    payload: dict[str, Any], *, names_only: bool, initial_bytes: int | None = None
):
    return _fit_result_budget(
        payload,
        names_only=names_only,
        max_bytes=SEARCH_RESULT_MAX_BYTES,
        initial_bytes=initial_bytes,
    )


def _enforce_result_budget(
    payload: dict[str, Any], *, names_only: bool
) -> tuple[dict[str, Any], bool]:
    outcome = _enforce_result_budget_rich(payload, names_only=names_only)
    return outcome.payload, outcome.hit


def _run_rg(
    root: Path,
    pattern: str,
    fixed_strings: bool,
    context: int,
    metrics: ExactSearchMetrics | None = None,
) -> tuple[list[dict], bool]:
    return _run_rg_impl(
        root,
        pattern,
        fixed_strings,
        context,
        rg_bin=RG_BIN,
        timeout_s=SEARCH_TIMEOUT_S,
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
) -> tuple[list[dict], dict[str, dict[int, str]], int, bool]:
    return _collect_impl(
        events,
        root,
        glob,
        max_results,
        metrics,
        max_line_chars=SEARCH_MAX_LINE_CHARS,
        clip_mark=LINE_CLIP_MARK,
    )


def _attach_context(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    span: int,
    line_numbers: bool = False,
) -> None:
    _attach_context_impl(
        matches,
        line_map,
        span,
        line_numbers,
        max_line_chars=SEARCH_MAX_LINE_CHARS,
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
):
    return _scan_exact_impl(
        EXACT_EXECUTION,
        resolved,
        pattern,
        glob,
        fixed_strings,
        context,
        max_results,
        metrics,
        run_rg=_run_rg,
        collect=_collect,
        matches_glob=_matches_glob,
        rg_bin=RG_BIN,
        timeout_s=SEARCH_TIMEOUT_S,
        max_line_chars=SEARCH_MAX_LINE_CHARS,
        clip_mark=LINE_CLIP_MARK,
    )


def _fit_budget_with_metrics(
    payload: dict[str, Any],
    *,
    names_only: bool,
    metrics: ExactSearchMetrics,
    pre_bytes: int | None = None,
):
    return _fit_budget_metrics(
        payload,
        names_only=names_only,
        metrics=metrics,
        structured_bytes=_structured_bytes,
        enforce=_enforce_result_budget_rich,
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
) -> ToolResult:
    explicit_context = context_lines if context_lines is not None else 0
    metrics.effective_context = explicit_context
    scan = _scan_exact(
        resolved, pattern, glob, fixed_strings, explicit_context, max_results, metrics
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
        span = AUTO_CONTEXT_SINGLE if len(matches) == 1 else AUTO_CONTEXT_FEW
        metrics.effective_context = span
        scan = _scan_exact(
            resolved, pattern, glob, fixed_strings, span, max_results, metrics
        )
        matches, line_map, total, truncated = (
            scan.matches,
            scan.line_map,
            scan.total,
            scan.truncated,
        )
        _timed_attach_context_impl(
            _attach_context, matches, line_map, span, line_numbers, metrics
        )
    elif explicit_context > 0:
        _timed_attach_context_impl(
            _attach_context, matches, line_map, explicit_context, line_numbers, metrics
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
        outcome = _fit_budget_with_metrics(payload, names_only=True, metrics=metrics)
        payload = outcome.payload
        if outcome.hit:
            log.info(
                "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
                "returned_entries=%s total_matches=%s names_only=true",
                current_call.get(),
                outcome.result_bytes,
                SEARCH_RESULT_MAX_BYTES,
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
        SEARCH_SETTINGS.adaptive_discovery_enabled
        and pre_budget_bytes > SEARCH_RESULT_MAX_BYTES
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
                settings=SEARCH_SETTINGS,
                matches_glob=_matches_glob,
                result_max_bytes=SEARCH_RESULT_MAX_BYTES,
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
                result_budget_bytes=SEARCH_RESULT_MAX_BYTES,
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
    )
    payload = outcome.payload
    if outcome.hit:
        log.info(
            "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
            "returned_entries=%s total_matches=%s names_only=false",
            current_call.get(),
            outcome.result_bytes,
            SEARCH_RESULT_MAX_BYTES,
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
) -> ToolResult:
    if not pattern:
        raise CodedToolError(
            "empty_pattern", "The 'pattern' parameter must be non-empty."
        )
    resolved = resolve_path(path)
    if not resolved.exists():
        raise CodedToolError(
            "path_not_found",
            f"Path not found: {resolved}.{nearby_hint(resolved.parent)}",
        )
    max_results = max(1, min(max_results, SEARCH_MAX_RESULTS_CAP))

    indexed_mode = not fixed_strings and pattern.startswith(INDEXED_CONTEXT_PREFIX)
    log.info(
        "event=search_dispatch call=%s mode=%s path_hash=%s pattern_chars=%s",
        current_call.get(),
        "indexed" if indexed_mode else "exact",
        hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12],
        len(pattern),
    )
    if indexed_mode:
        if glob is not None or names_only or context_lines not in (None, 0):
            raise CodedToolError(
                "indexed_args_invalid",
                "@context uses a fixed bounded context package; omit glob, "
                "context_lines and names_only. Use ordinary regex mode for those controls.",
            )
        return get_indexed_context_service().search(pattern, resolved)

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
        )
    except Exception as exc:
        metrics.log_terminal(log, exc)
        raise
    metrics.log_terminal(log)
    return result


def register(mcp: FastMCP) -> None:
    from binnacle.search_text_register import register_search_text

    register_search_text(
        mcp,
        search_text_impl,
        output_schema=OUTPUT_SCHEMA,
        max_results_default=SEARCH_MAX_RESULTS_DEFAULT,
        max_results_cap=SEARCH_MAX_RESULTS_CAP,
    )

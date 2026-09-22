"""Regex search with ripgrep plus indexed/adaptive discovery (see docs/tools/search_text.md)."""

import hashlib
import logging
import subprocess
import time
from pathlib import Path, PurePath
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.callctx import current_call
from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.indexed_context import PREFIX as INDEXED_CONTEXT_PREFIX
from binnacle.indexed_context import get_indexed_context_service
from binnacle.paths import full_match, nearby_hint, resolve_path
from binnacle.search_text_adaptive import build_adaptive_result, log_adaptive_result
from binnacle.search_text_budget import (
    enforce_result_budget as _fit_result_budget,
)
from binnacle.search_text_budget import (
    entry_count as _budget_entry_count,
)
from binnacle.search_text_budget import (
    structured_bytes as _budget_structured_bytes,
)
from binnacle.search_text_telemetry import ExactSearchMetrics

SEARCH_SETTINGS = get_settings().search_text
SEARCH_MAX_RESULTS_DEFAULT = SEARCH_SETTINGS.max_results_default
SEARCH_MAX_RESULTS_CAP = SEARCH_SETTINGS.max_results_cap
SEARCH_TIMEOUT_S = SEARCH_SETTINGS.timeout_s
SEARCH_MAX_LINE_CHARS = SEARCH_SETTINGS.max_line_chars
SEARCH_RESULT_MAX_BYTES = SEARCH_SETTINGS.result_max_bytes
LINE_CLIP_MARK = "… [line truncated]"
log = logging.getLogger("binnacle.search_text")
AUTO_CONTEXT_SINGLE = get_settings().search_text.auto_context_single
AUTO_CONTEXT_FEW = get_settings().search_text.auto_context_few
RG_BIN = get_settings().rg_bin


from binnacle.search_text_schema import OUTPUT_SCHEMA


def _clip(text: str) -> str:
    if len(text) > SEARCH_MAX_LINE_CHARS:
        return text[:SEARCH_MAX_LINE_CHARS] + LINE_CLIP_MARK
    return text


def _structured_bytes(payload: dict[str, Any]) -> int:
    return _budget_structured_bytes(payload)


def _entry_count(payload: dict[str, Any]) -> int:
    return _budget_entry_count(payload)


def _enforce_result_budget_rich(payload: dict[str, Any], *, names_only: bool):
    return _fit_result_budget(
        payload, names_only=names_only, max_bytes=SEARCH_RESULT_MAX_BYTES
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
    """Run rg --json; returns (events, hit_no_match). Raises ToolError."""
    import orjson

    cmd = [RG_BIN, "--json", "--smart-case"]
    if fixed_strings:
        cmd.append("--fixed-strings")
    if context > 0:
        cmd += ["--context", str(context)]
    cmd += ["--regexp", pattern, str(root)]
    if metrics is not None:
        metrics.rg_calls += 1
    started_ns = time.perf_counter_ns()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SEARCH_TIMEOUT_S, check=False
        )
    except FileNotFoundError:
        raise CodedToolError(
            "rg_missing",
            "ripgrep (rg) is not available; use run_command (grep -rn) instead.",
        )
    except subprocess.TimeoutExpired:
        raise CodedToolError(
            "rg_timeout",
            f"Search timed out after {SEARCH_TIMEOUT_S} s. Narrow the scope "
            f"with a more specific path or a glob filter.",
        )
    finally:
        if metrics is not None:
            metrics.rg_subprocess_ms += ExactSearchMetrics.elapsed_ms(started_ns)
    if proc.returncode == 2 or (proc.returncode not in (0, 1) and proc.stderr):
        raise CodedToolError(
            "rg_rejected",
            f"ripgrep rejected the search: {proc.stderr.strip()[-300:]}. "
            f"Fix the pattern, or use fixed_strings for literal text.",
        )

    if metrics is not None:
        metrics.rg_stdout_chars += len(proc.stdout)
    parse_started_ns = time.perf_counter_ns()
    events: list[dict] = []
    for line in proc.stdout.splitlines():
        try:
            event = orjson.loads(line)
        except orjson.JSONDecodeError:
            if metrics is not None:
                metrics.rg_bad_json += 1
            continue
        events.append(event)
        if metrics is not None:
            metrics.rg_events += 1
            kind = event.get("type")
            if kind == "match":
                metrics.rg_match_events += 1
            elif kind == "context":
                metrics.rg_context_events += 1
            elif kind == "begin":
                metrics.rg_begin_events += 1
    if metrics is not None:
        metrics.rg_parse_ms += ExactSearchMetrics.elapsed_ms(parse_started_ns)
    return events, proc.returncode == 1


def _matches_glob(file_path: str, root: Path, glob: str | None) -> bool:
    if not glob:
        return True
    pattern = glob if "/" in glob else f"**/{glob}"
    try:
        rel = (
            PurePath(file_path).relative_to(root)
            if root.is_dir()
            else PurePath(PurePath(file_path).name)
        )
    except ValueError:
        rel = PurePath(file_path)
    try:
        return full_match(rel, pattern)
    except ValueError as e:
        raise CodedToolError("invalid_glob", f"Invalid glob pattern {glob!r}: {e}")


def _collect(
    events: list[dict],
    root: Path,
    glob: str | None,
    max_results: int,
    metrics: ExactSearchMetrics | None = None,
) -> tuple[list[dict], dict[str, dict[int, str]], int, bool]:
    """Parse rg events into match entries plus a per-file line map."""
    started_ns = time.perf_counter_ns()
    matches: list[dict] = []
    line_map: dict[str, dict[int, str]] = {}
    total = 0
    truncated = False
    try:
        for ev in events:
            kind = ev.get("type")
            if kind not in ("match", "context"):
                continue
            if metrics is not None:
                metrics.collect_event_candidates += 1
            data = ev["data"]
            file = data["path"]["text"]
            if glob is not None and metrics is not None:
                metrics.collect_glob_checks += 1
            if not _matches_glob(file, root, glob):
                if glob is not None and metrics is not None:
                    metrics.collect_glob_rejected += 1
                continue
            line_no = data["line_number"]
            text = data["lines"].get("text", "").rstrip("\n")
            line_map.setdefault(file, {})[line_no] = text
            if kind == "match":
                total += 1
                if len(matches) < max_results:
                    matches.append({"file": file, "line": line_no, "text": _clip(text)})
                else:
                    truncated = True
        if metrics is not None:
            metrics.accepted_matches = total
            metrics.accepted_files = len(line_map)
            metrics.retained_matches = len(matches)
            metrics.match_cap_hit = truncated
        return matches, line_map, total, truncated
    finally:
        if metrics is not None:
            metrics.collect_ms += ExactSearchMetrics.elapsed_ms(started_ns)


def _attach_context(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    span: int,
    line_numbers: bool = False,
) -> None:
    for m in matches:
        lines = line_map.get(m["file"], {})
        nums = sorted(n for n in lines if m["line"] - span <= n <= m["line"] + span)
        if len(nums) <= 1:
            continue
        m["context_first_line"] = nums[0]
        if line_numbers:
            width = len(str(nums[-1]))
            m["context"] = "\n".join(f"{n:>{width}}: {_clip(lines[n])}" for n in nums)
        else:
            m["context"] = "\n".join(_clip(lines[n]) for n in nums)


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

    explicit_context = context_lines if context_lines is not None else 0
    events, _ = _run_rg(resolved, pattern, fixed_strings, explicit_context)
    matches, line_map, total, truncated = _collect(events, resolved, glob, max_results)

    if (
        not names_only
        and context_lines is None
        and 1 <= len(matches) <= 3
        and not truncated
    ):
        span = AUTO_CONTEXT_SINGLE if len(matches) == 1 else AUTO_CONTEXT_FEW
        events, _ = _run_rg(resolved, pattern, fixed_strings, span)
        matches, line_map, total, truncated = _collect(
            events, resolved, glob, max_results
        )
        _attach_context(matches, line_map, span, line_numbers)
    elif explicit_context > 0:
        _attach_context(matches, line_map, explicit_context, line_numbers)

    where = f"{resolved}" + (f" (glob {glob!r})" if glob else "")
    if names_only:
        counts: dict[str, int] = {}
        for m in matches:
            counts[m["file"]] = counts.get(m["file"], 0) + 1
        entries = [{"file": f, "count": c} for f, c in sorted(counts.items())]
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
        payload, budget_hit = _enforce_result_budget(payload, names_only=True)
        if budget_hit:
            result_bytes = _structured_bytes(payload)
            log.info(
                "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
                "returned_entries=%s total_matches=%s names_only=true",
                current_call.get(),
                result_bytes,
                SEARCH_RESULT_MAX_BYTES,
                _entry_count(payload),
                total,
            )
            summary = (
                f"Found {total} matches for {pattern!r} under {where}; "
                f"showing {_entry_count(payload)} within the response budget."
            )
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
    if (
        SEARCH_SETTINGS.adaptive_discovery_enabled
        and pre_budget_bytes > SEARCH_RESULT_MAX_BYTES
    ):
        adaptive = build_adaptive_result(
            events,
            root=resolved,
            pattern=pattern,
            glob=glob,
            fixed_strings=fixed_strings,
            max_match_entries=max_results,
            settings=SEARCH_SETTINGS,
            matches_glob=_matches_glob,
            result_max_bytes=SEARCH_RESULT_MAX_BYTES,
        )
        if adaptive is not None:
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
            return ToolResult(content=summary, structured_content=payload)

    payload, budget_hit = _enforce_result_budget(payload, names_only=False)
    if budget_hit:
        result_bytes = _structured_bytes(payload)
        log.info(
            "event=search_budget_hit call=%s result_bytes=%s result_budget_bytes=%s "
            "returned_entries=%s total_matches=%s names_only=false",
            current_call.get(),
            result_bytes,
            SEARCH_RESULT_MAX_BYTES,
            _entry_count(payload),
            total,
        )
        summary = (
            f"Found {total} matches for {pattern!r} under {where}; "
            f"showing {_entry_count(payload)} within the response budget."
        )
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=OUTPUT_SCHEMA,
    )
    def search_text(
        pattern: Annotated[
            str,
            Field(
                description=(
                    "Regex (Rust syntax), or `@context <query>` for indexed repository "
                    "discovery when path is the Git worktree root. Use fixed_strings for literal text."
                )
            ),
        ],
        path: Annotated[
            str,
            Field(
                description="File or directory to search. Absolute (~ ok); relative resolves against ~/Projects."
            ),
        ] = "~/Projects",
        glob: Annotated[
            str | None,
            Field(description="Only search files matching this glob (e.g. *.py)."),
        ] = None,
        fixed_strings: Annotated[
            bool, Field(description="Treat pattern as literal text.")
        ] = False,
        context_lines: Annotated[
            int | None,
            Field(
                ge=0,
                le=100,
                description="Context lines around each match. Omit for automatic context on few matches.",
            ),
        ] = None,
        names_only: Annotated[
            bool, Field(description="Return only files and their match counts.")
        ] = False,
        max_results: Annotated[
            int,
            Field(
                ge=1, le=SEARCH_MAX_RESULTS_CAP, description="Cap on returned matches."
            ),
        ] = SEARCH_MAX_RESULTS_DEFAULT,
        line_numbers: Annotated[
            bool,
            Field(
                description="Prefix each context line with its line number (grep -n style)."
            ),
        ] = False,
    ) -> ToolResult:
        """Search repository content. Normal regex search replaces grep -rn;
        names_only replaces grep -c; line_numbers supplies grep -n style context.
        Prefer this over grep in run_command. When the implementation location is
        unknown, use ``@context <query>``
        with ``path`` set to the Git worktree root, then verify/narrow with exact
        search as needed.
        """
        return search_text_impl(
            pattern,
            path,
            glob,
            fixed_strings,
            context_lines,
            names_only,
            max_results,
            line_numbers,
        )

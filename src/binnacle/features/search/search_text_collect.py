"""Exact-search event collection, glob filtering and context attachment."""

import os
import shutil
import subprocess
import time
from pathlib import Path, PurePath

from binnacle.errors import CodedToolError
from binnacle.features.files.paths import full_match
from binnacle.features.search.search_text_telemetry import ExactSearchMetrics
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError


def _rg_rejection(access, pattern: str, fixed_strings: bool) -> CodedToolError:
    """Linux rg_rejected sentence: the adapter drains stderr, so ask rg again
    about the pattern alone (no files are read) to recover its diagnostic."""
    rg = getattr(access.search, "_rg_bin", None) or shutil.which("rg") or "rg"
    cmd = [rg, "--no-config", "--smart-case"]
    if fixed_strings:
        cmd.append("--fixed-strings")
    cmd += ["--regexp", pattern, os.devnull]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=False
        )
        stderr = proc.stderr.strip()[-300:] if proc.returncode == 2 else ""
    except (OSError, subprocess.SubprocessError):
        stderr = ""
    return CodedToolError(
        "rg_rejected",
        f"ripgrep rejected the search: {stderr or 'unknown error'}. "
        "Fix the pattern, or use fixed_strings for literal text.",
    )


def clip(text: str, max_chars: int, mark: str) -> str:
    return text[:max_chars] + mark if len(text) > max_chars else text


def matches_glob(
    file_path: str,
    root: Path,
    glob: str | None,
    *,
    matcher=full_match,
) -> bool:
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
        return matcher(rel, pattern)
    except ValueError as exc:
        raise CodedToolError(
            "invalid_glob", f"Invalid glob pattern {glob!r}: {exc}"
        ) from exc


def collect(
    events: list[dict],
    root: Path,
    glob: str | None,
    max_results: int,
    metrics: ExactSearchMetrics | None,
    *,
    max_line_chars: int,
    clip_mark: str,
) -> tuple[list[dict], dict[str, dict[int, str]], int, bool]:
    started_ns = time.perf_counter_ns()
    matches: list[dict] = []
    line_map: dict[str, dict[int, str]] = {}
    total = 0
    truncated = False
    try:
        for event in events:
            kind = event.get("type")
            if kind not in ("match", "context"):
                continue
            if metrics is not None:
                metrics.collect_event_candidates += 1
            data = event["data"]
            file = data["path"]["text"]
            if glob is not None and metrics is not None:
                metrics.collect_glob_checks += 1
            if not matches_glob(file, root, glob):
                if glob is not None and metrics is not None:
                    metrics.collect_glob_rejected += 1
                continue
            line_no = data["line_number"]
            text = data["lines"].get("text", "").rstrip("\n")
            line_map.setdefault(file, {})[line_no] = text
            if kind == "match":
                total += 1
                if len(matches) < max_results:
                    matches.append(
                        {
                            "file": file,
                            "line": line_no,
                            "text": clip(text, max_line_chars, clip_mark),
                        }
                    )
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


def attach_context(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    span: int,
    line_numbers: bool,
    *,
    max_line_chars: int,
    clip_mark: str,
) -> None:
    for match in matches:
        lines = line_map.get(match["file"], {})
        nums = sorted(
            n for n in lines if match["line"] - span <= n <= match["line"] + span
        )
        if len(nums) <= 1:
            continue
        match["context_first_line"] = nums[0]
        if line_numbers:
            width = len(str(nums[-1]))
            match["context"] = "\n".join(
                f"{n:>{width}}: {clip(lines[n], max_line_chars, clip_mark)}"
                for n in nums
            )
        else:
            match["context"] = "\n".join(
                clip(lines[n], max_line_chars, clip_mark) for n in nums
            )


def search_opened(
    access,
    pattern,
    path,
    glob,
    fixed_strings,
    context_lines,
    names_only,
    max_results,
    line_numbers,
    settings,
):
    """Format authorized adapter events; no filesystem calls or path reopening."""
    from fastmcp.tools.base import ToolResult

    from binnacle.features.search.search_text_budget import enforce_result_budget
    from binnacle.platform.contracts.file_access_contracts import SearchRequest

    with access.operation(path, "search_text") as (grant, relative, display):
        if access.search is None:
            raise CodedToolError(
                "native_capability_unavailable", "Search provider missing."
            )
        span = (
            context_lines if context_lines is not None else settings.auto_context_single
        )
        try:
            batch = access.search.search(
                grant,
                SearchRequest(
                    relative,
                    pattern,
                    fixed_strings,
                    span,
                    glob,
                    settings.timeout_s,
                    16 * 1024 * 1024,  # Aggregate input and rg output caps.
                    10000,
                ),
            )
        except NativeCapabilityError as exc:
            if exc.code == "rg_rejected":
                raise _rg_rejection(access, pattern, fixed_strings) from exc
            raise
        # Adapter paths are grant-relative; the label is display-only.
        root_label = display
        for _ in PurePath(relative).parts:
            root_label = root_label.parent
        events = []
        for event in batch.events:
            mapped = dict(event)
            if mapped.get("type") in ("match", "context"):
                data = dict(mapped["data"])
                data["path"] = {"text": str(root_label / data["path"]["text"])}
                mapped["data"] = data
            events.append(mapped)
        matches, line_map, total, capped = collect(
            events,
            display,
            None,
            max(1, min(max_results, settings.max_results_cap)),
            None,
            max_line_chars=settings.max_line_chars,
            clip_mark="… [line truncated]",
        )
        if context_lines is None:
            # Linux adds automatic context only while the result is complete.
            span = (
                0
                if capped
                else settings.auto_context_single
                if len(matches) == 1
                else settings.auto_context_few
                if len(matches) <= 3
                else 0
            )
        if span and not names_only:
            attach_context(
                matches,
                line_map,
                span,
                line_numbers,
                max_line_chars=settings.max_line_chars,
                clip_mark="… [line truncated]",
            )
        entries = matches
        if names_only:
            counts: dict[str, int] = {}
            for match in matches:
                counts[match["file"]] = counts.get(match["file"], 0) + 1
            entries = [
                {"file": name, "count": count} for name, count in sorted(counts.items())
            ]
        payload = {
            "path": str(display),
            "pattern": pattern,
            "entries": entries,
            "count": total,
            "truncated": capped or batch.truncated,
        }
        outcome = enforce_result_budget(
            payload, names_only=names_only, max_bytes=settings.result_max_bytes
        )
        where = f"{display}" + (f" (glob {glob!r})" if glob else "")
        payload = outcome.payload
        if names_only:
            summary = (
                f"Found {total} matches for {pattern!r} in {len(entries)} files "
                f"under {where}."
                if entries
                else f"No matches for {pattern!r} under {where}."
            )
        elif not matches:
            payload.setdefault(
                "note",
                "No matches (gitignored and hidden files are not searched; "
                "use run_command rg --no-ignore to include them).",
            )
            summary = f"No matches for {pattern!r} under {where}."
        elif capped:
            payload.setdefault(
                "note",
                f"Showing first {len(matches)} of {total} matches; narrow the "
                f"pattern, add a glob, or raise max_results.",
            )
            summary = (
                f"Found {total} matches for {pattern!r} under {where}; "
                f"showing first {len(matches)}."
            )
        else:
            summary = f"Found {total} matches for {pattern!r} under {where}."
            if payload["truncated"]:
                summary += (
                    " Results truncated (truncated=true); narrow the path or glob."
                )
        if outcome.hit:
            summary = (
                f"Found {total} matches for {pattern!r} under {where}; "
                f"showing {len(payload['entries'])} within the response budget."
            )
        for event in batch.events:
            if event.get("type") == "summary":
                stats = event["data"]["stats"]
                skipped = [
                    f"{key}={value}"
                    for key, value in stats.items()
                    if (key.endswith("_skipped") or key.startswith("skipped_"))
                    and value
                ]
                if skipped:
                    summary += " Skipped files: " + ", ".join(skipped) + "."
                if stats.get("skipped_oversize"):
                    summary += (
                        f" {stats['skipped_oversize']} file(s) skipped: larger than the per-file limit"
                        " (bounded by the remaining input budget)."
                    )
                for budget in ("input", "output"):
                    if stats.get(f"{budget}_budget_exhausted"):
                        summary += f" Aggregate {budget} budget exhausted."
        return ToolResult(
            content=summary,
            structured_content=payload,
        )

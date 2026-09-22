"""Exact-search event collection, glob filtering and context attachment."""

import time
from pathlib import Path, PurePath

from binnacle.errors import CodedToolError
from binnacle.paths import full_match
from binnacle.search_text_telemetry import ExactSearchMetrics


def clip(text: str, max_chars: int, mark: str) -> str:
    return text[:max_chars] + mark if len(text) > max_chars else text


def matches_glob(file_path: str, root: Path, glob: str | None) -> bool:
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
    except ValueError as exc:
        raise CodedToolError("invalid_glob", f"Invalid glob pattern {glob!r}: {exc}")


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

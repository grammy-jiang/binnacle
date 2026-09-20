"""Replay engines for the search_text adaptive-discovery A/B."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from binnacle.logging_middleware import _compact_json
from binnacle.tools import search_text as st
from scripts.search_text_ab_dataset import HistoricalCase, expand

DEFAULT_DETAILED = 30
DEFAULT_TOTAL = 150
DEFAULT_REPRESENTATIVES = 2
DEFAULT_SNIPPET_CHARS = 180


@dataclass(frozen=True)
class FileFacts:
    count: int
    branches: frozenset[int]
    path_hits: int


def _content_chars(result: Any) -> int:
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return len(content)
    return sum(len(getattr(block, "text", "") or "") for block in (content or []))


def estimate_result(result: Any) -> tuple[int, int]:
    payload = getattr(result, "structured_content", None)
    structured = _compact_json(payload) if payload is not None else ""
    return (
        len(structured.encode("utf-8")),
        (_content_chars(result) + len(structured)) // 4,
    )


def estimate_payload(payload: dict[str, Any], summary: str) -> tuple[int, int]:
    structured = _compact_json(payload)
    return len(structured.encode("utf-8")), (len(summary) + len(structured)) // 4


def search_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "pattern": args["pattern"],
        "path": args["path"],
        "glob": args.get("glob"),
        "fixed_strings": bool(args.get("fixed_strings", False)),
        "context_lines": args.get("context_lines"),
        "names_only": bool(args.get("names_only", False)),
        "max_results": int(args.get("max_results", st.SEARCH_MAX_RESULTS_DEFAULT)),
        "line_numbers": bool(args.get("line_numbers", False)),
    }


def replay_a(case: HistoricalCase) -> dict[str, Any]:
    started = time.perf_counter()
    result = st.search_text_impl(**search_args(case.args))
    elapsed = (time.perf_counter() - started) * 1000
    payload = result.structured_content or {}
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    files = {
        expand(entry["file"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("file"), str)
    }
    structured_bytes, tokens = estimate_result(result)
    return {
        "structured_bytes": structured_bytes,
        "tokens": tokens,
        "duration_ms": round(elapsed, 2),
        "candidate_files": sorted(files),
        "candidate_file_count": len(files),
        "entry_count": len(entries),
        "count": int(payload.get("count", 0)) if isinstance(payload, dict) else 0,
        "truncated": bool(payload.get("truncated", False))
        if isinstance(payload, dict)
        else False,
    }


def split_top_level_alternatives(pattern: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    class_depth = 0
    group_depth = 0

    for char in pattern:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == "[":
            class_depth += 1
        elif char == "]" and class_depth:
            class_depth -= 1
        elif not class_depth and char == "(":
            group_depth += 1
        elif not class_depth and char == ")" and group_depth:
            group_depth -= 1

        if char == "|" and not class_depth and group_depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)

    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts if len(parts) > 1 else [pattern]


def compile_branches(pattern: str, fixed_strings: bool) -> list[re.Pattern[str]]:
    raw = split_top_level_alternatives(pattern)
    flags = 0 if any(char.isupper() for char in pattern) else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    for branch in raw:
        try:
            source = re.escape(branch) if fixed_strings else branch
            compiled.append(re.compile(source, flags))
        except re.error:
            return []
    return compiled


def collect_matches(
    case: HistoricalCase,
) -> tuple[Path, dict[str, list[dict[str, Any]]]]:
    args = search_args(case.args)
    root = st.resolve_path(args["path"])
    events, _ = st._run_rg(root, args["pattern"], args["fixed_strings"], 0)
    files: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in events:
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        file = data.get("path", {}).get("text")
        if not isinstance(file, str) or not st._matches_glob(file, root, args["glob"]):
            continue
        line = data.get("line_number")
        text = data.get("lines", {}).get("text", "").rstrip("\n")
        files[expand(file)].append({"line": line, "text": st._clip(text)})
    return root, dict(files)


def _file_facts(
    files: dict[str, list[dict[str, Any]]], branches: list[re.Pattern[str]]
) -> dict[str, FileFacts]:
    facts: dict[str, FileFacts] = {}
    for file, matches in files.items():
        joined = "\n".join(str(match["text"]) for match in matches)
        covered = frozenset(
            i for i, branch in enumerate(branches) if branch.search(joined)
        )
        path_hits = sum(bool(branch.search(file)) for branch in branches)
        facts[file] = FileFacts(len(matches), covered, path_hits)
    return facts


def rank_files(
    files: dict[str, list[dict[str, Any]]],
    pattern: str,
    fixed_strings: bool = False,
) -> tuple[list[str], dict[str, FileFacts], list[re.Pattern[str]]]:
    branches = compile_branches(pattern, fixed_strings)
    facts = _file_facts(files, branches)
    remaining = set(files)
    ranked: list[str] = []
    covered: set[int] = set()

    while remaining:
        best = max(
            remaining,
            key=lambda file: (
                len(facts[file].branches - covered),
                len(facts[file].branches),
                facts[file].path_hits,
                min(facts[file].count, 50),
                -len(file),
                file,
            ),
        )
        ranked.append(best)
        covered.update(facts[best].branches)
        remaining.remove(best)

    return ranked, facts, branches


def representative_matches(
    matches: list[dict[str, Any]],
    branches: list[re.Pattern[str]],
    limit: int = DEFAULT_REPRESENTATIVES,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> list[dict[str, Any]]:
    if len(matches) <= limit:
        return matches
    if not branches:
        return [matches[0], matches[-1]][:limit]

    branch_sets = [
        {i for i, branch in enumerate(branches) if branch.search(str(match["text"]))}
        for match in matches
    ]
    chosen: list[int] = []
    covered: set[int] = set()
    remaining = set(range(len(matches)))

    while remaining and len(chosen) < limit:
        best = max(
            remaining,
            key=lambda i: (
                len(branch_sets[i] - covered),
                len(branch_sets[i]),
                -i,
            ),
        )
        gained = branch_sets[best] - covered
        chosen.append(best)
        covered.update(branch_sets[best])
        remaining.remove(best)
        if not gained and len(chosen) == 1:
            break

    for index in (0, len(matches) - 1):
        if len(chosen) >= limit:
            break
        if index not in chosen:
            chosen.append(index)

    selected = [dict(matches[index]) for index in sorted(chosen[:limit])]
    for match in selected:
        text = str(match["text"])
        if len(text) > snippet_chars:
            match["text"] = text[:snippet_chars] + "…"
    return selected


def build_b(
    case: HistoricalCase,
    root: Path,
    files: dict[str, list[dict[str, Any]]],
    detailed: int = DEFAULT_DETAILED,
    total_candidates: int = DEFAULT_TOTAL,
    representatives: int = DEFAULT_REPRESENTATIVES,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> dict[str, Any]:
    ranked, facts, branches = rank_files(
        files,
        str(case.args["pattern"]),
        bool(case.args.get("fixed_strings", False)),
    )
    total_matches = sum(len(matches) for matches in files.values())
    detail_files = ranked[:detailed]
    candidate_files = ranked[:total_candidates]

    payload: dict[str, Any] = {
        "path": str(root),
        "pattern": case.args["pattern"],
        "count": total_matches,
        "file_count": len(files),
        "entries": [],
        "more_files": [],
        "truncated": len(ranked) > total_candidates,
        "note": (
            "Broad search summarized by ranked files. Narrow the search to a candidate "
            "file or use read_file for detail."
        ),
    }
    for file in detail_files:
        payload["entries"].append(
            {
                "file": file,
                "count": len(files[file]),
                "matches": representative_matches(
                    files[file], branches, representatives
                ),
            }
        )
    for file in ranked[detailed:total_candidates]:
        payload["more_files"].append({"file": file, "count": len(files[file])})

    summary = (
        f"Found {total_matches} matches in {len(files)} files; showing representative "
        f"matches for {len(detail_files)} files and ranked names/counts for "
        f"{len(candidate_files)} files."
    )
    structured_bytes, tokens = estimate_payload(payload, summary)
    return {
        "structured_bytes": structured_bytes,
        "tokens": tokens,
        "candidate_files": candidate_files,
        "candidate_file_count": len(candidate_files),
        "detailed_files": detail_files,
        "detailed_file_count": len(detail_files),
        "count": total_matches,
        "file_count": len(files),
        "truncated": len(ranked) > total_candidates,
        "ranked_files": ranked,
        "facts": facts,
    }

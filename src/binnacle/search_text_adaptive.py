"""Adaptive file-oriented representation for broad search_text results.

This module never decides whether adaptive discovery should run. The public tool
assembles its ordinary result first and calls here only when that result would
exceed the configured structured-result budget.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson

from binnacle.config import SearchTextSettings

MatchGlob = Callable[[str, Path, str | None], bool]


@dataclass(frozen=True)
class FileFacts:
    count: int
    branches: frozenset[int]
    path_hits: int


@dataclass(frozen=True)
class AdaptiveResult:
    payload: dict[str, Any]
    matching_files: int
    detailed_files: int
    candidate_files: int
    representative_entries: int
    tail_entries: int
    result_bytes: int
    budget_trimmed: bool
    match_events_scanned: int
    glob_checks: int
    glob_rejected: int


@dataclass
class AdaptiveWork:
    match_events_scanned: int = 0
    glob_checks: int = 0
    glob_rejected: int = 0


def _path_hashes(payload: dict[str, Any], *, detailed_only: bool) -> str:
    hashes: list[str] = []
    seen: set[str] = set()
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if detailed_only and "line" not in entry:
            continue
        path = entry.get("file")
        if not isinstance(path, str) or path in seen:
            continue
        seen.add(path)
        hashes.append(hashlib.sha256(path.encode("utf-8")).hexdigest()[:12])
    return ",".join(hashes) or "-"


def log_adaptive_result(
    logger: logging.Logger,
    *,
    call: str,
    trigger_bytes: int,
    total_matches: int,
    result: AdaptiveResult,
    result_budget_bytes: int,
) -> None:
    logger.info(
        "event=search_adaptive_discovery call=%s trigger_bytes=%s "
        "total_matches=%s matching_files=%s detailed_files=%s "
        "candidate_files=%s representative_entries=%s tail_entries=%s "
        "result_bytes=%s result_budget_bytes=%s budget_trimmed=%s "
        "candidate_hashes=%s detailed_hashes=%s",
        call,
        trigger_bytes,
        total_matches,
        result.matching_files,
        result.detailed_files,
        result.candidate_files,
        result.representative_entries,
        result.tail_entries,
        result.result_bytes,
        result_budget_bytes,
        str(result.budget_trimmed).lower(),
        _path_hashes(result.payload, detailed_only=False),
        _path_hashes(result.payload, detailed_only=True),
    )


def structured_bytes(payload: dict[str, Any]) -> int:
    return len(orjson.dumps(payload))


def _split_top_level_alternatives(pattern: str) -> list[str]:
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


def _compile_branches(pattern: str, fixed_strings: bool) -> list[re.Pattern[str]]:
    flags = 0 if any(char.isupper() for char in pattern) else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    branches = [pattern] if fixed_strings else _split_top_level_alternatives(pattern)
    for branch in branches:
        try:
            source = re.escape(branch) if fixed_strings else branch
            compiled.append(re.compile(source, flags))
        except re.error:
            return []
    return compiled


def _collect_files(
    events: list[dict[str, Any]],
    root: Path,
    glob: str | None,
    matches_glob: MatchGlob,
    work: AdaptiveWork | None = None,
) -> dict[str, list[dict[str, Any]]]:
    files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("type") != "match":
            continue
        if work is not None:
            work.match_events_scanned += 1
        data = event.get("data", {})
        path = data.get("path", {}).get("text")
        if not isinstance(path, str):
            continue
        if glob is not None and work is not None:
            work.glob_checks += 1
        if not matches_glob(path, root, glob):
            if glob is not None and work is not None:
                work.glob_rejected += 1
            continue
        line = data.get("line_number")
        if not isinstance(line, int):
            continue
        text = data.get("lines", {}).get("text", "").rstrip("\n")
        files[path].append({"file": path, "line": line, "text": text})
    return dict(files)


def _file_facts(
    files: dict[str, list[dict[str, Any]]],
    branches: list[re.Pattern[str]],
) -> dict[str, FileFacts]:
    facts: dict[str, FileFacts] = {}
    for path, matches in files.items():
        joined = "\n".join(str(match["text"]) for match in matches)
        covered = frozenset(
            index for index, branch in enumerate(branches) if branch.search(joined)
        )
        path_hits = sum(bool(branch.search(path)) for branch in branches)
        facts[path] = FileFacts(
            count=len(matches),
            branches=covered,
            path_hits=path_hits,
        )
    return facts


def _rank_files(
    files: dict[str, list[dict[str, Any]]],
    pattern: str,
    fixed_strings: bool,
) -> tuple[list[str], dict[str, FileFacts], list[re.Pattern[str]]]:
    branches = _compile_branches(pattern, fixed_strings)
    facts = _file_facts(files, branches)
    remaining = set(files)
    ranked: list[str] = []
    covered: set[int] = set()

    while remaining:
        best = min(
            remaining,
            key=lambda path: (
                -len(facts[path].branches - covered),
                -len(facts[path].branches),
                -facts[path].path_hits,
                -min(facts[path].count, 50),
                path,
            ),
        )
        ranked.append(best)
        covered.update(facts[best].branches)
        remaining.remove(best)

    return ranked, facts, branches


def _representative_matches(
    matches: list[dict[str, Any]],
    branches: list[re.Pattern[str]],
    *,
    limit: int,
    snippet_chars: int,
) -> list[dict[str, Any]]:
    if not matches or limit <= 0:
        return []

    branch_sets = [
        {
            index
            for index, branch in enumerate(branches)
            if branch.search(str(match["text"]))
        }
        for match in matches
    ]
    chosen: list[int] = []
    covered: set[int] = set()
    remaining = set(range(len(matches)))

    while remaining and len(chosen) < limit:
        best = min(
            remaining,
            key=lambda index: (
                -len(branch_sets[index] - covered),
                -len(branch_sets[index]),
                index,
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

    output: list[dict[str, Any]] = []
    for index in sorted(chosen[:limit]):
        match = dict(matches[index])
        text = str(match["text"])
        if len(text) > snippet_chars:
            match["text"] = text[:snippet_chars] + "…"
        output.append(match)
    return output


def _budget_note(
    *,
    returned_entries: int,
    returned_files: int,
    matching_files: int,
) -> str:
    return (
        "Adaptive discovery response budget reached; showing "
        f"{returned_entries} ranked entries across {returned_files} files from "
        f"{matching_files} matching files. Narrow pattern/path/glob or use read_file."
    )


def _fit_budget(
    payload: dict[str, Any],
    *,
    max_bytes: int,
    matching_files: int,
) -> tuple[dict[str, Any], bool] | None:
    if structured_bytes(payload) <= max_bytes:
        return payload, False

    entries = list(payload.get("entries", []))
    base = {
        key: value for key, value in payload.items() if key not in {"entries", "note"}
    }
    base["truncated"] = True

    def candidate(size: int) -> dict[str, Any]:
        prefix = entries[:size]
        returned_files = len(
            {
                entry.get("file")
                for entry in prefix
                if isinstance(entry, dict) and isinstance(entry.get("file"), str)
            }
        )
        return {
            **base,
            "entries": prefix,
            "note": _budget_note(
                returned_entries=size,
                returned_files=returned_files,
                matching_files=matching_files,
            ),
        }

    low = 0
    high = len(entries)
    while low < high:
        middle = (low + high + 1) // 2
        if structured_bytes(candidate(middle)) <= max_bytes:
            low = middle
        else:
            high = middle - 1

    fitted = candidate(low)
    if low == 0 or structured_bytes(fitted) > max_bytes:
        return None
    return fitted, True


def build_adaptive_result(
    events: list[dict[str, Any]],
    *,
    root: Path,
    pattern: str,
    glob: str | None,
    fixed_strings: bool,
    max_match_entries: int,
    settings: SearchTextSettings,
    matches_glob: MatchGlob,
    result_max_bytes: int,
) -> AdaptiveResult | None:
    work = AdaptiveWork()
    files = _collect_files(events, root, glob, matches_glob, work)
    if not files:
        return None

    ranked, facts, branches = _rank_files(files, pattern, fixed_strings)
    candidate_paths = ranked[: settings.adaptive_total_files]
    detailed_paths = candidate_paths[: settings.adaptive_detailed_files]

    entries: list[dict[str, Any]] = []
    match_budget = max_match_entries
    detailed_returned: set[str] = set()

    for path in detailed_paths:
        if match_budget <= 0:
            break
        representatives = _representative_matches(
            files[path],
            branches,
            limit=min(settings.adaptive_representative_matches, match_budget),
            snippet_chars=settings.adaptive_snippet_chars,
        )
        for representative in representatives:
            entries.append({**representative, "count": facts[path].count})
            match_budget -= 1
        if representatives:
            detailed_returned.add(path)

    for path in candidate_paths:
        if path not in detailed_returned:
            entries.append({"file": path, "count": facts[path].count})

    total_matches = sum(fact.count for fact in facts.values())
    payload: dict[str, Any] = {
        "path": str(root),
        "pattern": pattern,
        "entries": entries,
        "count": total_matches,
        "truncated": True,
        "note": (
            f"Adaptive discovery for {total_matches} matches across {len(files)} files: "
            f"representative matches for {len(detailed_returned)} ranked files plus "
            f"file/count summaries up to {len(candidate_paths)} candidates. "
            "Narrow pattern/path/glob or use read_file for detail."
        ),
    }

    fitted = _fit_budget(
        payload,
        max_bytes=result_max_bytes,
        matching_files=len(files),
    )
    if fitted is None:
        return None
    final_payload, budget_trimmed = fitted

    final_entries = final_payload.get("entries", [])
    representative_entries = sum(
        isinstance(entry, dict) and "line" in entry for entry in final_entries
    )
    tail_entries = sum(
        isinstance(entry, dict) and "line" not in entry for entry in final_entries
    )
    detailed_files = len(
        {
            entry.get("file")
            for entry in final_entries
            if isinstance(entry, dict)
            and "line" in entry
            and isinstance(entry.get("file"), str)
        }
    )
    candidate_files = len(
        {
            entry.get("file")
            for entry in final_entries
            if isinstance(entry, dict) and isinstance(entry.get("file"), str)
        }
    )

    return AdaptiveResult(
        payload=final_payload,
        matching_files=len(files),
        detailed_files=detailed_files,
        candidate_files=candidate_files,
        representative_entries=representative_entries,
        tail_entries=tail_entries,
        result_bytes=structured_bytes(final_payload),
        budget_trimmed=budget_trimmed,
        match_events_scanned=work.match_events_scanned,
        glob_checks=work.glob_checks,
        glob_rejected=work.glob_rejected,
    )

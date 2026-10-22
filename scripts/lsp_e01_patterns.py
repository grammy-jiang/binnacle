"""Cautious E0/E1 lexical labels and bounded request-group windows.

These do not prove task intent, causal savings, model steps or complete evidence.
"""

from __future__ import annotations

import collections
import re
from typing import Any

LABELS = (
    "git_read",
    "git_change",
    "text_search",
    "code_structure_query",
    "source_read_shell",
    "test",
    "lint_typecheck",
)
SHELL_START = r"(?:^|[;&|\n()])\s*"
RUNNER = r"(?:(?:uv|poetry|pipenv)\s+run(?:\s+--[\w-]+)*\s+)?"
PYTHON = r"(?:(?:[^\s'\";|&()]*/)?python(?:3(?:\.\d+)?)?\s+-m\s+)?"
BIN = r"(?:[^\s'\";|&()]*/)?"
PATTERNS = {
    "git_read": re.compile(
        SHELL_START
        + BIN
        + r"git\s+(?:-C\s+\S+\s+)?"
        + r"(?:status|log|show|diff|blame|grep|ls-files|rev-parse)\b"
    ),
    "git_change": re.compile(
        SHELL_START + BIN + r"git\s+(?:-C\s+\S+\s+)?(?:diff|show|blame)\b"
    ),
    "text_search": re.compile(SHELL_START + BIN + r"(?:rg|grep|ag)\s"),
    "source_read_shell": re.compile(SHELL_START + BIN + r"(?:cat|sed|head|tail|nl)\s"),
    "test": re.compile(
        SHELL_START
        + RUNNER
        + PYTHON
        + r"(?:pytest|tox|unittest|cargo\s+test|go\s+test|npm\s+test)\b"
    ),
    "lint_typecheck": re.compile(
        SHELL_START + RUNNER + PYTHON + r"(?:ruff|pyright|mypy|pylint|eslint|tsc)\b"
    ),
    "code_structure_query": re.compile(
        r"\b(?:def|class|fn|function|interface|struct|enum|impl|override)\b"
    ),
}
EXACT_TURN = re.compile(r"^wfr_[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")
REDACTED = ("[redacted]", "<redacted>", "***")
INCOMPLETE = ("[truncated]", "[redacted]", "<redacted>")
WINDOWS = (
    "search_then_read",
    "symbol_query_then_read",
    "git_change_then_inspect",
    "git_change_inspect_then_test",
    "lint_then_inspect",
    "failed_test_then_inspect",
)
SCAN_MAX_ACTIONS = 5
SCAN_MAX_SECONDS = 300
IMPACT_MAX_ACTIONS = 10
IMPACT_MAX_SECONDS = 900


def _label(tool: str, arguments: Any) -> tuple[frozenset[str], str]:
    if not isinstance(arguments, dict):
        return frozenset(), "missing"
    if tool in ("run_command", "search_text"):
        key = "command" if tool == "run_command" else "pattern"
        text = arguments.get(key)
        if not isinstance(text, str):
            # Search intent is visible as a tool name even when pattern is absent.
            return (
                frozenset({"text_search"}) if tool == "search_text" else frozenset()
            ), "missing"
        value = text.strip().casefold()
        if value in REDACTED:
            return (
                frozenset({"text_search"}) if tool == "search_text" else frozenset()
            ), "redacted"
        if any(marker in value for marker in INCOMPLETE):
            return (
                frozenset({"text_search"}) if tool == "search_text" else frozenset()
            ), "incomplete"
        if tool == "search_text":
            selected_names = {"text_search"}
            if PATTERNS["code_structure_query"].search(text):
                selected_names.add("code_structure_query")
            return frozenset(selected_names), "present"
        names = frozenset(k for k, rx in PATTERNS.items() if rx.search(text))
        if "code_structure_query" in names and "text_search" not in names:
            names = names - {"code_structure_query"}
        return names, "present"
    return frozenset(), "not_applicable"


def _windows(
    calls: list[Any],
    observed: list[Any],
    excluded_groups: set[tuple[str, str]] | None = None,
) -> dict[str, dict[str, int]]:
    eligible = {call.key for call in calls}
    by_group: dict[tuple[str, str], list[Any]] = collections.defaultdict(list)
    unorderable_groups: set[tuple[str, str]] = set(excluded_groups or ())
    # Every observed call consumes an action slot, even when unpaired.
    # A missing timestamp prevents a defensible ordering for its entire
    # request group; it must not silently collapse the five/ten-call bound.
    for call in observed:
        if call.group is None:
            continue
        if call.when is None:
            unorderable_groups.add(call.group)
        else:
            by_group[call.group].append(call)
    windows: collections.Counter[str] = collections.Counter()
    groups: dict[str, set] = collections.defaultdict(set)
    for group, ordered in by_group.items():
        if group in unorderable_groups:
            continue
        ordered.sort(key=lambda c: (c.when, c.key))
        for i, first in enumerate(ordered):
            if first.key not in eligible:
                continue
            # A shared timestamp has no defensible ordering.
            near = [
                c
                for c in ordered[i + 1 : i + 1 + SCAN_MAX_ACTIONS]
                if c.key in eligible
                and first.when < c.when <= first.when + SCAN_MAX_SECONDS
            ]
            wider = [
                c
                for c in ordered[i + 1 : i + 1 + IMPACT_MAX_ACTIONS]
                if c.key in eligible
                and first.when < c.when <= first.when + IMPACT_MAX_SECONDS
            ]
            found = []
            if first.tool == "search_text" and any(c.tool == "read_file" for c in near):
                found.append("search_then_read")
            if "code_structure_query" in first.categories and any(
                c.tool == "read_file" for c in near
            ):
                found.append("symbol_query_then_read")
            if "git_change" in first.categories:
                inspect = next(
                    (c for c in wider if c.tool in ("read_file", "search_text")),
                    None,
                )
                if inspect is not None:
                    found.append("git_change_then_inspect")
                    if any(
                        "test" in c.categories and c.when > inspect.when for c in wider
                    ):
                        found.append("git_change_inspect_then_test")
            if "lint_typecheck" in first.categories and any(
                c.tool in ("read_file", "search_text") for c in near
            ):
                found.append("lint_then_inspect")
            if (
                "test" in first.categories
                and (
                    first.status == "error"
                    or (first.result_exit is not None and first.result_exit != 0)
                )
                and first.end_when is not None
                and any(
                    c.tool in ("read_file", "search_text") and c.when > first.end_when
                    for c in near
                )
            ):
                found.append("failed_test_then_inspect")
            for label in found:
                windows[label] += 1
                groups[label].add(group)
    return {
        label: {
            "windows": windows[label],
            "distinct_request_groups": len(groups[label]),
        }
        for label in WINDOWS
    }

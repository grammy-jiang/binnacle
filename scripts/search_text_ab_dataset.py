"""Historical journal dataset for the search_text adaptive-discovery A/B."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REAL_EVENT = re.compile(r"\b(?:INFO|WARNING|ERROR): event=([a-zA-Z0-9_]+)\b")
FIELD = r"(?:^|\s){key}=([^\s]+)"
DEFAULT_HORIZON = 10


@dataclass(frozen=True)
class HistoricalCase:
    call: str
    turn: str | None
    args: dict[str, Any]
    historical_tokens: int
    evidence_files: tuple[str, ...]


def event_name(line: str) -> str | None:
    match = REAL_EVENT.search(line)
    return match.group(1) if match else None


def field(line: str, key: str) -> str | None:
    match = re.search(FIELD.format(key=re.escape(key)), line)
    return match.group(1) if match else None


def arguments(line: str) -> dict[str, Any] | None:
    marker = " args="
    if marker not in line:
        return None
    try:
        value = json.loads(line.split(marker, 1)[1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def expand(path: str) -> str:
    return str(Path(os.path.expanduser(path)).resolve())


def tool_events(
    log_text: str,
) -> tuple[list[dict[str, Any]], dict[str, int], set[str]]:
    calls: list[dict[str, Any]] = []
    result_tokens: dict[str, int] = {}
    budget_hits: set[str] = set()

    for line in log_text.splitlines():
        event = event_name(line)
        if event == "tool_call":
            call = field(line, "call")
            tool = field(line, "tool")
            if call and tool:
                calls.append(
                    {
                        "call": call,
                        "tool": tool,
                        "turn": (field(line, "turn") or "").split("/", 1)[0] or None,
                        "args": arguments(line) or {},
                    }
                )
        elif event == "tool_result":
            call = field(line, "call")
            tokens = field(line, "est_tokens")
            if call and tokens and tokens.isdigit():
                result_tokens[call] = int(tokens)
        elif event == "search_budget_hit":
            call = field(line, "call")
            if call:
                budget_hits.add(call)

    return calls, result_tokens, budget_hits


def _followup_evidence(
    origin: dict[str, Any],
    by_turn: dict[str, list[dict[str, Any]]],
    *,
    horizon: int,
) -> set[str]:
    turn = origin["turn"]
    if not turn:
        return set()
    turn_calls = by_turn[turn]
    try:
        pos = next(
            i for i, call in enumerate(turn_calls) if call["call"] == origin["call"]
        )
    except StopIteration:
        return set()

    evidence: set[str] = set()
    for follow in turn_calls[pos + 1 : pos + 1 + horizon]:
        follow_path = follow["args"].get("path")
        if not isinstance(follow_path, str):
            continue
        if follow["tool"] == "read_file":
            evidence.add(expand(follow_path))
        elif follow["tool"] == "search_text":
            candidate = Path(os.path.expanduser(follow_path))
            try:
                if candidate.is_file():
                    evidence.add(str(candidate.resolve()))
            except OSError:
                continue
    return evidence


def extract_cases(
    log_text: str, horizon: int = DEFAULT_HORIZON
) -> list[HistoricalCase]:
    calls, result_tokens, budget_hits = tool_events(log_text)
    call_by_id = {call["call"]: call for call in calls}
    by_turn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        if call["turn"]:
            by_turn[call["turn"]].append(call)

    cases: list[HistoricalCase] = []
    for call_id in sorted(budget_hits):
        origin = call_by_id.get(call_id)
        if not origin or origin["tool"] != "search_text":
            continue
        args = origin["args"]
        pattern = args.get("pattern")
        path = args.get("path")
        if not isinstance(pattern, str) or not isinstance(path, str):
            continue
        if pattern.startswith("@context ") or args.get("names_only", False):
            continue

        cases.append(
            HistoricalCase(
                call=call_id,
                turn=origin["turn"],
                args=args,
                historical_tokens=result_tokens.get(call_id, 0),
                evidence_files=tuple(
                    sorted(_followup_evidence(origin, by_turn, horizon=horizon))
                ),
            )
        )
    return cases


def median_search_or_read_tokens(log_text: str) -> float:
    calls, result_tokens, _ = tool_events(log_text)
    call_tools = {call["call"]: call["tool"] for call in calls}
    values = [
        tokens
        for call_id, tokens in result_tokens.items()
        if call_tools.get(call_id) in {"search_text", "read_file"}
    ]
    if not values:
        return 0.0
    values.sort()
    middle = len(values) // 2
    if len(values) % 2:
        return float(values[middle])
    return (values[middle - 1] + values[middle]) / 2

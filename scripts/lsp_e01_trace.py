"""E0/E1: read-only, privacy-safe analysis of host-local MCP capture history.

This module NEVER executes stored commands or emits source text, paths, identifiers,
hashes of private contents, or original tool results. Historical opportunities are
not model-step savings, causal A/B evidence, or reconstructed task gold.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Standalone python scripts/lsp_e01_trace.py and package import both work.
if __package__:
    from .lsp_e01_observer import _observer
    from .lsp_e01_patterns import EXACT_TURN, LABELS, _label, _windows
else:
    from lsp_e01_observer import _observer
    from lsp_e01_patterns import EXACT_TURN, LABELS, _label, _windows

TOOLS = frozenset(
    {
        "run_command",
        "job_status",
        "stop_job",
        "search_text",
        "read_file",
        "list_files",
        "edit_file",
        "write_file",
    }
)


def _digest(value: Any) -> str:
    # Quarantine invalid/unencodable historical JSON instead of mis-pairing it.
    try:
        wire = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid private JSON payload") from exc
    return hashlib.sha256(wire).hexdigest()


def _time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        )
        if parsed.tzinfo is None:
            return None
        when = parsed.astimezone(dt.timezone.utc)
        # Verify the numerical time is representable before downstream
        # sequencing; extreme timezone offsets may overflow at year 1/9999.
        when.timestamp()
        return when
    except (ValueError, OverflowError):
        return None


def _stamp(value: Any) -> float | None:
    parsed = _time(value)
    return parsed.timestamp() if parsed is not None else None


def _request_key(corr: dict) -> tuple[str, tuple[str, str | int]] | None:
    session = corr.get("session")
    request = corr.get("request_id")
    if not isinstance(session, str) or not session:
        return None
    if type(request) is int:
        return session, ("int", request)
    if isinstance(request, str) and request:
        return session, ("str", request)
    return None


def _tool(value: Any) -> str:
    return value if isinstance(value, str) and value in TOOLS else "other"


@dataclass
class Call:
    key: tuple[str, str]
    tool: str
    when: float | None
    group: tuple[str, str] | None
    join_source: str
    request_key: tuple[str, tuple[str, str | int]] | None
    raw_tool_name: str
    arguments_sha: str
    categories: frozenset[str]
    raw_state: str
    status: str = "unfinished"
    end_when: float | None = None
    result_truncated: bool = False
    result_exit: int | None = None


@dataclass
class Corpus:
    calls: dict[tuple[str, str], Call] = field(default_factory=dict)
    requests: dict[tuple[str, tuple[str, str | int]], tuple[str, str]] = field(
        default_factory=dict
    )
    terminals: dict[
        tuple[str, str], list[tuple[str, bool, int | None, float | None]]
    ] = field(default_factory=lambda: collections.defaultdict(list))
    duplicate_calls: set[tuple[str, str]] = field(default_factory=set)
    duplicate_requests: set[tuple[str, str]] = field(default_factory=set)
    duplicate_terminals: set[tuple[str, str]] = field(default_factory=set)
    counts: collections.Counter = field(default_factory=collections.Counter)
    events: collections.Counter = field(default_factory=collections.Counter)
    days: collections.Counter = field(default_factory=collections.Counter)
    unorderable_groups: set[tuple[str, str]] = field(default_factory=set)


def _group_for_call(key: tuple[str, str], corr: dict, observer: dict, ambiguous: set):
    if key in ambiguous:
        return None, "ambiguous_observer"
    if key in observer:
        return ("observer", observer[key]), "observer"
    turn = corr.get("turn")
    if isinstance(turn, str) and EXACT_TURN.fullmatch(turn):
        return ("header_turn", turn.split("/", 1)[0]), "header_turn"
    return None, "unattributed"


def _events(
    root: Path,
    corpus: Corpus,
    observer: dict,
    ambiguous: set,
    until_utc: dt.datetime | None = None,
) -> None:
    for path in sorted(root.glob("*.jsonl")):
        if not path.is_file() or path.is_symlink():
            corpus.counts["unsafe_or_missing_file"] += 1
            continue
        corpus.counts["files"] += 1
        # The active final JSONL row may still be written. Never guess it.
        with path.open("rb") as stream:
            for line in stream:
                corpus.counts["rows"] += 1
                if not line.endswith(b"\n"):
                    corpus.counts["incomplete_lines"] += 1
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    corpus.counts["invalid_json"] += 1
                    continue
                if not isinstance(data, dict):
                    corpus.counts["invalid_record_shape"] += 1
                    continue
                event = data.get("event")
                if not isinstance(event, str):
                    corpus.counts["invalid_record_shape"] += 1
                    continue
                if event not in {
                    "mcp_request",
                    "mcp_response",
                    "mcp_error",
                    "tool_call",
                    "tool_result",
                    "tool_error",
                }:
                    corpus.events["other"] += 1
                    continue
                when = _time(data.get("timestamp"))
                if until_utc is not None:
                    if when is None:
                        corpus.counts["unknown_timestamp_excluded"] += 1
                        if event == "tool_call":
                            corr = data.get("correlation")
                            if isinstance(corr, dict):
                                gen, call = corr.get("server_gen"), corr.get("call")
                                if all(isinstance(x, str) and x for x in (gen, call)):
                                    group, _ = _group_for_call(
                                        (gen, call), corr, observer, ambiguous
                                    )
                                    if group is not None:
                                        corpus.unorderable_groups.add(group)
                        continue
                    if when >= until_utc:
                        corpus.counts["after_cutoff_excluded"] += 1
                        continue
                corpus.events[event] += 1
                corpus.counts["included_rows"] += 1
                if when is not None:
                    corpus.days[when.date().isoformat()] += 1
                corr = data.get("correlation")
                if not isinstance(corr, dict):
                    corr = {}
                req_key = _request_key(corr)
                if event == "mcp_request" and data.get("method") == "tools/call":
                    params = data.get("payload")
                    if not isinstance(params, dict) or not isinstance(
                        params.get("name"), str
                    ):
                        corpus.counts["invalid_request_payload"] += 1
                        continue
                    if req_key is None:
                        corpus.counts["requests_without_identity"] += 1
                        continue
                    try:
                        candidate = (params["name"], _digest(params.get("arguments")))
                    except ValueError:
                        corpus.counts["invalid_request_payload"] += 1
                        continue
                    if req_key in corpus.requests:
                        corpus.duplicate_requests.add(req_key)
                    else:
                        corpus.requests[req_key] = candidate
                elif event == "tool_call":
                    gen, call = corr.get("server_gen"), corr.get("call")
                    if not all(isinstance(x, str) and x for x in (gen, call)):
                        corpus.counts["calls_without_identity"] += 1
                        continue
                    key = (gen, call)
                    if key in corpus.calls:
                        corpus.duplicate_calls.add(key)
                        continue
                    raw_name = data.get("tool_name") or corr.get("tool")
                    if not isinstance(raw_name, str):
                        corpus.counts["invalid_tool_call_payload"] += 1
                        continue
                    args = data.get("arguments")
                    try:
                        digest = _digest(args)
                    except ValueError:
                        corpus.counts["invalid_tool_call_payload"] += 1
                        continue
                    group, source = _group_for_call(key, corr, observer, ambiguous)
                    name = _tool(raw_name)
                    categories, state = _label(name, args)
                    corpus.calls[key] = Call(
                        key,
                        name,
                        when.timestamp() if when else None,
                        group,
                        source,
                        req_key,
                        raw_name,
                        digest,
                        categories,
                        state,
                    )
                elif event in ("tool_result", "tool_error"):
                    gen, call = corr.get("server_gen"), corr.get("call")
                    if not all(isinstance(x, str) and x for x in (gen, call)):
                        corpus.counts["terminals_without_identity"] += 1
                        continue
                    if event == "tool_error":
                        outcome, clipped, exit_code = "error", False, None
                    else:
                        result = data.get("result")
                        if not isinstance(result, dict):
                            outcome, clipped, exit_code = "invalid_result", False, None
                        else:
                            outcome = (
                                "error" if result.get("is_error") is True else "result"
                            )
                            structured = result.get("structured_content")
                            clipped = (
                                isinstance(structured, dict)
                                and structured.get("truncated") is True
                            )
                            code = (
                                structured.get("exit_code")
                                if isinstance(structured, dict)
                                else None
                            )
                            exit_code = code if type(code) is int else None
                    corpus.terminals[(gen, call)].append(
                        (
                            outcome,
                            clipped,
                            exit_code,
                            when.timestamp() if when else None,
                        )
                    )


def _resolve_terminals(corpus: Corpus) -> None:
    for key, terminals in corpus.terminals.items():
        call = corpus.calls.get(key)
        if call is None:
            corpus.counts["orphan_terminals"] += len(terminals)
            continue
        if len(terminals) != 1:
            corpus.duplicate_terminals.add(key)
            call.status = "ambiguous_terminal"
            continue
        call.status, call.result_truncated, call.result_exit, call.end_when = terminals[
            0
        ]
        if (
            call.when is not None
            and call.end_when is not None
            and call.end_when < call.when
        ):
            call.status = "invalid_chronology"
            corpus.counts["negative_duration_terminals"] += 1


def analyze(
    capture_dir: Path,
    observer_db: Path | None = None,
    until_utc: dt.datetime | None = None,
) -> dict:
    """Return aggregate-only E0/E1 evidence. No raw content is returned."""
    mapping, ambiguous = _observer(observer_db)
    corpus = Corpus()
    _events(capture_dir, corpus, mapping, ambiguous, until_utc)
    _resolve_terminals(corpus)
    tools = collections.Counter()
    labels = collections.Counter()
    group_sources = collections.Counter()
    input_states = collections.Counter()
    outcomes = collections.Counter()
    truncation = collections.Counter()
    coupled = collections.Counter()
    safe: list[Call] = []
    for key, call in corpus.calls.items():
        tools[call.tool] += 1
        input_states[f"{call.tool}:{call.raw_state}"] += 1
        outcomes[call.status] += 1
        if call.result_truncated:
            truncation[call.tool] += 1
        if key in corpus.duplicate_calls or key in corpus.duplicate_terminals:
            group_sources["duplicate_excluded"] += 1
            continue
        req = corpus.requests.get(call.request_key) if call.request_key else None
        if call.request_key is None:
            coupled["missing_identity"] += 1
        elif call.request_key in corpus.duplicate_requests:
            coupled["ambiguous_request"] += 1
        elif req is None:
            coupled["missing_request"] += 1
        elif req != (call.raw_tool_name, call.arguments_sha):
            coupled["request_mismatch"] += 1
        else:
            coupled["exact_argument_match"] += 1
            if call.status in (
                "invalid_chronology",
                "ambiguous_terminal",
                "invalid_result",
            ):
                group_sources["excluded_unreliable_outcome"] += 1
                continue
            safe.append(call)
            group_sources[call.join_source] += 1
            for name in call.categories:
                if name in LABELS:
                    labels[name] += 1
            continue
        # Unpaired calls are counted for coverage but must not enter
        # request-group sequences or confident candidate classifications.
        group_sources["excluded_unpaired"] += 1
    distinct_groups = len({c.group for c in safe if c.group is not None})
    return {
        "schema": "binnacle-development-intelligence-e01/1",
        "evidence": "retrospective_candidates_not_measured_savings",
        "privacy": "aggregate_only_no_source_or_command_content",
        "coverage": {
            "records": corpus.counts["rows"],
            "included_rows": corpus.counts["included_rows"],
            "after_cutoff_excluded": corpus.counts["after_cutoff_excluded"],
            "unknown_timestamp_excluded": corpus.counts["unknown_timestamp_excluded"],
            "until_utc": until_utc.isoformat() if until_utc else None,
            "files": corpus.counts["files"],
            "days_utc": dict(sorted(corpus.days.items())),
            "invalid_json": corpus.counts["invalid_json"],
            "incomplete_lines": corpus.counts["incomplete_lines"],
            "unrecognized_rows": corpus.events["other"],
            "invalid_record_shape": corpus.counts["invalid_record_shape"],
            "invalid_request_payload": corpus.counts["invalid_request_payload"],
            "invalid_tool_call_payload": corpus.counts["invalid_tool_call_payload"],
            "orphan_terminals": corpus.counts["orphan_terminals"],
        },
        "event_counts": dict(sorted(corpus.events.items())),
        "calls": {
            "total": len(corpus.calls),
            "tools": dict(sorted(tools.items())),
            "outcomes": dict(sorted(outcomes.items())),
            "input_states": dict(sorted(input_states.items())),
            "returned_truncated": dict(sorted(truncation.items())),
            "duplicate_calls_excluded": len(corpus.duplicate_calls),
            "duplicate_terminals_excluded": len(corpus.duplicate_terminals),
            "negative_duration_terminals": corpus.counts["negative_duration_terminals"],
        },
        "request_pairing": dict(sorted(coupled.items())),
        "grouping": {
            "exactly_grouped_calls": sum(c.group is not None for c in safe),
            "distinct_request_groups": distinct_groups,
            "source_counts": dict(sorted(group_sources.items())),
            "ambiguous_observer_keys": len(ambiguous),
            "groups_excluded_missing_timestamp": len(
                corpus.unorderable_groups
                | {
                    call.group
                    for call in corpus.calls.values()
                    if call.group is not None and call.when is None
                }
            ),
        },
        "candidate_command_labels_nonexclusive": dict(sorted(labels.items())),
        "opportunity_windows": _windows(
            safe, list(corpus.calls.values()), corpus.unorderable_groups
        ),
        "interpretation_limits": [
            "group_is_not_verified_development_task",
            "regex_label_is_not_verified_intent",
            "windows_overlap_and_are_not_saved_agent_steps",
            "action_budgets_count_all_observed_calls_including_unpaired",
            "groups_with_unorderable_calls_excluded_from_windows",
            "window_is_call_start_evidence_not_verified_task_completion",
            "no_prompt_or_model_token_evidence",
            "historic_commands_never_executed",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--observer-db", type=Path)
    parser.add_argument(
        "--until-utc", help="Exclusive frozen UTC timestamp; Z or offset accepted"
    )
    args = parser.parse_args()
    cutoff = _time(args.until_utc) if args.until_utc else None
    if args.until_utc and cutoff is None:
        parser.error("invalid UTC cutoff")
    if not args.capture_dir.is_dir():
        parser.error("capture directory missing")
    # JSON is restricted to authored, non-content keys and aggregate counts.
    try:
        result = analyze(args.capture_dir, args.observer_db, until_utc=cutoff)
    except (OSError, sqlite3.Error, ValueError, UnicodeError) as exc:
        # Never print private path, command, raw result or SQLite error text.
        print(f"E01_ANALYSIS_FAILED:{type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

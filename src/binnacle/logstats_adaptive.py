"""Adaptive search discovery pilot analysis for binnacle stats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from binnacle.logstats_models import AdaptiveDiscoveryStats, Record


def analyze_adaptive_discovery(records: list[Record]) -> AdaptiveDiscoveryStats:
    """Join adaptive broad-search first hops to the next ten calls in the turn.

    Imports shared journal helpers lazily so binnacle.logstats can import this
    analyzer without creating a module-import cycle.
    """
    from binnacle.logstats import (
        _base_turn,
        _int,
        _json_args,
        _path_hash,
        plain_fields,
    )

    out = AdaptiveDiscoveryStats()
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, str]] = {}
    dispatch: dict[str, str] = {}
    adaptive: list[tuple[int, dict[str, str]]] = []

    for seq, record in enumerate(records):
        if record.event == "tool_call":
            fields = plain_fields(record.body)
            call = fields.get("call")
            if call:
                calls[call] = {
                    "seq": seq,
                    "tool": fields.get("tool", "?"),
                    "turn": _base_turn(fields.get("turn")),
                    "args": _json_args(record.body),
                }
        elif record.event == "tool_result":
            fields = plain_fields(record.body)
            if fields.get("call"):
                results[fields["call"]] = fields
        elif record.event == "search_dispatch":
            fields = plain_fields(record.body)
            if fields.get("call"):
                dispatch[fields["call"]] = fields.get("mode", "unknown")
        elif record.event == "search_adaptive_discovery":
            adaptive.append((seq, plain_fields(record.body)))

    ordered = sorted(calls.items(), key=lambda item: item[1]["seq"])
    for seq, fields in adaptive:
        call_id = fields.get("call", "-")
        origin = calls.get(call_id, {})
        turn = origin.get("turn", "-")
        later_in_turn = [
            (cid, call)
            for cid, call in ordered
            if call["seq"] > seq and call["turn"] == turn and cid != call_id
        ][:10]
        followups = [
            item
            for item in later_in_turn
            if item[1]["tool"] in {"search_text", "read_file", "list_files"}
        ]
        exact = [
            item
            for item in followups
            if item[1]["tool"] == "search_text" and dispatch.get(item[0]) == "exact"
        ]
        reads = [item for item in followups if item[1]["tool"] == "read_file"]
        candidate = _hash_set(fields.get("candidate_hashes"))
        detailed = _hash_set(fields.get("detailed_hashes"))

        def path_hash(call: dict[str, Any]) -> str | None:
            path = call["args"].get("path")
            return _path_hash(path) if isinstance(path, str) else None

        candidate_reads = sum(path_hash(call) in candidate for _, call in reads)
        detailed_reads = sum(path_hash(call) in detailed for _, call in reads)
        candidate_searches = sum(
            _is_file_scoped(call) and path_hash(call) in candidate for _, call in exact
        )
        detailed_searches = sum(
            _is_file_scoped(call) and path_hash(call) in detailed for _, call in exact
        )
        follow_tokens = sum(
            _int(results.get(cid, {}).get("est_tokens")) for cid, _ in followups
        )
        result_tokens = _int(results.get(call_id, {}).get("est_tokens"))
        row = {
            "call": call_id,
            "turn": turn,
            "result_tokens": result_tokens,
            "trigger_bytes": _int(fields.get("trigger_bytes")),
            "result_bytes": _int(fields.get("result_bytes")),
            "total_matches": _int(fields.get("total_matches")),
            "matching_files": _int(fields.get("matching_files")),
            "detailed_files": _int(fields.get("detailed_files")),
            "candidate_files": _int(fields.get("candidate_files")),
            "representative_entries": _int(fields.get("representative_entries")),
            "tail_entries": _int(fields.get("tail_entries")),
            "budget_trimmed": fields.get("budget_trimmed") == "true",
            "followup_calls": len(followups),
            "followup_exact_searches": len(exact),
            "followup_reads": len(reads),
            "followup_result_tokens": follow_tokens,
            "investigation_result_tokens": result_tokens + follow_tokens,
            "candidate_reads": candidate_reads,
            "candidate_file_searches": candidate_searches,
            "detailed_reads": detailed_reads,
            "detailed_file_searches": detailed_searches,
        }
        _accumulate(out, row)

    return out


def _hash_set(value: str | None) -> set[str]:
    return {item for item in (value or "").split(",") if item and item != "-"}


def _is_file_scoped(call: dict[str, Any]) -> bool:
    path = call["args"].get("path")
    return isinstance(path, str) and Path(path).suffix != ""


def _accumulate(out: AdaptiveDiscoveryStats, row: dict[str, Any]) -> None:
    out.calls += 1
    out.budget_trimmed += int(row["budget_trimmed"])
    out.candidate_opened += int(
        bool(row["candidate_reads"] or row["candidate_file_searches"])
    )
    out.detailed_opened += int(
        bool(row["detailed_reads"] or row["detailed_file_searches"])
    )
    out.candidate_reads += int(row["candidate_reads"])
    out.candidate_file_searches += int(row["candidate_file_searches"])
    out.detailed_reads += int(row["detailed_reads"])
    out.detailed_file_searches += int(row["detailed_file_searches"])
    for attr in (
        "trigger_bytes",
        "result_bytes",
        "result_tokens",
        "total_matches",
        "matching_files",
        "detailed_files",
        "candidate_files",
        "representative_entries",
        "tail_entries",
        "followup_calls",
        "followup_exact_searches",
        "followup_reads",
        "followup_result_tokens",
        "investigation_result_tokens",
    ):
        getattr(out, attr).append(row[attr])
    out.rows.append(row)

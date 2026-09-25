"""Deterministic, privacy-minimizing scheduling-v2 operational evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from binnacle.logstats import plain_fields


# fmt: off
class OperationalEvidenceError(RuntimeError):
    """Required operational evidence is unavailable or inconsistent."""
ROLES = ("server", "jobs", "tunnel")
READ_TOOLS = {"read_file", "list_files", "search_text"}
_EVENT = re.compile(r"(?:INFO|WARNING|ERROR):\s+event=(?P<event>\w+)(?P<body>.*)$")
_BARE = re.compile(r"(?:^|\s)event=(?P<event>\w+)(?P<body>.*)$")
_INT = {'blocking_active_before', 'blocking_budget_s', 'content_chars', 'est_tokens', 'exit_code', 'log_bytes', 'output_bytes', 'processes', 'signal', 'structured_bytes', 'tokenizer_tokens', 'wait_bounded_s', 'wait_effective_s', 'wait_requested_s'}
_FLOAT = {'blocking_remaining_after_s', 'blocking_remaining_before_s', 'blocking_spent_after_s', 'blocking_spent_before_s', 'blocking_window_wall_s', 'duration_ms', 'runtime_s', 'state_ms', 'waited_s'}
_BOOL = {'background_job', 'blocking_budget_exhausted', 'is_error', 'truncated', 'validation_correct'}
_SAFE = {'background_job', 'blocking_active_before', 'blocking_budget_exhausted', 'blocking_budget_s', 'blocking_policy', 'blocking_remaining_after_s', 'blocking_remaining_before_s', 'blocking_spent_after_s', 'blocking_spent_before_s', 'blocking_window_wall_s', 'call', 'client', 'content_chars', 'error_class', 'error_code', 'est_tokens', 'exit_code', 'is_error', 'job_id', 'log_bytes', 'op', 'output_bytes', 'processes', 'reason', 'runtime_s', 'signal', 'state', 'state_ms', 'structured_bytes', 'tokenizer_encoding', 'tokenizer_tokens', 'tool', 'truncated', 'turn', 'validation_correct', 'validation_status', 'wait_bounded_s', 'wait_effective_s', 'wait_requested_s', 'waited_s'}
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
def _sha_payload(payload: Mapping[str, Any]) -> str:
    return _sha(_json_bytes(payload))
def _dt(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationalEvidenceError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OperationalEvidenceError("timestamps must be offset-aware")
    return parsed.astimezone(timezone.utc)
def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
def _entry_dt(entry: Mapping[str, Any]) -> datetime:
    raw = entry.get("__REALTIME_TIMESTAMP") or entry.get("_SOURCE_REALTIME_TIMESTAMP")
    if raw is not None:
        try:
            return datetime.fromtimestamp(int(str(raw)) / 1_000_000, tz=timezone.utc)
        except ValueError as exc:
            raise OperationalEvidenceError(
                "invalid journal realtime timestamp"
            ) from exc
    if isinstance(entry.get("timestamp"), str):
        return _dt(str(entry["timestamp"]))
    raise OperationalEvidenceError("journal entry has no realtime timestamp")
def _message(entry: Mapping[str, Any]) -> str:
    value = entry.get("MESSAGE", "")
    return "".join(map(str, value)) if isinstance(value, list) else str(value)
def _event_fields(message: str) -> tuple[str | None, dict[str, Any], str | None]:
    match = _EVENT.search(message) or _BARE.search(message)
    if not match:
        return None, {}, None
    event = match.group("event")
    raw = plain_fields("event=" + event + match.group("body"))
    safe: dict[str, Any] = {}
    for key in sorted(_SAFE & raw.keys()):
        value: Any = raw[key]
        try:
            if key in _INT:
                value = int(value)
            elif key in _FLOAT:
                value = float(value)
            elif key in _BOOL:
                value = str(value).lower() == "true"
            elif key == "turn":
                value = str(value).split("/", 1)[0]
        except (TypeError, ValueError):
            continue
        safe[key] = value
    args_hash = (
        _sha(str(raw["args"]).encode())
        if event == "tool_call" and "args" in raw
        else None
    )
    return event, safe, args_hash
def _priority(entry: Mapping[str, Any]) -> int | None:
    try:
        return int(str(entry["PRIORITY"])) if "PRIORITY" in entry else None
    except ValueError:
        return None
def _normalize_role(role: str, unit: str, entries: Sequence[Mapping[str, Any]], start: datetime, end: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected = [row for row in entries if start <= _entry_dt(row) < end]
    if not selected:
        raise OperationalEvidenceError(f"required {role} journal source {unit!r} is empty")
    observed = {str(value) for row in selected if (value := row.get("_SYSTEMD_UNIT") or row.get("UNIT"))}
    if observed and unit not in observed:
        raise OperationalEvidenceError(f"journal source mismatch for {role}: requested {unit!r}, observed {sorted(observed)!r}")
    unique: dict[tuple[str, str], Mapping[str, Any]] = {}
    cursor_hash: dict[str, str] = {}
    duplicates = 0
    for row in selected:
        cursor, digest = str(row.get("__CURSOR") or ""), _sha(_message(row).encode())
        key = ("cursor", cursor) if cursor else ("content", _sha(f"{_iso(_entry_dt(row))}|{unit}|{digest}".encode()))
        if cursor and cursor in cursor_hash and cursor_hash[cursor] != digest:
            raise OperationalEvidenceError(f"journal cursor {cursor!r} has conflicting payloads")
        if cursor:
            cursor_hash[cursor] = digest
        if key in unique:
            duplicates += 1
        else:
            unique[key] = row
    ordered = sorted(unique.values(), key=lambda row: (_entry_dt(row), str(row.get("__CURSOR") or ""), _sha(_message(row).encode())))
    normalized: list[dict[str, Any]] = []
    for row in ordered:
        message = _message(row)
        event, fields, args_hash = _event_fields(message)
        item: dict[str, Any] = {"at": _iso(_entry_dt(row)), "role": role, "unit": unit, "event": event or "unstructured", "message_sha256": _sha(message.encode())}
        if row.get("__CURSOR"):
            item["cursor"] = str(row["__CURSOR"])
        if (priority := _priority(row)) is not None:
            item["priority"] = priority
        if fields:
            item["fields"] = fields
        if args_hash:
            item["args_sha256"] = args_hash
        normalized.append(item)
    cursors = [str(row["__CURSOR"]) for row in ordered if row.get("__CURSOR")]
    meta = {"unit": unit, "raw_entry_count": len(entries), "in_window_entry_count": len(selected), "unique_entry_count": len(ordered), "duplicates_removed": duplicates, "observed_units": sorted(observed), "first_at": _iso(_entry_dt(ordered[0])), "last_at": _iso(_entry_dt(ordered[-1])), "first_cursor": cursors[0] if cursors else None, "last_cursor": cursors[-1] if cursors else None}
    return meta, normalized
def _epoch(value: str) -> float:
    return _dt(value).timestamp()
def _union(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted((a, b) for a, b in intervals if b > a)
    if not ordered:
        return 0.0
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        left, right = merged[-1]
        if start <= right:
            merged[-1] = (left, max(right, end))
        else:
            merged.append((start, end))
    return round(sum(end - start for start, end in merged), 6)
def _peak(intervals: Iterable[tuple[float, float]]) -> int:
    points = [(t, d) for a, b in intervals if b > a for t, d in ((a, 1), (b, -1))]
    active = maximum = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum
def _pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(
        ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))], 6
    )
def _turn(turns: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return turns.setdefault(
        name,
        {
            "turn": name,
            "tool_calls": 0,
            "job_ids": set(),
            "errors": 0,
            "exhausted_waits": 0,
        },
    )
def _telemetry(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    calls: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    waits: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    explicit: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    call_turn: dict[str, str] = {}
    closed: set[str] = set()
    for row in rows:
        event, fields = str(row["event"]), dict(row.get("fields") or {})
        call, turn = str(fields.get("call") or ""), str(fields.get("turn") or "").split("/", 1)[0]
        if event == "tool_call" and call:
            item: dict[str, Any] = calls.setdefault(call, {"call": call, "tool": fields.get("tool", "?"), "start_at": row["at"]})
            item["start_at"] = min(str(item["start_at"]), str(row["at"]))
            if turn and turn != "-":
                item["turn"], call_turn[call] = turn, turn
            if fields.get("client"):
                item["client"] = fields["client"]
            if row.get("args_sha256"):
                item["args_sha256"] = row["args_sha256"]
        elif event == "tool_result" and call:
            item = calls.setdefault(call, {"call": call, "tool": fields.get("tool", "?"), "start_at": row["at"]})
            item["end_at"], item["tool"] = row["at"], fields.get("tool", item["tool"])
            if call in call_turn:
                item["turn"] = call_turn[call]
            for key in ("background_job", "is_error", "job_id", "state", "truncated", "tokenizer_encoding"):
                if key in fields:
                    item[key] = fields[key]
            if isinstance(fields.get("tokenizer_tokens"), int):
                item["tool_result_tokens"], item["source_kind"] = fields["tokenizer_tokens"], "tokenizer"
            elif isinstance(fields.get("est_tokens"), int):
                item["tool_result_tokens"], item["source_kind"] = fields["est_tokens"], "estimate"
            values = [fields.get(key) for key in ("structured_bytes", "content_chars")]
            if (total_bytes := sum(value for value in values if isinstance(value, int))):
                item["tool_result_bytes"] = total_bytes
        if event in {"run_command_dispatch", "job_start", "job_exit", "job_interrupted"} and fields.get("job_id"):
            job_id = str(fields["job_id"])
            job: dict[str, Any] = jobs.setdefault(job_id, {"job_id": job_id})
            if call:
                job["origin_call"] = call
            if event == "job_start":
                job["start_at"] = row["at"]
            elif event == "job_exit":
                job["end_at"] = row["at"]
                for key in ("exit_code", "signal", "reason", "runtime_s"):
                    if key in fields:
                        job[key] = fields[key]
            elif event == "job_interrupted":
                job["interrupted"], job["interruption_reason"] = True, fields.get("reason")
        if event == "job_status_timing":
            wait: dict[str, Any] = {"at": row["at"], "call": call or None, "job_id": fields.get("job_id"), "turn": turn or call_turn.get(call), "client": fields.get("client"), "state": fields.get("state"), "requested_s": fields.get("wait_requested_s"), "effective_s": fields.get("wait_effective_s"), "waited_s": fields.get("waited_s"), "blocking_policy": fields.get("blocking_policy"), "blocking_budget_s": fields.get("blocking_budget_s"), "blocking_budget_exhausted": bool(fields.get("blocking_budget_exhausted", False))}
            waits.append({key: value for key, value in wait.items() if value is not None})
            if fields.get("job_id"):
                job = jobs.setdefault(str(fields["job_id"]), {"job_id": str(fields["job_id"])})
                if turn and turn != "-":
                    job["turn"] = turn
        if event == "blocking_window_closed" and isinstance(fields.get("blocking_window_wall_s"), (int, float)) and float(fields["blocking_window_wall_s"]) > 0:
            duration, end_at = float(fields["blocking_window_wall_s"]), _epoch(str(row["at"]))
            block: dict[str, Any] = {"start_at": _iso(datetime.fromtimestamp(end_at - duration, tz=timezone.utc)), "end_at": row["at"], "duration_s": duration, "call": call or None, "turn": turn or call_turn.get(call), "client": fields.get("client")}
            blocks.append({key: value for key, value in block.items() if value is not None})
            if call:
                closed.add(call)
        if event in {"continuation_incident", "manual_continuation", "chat_continuation"}:
            explicit.append({"at": row["at"], "event": event, "turn": turn or None})
        if event in {"validation_result", "chat_validation"} or "validation_correct" in fields:
            validations.append({"at": row["at"], "turn": turn or None, "correct": fields.get("validation_correct"), "status": fields.get("validation_status")})
        category: str | None = None
        if event == "tool_result" and fields.get("is_error") is True:
            category = "tool_error"
        elif event == "job_interrupted":
            category = "job_interrupted"
        elif event == "job_manager_client_disconnected":
            category = "manager_disconnect"
        elif event in {"job_manager_request_error", "job_manager_request_invalid", "run_command_dispatch_error"}:
            category = event
        elif event == "job_status_timing" and fields.get("state") == "error":
            category = "job_status_error"
        elif isinstance(row.get("priority"), int) and int(row["priority"]) <= 3:
            category = "tunnel_journal_error" if row["role"] == "tunnel" else "journal_error"
        if category:
            errors.append({"at": row["at"], "category": category, "role": row["role"], "event": event, "turn": turn or call_turn.get(call), "call": call or None, "job_id": fields.get("job_id"), "error_class": fields.get("error_class"), "error_code": fields.get("error_code"), "reason": fields.get("reason")})
    for wait in waits:
        call, waited = str(wait.get("call") or ""), wait.get("waited_s")
        if call and call not in closed and isinstance(waited, (int, float)) and waited > 0:
            end_at = _epoch(str(wait["at"]))
            blocks.append({"start_at": _iso(datetime.fromtimestamp(end_at - float(waited), tz=timezone.utc)), "end_at": wait["at"], "duration_s": float(waited), "call": call, "turn": wait.get("turn"), "client": wait.get("client"), "source": "job_status_timing_fallback"})
    for job in jobs.values():
        origin = str(job.get("origin_call") or "")
        if origin in call_turn and not job.get("turn"):
            job["turn"] = call_turn[origin]
    call_rows = sorted(calls.values(), key=lambda item: (str(item.get("start_at", "")), item["call"]))
    job_rows = sorted(jobs.values(), key=lambda item: (str(item.get("start_at") or item.get("end_at") or ""), item["job_id"]))
    waits.sort(key=lambda item: (str(item["at"]), str(item.get("call") or "")))
    blocks.sort(key=lambda item: (str(item["start_at"]), str(item.get("call") or "")))
    errors.sort(key=lambda item: (str(item["at"]), item["category"], str(item.get("call") or "")))
    explicit.sort(key=lambda item: (str(item["at"]), str(item.get("turn") or "")))
    validations.sort(key=lambda item: (str(item["at"]), str(item.get("turn") or "")))
    dup = Counter((str(item.get("turn") or ""), str(item.get("tool") or ""), str(item.get("args_sha256") or "")) for item in call_rows if item.get("tool") in READ_TOOLS and item.get("args_sha256"))
    turns: dict[str, dict[str, Any]] = {}
    for item in call_rows:
        if item.get("turn"):
            turn_item = _turn(turns, str(item["turn"]))
            turn_item["tool_calls"] += 1
            if item.get("job_id"):
                turn_item["job_ids"].add(str(item["job_id"]))
    for item in job_rows:
        if item.get("turn"):
            _turn(turns, str(item["turn"]))["job_ids"].add(str(item["job_id"]))
    for item in waits:
        if item.get("turn") and item.get("blocking_budget_exhausted"):
            _turn(turns, str(item["turn"]))["exhausted_waits"] += 1
    for item in errors:
        if item.get("turn"):
            _turn(turns, str(item["turn"]))["errors"] += 1
    completed = {str(item["job_id"]) for item in job_rows if item.get("end_at")}
    turn_rows: list[dict[str, Any]] = []
    for item in turns.values():
        ids = sorted(item["job_ids"])
        item["job_ids"] = ids
        item["same_turn_job_completion_proxy"] = bool(ids and all(job_id in completed for job_id in ids))
        turn_rows.append(item)
    turn_rows.sort(key=lambda item: item["turn"])
    intervals = [(_epoch(str(item["start_at"])), _epoch(str(item["end_at"]))) for item in call_rows if item.get("end_at")]
    block_intervals = [(_epoch(str(item["start_at"])), _epoch(str(item["end_at"]))) for item in blocks]
    durations = [float(item["waited_s"]) for item in waits if isinstance(item.get("waited_s"), (int, float))]
    reliability = {"error_event_count": len(errors), "tool_error_count": sum(item["category"] == "tool_error" for item in errors), "interrupted_job_count": sum(item["category"] == "job_interrupted" for item in errors), "manager_disconnect_count": sum(item["category"] == "manager_disconnect" for item in errors), "tunnel_error_count": sum(item["category"] == "tunnel_journal_error" for item in errors), "affected_turn_count": len({str(item["turn"]) for item in errors if item.get("turn")})}
    blocking = {"blocking_window_count": len(blocks), "blocking_wall_union_s": _union(block_intervals), "positive_wait_count": sum(isinstance(item.get("requested_s"), (int, float)) and float(item["requested_s"]) > 0 for item in waits), "exhausted_wait_count": sum(bool(item.get("blocking_budget_exhausted")) for item in waits), "waited_s_p50": _pct(durations, 0.5), "waited_s_p90": _pct(durations, 0.9), "waited_s_p95": _pct(durations, 0.95), "waited_s_max": max(durations) if durations else None}
    efficiency = {"tool_call_count": len(call_rows), "paired_tool_call_count": sum(bool(item.get("end_at")) for item in call_rows), "tool_result_tokens_total": sum(int(item.get("tool_result_tokens", 0)) for item in call_rows), "tool_result_bytes_total": sum(int(item.get("tool_result_bytes", 0)) for item in call_rows), "tokenizer_telemetry_calls": sum(item.get("source_kind") == "tokenizer" for item in call_rows), "estimated_token_calls": sum(item.get("source_kind") == "estimate" for item in call_rows), "job_status_call_count": len({str(item["call"]) for item in waits if item.get("call")}), "peak_tool_concurrency": _peak(intervals), "duplicate_read_calls": sum(max(0, count - 1) for count in dup.values())}
    workflow = {"turn_count": len(turn_rows), "turns_with_job_activity": sum(bool(item["job_ids"]) for item in turn_rows), "same_turn_job_completion_proxy_count": sum(bool(item["same_turn_job_completion_proxy"]) for item in turn_rows), "explicit_continuation_incident_count": len(explicit), "tagged_validation_count": len(validations), "tagged_validation_correct_count": sum(item.get("correct") is True or str(item.get("status") or "").lower() in {"pass", "passed", "ok"} for item in validations), "paired_result_ratio": round(sum(bool(item.get("end_at")) for item in call_rows) / len(call_rows), 6) if call_rows else None}
    return {"calls": call_rows, "jobs": job_rows, "waits": waits, "blocking_windows": blocks, "errors": errors, "turns": turn_rows, "explicit_continuations": explicit, "tagged_validation": validations, "summary": {"reliability": reliability, "blocking_wall": blocking, "efficiency": efficiency, "workflow_ux": workflow}}
def build_evidence(
    *,
    start: str,
    end: str,
    units: Mapping[str, str],
    entries_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    start_dt, end_dt = _dt(start), _dt(end)
    if end_dt <= start_dt:
        raise OperationalEvidenceError("window end must be after start")
    if set(units) != set(ROLES):
        raise OperationalEvidenceError(
            f"units must contain exactly: {', '.join(ROLES)}"
        )
    sources: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for role in ROLES:
        if role not in entries_by_role:
            raise OperationalEvidenceError(f"missing required journal source: {role}")
        sources[role], normalized = _normalize_role(
            role, str(units[role]), entries_by_role[role], start_dt, end_dt
        )
        rows.extend(normalized)
    rank = {role: index for index, role in enumerate(ROLES)}
    rows.sort(
        key=lambda row: (
            row["at"],
            rank[str(row["role"])],
            str(row["event"]),
            str(row.get("cursor") or ""),
            row["message_sha256"],
        )
    )
    telemetry = _telemetry(rows)
    return {
        "schema_version": 1,
        "report_kind": "chat-scheduling-operational-evidence",
        "privacy": {
            "arbitrary_message_text_retained": False,
            "tool_arguments_retained": False,
            "tool_argument_fingerprints_retained": True,
            "conversation_prompt_text_retained": False,
        },
        "window": {
            "start": _iso(start_dt),
            "end": _iso(end_dt),
            "semantics": "[start,end)",
            "duration_s": round((end_dt - start_dt).total_seconds(), 6),
        },
        "sources": sources,
        "journal_events": rows,
        "telemetry": telemetry,
        "summary": telemetry["summary"],
    }
def _journal(unit: str, start: str, end: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "journalctl",
            "--no-pager",
            "--output=json",
            "--unit",
            unit,
            "--since",
            start,
            "--until",
            end,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        reason = (result.stderr or "journalctl failed").strip().splitlines()[-1]
        raise OperationalEvidenceError(
            f"failed to read required journal source {unit!r}: {reason}"
        )
    records: list[dict[str, Any]] = []
    for number, line in enumerate(result.stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OperationalEvidenceError(
                f"journal source {unit!r} emitted invalid JSON on line {number}"
            ) from exc
        if not isinstance(value, dict):
            raise OperationalEvidenceError(
                f"journal source {unit!r} emitted a non-object record"
            )
        records.append(value)
    return records
def freeze_evidence(
    *, start: str, end: str, server_unit: str, jobs_unit: str, tunnel_unit: str
) -> dict[str, Any]:
    units = {"server": server_unit, "jobs": jobs_unit, "tunnel": tunnel_unit}
    return build_evidence(
        start=start,
        end=end,
        units=units,
        entries_by_role={
            role: _journal(unit, start, end) for role, unit in units.items()
        },
    )
def _find(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find(child, key)
            if found is not None:
                return found
    return None
def build_review(evidence: Mapping[str, Any], *, focus: str, reference: Mapping[str, Any], evidence_sha256: str | None = None, reference_sha256: str | None = None) -> dict[str, Any]:
    if focus not in {"reliability", "blocking-wall", "efficiency", "workflow-ux"}:
        raise OperationalEvidenceError(f"unsupported review focus: {focus}")
    if evidence.get("report_kind") != "chat-scheduling-operational-evidence":
        raise OperationalEvidenceError("evidence has unexpected report kind")
    telemetry, summary = evidence.get("telemetry"), evidence.get("summary")
    if not isinstance(telemetry, Mapping) or not isinstance(summary, Mapping):
        raise OperationalEvidenceError("evidence is missing normalized telemetry")
    if focus == "reliability":
        metrics: dict[str, Any] = dict(summary["reliability"])
        metrics["error_chronology"] = [{key: item.get(key) for key in ("at", "category", "role", "event", "turn") if item.get(key) is not None} for item in telemetry.get("errors", [])]
    elif focus == "blocking-wall":
        metrics = dict(summary["blocking_wall"])
        per_turn: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for item in telemetry.get("blocking_windows", []):
            if item.get("turn"):
                per_turn[str(item["turn"])].append((_epoch(str(item["start_at"])), _epoch(str(item["end_at"]))))
        metrics["blocking_wall_union_s_by_turn"] = {turn: _union(intervals) for turn, intervals in sorted(per_turn.items())}
        metrics["exhausted_turns"] = sorted({str(item["turn"]) for item in telemetry.get("waits", []) if item.get("turn") and item.get("blocking_budget_exhausted")})
    elif focus == "efficiency":
        metrics = dict(summary["efficiency"])
    else:
        metrics = dict(summary["workflow_ux"])
        metrics["continuation_evidence"] = list(telemetry.get("explicit_continuations", []))
        metrics["tagged_validation"] = list(telemetry.get("tagged_validation", []))
        metrics["proxy_note"] = "Same-turn values are server-derived job/tool proxies only; no user prompt text is inferred or retained."
    return {"schema_version": 1, "report_kind": "chat-scheduling-operational-review", "focus": focus, "window": evidence["window"], "evidence_sha256": evidence_sha256 or _sha_payload(evidence), "reference": {"sha256": reference_sha256 or _sha_payload(reference), "report_kind": reference.get("report_kind"), "verdict": _find(reference, "verdict"), "selected_budget_s": _find(reference, "selected_budget_s"), "phase4_source_head": _find(reference, "phase4_source_head")}, "metrics": metrics}
def _markdown(payload: Mapping[str, Any]) -> str:
    if payload["report_kind"] == "chat-scheduling-operational-review":
        return "\n".join([f"# Chat scheduling operational review: {payload['focus']}", "", f"- Window: {payload['window']['start']} to {payload['window']['end']} (half-open)", f"- Evidence SHA-256: {payload['evidence_sha256']}", f"- Reference SHA-256: {payload['reference']['sha256']}", "", "## Metrics", "", "JSON metrics are in the companion artifact.", ""])
    summary, sources = payload["summary"], payload["sources"]
    lines = ["# Chat scheduling operational evidence", "", f"- Window: {payload['window']['start']} to {payload['window']['end']} (half-open)", f"- Evidence SHA-256: {_sha_payload(payload)}", "- Privacy: arbitrary journal/conversation prose is not retained.", "", "## Journal sources", ""]
    lines.extend(f"- {role}: {sources[role]['unit']}; {sources[role]['unique_entry_count']} unique entries; {sources[role]['duplicates_removed']} duplicates removed" for role in ROLES)
    lines.extend(["", "## Summary", "", f"- Reliability errors: {summary['reliability']['error_event_count']}", f"- Blocking wall union: {summary['blocking_wall']['blocking_wall_union_s']} s", f"- Tool calls: {summary['efficiency']['tool_call_count']}", f"- Turns observed: {summary['workflow_ux']['turn_count']}", ""])
    return "\n".join(lines)
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chat-scheduling-operational")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    for name in ("start", "end", "server-unit", "jobs-unit", "tunnel-unit"):
        freeze.add_argument(f"--{name}", required=True)
    freeze.add_argument("--output-json", type=Path, required=True)
    freeze.add_argument("--output-md", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("--evidence", type=Path, required=True)
    review.add_argument(
        "--focus",
        choices=("reliability", "blocking-wall", "efficiency", "workflow-ux"),
        required=True,
    )
    review.add_argument("--reference", type=Path, required=True)
    review.add_argument("--output-json", type=Path, required=True)
    review.add_argument("--output-md", type=Path, required=True)
    return parser
def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "freeze":
            payload = freeze_evidence(start=args.start, end=args.end, server_unit=args.server_unit, jobs_unit=args.jobs_unit, tunnel_unit=args.tunnel_unit)
        else:
            evidence_bytes, reference_bytes = args.evidence.read_bytes(), args.reference.read_bytes()
            payload = build_review(json.loads(evidence_bytes), focus=args.focus, reference=json.loads(reference_bytes), evidence_sha256=_sha(evidence_bytes), reference_sha256=_sha(reference_bytes))
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_bytes(_json_bytes(payload))
        args.output_md.write_text(_markdown(payload), encoding="utf-8")
    except (OperationalEvidenceError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"operational evidence error: {exc}") from exc
# fmt: on

if __name__ == "__main__":
    main()

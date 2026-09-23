"""Convert frozen benchmark evidence into a normalized TrialTrace."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.chat_scheduling_journal import (
    RawCall,
    RawJob,
    coerce_fields,
    parse_journal,
)
from scripts.chat_scheduling_manifest import Node, Scenario
from scripts.chat_scheduling_runtime import TrialIdentity, render_text
from scripts.chat_scheduling_trace import JobInterval, ToolInterval, TrialTrace

_RESULT_REF = re.compile(r"\{result:([^.{}]+)\.([^{}]+)\}")
_ABS_PATH = re.compile(r'(?<![A-Za-z0-9_])(/[^\s\'";|&<>]+)')
_INTERRUPTION_TEXT = (
    "streaming interrupted",
    "request timed out",
    "request timeout",
    "no complete reply within",
    "connection interrupted",
    "connection lost",
    "network error",
    "something went wrong",
    "error generating a response",
)


def _conversation_facts(path: Path) -> tuple[str, bool, int, str | None]:
    if not path.exists():
        return "", False, 1, None
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("mapping") or {}
    user_messages = 0
    assistants: list[dict[str, Any]] = []
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if not isinstance(message, dict):
            continue
        role = (message.get("author") or {}).get("role")
        if role == "user":
            user_messages += 1
        elif role == "assistant":
            assistants.append(message)
    current = mapping.get(data.get("current_node"), {})
    final = current.get("message") if isinstance(current, dict) else None
    if (
        not isinstance(final, dict)
        or (final.get("author") or {}).get("role") != "assistant"
    ):
        final = assistants[-1] if assistants else None
    if not isinstance(final, dict):
        return "", False, max(user_messages, 1), "missing_final_assistant"
    content = final.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else []
    reply = "\n".join(part for part in (parts or []) if isinstance(part, str))
    metadata = final.get("metadata") or {}
    complete = (
        bool(metadata.get("is_complete"))
        or final.get("status") == "finished_successfully"
    )
    low = reply.lower()
    interruption = next((item for item in _INTERRUPTION_TEXT if item in low), None)
    return reply, complete, max(user_messages, 1), interruption


def _seed_strings(record: dict[str, Any]) -> list[str]:
    values = [
        str(record.get("run_id") or ""),
        str(record.get("nonce") or ""),
        str((record.get("fixture") or {}).get("root") or ""),
    ]
    values.extend(
        str(value)
        for value in ((record.get("fixture") or {}).get("jobs") or {}).values()
    )
    return [value for value in values if value]


def _trial_calls(record: dict[str, Any], calls: list[RawCall]) -> list[RawCall]:
    openai = [call for call in calls if call.client.startswith("openai-mcp")]
    seeds = _seed_strings(record)
    matching_turns = {
        call.turn
        for call in openai
        if call.turn
        and any(
            seed in (call.args_raw + json.dumps(call.args, sort_keys=True))
            for seed in seeds
        )
    }
    if not matching_turns:
        return []
    return [call for call in openai if call.turn in matching_turns]


def _render_expected(
    value: Any,
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str],
    node_results: dict[str, dict[str, Any]],
) -> Any:
    if isinstance(value, str):
        rendered = render_text(value, identity, root, jobs)

        def replace(match: re.Match[str]) -> str:
            node_id, field = match.groups()
            result = node_results.get(node_id, {})
            if field not in result:
                return match.group(0)
            return str(result[field])

        return _RESULT_REF.sub(replace, rendered)
    if isinstance(value, list):
        return [
            _render_expected(item, identity, root, jobs, node_results) for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _render_expected(item, identity, root, jobs, node_results)
            for key, item in value.items()
        }
    return value


def _auto_reasoning_nodes(scenario: Scenario, completed: set[str]) -> bool:
    changed = False
    for node in scenario.dag:
        if node.kind != "reasoning" or node.id in completed:
            continue
        if set(node.depends_on) <= completed:
            completed.add(node.id)
            changed = True
    return changed


def _node_matches(
    node: Node,
    call: RawCall,
    expected: dict[str, Any],
) -> bool:
    if node.tool != call.tool:
        return False
    for key, value in expected.items():
        # These fields affect presentation/test metadata, not scheduler
        # semantics, so they must not participate in logical DAG identity.
        if key in {"operation", "tail_lines"}:
            continue
        if isinstance(value, str) and "{result:" in value:
            continue
        if key not in call.args:
            return False
        if call.args[key] != value:
            return False
    return True


def _assign_nodes(
    scenario: Scenario,
    calls: list[RawCall],
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str],
) -> tuple[dict[str, str], set[str], dict[str, dict[str, Any]]]:
    assigned: dict[str, str] = {}
    completed: set[str] = set()
    node_results: dict[str, dict[str, Any]] = {}
    final_for_repeat: set[str] = set()

    for call in calls:
        while _auto_reasoning_nodes(scenario, completed):
            pass
        candidates: list[Node] = []
        for node in scenario.dag:
            if node.kind != "tool":
                continue
            if not set(node.depends_on) <= completed:
                continue
            if node.id in completed and not node.allow_repeats:
                continue
            if node.id in final_for_repeat:
                continue
            expected = _render_expected(
                node.arguments, identity, root, jobs, node_results
            )
            if _node_matches(node, call, expected):
                candidates.append(node)
        if not candidates:
            continue
        node = candidates[0]
        assigned[call.call_id] = node.id
        result = coerce_fields(call.result_fields or {})
        node_results[node.id] = result
        if result.get("is_error"):
            continue
        if node.allow_repeats and node.completion_condition == "job_state=exited":
            if result.get("state") == "exited":
                completed.add(node.id)
                final_for_repeat.add(node.id)
        else:
            completed.add(node.id)
    while _auto_reasoning_nodes(scenario, completed):
        pass
    return assigned, completed, node_results


def _tool_intervals(
    calls: list[RawCall],
    assigned: dict[str, str],
    origin_epoch_s: float,
) -> list[ToolInterval]:
    out: list[ToolInterval] = []
    for call in calls:
        if call.end_epoch_s is None:
            continue
        fields = coerce_fields(call.result_fields or {})
        start = max(0.0, call.start_epoch_s - origin_epoch_s)
        end = max(start, call.end_epoch_s - origin_epoch_s)
        start_s = round(start, 6)
        end_s = round(end, 6)
        waited = fields.get("waited_s")
        blocking_start = blocking_end = None
        if (
            call.tool == "job_status"
            and float(call.args.get("wait_seconds", 0) or 0) > 0
            and isinstance(waited, (int, float))
            and waited > 0
        ):
            blocking_start = start_s
            blocking_end = max(
                start_s,
                min(end_s, round(start + float(waited), 6)),
            )
        tokens = fields.get("tokenizer_tokens")
        if not isinstance(tokens, int):
            tokens = fields.get("est_tokens")
        structured = fields.get("structured_bytes")
        content = fields.get("content_chars")
        out.append(
            ToolInterval(
                call_id=call.call_id,
                node_id=assigned.get(call.call_id),
                tool=call.tool,
                turn=call.turn,
                start_s=start_s,
                end_s=end_s,
                args=call.args,
                result=fields,
                is_error=bool(fields.get("is_error")),
                tokenizer_tokens=tokens if isinstance(tokens, int) else 0,
                result_bytes=(structured if isinstance(structured, int) else 0)
                + (content if isinstance(content, int) else 0),
                blocking_start_s=blocking_start,
                blocking_end_s=blocking_end,
            )
        )
    return out


def _job_intervals(
    raw_jobs: list[RawJob],
    trial_job_ids: set[str],
    origin_epoch_s: float,
) -> list[JobInterval]:
    out = []
    for job in raw_jobs:
        if job.job_id not in trial_job_ids:
            continue
        out.append(
            JobInterval(
                job_id=job.job_id,
                start_s=max(0.0, round(job.start_epoch_s - origin_epoch_s, 6)),
                end_s=(
                    max(0.0, round(job.end_epoch_s - origin_epoch_s, 6))
                    if job.end_epoch_s is not None
                    else None
                ),
                exit_code=job.exit_code,
                signal=job.signal,
            )
        )
    return out


def _is_under_text(path_text: str, root: Path) -> bool:
    try:
        Path(path_text).expanduser().resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _mutation_scope_ok(
    scenario: Scenario,
    trace_tools: list[ToolInterval],
    record: dict[str, Any],
    root: Path,
) -> bool:
    if record.get("production_unchanged") is not True:
        return False
    nodes = {node.id: node for node in scenario.dag}
    for call in trace_tools:
        node = nodes.get(call.node_id or "")
        if node is None or node.access != "non_read_only":
            continue
        if call.tool == "run_command":
            workdir = call.args.get("workdir")
            if not isinstance(workdir, str) or not _is_under_text(workdir, root):
                return False
            command = call.args.get("command")
            if isinstance(command, str):
                for match in _ABS_PATH.finditer(command):
                    absolute = match.group(1).rstrip("),]")
                    if absolute == "/dev/null":
                        continue
                    if not _is_under_text(absolute, root):
                        return False
        elif call.tool == "stop_job":
            job_id = call.args.get("job_id")
            fixture_jobs = {
                str(value)
                for value in ((record.get("fixture") or {}).get("jobs") or {}).values()
            }
            if job_id not in fixture_jobs:
                return False
    return True


def load_trial_trace(state_dir: Path, scenario: Scenario) -> TrialTrace:
    record = json.loads((state_dir / "trial.json").read_text(encoding="utf-8"))
    timing_path = state_dir / "chat-timing.json"
    timing = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    origin = float(
        timing.get("sent_at_epoch_s") or record.get("trial_start_epoch_s") or 0.0
    )
    wall = timing.get("wall_s")
    timing_status = str(timing.get("status") or "unknown")
    if timing_status not in {"complete", "timeout"}:
        timing_status = "unknown"

    reply, assistant_complete, user_messages, conversation_interruption = (
        _conversation_facts(state_dir / "conversation.json")
    )
    error = record.get("error") or {}
    error_text = json.dumps(error).lower()
    interruption = conversation_interruption
    if isinstance(error, dict) and error.get("type") == "TimeoutExpired":
        interruption = "harness_timeout"
    if interruption is None:
        interruption = next(
            (item for item in _INTERRUPTION_TEXT if item in error_text),
            None,
        )
    if timing_status == "timeout" and interruption is None:
        interruption = "timeout"

    journal = (state_dir / "journal.log").read_text(encoding="utf-8")
    raw_calls, raw_jobs = parse_journal(journal)
    calls = _trial_calls(record, raw_calls)
    root = Path((record.get("fixture") or {}).get("root") or "/tmp")
    jobs = {
        str(key): str(value)
        for key, value in ((record.get("fixture") or {}).get("jobs") or {}).items()
    }
    identity = TrialIdentity(
        scenario_id=scenario.id,
        run_id=str(record["run_id"]),
        nonce=str(record["nonce"]),
    )
    assigned, completed, node_results = _assign_nodes(
        scenario, calls, identity, root, jobs
    )
    tools = _tool_intervals(calls, assigned, origin)

    trial_job_ids = set(jobs.values())
    for result in node_results.values():
        job_id = result.get("job_id")
        if isinstance(job_id, str):
            trial_job_ids.add(job_id)

    fixture_snapshot_path = state_dir / "fixture-final.json"
    fixture_snapshot = (
        json.loads(fixture_snapshot_path.read_text(encoding="utf-8"))
        if fixture_snapshot_path.exists()
        else {}
    )
    trace = TrialTrace(
        scenario_id=scenario.id,
        run_id=str(record["run_id"]),
        nonce=str(record["nonce"]),
        fixture_root=str(root),
        fixture_jobs=jobs,
        arm=record.get("arm"),
        wall_s=float(wall) if isinstance(wall, (int, float)) else None,
        timing_status=timing_status,
        final_reply=reply,
        assistant_complete=assistant_complete,
        interruption_kind=interruption,
        budget_exhausted=any(
            bool(call.result.get("blocking_budget_exhausted")) for call in tools
        ),
        user_messages=user_messages,
        tools=tools,
        jobs=_job_intervals(raw_jobs, trial_job_ids, origin),
        explicit_completed_nodes=sorted(completed),
        final_files={
            str(key): str(value)
            for key, value in (fixture_snapshot.get("final_files") or {}).items()
        },
        production_unchanged=record.get("production_unchanged"),
    )
    trace.mutation_scope_ok = _mutation_scope_ok(scenario, tools, record, root)
    return trace

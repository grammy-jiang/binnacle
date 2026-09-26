from __future__ import annotations

import hashlib
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
from scripts.chat_scheduling_postsend import captured_send_reply, conversation_facts
from scripts.chat_scheduling_runtime import (
    HarnessError,
    TrialIdentity,
    render_text,
    write_json,
)
from scripts.chat_scheduling_trace import JobInterval, ToolInterval, TrialTrace


class EvidenceIntegrityError(HarnessError): ...


_RESULT_REF = re.compile(r"\{result:([^.{}]+)\.([^{}]+)\}")
_ABS_PATH = re.compile(r'(?<![A-Za-z0-9_])(/[^\s\'";|&<>]+)')


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


def _trial_calls(record: dict, calls: list[RawCall], *, strict=False) -> list[RawCall]:
    openai = [call for call in calls if call.client.startswith("openai-mcp")]
    seeds = _seed_strings(record)
    turns = {
        call.turn
        for call in openai
        if call.turn
        and any(
            seed in (call.args_raw + json.dumps(call.args, sort_keys=True))
            for seed in seeds
        )
    }
    if strict and len(turns) != 1:
        raise EvidenceIntegrityError(f"base turn matches: {sorted(turns)}")
    return [call for call in openai if call.turn in turns]


def _render_expected(
    value: Any,
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str],
    node_results: dict[str, dict[str, Any]],
    budget_s: int | None = None,
    margin_s: int | None = 0,
) -> Any:
    if isinstance(value, str):
        rendered = render_text(
            value, identity, root, jobs, budget_s=budget_s, margin_s=margin_s
        )

        def replace(match: re.Match[str]) -> str:
            node_id, field = match.groups()
            result = node_results.get(node_id, {})
            if field not in result:
                return match.group(0)
            return str(result[field])

        return _RESULT_REF.sub(replace, rendered)

    def render(item: Any) -> Any:
        return _render_expected(
            item, identity, root, jobs, node_results, budget_s, margin_s
        )

    if isinstance(value, list):
        return [render(item) for item in value]
    if isinstance(value, dict):
        return {key: render(item) for key, item in value.items()}
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


def _node_matches(node: Node, call: RawCall, expected: dict[str, Any]) -> bool:
    if node.tool != call.tool:
        return False
    advisory_positive_wait = (
        node.tool == "job_status"
        and node.allow_repeats
        and isinstance(node.completion_condition, str)
        and node.completion_condition.startswith("job_state=")
    )
    for key, value in expected.items():
        if key in {"operation", "tail_lines"}:
            continue
        if isinstance(value, str) and "{result:" in value:
            continue
        if key not in call.args:
            return False
        if key == "wait_seconds" and advisory_positive_wait:
            actual_wait = call.args[key]
            if (
                not isinstance(actual_wait, int)
                or isinstance(actual_wait, bool)
                or not 1 <= actual_wait <= 50
            ):
                return False
            continue
        if call.args[key] != value:
            return False
    return True


def _assign_nodes(
    scenario: Scenario,
    calls: list[RawCall],
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str],
    budget_s: int | None = None,
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
                node.arguments,
                identity,
                root,
                jobs,
                node_results,
                budget_s,
                scenario.runtime_budget_margin_s,
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


def _phase4_source(
    state_dir: Path, record: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    path = state_dir / "endpoint-evidence.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("evidence_integrity_error"):
        raise EvidenceIntegrityError("endpoint slice was marked invalid")
    actual = (
        evidence.get("endpoint_id"),
        evidence.get("logical_arm"),
        evidence.get("trial_run_id"),
        evidence.get("trial_nonce_sha256"),
    )
    expected = (
        record.get("endpoint_id"),
        record.get("arm"),
        record.get("run_id"),
        hashlib.sha256(str(record["nonce"]).encode()).hexdigest(),
    )
    if actual != expected:
        raise EvidenceIntegrityError("endpoint evidence identity mismatch")
    parts = []
    for name in ("server", "manager", "tunnel"):
        data = (state_dir / f"endpoint-{name}.log").read_bytes()
        if hashlib.sha256(data).hexdigest() != evidence.get(f"{name}_log_sha256"):
            raise EvidenceIntegrityError(f"{name} log hash mismatch")
        span = evidence.get(f"{name}_log_end_offset", -1) - evidence.get(
            f"{name}_log_start_offset", 0
        )
        if len(data) != span:
            raise EvidenceIntegrityError(f"{name} log offset mismatch")
        if name != "tunnel":
            parts.append(data.decode(errors="replace"))
    return "\\n".join(parts), evidence


def load_trial_trace(state_dir: Path, scenario: Scenario) -> TrialTrace:
    record = json.loads((state_dir / "trial.json").read_text(encoding="utf-8"))
    timing_path = state_dir / "chat-timing.json"
    timing = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    origin = float(
        timing.get("sent_at_epoch_s") or record.get("trial_start_epoch_s") or 0.0
    )
    wall = timing.get("wall_s")
    settled = timing.get("settled_at_epoch_s")
    if isinstance(settled, (int, float)) and origin > 0:
        wall = round(max(0.0, float(settled) - origin), 3)
    timing_status = str(timing.get("status") or "unknown")
    if timing_status not in {"complete", "timeout"}:
        timing_status = "unknown"

    reply, assistant_complete, user_messages, conversation_interruption = (
        conversation_facts(state_dir / "conversation.json")
    )
    if not reply:
        captured_reply, captured_complete = captured_send_reply(record)
        if captured_reply:
            reply = captured_reply
            assistant_complete = assistant_complete or captured_complete
            conversation_interruption = None
    error = record.get("error") or {}
    error_text = json.dumps(error).lower()
    interruption = conversation_interruption
    if isinstance(error, dict) and error.get("type") == "TimeoutExpired":
        interruption = "harness_timeout"
    if interruption is None:
        interruption = next(
            (
                item
                for item in (
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
                if item in error_text
            ),
            None,
        )
    if timing_status == "timeout" and interruption is None:
        interruption = "timeout"

    phase4 = record.get("phase") == 4
    evidence = None
    try:
        journal, evidence = (
            _phase4_source(state_dir, record)
            if phase4
            else ((state_dir / "journal.log").read_text(encoding="utf-8"), None)
        )
        raw_calls, raw_jobs = parse_journal(journal)
        calls = _trial_calls(record, raw_calls, strict=phase4)
    except (EvidenceIntegrityError, OSError, json.JSONDecodeError) as exc:
        record["evidence_integrity_error"] = True
        write_json(state_dir / "trial.json", record)
        if (state_dir / "endpoint-evidence.json").exists():
            failed = evidence or json.loads(
                (state_dir / "endpoint-evidence.json").read_text()
            )
            failed["evidence_integrity_error"] = True
            failed["evidence_integrity_errors"] = [str(exc)]
            write_json(state_dir / "endpoint-evidence.json", failed)
        raise EvidenceIntegrityError(str(exc)) from exc
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
        scenario, calls, identity, root, jobs, record.get("budget_s")
    )
    tools = _tool_intervals(calls, assigned, origin)

    trial_job_ids = set(jobs.values())
    for call in calls:
        for job_id in (
            call.args.get("job_id"),
            (call.result_fields or {}).get("job_id"),
        ):
            if isinstance(job_id, str):
                trial_job_ids.add(job_id)
    for result in node_results.values():
        job_id = result.get("job_id")
        if isinstance(job_id, str):
            trial_job_ids.add(job_id)
    if phase4 and evidence is not None:
        matched_turn = calls[0].turn
        evidence.update(
            matched_base_turn=matched_turn,
            matched_call_ids=[call.call_id for call in calls],
            matched_job_ids=sorted(trial_job_ids),
            raw_foreign_turns_present=any(
                call.client.startswith("openai-mcp") and call.turn != matched_turn
                for call in raw_calls
            ),
            normalized_foreign_calls=0,
        )
        write_json(state_dir / "endpoint-evidence.json", evidence)

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

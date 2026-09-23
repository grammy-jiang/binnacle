"""Deterministic correctness-oracle evaluation for scheduling benchmarks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.chat_scheduling_manifest import OracleCheck, Scenario
from scripts.chat_scheduling_runtime import TrialIdentity, render_text
from scripts.chat_scheduling_trace import ToolInterval, TrialTrace, calls_by_node


def _render(value: Any, trace: TrialTrace) -> Any:
    identity = TrialIdentity(trace.scenario_id, trace.run_id, trace.nonce)
    root = Path(trace.fixture_root)
    if isinstance(value, str):
        return render_text(value, identity, root, trace.fixture_jobs)
    if isinstance(value, list):
        return [_render(item, trace) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, trace) for key, item in value.items()}
    return value


def _successful(call: ToolInterval) -> bool:
    return not call.is_error and not bool(call.result.get("is_error"))


def _check(
    check: OracleCheck,
    scenario: Scenario,
    trace: TrialTrace,
    completion: dict[str, float],
    relations: dict[str, bool],
) -> tuple[bool, str]:
    params = _render(check.params, trace)
    grouped = calls_by_node(trace)
    kind = check.type

    if kind == "all_nodes_complete":
        missing = [node.id for node in scenario.dag if node.id not in completion]
        return not missing, f"missing nodes: {missing}"

    if kind == "exact_reply":
        expected = str(params.get("value", ""))
        return trace.final_reply.strip() == expected.strip(), "final reply mismatch"

    if kind == "reply_contains_all":
        missing = [
            str(value)
            for value in params.get("values", [])
            if str(value) not in trace.final_reply
        ]
        return not missing, f"reply missing: {missing}"

    if kind == "tool_calls_exact_once":
        bad = {
            node_id: len(grouped.get(str(node_id), []))
            for node_id in params.get("nodes", [])
            if len(grouped.get(str(node_id), [])) != 1
        }
        return not bad, f"tool call counts: {bad}"

    if kind == "event_relation":
        if not bool(params.get("hard_gate", True)):
            return True, ""
        name = str(params.get("relation"))
        return relations.get(name) is True, f"event relation failed: {name}"

    if kind in {"command_exit_zero", "pytest_pass"}:
        node_id = str(params.get("node"))
        calls = grouped.get(node_id, [])
        passed = bool(
            calls and calls[-1].result.get("exit_code") == 0 and _successful(calls[-1])
        )
        return passed, f"{node_id} did not exit zero"

    if kind == "command_contains_exit_zero":
        substring = str(params.get("contains", ""))
        matches = [
            call
            for call in trace.tools
            if call.tool == "run_command"
            and substring in str(call.args.get("command", ""))
        ]
        passed = any(
            call.result.get("exit_code") == 0 and _successful(call) for call in matches
        )
        return passed, f"no successful run_command containing {substring!r}"

    if kind == "job_state":
        if "node" in params:
            node_id = str(params["node"])
            calls = grouped.get(node_id, [])
            result = calls[-1].result if calls else {}
            for key in ("state", "exit_code", "signal"):
                if key in params and result.get(key) != params[key]:
                    return False, f"{node_id} {key}={result.get(key)!r}"
            return bool(calls), f"missing job-state node {node_id}"
        names = [str(name) for name in params.get("jobs", [])]
        jobs_by_id = {job.job_id: job for job in trace.jobs}
        for name in names:
            job_id = trace.fixture_jobs.get(name)
            job = jobs_by_id.get(job_id or "")
            if job is None:
                return False, f"missing fixture job {name}"
            if params.get("state") == "exited" and job.end_s is None:
                return False, f"fixture job {name} did not exit"
            if "signal" in params and job.signal != params["signal"]:
                return False, f"fixture job {name} signal={job.signal!r}"
        return True, ""

    if kind == "file_content":
        path = str(params.get("path"))
        content = trace.final_files.get(path)
        if content is None:
            try:
                relative = str(Path(path).relative_to(Path(trace.fixture_root)))
            except ValueError:
                relative = path
            content = trace.final_files.get(relative)
        expected = str(params.get("contains", ""))
        return (
            content is not None and expected in content,
            f"file content missing {expected!r}",
        )

    if kind == "no_mutation_outside_scope":
        return trace.mutation_scope_ok is True, "mutation scope not proven"

    raise ValueError(f"unsupported oracle check: {kind}")


def evaluate_oracles(
    scenario: Scenario,
    trace: TrialTrace,
    completion: dict[str, float],
    relations: dict[str, bool],
) -> list[str]:
    failures: list[str] = []
    for check in scenario.oracle.checks:
        passed, detail = _check(check, scenario, trace, completion, relations)
        if not passed:
            failures.append(f"{check.type}: {detail}")
    return failures

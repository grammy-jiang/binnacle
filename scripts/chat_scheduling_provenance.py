"""Diagnostic provenance classification for benchmark failures and handoffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from scripts.chat_scheduling_evidence import load_trial_trace
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import Scenario, load_scenario
from scripts.chat_scheduling_trace import TrialTrace

ProvenanceClass = Literal[
    "pre_mcp_submission_failure",
    "active_turn_browser_timeout",
    "mcp_completed_browser_timeout",
    "budget_exhaustion",
    "other_submitted_error",
]

PRE_MCP_SUBMISSION_FAILURE: ProvenanceClass = "pre_mcp_submission_failure"
ACTIVE_TURN_BROWSER_TIMEOUT: ProvenanceClass = "active_turn_browser_timeout"
MCP_COMPLETED_BROWSER_TIMEOUT: ProvenanceClass = "mcp_completed_browser_timeout"
BUDGET_EXHAUSTION: ProvenanceClass = "budget_exhaustion"
OTHER_SUBMITTED_ERROR: ProvenanceClass = "other_submitted_error"

FAILURE_PROVENANCE_CLASSES: tuple[ProvenanceClass, ...] = (
    PRE_MCP_SUBMISSION_FAILURE,
    ACTIVE_TURN_BROWSER_TIMEOUT,
    MCP_COMPLETED_BROWSER_TIMEOUT,
    BUDGET_EXHAUSTION,
    OTHER_SUBMITTED_ERROR,
)

_TIMEOUT_INTERRUPTION_MARKERS = (
    "timeout",
    "timed out",
    "streaming interrupted",
    "connection interrupted",
    "connection lost",
    "network error",
    "something went wrong",
    "error generating a response",
)

_SUBMITTED_STATUS_VALUES = {
    "submitted",
    "running",
    "complete",
    "completed",
    "timeout",
    "timed_out",
    "settled",
    "success",
    "failed_after_submission",
}

_NOT_SUBMITTED_STATUS_VALUES = {
    "not_submitted",
    "pre_submit_failure",
    "pre_submission_failure",
    "created",
}


def dag_completed(scenario: Scenario, trace: TrialTrace) -> bool:
    """Return whether every logical node in the scenario DAG completed."""
    completed = set(trace.explicit_completed_nodes)
    return all(node.id in completed for node in scenario.dag)


def budget_exhausted(trace: TrialTrace) -> bool:
    """Return whether normalized evidence records explicit guard exhaustion."""
    if trace.budget_exhausted:
        return True
    return any(
        call.result.get("blocking_budget_exhausted") is True for call in trace.tools
    )


def browser_timeout(trace: TrialTrace) -> bool:
    """Return whether normalized evidence represents browser/turn interruption."""
    if trace.timing_status == "timeout":
        return True
    interruption = (trace.interruption_kind or "").strip().lower()
    return any(marker in interruption for marker in _TIMEOUT_INTERRUPTION_MARKERS)


def classify_failure_provenance(
    trace: TrialTrace,
    scenario: Scenario,
    *,
    submitted: bool,
    failed: bool = True,
) -> ProvenanceClass | None:
    """Classify diagnostic provenance without changing canonical inclusion.

    A non-submitted failed attempt is always pre-MCP/submission infrastructure.
    Explicit blocking-budget exhaustion takes precedence for submitted evidence.
    Browser/turn timeouts split on whether all required logical DAG work completed
    before the browser settling timeout. Submitted failures with no stronger
    provenance evidence are retained as other_submitted_error.

    Successful submitted trials have no failure provenance and return None.
    """

    if not submitted:
        return PRE_MCP_SUBMISSION_FAILURE

    if budget_exhausted(trace):
        return BUDGET_EXHAUSTION

    timed_out = browser_timeout(trace)
    if not failed and not timed_out:
        return None

    if timed_out:
        if dag_completed(scenario, trace):
            return MCP_COMPLETED_BROWSER_TIMEOUT
        return ACTIVE_TURN_BROWSER_TIMEOUT

    return OTHER_SUBMITTED_ERROR


def classify_provenance(
    trace: TrialTrace,
    scenario: Scenario,
    *,
    submitted: bool,
    failed: bool = True,
) -> ProvenanceClass | None:
    """Stable public alias for failure provenance classification."""
    return classify_failure_provenance(
        trace,
        scenario,
        submitted=submitted,
        failed=failed,
    )


def _submission_from_record(record: dict, state_dir: Path) -> bool:
    status = record.get("submission_status")
    if isinstance(status, bool):
        return status
    if isinstance(status, str):
        normalized = status.strip().lower()
        if normalized in _SUBMITTED_STATUS_VALUES:
            return True
        if normalized in _NOT_SUBMITTED_STATUS_VALUES:
            return False

    chat = record.get("chat")
    if isinstance(chat, dict) and chat.get("chat_id"):
        return True
    return (state_dir / "chat-url.txt").exists() or (
        state_dir / "chat-timing.json"
    ).exists()


def _trial_failed(record: dict, state_dir: Path) -> bool:
    if record.get("status") == "failed" or bool(record.get("error")):
        return True
    timing_path = state_dir / "chat-timing.json"
    if timing_path.exists():
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        return timing.get("status") == "timeout"
    return False


def _load_trace(state_dir: Path, scenario: Scenario) -> TrialTrace:
    trace_path = state_dir / "trace.json"
    if trace_path.exists():
        return TrialTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    return load_trial_trace(state_dir, scenario)


def classify_state_dir(
    state_dir: Path,
    scenario: Scenario | None = None,
) -> ProvenanceClass | None:
    """Classify a frozen trial directory from existing raw/normalized evidence."""
    state_dir = Path(state_dir)
    record = json.loads((state_dir / "trial.json").read_text(encoding="utf-8"))
    submitted = _submission_from_record(record, state_dir)
    if not submitted:
        # Frozen non-submitted attempts are infrastructure/submission failures even
        # when an interrupted old harness left trial.status="running".
        return PRE_MCP_SUBMISSION_FAILURE

    if scenario is None:
        scenario_id = str(record["scenario_id"])
        scenario = load_scenario(SCENARIO_ROOT / f"{scenario_id}.json")

    trace = _load_trace(state_dir, scenario)
    return classify_failure_provenance(
        trace,
        scenario,
        submitted=True,
        failed=_trial_failed(record, state_dir),
    )

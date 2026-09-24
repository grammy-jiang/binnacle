import json

from scripts import chat_scheduling_provenance as provenance
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario
from scripts.chat_scheduling_trace import ToolInterval, TrialTrace

R7 = load_scenario(SCENARIO_ROOT / "R7.json")


def _trace(
    run_id: str,
    *,
    timing_status: str = "complete",
    interruption_kind: str | None = None,
    completed: list[str] | None = None,
    budget_exhausted: bool = False,
    tools: list[ToolInterval] | None = None,
) -> TrialTrace:
    return TrialTrace(
        scenario_id="R7",
        run_id=run_id,
        nonce="nonce",
        fixture_root=f"/tmp/{run_id}",
        timing_status=timing_status,
        interruption_kind=interruption_kind,
        budget_exhausted=budget_exhausted,
        explicit_completed_nodes=completed or [],
        tools=tools or [],
    )


def test_failure_provenance_classes_are_exactly_the_frozen_contract():
    assert provenance.FAILURE_PROVENANCE_CLASSES == (
        "pre_mcp_submission_failure",
        "active_turn_browser_timeout",
        "mcp_completed_browser_timeout",
        "budget_exhaustion",
        "other_submitted_error",
    )


def test_pre_mcp_submission_failure_wins_without_submission():
    trace = _trace("pre-submit")

    assert (
        provenance.classify_failure_provenance(
            trace,
            R7,
            submitted=False,
        )
        == provenance.PRE_MCP_SUBMISSION_FAILURE
    )


def test_frozen_phase1_r7_timeout_examples_split_on_required_mcp_completion():
    active = _trace(
        "r7-20260923T211346-942d651555",
        timing_status="timeout",
        interruption_kind="timeout",
    )
    completed = _trace(
        "r7-20260923T203622-d51ce307ef",
        timing_status="timeout",
        interruption_kind="timeout",
        completed=["start_first", "wait_first", "start_second", "wait_second"],
    )

    assert (
        provenance.classify_failure_provenance(
            active,
            R7,
            submitted=True,
        )
        == provenance.ACTIVE_TURN_BROWSER_TIMEOUT
    )
    assert (
        provenance.classify_failure_provenance(
            completed,
            R7,
            submitted=True,
        )
        == provenance.MCP_COMPLETED_BROWSER_TIMEOUT
    )


def test_explicit_blocking_budget_exhaustion_has_its_own_provenance():
    status = ToolInterval(
        call_id="status-1",
        node_id="wait_first",
        tool="job_status",
        start_s=1.0,
        end_s=2.0,
        args={"job_id": "job-1", "wait_seconds": 50},
        result={
            "state": "running",
            "blocking_budget_exhausted": True,
        },
    )
    trace = _trace("budget", tools=[status])

    assert (
        provenance.classify_failure_provenance(
            trace,
            R7,
            submitted=True,
        )
        == provenance.BUDGET_EXHAUSTION
    )


def test_other_submitted_error_is_fallback_for_non_timeout_failure():
    trace = _trace("submitted-error")

    assert (
        provenance.classify_failure_provenance(
            trace,
            R7,
            submitted=True,
        )
        == provenance.OTHER_SUBMITTED_ERROR
    )


def test_successful_submitted_trial_has_no_failure_provenance():
    trace = _trace(
        "success",
        completed=["start_first", "wait_first", "start_second", "wait_second"],
    )

    assert (
        provenance.classify_failure_provenance(
            trace,
            R7,
            submitted=True,
            failed=False,
        )
        is None
    )


def test_stream_interruption_without_timeout_status_is_browser_timeout():
    trace = _trace(
        "stream",
        interruption_kind="streaming interrupted",
    )

    assert (
        provenance.classify_failure_provenance(
            trace,
            R7,
            submitted=True,
        )
        == provenance.ACTIVE_TURN_BROWSER_TIMEOUT
    )


def test_state_dir_classifies_stale_phase1_pre_submit_record_without_trace(tmp_path):
    (tmp_path / "trial.json").write_text(
        json.dumps(
            {
                "scenario_id": "R7",
                "run_id": "r7-pre-submit",
                "status": "running",
                "stage": "created",
                "chat": {},
            }
        )
    )

    assert (
        provenance.classify_state_dir(tmp_path, R7)
        == provenance.PRE_MCP_SUBMISSION_FAILURE
    )


def test_state_dir_uses_frozen_normalized_trace_for_submitted_timeout(tmp_path):
    trace = _trace(
        "r7-frozen",
        timing_status="timeout",
        interruption_kind="timeout",
        completed=["start_first", "wait_first", "start_second", "wait_second"],
    )
    (tmp_path / "trial.json").write_text(
        json.dumps(
            {
                "scenario_id": "R7",
                "run_id": "r7-frozen",
                "status": "failed",
                "error": {"type": "CalledProcessError"},
                "chat": {},
            }
        )
    )
    (tmp_path / "chat-timing.json").write_text(
        json.dumps({"status": "timeout", "wall_s": 250.0})
    )
    (tmp_path / "trace.json").write_text(trace.model_dump_json())

    assert (
        provenance.classify_state_dir(tmp_path, R7)
        == provenance.MCP_COMPLETED_BROWSER_TIMEOUT
    )

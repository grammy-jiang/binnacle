from scripts.chat_scheduling_manifest import load_all
from scripts.chat_scheduling_oracle import evaluate_oracles
from scripts.chat_scheduling_trace import ToolInterval, TrialTrace


def _call(
    call_id: str,
    node_id: str,
    tool: str,
    start_s: float,
    end_s: float,
    result: dict,
    *,
    is_error: bool = False,
) -> ToolInterval:
    return ToolInterval(
        call_id=call_id,
        node_id=node_id,
        tool=tool,
        start_s=start_s,
        end_s=end_s,
        result=result,
        is_error=is_error,
    )


def _trace(
    scenario_id: str,
    tools: list[ToolInterval],
    final_reply: str,
    *,
    budget_exhausted: bool = False,
) -> TrialTrace:
    return TrialTrace(
        scenario_id=scenario_id,
        run_id="run-1",
        nonce="N0",
        fixture_root=f"/tmp/binnacle-chat-scheduling-v2/{scenario_id}/run-1",
        timing_status="complete",
        final_reply=final_reply,
        assistant_complete=True,
        budget_exhausted=budget_exhausted,
        tools=tools,
    )


def test_r10_job_status_any_call_accepts_earlier_running_quiet_call():
    scenario = load_all()["R10"]
    trace = _trace(
        "R10",
        [
            _call(
                "start",
                "start_job",
                "run_command",
                0,
                1,
                {"job_id": "J10", "state": "running"},
            ),
            _call(
                "wait-1",
                "wait_result",
                "job_status",
                1,
                51,
                {"job_id": "J10", "state": "running", "quiet": True},
            ),
            _call(
                "wait-2",
                "wait_result",
                "job_status",
                51,
                91,
                {"job_id": "J10", "state": "exited", "exit_code": 0},
            ),
        ],
        "DONE",
    )

    failures = evaluate_oracles(
        scenario,
        trace,
        completion={"start_job": 1, "wait_result": 91},
        relations={},
    )

    assert failures == []


def test_job_status_any_call_ignores_unsuccessful_matching_calls():
    scenario = load_all()["R10"]
    trace = _trace(
        "R10",
        [
            _call(
                "start",
                "start_job",
                "run_command",
                0,
                1,
                {"job_id": "J10", "state": "running"},
            ),
            _call(
                "wait-error",
                "wait_result",
                "job_status",
                1,
                2,
                {"job_id": "J10", "state": "running", "quiet": True},
                is_error=True,
            ),
            _call(
                "wait-exit",
                "wait_result",
                "job_status",
                2,
                91,
                {"job_id": "J10", "state": "exited", "exit_code": 0},
            ),
        ],
        "DONE",
    )

    failures = evaluate_oracles(
        scenario,
        trace,
        completion={"start_job": 1, "wait_result": 91},
        relations={},
    )

    assert any(failure.startswith("job_status_any_call:") for failure in failures)


def test_r12_oracle_accepts_nonterminal_budget_exhaustion_handoff():
    scenario = load_all()["R12"]
    trace = _trace(
        "R12",
        [
            _call(
                "start",
                "start_job",
                "run_command",
                0,
                1,
                {"job_id": "J12", "state": "running"},
            ),
            _call(
                "wait-budget",
                "wait_result",
                "job_status",
                1,
                121,
                {
                    "job_id": "J12",
                    "state": "running",
                    "blocking_budget_exhausted": True,
                },
            ),
        ],
        (
            "BUDGET_EXHAUSTED job_id=J12 state=running "
            "pending=dependency resume=job_status"
        ),
        budget_exhausted=True,
    )

    failures = evaluate_oracles(
        scenario,
        trace,
        completion={"start_job": 1},
        relations={},
    )

    assert failures == []
    assert "all_nodes_complete" not in {check.type for check in scenario.oracle.checks}


def test_r12_oracle_requires_structured_budget_exhaustion_field():
    scenario = load_all()["R12"]
    trace = _trace(
        "R12",
        [
            _call(
                "start",
                "start_job",
                "run_command",
                0,
                1,
                {"job_id": "J12", "state": "running"},
            ),
            _call(
                "wait-budget",
                "wait_result",
                "job_status",
                1,
                121,
                {
                    "job_id": "J12",
                    "state": "running",
                    "blocking_budget_exhausted": False,
                },
            ),
        ],
        (
            "BUDGET_EXHAUSTED job_id=J12 state=running "
            "pending=dependency resume=job_status"
        ),
        budget_exhausted=True,
    )

    failures = evaluate_oracles(
        scenario,
        trace,
        completion={"start_job": 1},
        relations={},
    )

    assert any(failure.startswith("job_status_any_call:") for failure in failures)

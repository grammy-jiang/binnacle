from scripts.chat_scheduling_evidence import _tool_intervals
from scripts.chat_scheduling_journal import RawCall


def _status_call(**result_fields: str) -> RawCall:
    return RawCall(
        call_id="status-1",
        tool="job_status",
        turn="turn-1",
        client="openai-mcp",
        start_epoch_s=10.0,
        end_epoch_s=12.0,
        args={"job_id": "job-1", "wait_seconds": 50},
        args_raw='{"job_id":"job-1","wait_seconds":50}',
        result_fields={
            "is_error": "False",
            "waited_s": "2.0",
            "state": "running",
            **result_fields,
        },
    )


def test_normalized_result_retains_quiet_and_budget_exhaustion_true_fields():
    [interval] = _tool_intervals(
        [
            _status_call(
                quiet="True",
                blocking_budget_exhausted="True",
            )
        ],
        {"status-1": "wait_result"},
        origin_epoch_s=10.0,
    )

    assert interval.result["quiet"] is True
    assert interval.result["blocking_budget_exhausted"] is True


def test_normalized_result_retains_false_structured_fields_instead_of_dropping_them():
    [interval] = _tool_intervals(
        [
            _status_call(
                quiet="False",
                blocking_budget_exhausted="False",
            )
        ],
        {"status-1": "wait_result"},
        origin_epoch_s=10.0,
    )

    assert "quiet" in interval.result
    assert interval.result["quiet"] is False
    assert "blocking_budget_exhausted" in interval.result
    assert interval.result["blocking_budget_exhausted"] is False

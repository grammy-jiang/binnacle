from scripts.chat_scheduling_evidence import _node_matches, _tool_intervals
from scripts.chat_scheduling_journal import RawCall
from scripts.chat_scheduling_manifest import Node


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


def _repeat_wait_node(**arguments: object) -> Node:
    return Node(
        id="wait_result",
        kind="tool",
        tool="job_status",
        access="read_only",
        arguments={
            "job_id": "job-1",
            "tail_lines": 20,
            "wait_seconds": 50,
            **arguments,
        },
        allow_repeats=True,
        completion_condition="job_state=exited",
    )


def _matching_status_call(args: dict[str, object]) -> RawCall:
    return RawCall(
        call_id="status-match",
        tool="job_status",
        turn="turn-1",
        client="openai-mcp",
        start_epoch_s=10.0,
        end_epoch_s=12.0,
        args=args,
        args_raw="{}",
        result_fields={"is_error": "False", "state": "exited"},
    )


def test_repeat_wait_node_accepts_model_chosen_positive_wait_seconds():
    node = _repeat_wait_node()
    call = _matching_status_call({"job_id": "job-1", "wait_seconds": 30})

    assert _node_matches(node, call, node.arguments)


def test_repeat_wait_node_rejects_zero_or_missing_wait_seconds():
    node = _repeat_wait_node()

    assert not _node_matches(
        node,
        _matching_status_call({"job_id": "job-1", "wait_seconds": 0}),
        node.arguments,
    )
    assert not _node_matches(
        node,
        _matching_status_call({"job_id": "job-1"}),
        node.arguments,
    )


def test_repeat_wait_node_keeps_other_expected_arguments_exact():
    node = _repeat_wait_node()
    call = _matching_status_call({"job_id": "different-job", "wait_seconds": 30})

    assert not _node_matches(node, call, node.arguments)


def test_nonrepeat_job_status_keeps_wait_seconds_exact():
    node = _repeat_wait_node()
    node.allow_repeats = False
    call = _matching_status_call({"job_id": "job-1", "wait_seconds": 30})

    assert not _node_matches(node, call, node.arguments)

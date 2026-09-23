import json
from datetime import datetime

import pytest

from scripts.chat_scheduling_analyzer import analyze_trace
from scripts.chat_scheduling_evidence import load_trial_trace
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario
from scripts.chat_scheduling_trace import (
    ToolInterval,
    TrialTrace,
    interval_union_seconds,
    peak_inflight,
)


def scenario(name: str):
    return load_scenario(SCENARIO_ROOT / f"{name}.json")


def call(
    node_id: str,
    tool: str,
    start: float,
    end: float,
    *,
    args=None,
    result=None,
    blocking=None,
    tokens=0,
    result_bytes=0,
    call_id=None,
):
    return ToolInterval(
        call_id=call_id or f"{node_id}-{start}",
        node_id=node_id,
        tool=tool,
        turn="turn-1",
        start_s=start,
        end_s=end,
        args=args or {},
        result=result or {},
        tokenizer_tokens=tokens,
        result_bytes=result_bytes,
        blocking_start_s=blocking[0] if blocking else None,
        blocking_end_s=blocking[1] if blocking else None,
    )


def trace(
    name: str,
    tools: list[ToolInterval],
    *,
    wall=10.0,
    reply="DONE",
    complete=True,
    budget=False,
    interruption=None,
    final_files=None,
    mutation_scope_ok=True,
):
    return TrialTrace(
        scenario_id=name,
        run_id="run-1",
        nonce="N0",
        fixture_root=f"/tmp/binnacle-chat-scheduling-v2/{name}/run-1",
        fixture_jobs={},
        arm="B",
        wall_s=wall,
        timing_status="timeout" if interruption == "timeout" else "complete",
        final_reply=reply,
        assistant_complete=complete,
        interruption_kind=interruption,
        budget_exhausted=budget,
        user_messages=1,
        tools=tools,
        final_files=final_files or {},
        mutation_scope_ok=mutation_scope_ok,
        production_unchanged=True,
    )


def m2_parallel_tools():
    out = []
    for i in range(1, 6):
        out.append(
            call(
                f"read_{i:02d}",
                "read_file",
                1.0,
                2.0,
                args={"path": f"/tmp/x/f{i:02d}.txt"},
                tokens=10,
                result_bytes=30,
            )
        )
    for i in range(6, 9):
        out.append(
            call(
                f"read_{i:02d}",
                "read_file",
                2.1,
                3.0,
                args={"path": f"/tmp/x/f{i:02d}.txt"},
                tokens=10,
                result_bytes=30,
            )
        )
    return out


def test_interval_union_and_peak_use_half_open_semantics():
    assert interval_union_seconds([(0, 2), (1, 3), (4, 5)]) == 4
    assert peak_inflight([(0, 2), (0.5, 1.5), (2, 3)]) == 2


def test_m2_parallel_trace_scores_overlap_wall_and_costs():
    metrics = analyze_trace(scenario("M2"), trace("M2", m2_parallel_tools(), wall=7))

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True
    assert metrics.read_only_peak_inflight == 5
    assert metrics.eligible_read_only_calls == 8
    assert metrics.overlapped_eligible_read_only_calls == 8
    assert metrics.eligible_read_only_overlap_ratio == 1.0
    assert metrics.tool_result_tokens == 80
    assert metrics.tool_result_bytes == 240
    assert metrics.wall_s == 7


def test_m2_fully_serial_trace_has_zero_eligible_overlap():
    tools = [
        call(
            f"read_{i:02d}",
            "read_file",
            float(i),
            float(i) + 0.5,
            args={"path": f"/tmp/x/f{i:02d}.txt"},
        )
        for i in range(1, 9)
    ]

    metrics = analyze_trace(scenario("M2"), trace("M2", tools))

    assert metrics.read_only_peak_inflight == 1
    assert metrics.eligible_read_only_calls == 8
    assert metrics.overlapped_eligible_read_only_calls == 0
    assert metrics.eligible_read_only_overlap_ratio == 0.0


def test_m3_avoidable_idle_is_pending_read_time_inside_blocking_wait():
    tools = [
        call(
            "slow_status",
            "job_status",
            0,
            5,
            args={"job_id": "J", "wait_seconds": 5},
            result={"state": "running", "waited_s": 5.0},
            blocking=(0, 5),
        )
    ]
    for i in range(1, 6):
        tools.append(
            call(
                f"read_{i}",
                "read_file",
                2,
                2.5,
                args={"path": f"/tmp/x/f{i}.txt"},
            )
        )

    metrics = analyze_trace(scenario("M3"), trace("M3", tools, wall=7))

    assert metrics.correctness_passed is True
    assert metrics.blocking_wall_s == 5
    assert metrics.avoidable_idle_wall_s == 2
    assert metrics.read_only_peak_inflight == 6


def test_m3_good_submission_has_only_small_dispatch_idle_gap():
    tools = [
        call(
            "slow_status",
            "job_status",
            0,
            5,
            args={"job_id": "J", "wait_seconds": 5},
            result={"state": "running", "waited_s": 5.0},
            blocking=(0, 5),
        )
    ]
    for i in range(1, 6):
        tools.append(
            call(
                f"read_{i}",
                "read_file",
                0.2,
                0.7,
                args={"path": f"/tmp/x/f{i}.txt"},
            )
        )

    metrics = analyze_trace(scenario("M3"), trace("M3", tools, wall=7))

    assert metrics.avoidable_idle_wall_s == pytest.approx(0.2)


def r5_start():
    return call(
        "start_job",
        "run_command",
        0,
        1,
        args={"workdir": "/tmp/x", "background": True, "wait_seconds": 1},
        result={"job_id": "J", "state": "running", "background_job": True},
    )


def test_r5_repeated_status_is_legitimate_logical_barrier_not_duplicate():
    tools = [
        r5_start(),
        call(
            "wait_result",
            "job_status",
            1,
            51,
            args={"job_id": "J", "wait_seconds": 50},
            result={"state": "running", "waited_s": 50.0},
            blocking=(1, 51),
            call_id="wait-1",
        ),
        call(
            "wait_result",
            "job_status",
            52,
            77,
            args={"job_id": "J", "wait_seconds": 50},
            result={"state": "exited", "exit_code": 0, "waited_s": 25.0},
            blocking=(52, 77),
            call_id="wait-2",
        ),
    ]
    t = trace("R5", tools, wall=80, reply="R5-N0")
    metrics = analyze_trace(scenario("R5"), t)

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True
    assert metrics.job_status_calls == 2
    assert metrics.positive_job_status_calls == 2
    assert metrics.blocking_wall_s == 75
    assert metrics.duplicate_calls == 0
    assert metrics.redundant_exact_calls == 0


def test_premature_handoff_is_not_confused_with_correctness_or_interruption():
    t = trace("R5", [r5_start()], reply="Job still running.", complete=True)
    metrics = analyze_trace(scenario("R5"), t)

    assert metrics.correctness_passed is False
    assert metrics.same_prompt_completion is False
    assert metrics.premature_handoff is True
    assert metrics.budget_exhaustion_handoff is False
    assert metrics.manual_continuations_required == 1
    assert metrics.interrupted is False


def test_budget_exhaustion_handoff_is_separate_from_premature_handoff():
    t = trace("R5", [r5_start()], reply="Budget exhausted.", budget=True)
    metrics = analyze_trace(scenario("R5"), t)

    assert metrics.premature_handoff is False
    assert metrics.budget_exhaustion_handoff is True
    assert metrics.manual_continuations_required == 1


def test_interruption_is_not_counted_as_premature_handoff():
    t = trace(
        "R5",
        [r5_start()],
        reply="",
        complete=False,
        interruption="timeout",
    )
    metrics = analyze_trace(scenario("R5"), t)

    assert metrics.interrupted is True
    assert metrics.interruption_kind == "timeout"
    assert metrics.premature_handoff is False
    assert metrics.budget_exhaustion_handoff is False


def test_wrong_final_reply_after_terminal_work_is_correctness_not_handoff():
    tools = [
        call(f"read_{i:02d}", "read_file", i / 10, i / 10 + 0.2) for i in range(1, 9)
    ]
    metrics = analyze_trace(
        scenario("M2"),
        trace("M2", tools, reply="WRONG", complete=True),
    )

    assert metrics.correctness_passed is False
    assert metrics.premature_handoff is False
    assert metrics.same_prompt_completion is False


def test_nonrepeat_duplicate_and_exact_redundancy_are_counted():
    tools = m2_parallel_tools()
    tools.append(
        call(
            "read_01",
            "read_file",
            4,
            4.2,
            args={"path": "/tmp/x/f01.txt"},
            call_id="duplicate",
        )
    )
    metrics = analyze_trace(scenario("M2"), trace("M2", tools))

    assert metrics.duplicate_calls == 1
    assert metrics.redundant_exact_calls == 1


def test_r8_oracles_cover_reasoning_free_edit_journey_and_final_file():
    root = "/tmp/binnacle-chat-scheduling-v2/R8/run-1"
    tools = [
        call("read_readme", "read_file", 0, 0.2),
        call("read_app", "read_file", 0, 0.2),
        call("read_test", "read_file", 0, 0.2),
        call(
            "edit_app",
            "run_command",
            0.5,
            1,
            args={"workdir": root, "command": "python3 -c 'edit'"},
            result={"exit_code": 0},
        ),
        call(
            "focused_test",
            "run_command",
            1.1,
            1.5,
            args={"workdir": root, "command": "python3 test_app.py"},
            result={"exit_code": 0},
        ),
        call("verify_app", "read_file", 1.6, 1.8),
    ]
    t = trace(
        "R8",
        tools,
        wall=2,
        final_files={"app.py": "def message():\n    return 'AFTER-N0'\n"},
        mutation_scope_ok=True,
    )
    metrics = analyze_trace(scenario("R8"), t)

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True


def _conversation_json() -> dict:
    user = {
        "message": {
            "author": {"role": "user"},
            "status": "finished_successfully",
            "content": {"parts": ["benchmark"]},
            "metadata": {},
        }
    }
    assistant = {
        "message": {
            "author": {"role": "assistant"},
            "status": "finished_successfully",
            "content": {"parts": ["DONE"]},
            "metadata": {"is_complete": True},
        }
    }
    return {
        "current_node": "a",
        "mapping": {"u": user, "a": assistant},
    }


def test_real_evidence_loader_pairs_journal_calls_and_assigns_m2_nodes(tmp_path):
    root = "/tmp/binnacle-chat-scheduling-v2/M2/run-evidence"
    record = {
        "run_id": "run-evidence",
        "nonce": "NEVIDENCE",
        "scenario_id": "M2",
        "arm": "A",
        "trial_start_epoch_s": 0,
        "fixture": {"root": root, "jobs": {}},
        "production_unchanged": True,
        "error": None,
    }
    (tmp_path / "trial.json").write_text(json.dumps(record))
    sent = datetime.fromisoformat("2026-09-23T12:00:00").astimezone().timestamp()
    (tmp_path / "chat-timing.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "sent_at_epoch_s": sent,
                "settled_at_epoch_s": sent + 4,
                "wall_s": 4.0,
            }
        )
    )
    (tmp_path / "conversation.json").write_text(json.dumps(_conversation_json()))
    (tmp_path / "fixture-final.json").write_text(
        json.dumps({"root": root, "final_files": {}})
    )

    lines = []
    starts = [1, 1, 1, 1, 1, 2.1, 2.1, 2.1]
    ends = [2, 2, 2, 2, 2, 3, 3, 3]
    for i, (start, end) in enumerate(zip(starts, ends, strict=True), 1):
        call_id = f"c{i}"
        path = f"{root}/f{i:02d}.txt"
        start_ts = (
            datetime.fromtimestamp(sent + start).astimezone().replace(tzinfo=None)
        )
        end_ts = datetime.fromtimestamp(sent + end).astimezone().replace(tzinfo=None)
        lines.append(
            f"{start_ts.isoformat(timespec='milliseconds')} INFO: event=tool_call "
            f"call={call_id} tool=read_file client=openai-mcp session=s request_id=0 "
            f"turn=base/{i} oai_session=o args_chars=40 args="
            + json.dumps({"path": path}, separators=(",", ":"))
        )
        lines.append(
            f"{end_ts.isoformat(timespec='milliseconds')} INFO: event=tool_result "
            f"call={call_id} tool=read_file client=openai-mcp session=s request_id=0 "
            f"turn=base/{i} oai_session=o duration_ms=1000 is_error=False "
            f"content_chars=10 structured_bytes=20 est_tokens=5 tokenizer_tokens=7"
        )
    lines.sort()
    (tmp_path / "journal.log").write_text("\n".join(lines) + "\n")

    loaded = load_trial_trace(tmp_path, scenario("M2"))
    metrics = analyze_trace(scenario("M2"), loaded)

    assert len(loaded.tools) == 8
    assert {tool.node_id for tool in loaded.tools} == {
        f"read_{i:02d}" for i in range(1, 9)
    }
    assert metrics.correctness_passed is True
    assert metrics.read_only_peak_inflight == 5
    assert metrics.eligible_read_only_overlap_ratio == 1.0
    assert metrics.tool_result_tokens == 56
    assert metrics.tool_result_bytes == 240


def test_real_wait_interval_uses_same_rounding_as_tool_interval():
    from scripts.chat_scheduling_evidence import _tool_intervals
    from scripts.chat_scheduling_journal import RawCall

    raw = RawCall(
        call_id="wait-precision",
        tool="job_status",
        turn="turn-1",
        client="openai-mcp",
        start_epoch_s=19.797935932159422,
        end_epoch_s=23.315185932159422,
        args={"job_id": "J", "wait_seconds": 5},
        args_raw='{"job_id":"J","wait_seconds":5}',
        result_fields={"waited_s": "3.493", "is_error": "False"},
    )

    [interval] = _tool_intervals(
        [raw],
        {"wait-precision": "slow_status"},
        origin_epoch_s=0.0,
    )

    assert interval.blocking_start_s == interval.start_s
    assert interval.blocking_end_s is not None
    assert interval.blocking_end_s <= interval.end_s

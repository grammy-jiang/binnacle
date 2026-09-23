from pathlib import Path

from scripts.chat_scheduling_analyzer import analyze_trace
from scripts.chat_scheduling_evidence import _assign_nodes
from scripts.chat_scheduling_journal import RawCall
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario
from scripts.chat_scheduling_runtime import TrialIdentity
from scripts.chat_scheduling_trace import ToolInterval, TrialTrace


def test_tail_lines_does_not_change_logical_job_status_identity():
    scenario = load_scenario(SCENARIO_ROOT / "R5.json")
    root = "/tmp/binnacle-chat-scheduling-v2/R5/run-1"
    start = ToolInterval(
        call_id="start",
        node_id="start_job",
        tool="run_command",
        turn="turn-1",
        start_s=0,
        end_s=1,
        args={
            "workdir": root,
            "background": True,
            "wait_seconds": 1,
            "command": ("python3 -c 'import time; time.sleep(25); print(\"R5-N0\")'"),
        },
        result={"job_id": "J", "state": "running"},
    )
    wait = ToolInterval(
        call_id="wait",
        node_id="wait_result",
        tool="job_status",
        turn="turn-1",
        start_s=2,
        end_s=25,
        args={"job_id": "J", "wait_seconds": 50, "tail_lines": 100},
        result={"job_id": "J", "state": "exited", "exit_code": 0, "waited_s": 23.0},
        blocking_start_s=2,
        blocking_end_s=25,
    )
    trace = TrialTrace(
        scenario_id="R5",
        run_id="run-1",
        nonce="N0",
        fixture_root=root,
        arm="B",
        wall_s=30,
        timing_status="complete",
        final_reply="R5-N0",
        assistant_complete=True,
        user_messages=1,
        tools=[start, wait],
        mutation_scope_ok=True,
        production_unchanged=True,
    )

    metrics = analyze_trace(scenario, trace)

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True


def test_r8_combined_edit_and_test_command_satisfies_test_oracle():
    scenario = load_scenario(SCENARIO_ROOT / "R8.json")
    root = "/tmp/binnacle-chat-scheduling-v2/R8/run-r8"
    tools = [
        ToolInterval(
            call_id=f"read-{name}",
            node_id=node,
            tool="read_file",
            turn="turn-1",
            start_s=0,
            end_s=1,
            args={"path": f"{root}/{name}"},
            result={},
        )
        for name, node in (
            ("README.md", "read_readme"),
            ("app.py", "read_app"),
            ("test_app.py", "read_test"),
        )
    ]
    tools.extend(
        [
            ToolInterval(
                call_id="edit-test",
                node_id="edit_app",
                tool="run_command",
                turn="turn-1",
                start_s=2,
                end_s=3,
                args={
                    "workdir": root,
                    "command": "printf AFTER-N0 > app.py && python test_app.py",
                },
                result={"exit_code": 0},
            ),
            ToolInterval(
                call_id="verify",
                node_id="verify_app",
                tool="read_file",
                turn="turn-1",
                start_s=4,
                end_s=5,
                args={"path": f"{root}/app.py"},
                result={},
            ),
        ]
    )
    trace = TrialTrace(
        scenario_id="R8",
        run_id="run-r8",
        nonce="N0",
        fixture_root=root,
        arm="B",
        wall_s=6,
        timing_status="complete",
        final_reply="DONE",
        assistant_complete=True,
        user_messages=1,
        tools=tools,
        final_files={"app.py": "def message():\n    return 'AFTER-N0'\n"},
        mutation_scope_ok=True,
        production_unchanged=True,
    )

    metrics = analyze_trace(scenario, trace)

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True


def test_r9_combined_fix_and_retest_command_satisfies_recovery_oracle():
    scenario = load_scenario(SCENARIO_ROOT / "R9.json")
    root = "/tmp/binnacle-chat-scheduling-v2/R9/run-r9"
    tools = [
        ToolInterval(
            call_id="initial",
            node_id=None,
            tool="run_command",
            turn="turn-1",
            start_s=0,
            end_s=1,
            args={"workdir": root, "command": "python3 test_math_utils.py"},
            result={"exit_code": 1},
        ),
        ToolInterval(
            call_id="source",
            node_id="read_source",
            tool="read_file",
            turn="turn-1",
            start_s=2,
            end_s=3,
            args={"path": f"{root}/math_utils.py"},
            result={},
        ),
        ToolInterval(
            call_id="test",
            node_id="read_test",
            tool="read_file",
            turn="turn-1",
            start_s=2,
            end_s=3,
            args={"path": f"{root}/test_math_utils.py"},
            result={},
        ),
        ToolInterval(
            call_id="fix-test",
            node_id="fix_source",
            tool="run_command",
            turn="turn-1",
            start_s=4,
            end_s=5,
            args={
                "workdir": root,
                "command": "sed -i s/bad/good/ math_utils.py && python3 test_math_utils.py",
            },
            result={"exit_code": 0},
        ),
        ToolInterval(
            call_id="verify",
            node_id="verify_source",
            tool="read_file",
            turn="turn-1",
            start_s=6,
            end_s=7,
            args={"path": f"{root}/math_utils.py"},
            result={},
        ),
    ]
    trace = TrialTrace(
        scenario_id="R9",
        run_id="run-r9",
        nonce="N0",
        fixture_root=root,
        arm="B",
        wall_s=8,
        timing_status="complete",
        final_reply="DONE",
        assistant_complete=True,
        user_messages=1,
        tools=tools,
        final_files={
            "math_utils.py": "def clamp(value, low, high):\n    return max(low, min(high, value))\n"
        },
        mutation_scope_ok=True,
        production_unchanged=True,
    )

    metrics = analyze_trace(scenario, trace)

    assert metrics.correctness_passed is True
    assert metrics.same_prompt_completion is True


def test_r7_repeated_wait_duration_does_not_change_dependency_identity():
    scenario = load_scenario(SCENARIO_ROOT / "R7.json")
    root = Path("/tmp/binnacle-chat-scheduling-v2/R7/run-r7")
    identity = TrialIdentity(scenario_id="R7", run_id="run-r7", nonce="N0")
    command_a = "python3 -c 'import time; time.sleep(60); print(\"R7-A-N0\")'"
    command_b = "python3 -c 'import time; time.sleep(75); print(\"R7-B-N0\")'"

    calls = [
        RawCall(
            call_id="start-a",
            tool="run_command",
            turn="t",
            client="openai-mcp",
            start_epoch_s=0,
            args={
                "background": True,
                "wait_seconds": 1,
                "workdir": str(root),
                "command": command_a,
            },
            args_raw="",
            end_epoch_s=1,
            result_fields={"job_id": "JA", "state": "running"},
        ),
        RawCall(
            call_id="wait-a-1",
            tool="job_status",
            turn="t",
            client="openai-mcp",
            start_epoch_s=2,
            args={"job_id": "JA", "wait_seconds": 50, "tail_lines": 20},
            args_raw="",
            end_epoch_s=52,
            result_fields={"job_id": "JA", "state": "running", "waited_s": "50"},
        ),
        RawCall(
            call_id="wait-a-2",
            tool="job_status",
            turn="t",
            client="openai-mcp",
            start_epoch_s=53,
            args={"job_id": "JA", "wait_seconds": 10, "tail_lines": 20},
            args_raw="",
            end_epoch_s=60,
            result_fields={
                "job_id": "JA",
                "state": "exited",
                "exit_code": "0",
                "waited_s": "7",
            },
        ),
        RawCall(
            call_id="start-b",
            tool="run_command",
            turn="t",
            client="openai-mcp",
            start_epoch_s=61,
            args={
                "background": True,
                "wait_seconds": 1,
                "workdir": str(root),
                "command": command_b,
            },
            args_raw="",
            end_epoch_s=62,
            result_fields={"job_id": "JB", "state": "running"},
        ),
        RawCall(
            call_id="wait-b-1",
            tool="job_status",
            turn="t",
            client="openai-mcp",
            start_epoch_s=63,
            args={"job_id": "JB", "wait_seconds": 50, "tail_lines": 20},
            args_raw="",
            end_epoch_s=113,
            result_fields={"job_id": "JB", "state": "running", "waited_s": "50"},
        ),
        RawCall(
            call_id="wait-b-2",
            tool="job_status",
            turn="t",
            client="openai-mcp",
            start_epoch_s=114,
            args={"job_id": "JB", "wait_seconds": 30, "tail_lines": 20},
            args_raw="",
            end_epoch_s=135,
            result_fields={
                "job_id": "JB",
                "state": "exited",
                "exit_code": "0",
                "waited_s": "21",
            },
        ),
    ]

    assigned, completed, _ = _assign_nodes(scenario, calls, identity, root, {})

    assert assigned["wait-a-2"] == "wait_first"
    assert assigned["wait-b-2"] == "wait_second"
    assert completed == {"start_first", "wait_first", "start_second", "wait_second"}

from scripts.chat_scheduling_analyzer import analyze_trace
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario
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

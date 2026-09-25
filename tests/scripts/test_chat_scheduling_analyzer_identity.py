import hashlib
import json
from pathlib import Path

import pytest

from scripts import chat_scheduling_runtime as runtime
from scripts.chat_scheduling_analyzer import analyze_trace
from scripts.chat_scheduling_evidence import (
    EvidenceIntegrityError,
    _assign_nodes,
    load_trial_trace,
)
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


def _phase4_log_pair(run, nonce, turn, prefix, job):
    root = f"/tmp/binnacle-chat-scheduling-v2/R5/{run}"
    args = json.dumps(
        {
            "background": True,
            "command": f"printf {nonce}",
            "wait_seconds": 1,
            "workdir": root,
        },
        separators=(",", ":"),
    )
    wait = json.dumps({"job_id": job, "wait_seconds": 50}, separators=(",", ":"))
    server = [
        f"2026-09-25T12:00:00.000 INFO: event=tool_call call={prefix}a tool=run_command client=openai-mcp turn={turn}/1 args={args}",
        f"2026-09-25T12:00:01.000 INFO: event=tool_result call={prefix}a tool=run_command client=openai-mcp turn={turn}/1 is_error=False job_id={job} state=running",
        f"2026-09-25T12:00:02.000 INFO: event=tool_call call={prefix}b tool=job_status client=openai-mcp turn={turn}/2 args={wait}",
        f"2026-09-25T12:00:03.000 INFO: event=tool_result call={prefix}b tool=job_status client=openai-mcp turn={turn}/2 is_error=False job_id={job} state=exited exit_code=0 waited_s=1",
    ]
    manager = [
        f"2026-09-25T12:00:00.500 INFO: event=job_start job_id={job}",
        f"2026-09-25T12:00:03.500 INFO: event=job_exit job_id={job} exit_code=0 signal=None",
    ]
    return server, manager


def _phase4_state(path, run, nonce, arm, endpoint, budget, server, manager, primary=""):
    path.mkdir()
    root = f"/tmp/binnacle-chat-scheduling-v2/R5/{run}"
    trial = {"phase": 4, "run_id": run, "nonce": nonce, "scenario_id": "R5", "arm": arm, "budget_s": budget, "endpoint_id": endpoint, "fixture": {"root": root, "jobs": {}}, "production_unchanged": True}  # fmt: skip
    (path / "trial.json").write_text(json.dumps(trial))
    (path / "journal.log").write_text(primary)
    payloads = {"server": "\n".join(server) + "\n", "manager": "\n".join(manager) + "\n", "tunnel": "health C300-FOREIGN-NONCE\n"}  # fmt: skip
    evidence = {"endpoint_id": endpoint, "logical_arm": arm, "trial_run_id": run, "trial_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(), "evidence_integrity_error": False}  # fmt: skip
    for name, value in payloads.items():
        data = value.encode()
        (path / f"endpoint-{name}.log").write_bytes(data)
        evidence[f"{name}_log_start_offset"] = 0
        evidence[f"{name}_log_end_offset"] = len(data)
        evidence[f"{name}_log_sha256"] = hashlib.sha256(data).hexdigest()
    (path / "endpoint-evidence.json").write_text(json.dumps(evidence))


def test_phase4_same_endpoint_interleaving_normalizes_disjoint_identity(tmp_path):
    a_s, a_m = _phase4_log_pair("run-a", "NONCE-A", "turn-a", "a", "JOB-A")
    b_s, b_m = _phase4_log_pair("run-b", "NONCE-B", "turn-b", "b", "JOB-B")
    for name, run, nonce in (("a", "run-a", "NONCE-A"), ("b", "run-b", "NONCE-B")):
        state = tmp_path / name
        _phase4_state(state, run, nonce, "C", "C300", 300, a_s + b_s, a_m + b_m)
        trace = load_trial_trace(state, load_scenario(SCENARIO_ROOT / "R5.json"))
        expected = name
        assert {call.turn for call in trace.tools} == {f"turn-{expected}"}
        assert {job.job_id for job in trace.jobs} == {f"JOB-{expected.upper()}"}
        evidence = json.loads((state / "endpoint-evidence.json").read_text())
        assert evidence["raw_foreign_turns_present"] is True
        assert evidence["normalized_foreign_calls"] == 0


@pytest.mark.parametrize(
    ("arm", "endpoint", "budget"),
    [
        ("A", "A", None),
        ("B", "B", None),
        ("C", "C120", 120),
        ("C", "C600", 600),
        ("H", "H", 10),
    ],
)
def test_phase4_c300_foreign_nonce_and_primary_journal_never_normalize(
    tmp_path, arm, endpoint, budget
):
    local_s, local_m = _phase4_log_pair(
        "local", f"LOCAL-{endpoint}", "local-turn", "l", "LOCAL-JOB"
    )
    foreign_s, foreign_m = _phase4_log_pair(
        "foreign", "C300-FOREIGN-NONCE", "foreign-turn", "f", "C300-JOB"
    )
    state = tmp_path / endpoint
    _phase4_state(
        state,
        "local",
        f"LOCAL-{endpoint}",
        arm,
        endpoint,
        budget,
        local_s + foreign_s,
        local_m + foreign_m,
        "\n".join(foreign_s),
    )
    trace = load_trial_trace(state, load_scenario(SCENARIO_ROOT / "R5.json"))
    serialized = json.dumps(trace.model_dump(mode="json"))
    assert "C300-FOREIGN-NONCE" not in serialized and "C300-JOB" not in serialized
    assert {call.turn for call in trace.tools} == {"local-turn"}


@pytest.mark.parametrize("ambiguous", [False, True])
def test_phase4_zero_or_ambiguous_base_turn_marks_integrity_error(tmp_path, ambiguous):
    if ambiguous:
        one_s, one_m = _phase4_log_pair("local", "NONCE", "one", "a", "J1")
        two_s, two_m = _phase4_log_pair("local", "NONCE", "two", "b", "J2")
        server, manager = one_s + two_s, one_m + two_m
    else:
        server, manager = _phase4_log_pair("foreign", "OTHER", "foreign", "f", "JX")
    state = tmp_path / str(ambiguous)
    _phase4_state(state, "local", "NONCE", "C", "C300", 300, server, manager)
    with pytest.raises(EvidenceIntegrityError, match="base turn matches"):
        load_trial_trace(state, load_scenario(SCENARIO_ROOT / "R5.json"))
    assert (
        json.loads((state / "trial.json").read_text())["evidence_integrity_error"]
        is True
    )


def _resolver_env(monkeypatch, arm="B", endpoint="B", budget=None):
    source, pid, profile = "0" * 40, 7, f"profile-{endpoint}"
    base = {
        "endpoint_id": endpoint,
        "logical_arm": arm,
        "budget_s": budget,
        "port": 8110,
        "tunnel_profile": profile,
    }
    manifest = {**base, "phase4_source_head": source, "base_topology_sha256": "TOP", "project_name": f"project-{endpoint}", "project_id": f"pid-{endpoint}", "connector_logical_name": f"connector-{endpoint}", "attachment_status": "verified", "instruction_sha256": "INST"}  # fmt: skip
    live = {**base, "phase4_source_head": source, "token_path": "/token", "server_log_path": "/server", "manager_log_path": "/manager", "tunnel_log_path": "/tunnel", "server_pid": pid, "manager_pid": pid, "tunnel_pid": pid, "process_start_identity": {name: f"{pid}:123" for name in ("server", "manager", "tunnel")}}  # fmt: skip
    docs = {"/baseline": {"phase4_source_head": source, "benchmark_source_project": {"instructions_snapshot_path": "/A", "instructions_sha256": "INST"}, "canonical_v2_instruction": {"path": "/V", "sha256": "INST"}, "model_thinking": {"thinking_effort": "max"}}, "/topology": {"phase4_source_head": source, "endpoints": {endpoint: base}}, f"/lanes/{endpoint}.json": manifest, "/registry": {"phase4_source_head": source, "endpoints": {endpoint: live}}}  # fmt: skip

    def fake_read(path, *args, **kwargs):
        if str(path).startswith("/proc/"):
            return "7 (x) " + " ".join(["S"] + ["0"] * 18 + ["123"])
        return json.dumps(docs[str(path)])

    monkeypatch.setattr(Path, "read_text", fake_read)
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(runtime, "_file_sha", lambda path: {"/topology": "TOP", "/lanes/" + endpoint + ".json": "LANE", "/registry": "REG", "/A": "INST", "/V": "INST"}[str(path)])  # fmt: skip
    sources = {
        "baseline": "/baseline",
        "topology": "/topology",
        "lanes": "/lanes",
        "registry": "/registry",
        "admission_revision": "r01",
    }
    return sources, docs


def test_phase4_resolver_rejects_private_identity_mismatch_and_stale_pid(monkeypatch):
    sources, docs = _resolver_env(monkeypatch)
    selected = runtime.resolve_phase4_endpoint("B", None, "B", sources=sources)
    assert selected["runtime_registry_sha256"] == "REG"
    docs["/registry"]["endpoints"]["B"]["port"] = 8111
    with pytest.raises(runtime.HarnessError, match="identity mismatch"):
        runtime.resolve_phase4_endpoint("B", None, "B", sources=sources)
    docs["/registry"]["endpoints"]["B"]["port"] = 8110
    docs["/registry"]["endpoints"]["B"]["process_start_identity"]["server"] = "7:stale"
    with pytest.raises(runtime.HarnessError, match="stale server"):
        runtime.resolve_phase4_endpoint("B", None, "B", sources=sources)
    sources, _ = _resolver_env(monkeypatch, arm="A", endpoint="A")
    assert (
        runtime.resolve_phase4_endpoint("A", None, "A", sources=sources)[
            "instruction_sha256"
        ]
        == "INST"
    )

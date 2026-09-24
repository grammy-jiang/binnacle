from copy import deepcopy

import pytest
from pydantic import ValidationError

from scripts.chat_scheduling_manifest import (
    CATALOG_SCENARIOS,
    EXPECTED_PHASE1_STEPS,
    Scenario,
    load_all,
)


def _minimal() -> dict:
    return {
        "schema_version": 1,
        "id": "M1",
        "benchmark_class": "micro",
        "phase1_step": "1.2",
        "title": "minimal",
        "purpose": "test",
        "expected_runtime_s": 1,
        "max_turn_runtime_s": 2,
        "fixture": {
            "kind": "ephemeral_dir",
            "root_template": "/tmp/x/{run_id}",
            "files": [],
            "jobs": [],
            "allowed_mutation_globs": [],
            "production_mutation_allowed": False,
        },
        "prompt_template": "read",
        "dag": [
            {
                "id": "read",
                "kind": "tool",
                "tool": "read_file",
                "access": "read_only",
                "depends_on": [],
                "arguments": {"path": "{root}/x"},
                "allow_repeats": False,
                "completion_condition": None,
            }
        ],
        "oracle": {
            "terminal_state": "all_required_nodes_complete",
            "checks": [{"type": "all_nodes_complete", "params": {}}],
        },
        "metric_tags": ["wall_time"],
    }


def test_catalog_is_exact_and_all_manifests_validate():
    scenarios = load_all()

    assert set(scenarios) == CATALOG_SCENARIOS
    assert {key: value.phase1_step for key, value in scenarios.items()} == (
        EXPECTED_PHASE1_STEPS
    )


def test_r1_discovery_identity_uses_semantic_arguments_only():
    scenario = load_all()["R1"]
    discover = next(node for node in scenario.dag if node.id == "discover")

    assert discover.tool == "search_text"
    assert discover.arguments == {
        "path": "{root}",
        "pattern": "discover-{nonce}",
    }


def test_m3_slow_fixture_outlives_the_entire_micro_turn():
    scenario = load_all()["M3"]

    assert scenario.max_turn_runtime_s == 75
    assert "time.sleep(300)" in scenario.fixture.jobs[0].command


def test_phase1_single_turn_bounds_are_explicit_and_reasonable():
    scenarios = load_all()

    for scenario_id, scenario in scenarios.items():
        assert 0 <= scenario.expected_runtime_s <= scenario.max_turn_runtime_s
        if scenario_id != "R12":
            assert scenario.max_turn_runtime_s <= 240

    assert scenarios["R7"].max_turn_runtime_s == 230
    assert scenarios["R12"].max_turn_runtime_s == 690


def test_mutating_scenarios_are_disposable_and_scoped():
    scenarios = load_all()

    for scenario in scenarios.values():
        mutating = [
            node
            for node in scenario.dag
            if node.kind == "tool" and node.access == "non_read_only"
        ]
        assert scenario.fixture.production_mutation_allowed is False
        if mutating:
            assert scenario.fixture.kind != "none"
            assert scenario.fixture.allowed_mutation_globs


def test_repeating_nodes_are_only_logical_job_status_barriers():
    scenarios = load_all()

    repeating = [
        (scenario.id, node)
        for scenario in scenarios.values()
        for node in scenario.dag
        if node.allow_repeats
    ]
    assert {(scenario_id, node.id) for scenario_id, node in repeating} == {
        ("M6", "barrier_wait"),
        ("R3", "validation_result"),
        ("R4", "validation_result"),
        ("R5", "wait_result"),
        ("R6", "wait_result"),
        ("R7", "wait_first"),
        ("R7", "wait_second"),
        ("R10", "wait_result"),
        ("R12", "wait_result"),
    }
    assert all(node.tool == "job_status" for _, node in repeating)
    assert all(node.completion_condition == "job_state=exited" for _, node in repeating)


def test_cycle_is_rejected():
    data = _minimal()
    data["dag"] = [
        {
            "id": "a",
            "kind": "reasoning",
            "tool": None,
            "access": "reasoning",
            "depends_on": ["b"],
            "arguments": {},
            "allow_repeats": False,
            "completion_condition": None,
        },
        {
            "id": "b",
            "kind": "reasoning",
            "tool": None,
            "access": "reasoning",
            "depends_on": ["a"],
            "arguments": {},
            "allow_repeats": False,
            "completion_condition": None,
        },
    ]

    with pytest.raises(ValidationError, match="cycle"):
        Scenario.model_validate(data)


def test_production_mutation_is_rejected():
    data = _minimal()
    data["fixture"]["production_mutation_allowed"] = True

    with pytest.raises(ValidationError, match="production mutation"):
        Scenario.model_validate(data)


def test_non_status_repeat_is_rejected():
    data = _minimal()
    data["dag"][0]["allow_repeats"] = True

    with pytest.raises(ValidationError, match="only job_status"):
        Scenario.model_validate(data)


def test_mutating_tool_without_scope_is_rejected():
    data = deepcopy(_minimal())
    data["dag"] = [
        {
            "id": "run",
            "kind": "tool",
            "tool": "run_command",
            "access": "non_read_only",
            "depends_on": [],
            "arguments": {"command": "true"},
            "allow_repeats": False,
            "completion_condition": None,
        }
    ]

    with pytest.raises(ValidationError, match="allowed_mutation_globs"):
        Scenario.model_validate(data)


def test_overlong_single_turn_is_rejected():
    data = _minimal()
    data["max_turn_runtime_s"] = 241

    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_readonly_annotation_truth_is_enforced():
    data = _minimal()
    data["dag"][0]["access"] = "non_read_only"

    with pytest.raises(ValidationError, match="must be access=read_only"):
        Scenario.model_validate(data)


def test_unknown_placeholder_is_rejected():
    data = _minimal()
    data["prompt_template"] = "read {mystery}"

    with pytest.raises(ValidationError, match="unknown placeholder"):
        Scenario.model_validate(data)


def test_fixture_path_escape_is_rejected():
    data = _minimal()
    data["fixture"]["files"] = [{"path": "../escape.txt", "content": "x"}]

    with pytest.raises(ValidationError, match="stay relative"):
        Scenario.model_validate(data)


def test_mutation_glob_escape_is_rejected():
    data = _minimal()
    data["fixture"]["allowed_mutation_globs"] = ["/home/user/**"]

    with pytest.raises(ValidationError, match="must stay under"):
        Scenario.model_validate(data)


import subprocess
import sys


def _render_fixture(scenario_id: str, root, nonce: str = "N0"):
    scenario = load_all()[scenario_id]
    for item in scenario.fixture.files:
        path = root / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.content.replace("{nonce}", nonce))
    return scenario


def test_r8_fixture_has_deterministic_before_after_oracle(tmp_path):
    _render_fixture("R8", tmp_path)

    before = subprocess.run(
        [sys.executable, "test_app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert before.returncode != 0

    app = tmp_path / "app.py"
    app.write_text(app.read_text().replace("BEFORE-N0", "AFTER-N0"))
    after = subprocess.run(
        [sys.executable, "test_app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert after.returncode == 0
    assert "R8-test-pass" in after.stdout


def test_r9_fixture_has_deterministic_failure_and_fix(tmp_path):
    _render_fixture("R9", tmp_path)

    before = subprocess.run(
        [sys.executable, "test_math_utils.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert before.returncode != 0

    source = tmp_path / "math_utils.py"
    source.write_text(
        source.read_text().replace(
            "return min(low, max(high, value))",
            "return max(low, min(high, value))",
        )
    )
    after = subprocess.run(
        [sys.executable, "test_math_utils.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert after.returncode == 0
    assert "R9-test-pass" in after.stdout


def test_r11_fragments_derive_exact_wave2_marker(tmp_path):
    _render_fixture("R11", tmp_path, nonce="N11")

    fragments = []
    for path in sorted((tmp_path / "wave1").glob("*.txt")):
        line = next(
            line
            for line in path.read_text().splitlines()
            if line.startswith("fragment=")
        )
        fragments.append(line.removeprefix("fragment="))
    marker = "".join(fragments)

    assert marker == "wave2-N11-final-key"
    wave2 = sorted((tmp_path / "wave2").glob("*.txt"))
    assert len(wave2) == 4
    assert all(marker in path.read_text() for path in wave2)


def test_phase4_scenario_runtime_contracts_are_frozen():
    scenarios = load_all()

    for scenario_id in ("R4", "R6", "R10"):
        scenario = scenarios[scenario_id]
        assert scenario.phase1_step is None
        assert scenario.expected_runtime_s == 110
        assert scenario.max_turn_runtime_s == 180

    r4 = scenarios["R4"]
    assert [item.path for item in r4.fixture.files] == [
        f"inspect/f{i:02d}.txt" for i in range(1, 9)
    ]
    assert [item.content for item in r4.fixture.files] == [
        f"payload-R4-{i:02d}-{{nonce}}\n" for i in range(1, 9)
    ]
    assert "time.sleep(90)" in r4.dag[0].arguments["command"]

    assert "time.sleep(90)" in scenarios["R6"].dag[0].arguments["command"]
    assert "R6-{nonce}" in scenarios["R6"].dag[0].arguments["command"]

    r10 = scenarios["R10"]
    assert "time.sleep(90)" in r10.dag[0].arguments["command"]
    assert "print(" not in r10.dag[0].arguments["command"]
    assert any(
        check.type == "job_status_any_call"
        and check.params
        == {
            "node": "wait_result",
            "fields": {"state": "running", "quiet": True},
        }
        for check in r10.oracle.checks
    )


def test_r12_budget_contract_is_parameterized_and_nonterminal():
    r12 = load_all()["R12"]

    assert r12.phase1_step is None
    assert r12.runtime_budget_margin_s == 30
    assert r12.max_turn_runtime_s == 690
    assert "{budget_plus_margin_s}" in r12.dag[0].arguments["command"]
    assert "{budget_plus_margin_s}" in r12.prompt_template
    assert "300" not in r12.dag[0].arguments["command"]
    assert "exclude_aggregate_performance" in r12.metric_tags
    assert "all_nodes_complete" not in {check.type for check in r12.oracle.checks}
    assert any(
        check.type == "reply_contains_all"
        and check.params["values"]
        == [
            "BUDGET_EXHAUSTED",
            "job_id=",
            "state=running",
            "pending=dependency",
            "resume=job_status",
        ]
        for check in r12.oracle.checks
    )
    assert any(
        check.type == "job_status_any_call"
        and check.params
        == {
            "node": "wait_result",
            "fields": {
                "state": "running",
                "blocking_budget_exhausted": True,
            },
        }
        for check in r12.oracle.checks
    )


def test_only_r12_may_exceed_phase1_runtime_bound():
    data = _minimal()
    data["max_turn_runtime_s"] = 241
    with pytest.raises(ValidationError, match="240-second"):
        Scenario.model_validate(data)

    r12 = load_all()["R12"].model_dump()
    r12["max_turn_runtime_s"] = 691
    with pytest.raises(ValidationError, match="690-second"):
        Scenario.model_validate(r12)


def test_budget_margin_and_placeholder_are_r12_only():
    data = _minimal()
    data["runtime_budget_margin_s"] = 30
    with pytest.raises(ValidationError, match="only valid for R12"):
        Scenario.model_validate(data)

    data = _minimal()
    data["prompt_template"] = "wait {budget_plus_margin_s}"
    with pytest.raises(ValidationError, match="unknown placeholder"):
        Scenario.model_validate(data)

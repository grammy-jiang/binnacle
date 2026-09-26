import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.chat_scheduling_confirmatory import (
    EXPECTED_MAIN_SCHEDULE_SLOTS,
    build_gate_matrix,
    build_schedule,
    validate_schedule,
)
from tests.chat_scheduling_confirmatory_support import (
    create_trial,
    populate_main_runs,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]


def all_slots(schedule: dict) -> list[dict]:
    return [slot for block in schedule["blocks"] for slot in block["slots"]]


def h_slots() -> list[dict]:
    repeats = {"R5": 3, "R6": 3, "R7": 3, "R12": 1}
    slots = []
    for scenario_id, count in repeats.items():
        for repeat in range(1, count + 1):
            slots.append(
                {
                    "slot_id": f"{scenario_id}-r{repeat:02d}-H",
                    "scenario_id": scenario_id,
                    "repeat": repeat,
                    "arm": "H",
                    "endpoint_id": "H",
                    "budget_s": 10,
                }
            )
    return slots


def populate_h_runs(runs_root: Path, *, start_index: int = 1000) -> None:
    for offset, slot in enumerate(h_slots()):
        create_trial(
            runs_root,
            slot,
            index=start_index + offset,
            wall_s=90.0 if slot["scenario_id"] != "R12" else 40.0,
            same_prompt=slot["scenario_id"] != "R12",
            continuations=0 if slot["scenario_id"] != "R12" else 1,
        )


def review_files(tmp_path: Path, *, diagnostic_passed: bool = False) -> dict[str, Path]:
    paths = {
        "correctness": tmp_path / "correctness.json",
        "performance": tmp_path / "performance.json",
        "reliability": tmp_path / "reliability.json",
        "efficiency": tmp_path / "efficiency.json",
    }
    write_json(
        paths["correctness"],
        {
            "report_kind": "phase4-review-correctness-safety",
            "gates": {
                "safety_zero_out_of_scope_writes": {"passed": True},
                "tool_contract_preserved": {"passed": True},
                "production_isolation_preserved": {"passed": True},
            },
        },
    )
    write_json(
        paths["performance"],
        {
            "report_kind": "phase4-review-performance-bootstrap",
            "gates": {},
        },
    )
    write_json(
        paths["reliability"],
        {
            "report_kind": "phase4-review-reliability-provenance",
            "gates": {},
        },
    )
    write_json(
        paths["efficiency"],
        {
            "report_kind": "phase4-review-scheduling-efficiency",
            "gates": {
                "m2_m3_sliding_refill_demonstrated": {"passed": True},
                "union_blocking_wall_le_budget_plus_1s": {"passed": True},
                "overlap_charged_once": {"passed": True},
                "exhausted_calls_nonblocking": {"passed": True},
                "guard_overhead_p95_lt_1ms": {"passed": True},
                "guard_overhead_p99_lt_2ms": {"passed": True},
                "repeated_wait_burden_reduction_ge_60_percent": {"passed": True},
                "duplicate_completed_reads_no_increase": {"passed": True},
                "long_job_status_call_result_burden_reduction_ge_10_percent": {
                    "passed": diagnostic_passed
                },
            },
        },
    )
    return paths


def build_matrix(tmp_path: Path, *, diagnostic_passed: bool = False) -> dict:
    schedule = build_schedule(20260925, 300, 2)
    schedule_path = tmp_path / "schedule.json"
    write_json(schedule_path, schedule)
    runs_root = tmp_path / "runs"
    populate_main_runs(runs_root, schedule)
    populate_h_runs(runs_root)
    reviews = review_files(tmp_path, diagnostic_passed=diagnostic_passed)
    return build_gate_matrix(
        schedule_path=schedule_path,
        runs_root=runs_root,
        correctness_path=reviews["correctness"],
        performance_path=reviews["performance"],
        reliability_path=reviews["reliability"],
        efficiency_path=reviews["efficiency"],
        bootstrap_samples=500,
    )


def test_schedule_has_frozen_counts_reuse_and_determinism():
    first = build_schedule(12345, 300, 0)
    second = build_schedule(12345, 300, 0)
    other = build_schedule(54321, 300, 0)

    assert first == second
    assert first != other
    assert first["selected_c_endpoint"] == "C300"
    assert first["execution_mode"] == "serial_randomized"
    assert first["summary"] == {
        "performance_blocks": 53,
        "performance_slots": 159,
        "safety_slots": 1,
        "total_slots": 160,
        "canonical_slots_by_arm": {"A": 53, "B": 53, "C": 54},
        "performance_slots_by_arm": {"A": 53, "B": 53, "C": 53},
        "reused_calibration_slots": 10,
    }

    slots = all_slots(first)
    assert len(slots) == EXPECTED_MAIN_SCHEDULE_SLOTS
    assert len({slot["slot_id"] for slot in slots}) == 160
    assert sum(slot["reused_calibration_slot"] for slot in slots) == 10
    assert [slot["arm"] for slot in slots if slot["scenario_id"] == "R12"] == ["C"]
    assert (
        len(
            {
                tuple(block["arm_order"])
                for block in first["blocks"]
                if block["kind"] == "performance"
            }
        )
        > 1
    )


def test_parallel_schedule_rotates_session_lanes_and_rejects_bad_inputs():
    schedule = build_schedule(12345, 120, 2)
    assert schedule["execution_mode"] == "matched_parallel"
    for block in schedule["blocks"][:-1]:
        assert sorted(slot["session_lane"] for slot in block["slots"]) == [1, 2, 3]
        assert block["parallel_block_lane"] in {1, 2}
    assert schedule["selected_c_endpoint"] == "C120"
    orders = [block["arm_order"] for block in schedule["blocks"][:4]]
    assert orders[1] == orders[0][1:] + orders[0][:1]
    assert orders[2] == orders[1][1:] + orders[1][:1]
    assert orders[3] == orders[2][1:] + orders[2][:1]

    with pytest.raises(ValueError, match="selected budget"):
        build_schedule(1, 301, 0)
    with pytest.raises(ValueError, match="non-negative"):
        build_schedule(1, 300, -1)

    tampered = json.loads(json.dumps(schedule))
    tampered["blocks"][0]["slots"][0]["endpoint_id"] = "C600"
    with pytest.raises(ValueError, match="endpoint"):
        validate_schedule(tampered)


def test_schedule_cli_matches_frozen_contract(tmp_path: Path):
    output = tmp_path / "schedule.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/chat_scheduling_confirmatory.py",
            "schedule",
            "--seed",
            "99",
            "--selected-budget",
            "600",
            "--max-parallel-blocks",
            "3",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["seed"] == 99
    assert payload["selected_budget_s"] == 600
    assert payload["selected_c_endpoint"] == "C600"
    assert payload["max_safe_parallel_blocks"] == 3
    validate_schedule(payload)


def test_gate_matrix_aggregates_all_arms_and_diagnostic_miss_is_non_gating(
    tmp_path: Path,
):
    matrix = build_matrix(tmp_path)

    assert matrix["analytics"]["slot_integrity"]["passed"] is True
    aggregate = matrix["analytics"]["aggregate_by_arm"]
    assert aggregate["A"]["expected_performance_slots"] == 53
    assert aggregate["C"]["same_prompt_completions"] == 53
    assert aggregate["C"]["same_prompt_completion_rate"] == 1.0
    assert aggregate["H"]["submitted_slots"] == 0
    assert matrix["analytics"]["slot_integrity"]["h"]["expected_slots"] == 0

    bootstrap = matrix["analytics"]["paired_c_a_bootstrap"]
    assert bootstrap["complete_population"] is True
    assert bootstrap["pair_count"] == 53
    assert bootstrap["median_ratio"] == 0.7
    assert bootstrap["ci_95_upper"] == 0.7

    categories = matrix["analytics"]["category_medians"]
    assert categories["read_heavy"]["arms"]["C"]["median_wall_s"] == 70.0
    assert categories["read_heavy"]["arms"]["C"]["ratio_vs_a"] == 0.7
    reliability = matrix["analytics"]["reliability_deltas"]
    assert reliability["required_continuation_reduction_percent"] == 100.0

    assert matrix["all_required_gates_pass"] is True
    diagnostic = matrix["gates"][
        "long_job_status_call_result_burden_reduction_ge_10_percent"
    ]
    assert diagnostic["classification"] == "DIAGNOSTIC_TARGET"
    assert diagnostic["status"] == "TARGET_MISSED"


def test_foreign_submitted_run_does_not_change_frozen_population(
    tmp_path: Path,
):
    schedule = build_schedule(11, 300, 0)
    runs_root = tmp_path / "runs"
    populate_main_runs(runs_root, schedule)
    slot = all_slots(schedule)[0]
    duplicate_id = create_trial(
        runs_root,
        slot,
        index=9999,
        wall_s=1.0,
        same_prompt=True,
        continuations=0,
        run_id="duplicate-later",
    )
    schedule_path = tmp_path / "schedule.json"
    write_json(schedule_path, schedule)
    reviews = review_files(tmp_path)

    matrix = build_gate_matrix(
        schedule_path=schedule_path,
        runs_root=runs_root,
        correctness_path=reviews["correctness"],
        performance_path=reviews["performance"],
        reliability_path=reviews["reliability"],
        efficiency_path=reviews["efficiency"],
        bootstrap_samples=100,
    )

    integrity = matrix["analytics"]["slot_integrity"]
    assert integrity["passed"] is True
    assert integrity["submitted_main_slots"] == 160
    assert integrity["scorable_main_slots"] == 160
    assert duplicate_id not in integrity["unscheduled_main_run_ids"]
    assert matrix["analytics"]["population"]["total_owners"] == 160


def test_failed_after_submission_is_submitted_frozen_owner(tmp_path: Path):
    schedule = build_schedule(14, 300, 0)
    runs_root = tmp_path / "runs"
    populate_main_runs(runs_root, schedule)
    checkpoint_path = tmp_path / "phase4-confirmatory-R7-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    owner = next(
        row for row in checkpoint["canonical_slots"] if row["slot_id"] == "R7-r02-B"
    )
    trial_path = Path(owner["state_dir"]) / "trial.json"
    trial = json.loads(trial_path.read_text(encoding="utf-8"))
    trial["submission_status"] = "failed_after_submission"
    write_json(trial_path, trial)

    schedule_path = tmp_path / "schedule.json"
    write_json(schedule_path, schedule)
    reviews = review_files(tmp_path)
    matrix = build_gate_matrix(
        schedule_path=schedule_path,
        runs_root=runs_root,
        correctness_path=reviews["correctness"],
        performance_path=reviews["performance"],
        reliability_path=reviews["reliability"],
        efficiency_path=reviews["efficiency"],
        bootstrap_samples=100,
    )

    integrity = matrix["analytics"]["slot_integrity"]
    assert integrity["passed"] is True
    assert integrity["submitted_main_slots"] == 160
    assert integrity["scorable_main_slots"] == 160
    assert matrix["analytics"]["aggregate_by_arm"]["B"]["submitted_slots"] == 53


def test_missing_metric_is_not_silently_dropped_from_confirmatory_population(
    tmp_path: Path,
):
    schedule = build_schedule(12, 300, 0)
    runs_root = tmp_path / "runs"
    populate_main_runs(runs_root, schedule)
    c_slot = next(
        slot
        for slot in all_slots(schedule)
        if slot["arm"] == "C" and slot["scenario_id"] == "R1"
    )
    run_id = next(
        path.parent.name
        for path in runs_root.glob("*/trial.json")
        if json.loads(path.read_text(encoding="utf-8")).get("schedule_slot_id")
        == c_slot["slot_id"]
    )
    (runs_root / run_id / "metrics.json").unlink()

    schedule_path = tmp_path / "schedule.json"
    write_json(schedule_path, schedule)
    reviews = review_files(tmp_path)
    matrix = build_gate_matrix(
        schedule_path=schedule_path,
        runs_root=runs_root,
        correctness_path=reviews["correctness"],
        performance_path=reviews["performance"],
        reliability_path=reviews["reliability"],
        efficiency_path=reviews["efficiency"],
        bootstrap_samples=100,
    )

    integrity = matrix["analytics"]["slot_integrity"]
    assert integrity["passed"] is False
    assert integrity["submitted_main_slots"] == 160
    assert integrity["scorable_main_slots"] == 159
    assert matrix["analytics"]["paired_c_a_bootstrap"]["pair_count"] == 52
    assert matrix["gates"]["paired_c_a_bootstrap_upper_lt_1"]["status"] == "FAIL"
    assert matrix["all_required_gates_pass"] is False


def test_review_cannot_reclassify_or_disagree_with_computed_gate(tmp_path: Path):
    schedule = build_schedule(13, 300, 0)
    runs_root = tmp_path / "runs"
    populate_main_runs(runs_root, schedule)
    schedule_path = tmp_path / "schedule.json"
    write_json(schedule_path, schedule)
    reviews = review_files(tmp_path)

    efficiency = json.loads(reviews["efficiency"].read_text(encoding="utf-8"))
    efficiency["gates"]["long_job_status_call_result_burden_reduction_ge_10_percent"][
        "classification"
    ] = "REQUIRED"
    write_json(reviews["efficiency"], efficiency)
    with pytest.raises(ValueError, match="classification"):
        build_gate_matrix(
            schedule_path=schedule_path,
            runs_root=runs_root,
            correctness_path=reviews["correctness"],
            performance_path=reviews["performance"],
            reliability_path=reviews["reliability"],
            efficiency_path=reviews["efficiency"],
            bootstrap_samples=50,
        )

    reviews = review_files(tmp_path)
    performance = json.loads(reviews["performance"].read_text(encoding="utf-8"))
    performance["gates"]["paired_c_a_bootstrap_upper_lt_1"] = {"passed": False}
    write_json(reviews["performance"], performance)
    with pytest.raises(ValueError, match="disagree"):
        build_gate_matrix(
            schedule_path=schedule_path,
            runs_root=runs_root,
            correctness_path=reviews["correctness"],
            performance_path=reviews["performance"],
            reliability_path=reviews["reliability"],
            efficiency_path=reviews["efficiency"],
            bootstrap_samples=50,
        )

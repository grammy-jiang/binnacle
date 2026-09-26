"""Synthetic fixtures for confirmatory analyzer tests."""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def metric(
    slot: dict,
    run_id: str,
    *,
    wall_s: float,
    same_prompt: bool,
    continuations: int,
    interrupted: bool = False,
    correctness: bool = True,
) -> dict:
    arm = slot["arm"]
    return {
        "schema_version": 1,
        "scenario_id": slot["scenario_id"],
        "run_id": run_id,
        "arm": arm,
        "wall_s": wall_s,
        "correctness_passed": correctness,
        "oracle_failures": [] if correctness else ["synthetic failure"],
        "same_prompt_completion": same_prompt,
        "premature_handoff": False,
        "budget_exhaustion_handoff": slot["scenario_id"] == "R12",
        "manual_continuations_required": continuations,
        "interrupted": interrupted,
        "interruption_kind": "timeout" if interrupted else None,
        "tool_calls": 10,
        "duplicate_calls": 0,
        "redundant_exact_calls": 0,
        "job_status_calls": 2,
        "positive_job_status_calls": 1,
        "blocking_wall_s": 1.0,
        "avoidable_idle_wall_s": 1.0 if arm == "C" else 5.0,
        "read_only_peak_inflight": 3,
        "eligible_read_only_calls": 10,
        "overlapped_eligible_read_only_calls": 9 if arm == "C" else 5,
        "eligible_read_only_overlap_ratio": 0.9 if arm == "C" else 0.5,
        "tool_result_tokens": 100,
        "tool_result_bytes": 500,
        "tool_errors": 0,
    }


def create_trial(
    runs_root: Path,
    slot: dict,
    *,
    index: int,
    wall_s: float,
    same_prompt: bool,
    continuations: int,
    run_id: str | None = None,
    explicit_slot: bool = True,
) -> str:
    run_id = run_id or f"run-{index:04d}"
    run_dir = runs_root / run_id
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "scenario_id": slot["scenario_id"],
        "arm": slot["arm"],
        "endpoint_id": slot["endpoint_id"],
        "budget_s": slot["budget_s"],
        "repeat": slot["repeat"],
        "submission_status": "submitted",
        "submission_epoch_s": float(index),
        "evidence_integrity_error": False,
    }
    if explicit_slot:
        record["schedule_slot_id"] = slot["slot_id"]
    write_json(run_dir / "trial.json", record)
    write_json(
        run_dir / "metrics.json",
        metric(
            slot,
            run_id,
            wall_s=wall_s,
            same_prompt=same_prompt,
            continuations=continuations,
        ),
    )
    return run_id


def _checkpoint_partition(scenario_id: str) -> str:
    number = int(scenario_id[1:])
    if number <= 2:
        return "R1-R2"
    if number <= 4:
        return "R3-R4"
    if number <= 6:
        return "R5-R6"
    if number == 7:
        return "R7"
    if number <= 9:
        return "R8-R9"
    return "R10-R11"


def populate_main_runs(runs_root: Path, schedule: dict) -> None:
    continuation_prone = {"R5", "R6", "R7", "R10"}
    owners: dict[str, list[dict]] = {
        name: [] for name in ("R1-R2", "R3-R4", "R5-R6", "R7", "R8-R9", "R10-R11")
    }
    r12_state_dir: Path | None = None
    slots = [slot for block in schedule["blocks"] for slot in block["slots"]]
    for index, slot in enumerate(slots, start=1):
        arm = slot["arm"]
        scenario_id = slot["scenario_id"]
        if scenario_id == "R12":
            wall_s, same_prompt, continuations = 330.0, False, 1
        elif arm == "A":
            wall_s = 100.0
            continuations = 1 if scenario_id in continuation_prone else 0
            same_prompt = continuations == 0
        elif arm == "B":
            wall_s, same_prompt, continuations = 85.0, True, 0
        else:
            wall_s, same_prompt, continuations = 70.0, True, 0
        run_id = create_trial(
            runs_root,
            slot,
            index=index,
            wall_s=wall_s,
            same_prompt=same_prompt,
            continuations=continuations,
        )
        state_dir = runs_root / run_id
        if scenario_id == "R12":
            r12_state_dir = state_dir
            continue
        owners[_checkpoint_partition(scenario_id)].append(
            {
                "slot_id": slot["slot_id"],
                "run_id": run_id,
                "state_dir": str(state_dir),
                "repeat": slot["repeat"],
                "arm": arm,
                "endpoint_id": slot["endpoint_id"],
                "submission_status": "submitted",
            }
        )

    for partition, rows in owners.items():
        write_json(
            runs_root.parent / f"phase4-confirmatory-{partition}-checkpoint.json",
            {"canonical_slots": rows},
        )
    if r12_state_dir is None:
        raise AssertionError("synthetic schedule did not create R12")
    write_json(
        runs_root.parent / "phase4" / "runs" / "4B-C300.json",
        {
            "rows": [
                {
                    "slot_id": "4B:C300:R12:1",
                    "scenario": "R12",
                    "arm": "C",
                    "state_dir": str(r12_state_dir),
                }
            ]
        },
    )

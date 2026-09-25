import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.chat_scheduling_replay import (
    interval_union_seconds,
    repeated_wait_burden,
    replay_corpus,
    replay_turn,
)

ROOT = Path(__file__).resolve().parents[2]


def make_wait(
    index: int,
    start: float,
    duration: float,
    *,
    requested: float = 50.0,
    required: bool = False,
    observed: bool = False,
    exit_offset: float | None = None,
    job_id: str | None = None,
) -> dict:
    end = start + duration
    return {
        "wait_index": index,
        "node_id": f"wait_{index}",
        "job_id_hash": job_id or f"job-{index}",
        "requested_wait_s": requested,
        "call_start_offset_s": start,
        "call_end_offset_s": end,
        "blocking_start_offset_s": start,
        "blocking_end_offset_s": end,
        "waited_s": duration,
        "state": "exited" if observed else "running",
        "job_exit_offset_s": exit_offset,
        "required_completion": required,
        "observed_completion": observed,
    }


def make_row(
    waits: list[dict],
    *,
    trial_id: str = "trial-1",
    scenario: str = "R5",
    source_id: str = "source-1",
) -> dict:
    observed_wall = interval_union_seconds(
        (wait["blocking_start_offset_s"], wait["blocking_end_offset_s"])
        for wait in waits
    )
    observed_required = sum(
        bool(wait["required_completion"]) and bool(wait["observed_completion"])
        for wait in waits
    )
    return {
        "source_id": source_id,
        "source_sha256": "a" * 64,
        "trial_id": trial_id,
        "scenario": scenario,
        "arm": "B",
        "base_turn": "base/1",
        "observed_blocking_wall_s": observed_wall,
        "waits": waits,
        "observed_required_completions": observed_required,
        "terminal_state": "complete",
        "correct": True,
        "same_prompt": True,
    }


def test_cumulative_serial_waits_clip_at_budget_without_fabricating_waits():
    source = make_row(
        [
            make_wait(1, 0.0, 50.0),
            make_wait(2, 50.0, 50.0),
            make_wait(3, 100.0, 50.0),
        ]
    )
    snapshot = deepcopy(source)

    result = replay_turn(source, policy="cumulative", budget_s=120)

    assert source == snapshot
    assert result["observed_blocking_wall_s"] == 150.0
    assert result["candidate_blocking_wall_s"] == 120.0
    assert result["burden_reduction_percent"] == 20.0
    assert result["positive_waits_observed"] == 3
    assert result["waits_clipped"] == 1
    assert result["waits_converted_to_nonblocking"] == 0
    assert result["candidate_exhaustion_offset_s"] == 120.0


def test_cumulative_fully_overlapping_waits_charge_union_wall_once():
    result = replay_turn(
        make_row([make_wait(1, 0.0, 50.0), make_wait(2, 0.0, 50.0)]),
        policy="cumulative",
        budget_s=50,
    )

    assert result["observed_blocking_wall_s"] == 50.0
    assert result["candidate_blocking_wall_s"] == 50.0
    assert result["waits_clipped"] == 0
    assert result["candidate_exhaustion_offset_s"] == 50.0


def test_cumulative_partial_overlap_clips_against_elapsed_union_not_sum():
    result = replay_turn(
        make_row([make_wait(1, 0.0, 50.0), make_wait(2, 25.0, 50.0)]),
        policy="cumulative",
        budget_s=60,
    )

    assert result["observed_blocking_wall_s"] == 75.0
    assert result["candidate_blocking_wall_s"] == 60.0
    assert result["waits_clipped"] == 1
    assert result["candidate_exhaustion_offset_s"] == 60.0


def test_repeated_wait_burden_one_job_with_one_wait_is_zero():
    metrics = repeated_wait_burden(
        make_row([make_wait(1, 0.0, 10.0, job_id="job-a")]),
        policy="cumulative",
        budget_s=120,
    )

    assert metrics["observed_repeated_wait_burden_s"] == 0.0
    assert metrics["candidate_repeated_wait_burden_s"] == 0.0
    assert metrics["repeated_wait_burden_reduction_percent"] is None


def test_repeated_wait_burden_two_waits_on_one_job_counts_only_second():
    metrics = repeated_wait_burden(
        make_row(
            [
                make_wait(1, 0.0, 10.0, job_id="job-a"),
                make_wait(2, 20.0, 20.0, job_id="job-a"),
            ]
        ),
        policy="cumulative",
        budget_s=120,
    )

    assert metrics["observed_repeated_wait_burden_s"] == 20.0
    assert metrics["candidate_repeated_wait_burden_s"] == 20.0
    assert metrics["repeated_wait_burden_reduction_percent"] == 0.0


def test_repeated_wait_burden_two_jobs_with_one_wait_each_is_zero():
    metrics = repeated_wait_burden(
        make_row(
            [
                make_wait(1, 0.0, 10.0, job_id="job-a"),
                make_wait(2, 20.0, 20.0, job_id="job-b"),
            ]
        ),
        policy="cumulative",
        budget_s=120,
    )

    assert metrics["observed_repeated_wait_burden_s"] == 0.0
    assert metrics["candidate_repeated_wait_burden_s"] == 0.0
    assert metrics["repeated_wait_burden_reduction_percent"] is None


def test_repeated_wait_burden_overlapping_second_waits_are_charged_once():
    metrics = repeated_wait_burden(
        make_row(
            [
                make_wait(1, 0.0, 10.0, job_id="job-a"),
                make_wait(2, 20.0, 20.0, job_id="job-a"),
                make_wait(3, 30.0, 20.0, job_id="job-a"),
            ]
        ),
        policy="cumulative",
        budget_s=120,
    )

    assert metrics["observed_repeated_wait_burden_s"] == 30.0
    assert metrics["candidate_repeated_wait_burden_s"] == 30.0
    assert metrics["repeated_wait_burden_reduction_percent"] == 0.0


def test_cumulative_nearly_exhausted_budget_converts_later_positive_wait():
    result = replay_turn(
        make_row([make_wait(1, 0.0, 9.5), make_wait(2, 20.0, 5.0)]),
        policy="cumulative",
        budget_s=10,
    )

    assert result["candidate_blocking_wall_s"] == 9.5
    assert result["candidate_exhaustion_offset_s"] == 20.0
    assert result["waits_clipped"] == 1
    assert result["waits_converted_to_nonblocking"] == 1


@pytest.mark.parametrize(
    ("exit_offset", "preserved", "at_risk"),
    [(15.0, 1, 0), (30.0, 0, 1)],
)
def test_required_completion_depends_on_exit_point_inside_candidate_interval(
    exit_offset: float,
    preserved: int,
    at_risk: int,
):
    source = make_row(
        [
            make_wait(
                1,
                0.0,
                50.0,
                required=True,
                observed=True,
                exit_offset=exit_offset,
            )
        ]
    )

    result = replay_turn(source, policy="cumulative", budget_s=20)

    assert result["observed_required_completions"] == 1
    assert result["required_completions_preserved"] == preserved
    assert result["completion_at_risk"] == at_risk


def test_h10_uses_observed_wait_for_first_call_and_zero_for_later_positive_waits():
    result = replay_turn(
        make_row([make_wait(1, 0.0, 3.0), make_wait(2, 10.0, 20.0)]),
        policy="historical-one-shot",
        budget_s=10,
    )

    assert result["candidate_blocking_wall_s"] == 3.0
    assert result["candidate_exhaustion_offset_s"] == 3.0
    assert result["positive_waits_observed"] == 2
    assert result["waits_clipped"] == 1
    assert result["waits_converted_to_nonblocking"] == 1


def test_h10_caps_first_observed_wait_at_ten_seconds():
    result = replay_turn(
        make_row([make_wait(1, 0.0, 30.0), make_wait(2, 40.0, 5.0)]),
        policy="historical-one-shot",
        budget_s=10,
    )

    assert result["candidate_blocking_wall_s"] == 10.0
    assert result["waits_clipped"] == 2
    assert result["waits_converted_to_nonblocking"] == 1
    assert result["candidate_exhaustion_offset_s"] == 10.0


def test_replay_corpus_sorts_rows_and_builds_summary_and_scenario_table():
    row_b = make_row(
        [make_wait(1, 0.0, 10.0)],
        trial_id="trial-b",
        scenario="R6",
        source_id="source-b",
    )
    row_a = make_row(
        [make_wait(1, 0.0, 20.0)],
        trial_id="trial-a",
        scenario="R5",
        source_id="source-a",
    )
    corpus = {"schema_version": 1, "rows": [row_b, row_a]}

    report = replay_corpus(
        corpus,
        policy="cumulative",
        budget_s=120,
        corpus_sha256="f" * 64,
    )

    assert [row["source_id"] for row in report["rows"]] == ["source-a", "source-b"]
    assert report["summary"]["turns"] == 2
    assert report["summary"]["observed_blocking_wall_s"] == 30.0
    assert report["summary"]["candidate_blocking_wall_s"] == 30.0
    assert report["summary"]["burden_reduction_percent"] == 0.0
    assert report["summary"]["observed_repeated_wait_burden_s"] == 0.0
    assert report["summary"]["candidate_repeated_wait_burden_s"] == 0.0
    assert report["summary"]["repeated_wait_burden_reduction_percent"] is None
    assert [item["scenario"] for item in report["per_scenario"]] == ["R5", "R6"]
    assert report["corpus_sha256"] == "f" * 64
    assert report["algorithm_id"] == "phase3-replay-v1"


def test_cli_contract_writes_canonical_json_and_deterministic_companion_markdown(
    tmp_path: Path,
):
    corpus = {
        "schema_version": 1,
        "rows": [make_row([make_wait(1, 0.0, 50.0)])],
    }
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(corpus, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    first = tmp_path / "replay-first.json"
    second = tmp_path / "replay-second.json"
    base_command = [
        sys.executable,
        "scripts/chat_scheduling_replay.py",
        "--corpus",
        str(corpus_path),
        "--policy",
        "cumulative",
        "--budget-s",
        "120",
    ]

    subprocess.run(
        [*base_command, "--output", str(first)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [*base_command, "--output", str(second)],
        cwd=ROOT,
        check=True,
    )

    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_suffix(".md").read_bytes() == second.with_suffix(".md").read_bytes()
    )
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert (
        payload["corpus_sha256"] == hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    )
    assert payload["policy"] == "cumulative"
    assert payload["budget_s"] == 120.0

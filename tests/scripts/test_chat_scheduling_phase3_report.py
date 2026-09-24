import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.chat_scheduling_phase3_report import build_final, build_shortlist

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _corpus(
    tmp_path: Path, *, missing_state: bool = False
) -> tuple[Path, str, list[dict]]:
    rows = []
    for index in range(10):
        wait = {
            "wait_index": 1,
            "node_id": f"wait-{index}",
            "job_id_hash": f"job-{index}",
            "requested_wait_s": 50.0,
            "call_start_offset_s": 0.0,
            "call_end_offset_s": 20.0,
            "blocking_start_offset_s": 0.0,
            "blocking_end_offset_s": 20.0,
            "waited_s": 20.0,
            "state": "exited",
            "job_exit_offset_s": 10.0,
            "required_completion": True,
            "observed_completion": True,
        }
        if missing_state and index == 0:
            wait.pop("state")
        rows.append(
            {
                "source_id": "source",
                "source_sha256": "a" * 64,
                "trial_id": f"trial-{index:02d}",
                "scenario": "R6",
                "arm": "B",
                "base_turn": "base/1",
                "observed_blocking_wall_s": 20.0,
                "waits": [wait],
                "observed_required_completions": 1,
                "terminal_state": "complete",
                "correct": True,
                "same_prompt": True,
            }
        )
    path = tmp_path / "corpus.json"
    _write_json(
        path,
        {
            "schema_version": 1,
            "fields": [],
            "wait_fields": [],
            "rows": rows,
        },
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), rows


def _candidate_report(
    path: Path,
    corpus_sha256: str,
    corpus_rows: list[dict],
    *,
    budget_s: float,
    preserved: int = 10,
    exhausted: int = 0,
    candidate_wall_s: float = 40.0,
    provisional: bool = False,
    audit_status: str = "pass",
) -> Path:
    rows = [
        {
            "source_id": row["source_id"],
            "source_sha256": row["source_sha256"],
            "trial_id": row["trial_id"],
            "scenario": row["scenario"],
            "historical_arm": row["arm"],
            "base_turn": row["base_turn"],
            "observed_blocking_wall_s": row["observed_blocking_wall_s"],
            "candidate_blocking_wall_s": min(
                row["observed_blocking_wall_s"], candidate_wall_s / 10.0
            ),
            "burden_reduction_percent": None,
            "candidate_exhaustion_offset_s": None,
            "positive_waits_observed": 1,
            "waits_clipped": 0,
            "waits_converted_to_nonblocking": 0,
            "observed_required_completions": 1,
            "required_completions_preserved": 1,
            "completion_at_risk": 0,
            "terminal_state": row["terminal_state"],
            "correct": row["correct"],
            "same_prompt": row["same_prompt"],
        }
        for row in corpus_rows
    ]
    if exhausted:
        for row in rows[:exhausted]:
            row["candidate_exhaustion_offset_s"] = budget_s
    observed_wall_s = 200.0
    burden_reduction = round(
        100.0 * (observed_wall_s - candidate_wall_s) / observed_wall_s, 6
    )
    report = {
        "schema_version": 1,
        "algorithm_id": "phase3-replay-v1",
        "audit_status_at_start": "pending",
        "audit_status": audit_status,
        "provisional": provisional,
        "corpus_sha256": corpus_sha256,
        "policy": "cumulative",
        "budget_s": budget_s,
        "summary": {
            "turns": 10,
            "turns_with_positive_waits": 10,
            "observed_blocking_wall_s": observed_wall_s,
            "candidate_blocking_wall_s": candidate_wall_s,
            "burden_reduction_percent": burden_reduction,
            "positive_waits_observed": 10,
            "waits_clipped": 0,
            "waits_converted_to_nonblocking": 0,
            "observed_required_completions": 10,
            "required_completions_preserved": preserved,
            "completion_at_risk": 10 - preserved,
            "completion_preservation_percent": preserved * 10.0,
            "turns_exhausted": exhausted,
            "exhaustion_percent": exhausted * 10.0,
        },
        "per_scenario": [],
        "rows": rows,
    }
    _write_json(path, report)
    return path


def _candidate_set(
    tmp_path: Path,
    corpus_sha256: str,
    rows: list[dict],
) -> list[Path]:
    return [
        _candidate_report(
            tmp_path / "c120.json",
            corpus_sha256,
            rows,
            budget_s=120.0,
            candidate_wall_s=30.0,
        ),
        _candidate_report(
            tmp_path / "c300.json",
            corpus_sha256,
            rows,
            budget_s=300.0,
            candidate_wall_s=50.0,
        ),
        _candidate_report(
            tmp_path / "c600.json",
            corpus_sha256,
            rows,
            budget_s=600.0,
            candidate_wall_s=100.0,
        ),
    ]


def _run_shortlist_cli(
    tmp_path: Path,
    corpus_path: Path,
    candidates: list[Path],
    stem: str,
) -> tuple[Path, Path]:
    output_json = tmp_path / f"{stem}.json"
    output_md = tmp_path / f"{stem}.md"
    command = [
        sys.executable,
        "scripts/chat_scheduling_phase3_report.py",
        "shortlist",
        "--corpus",
        str(corpus_path),
    ]
    for candidate in candidates:
        command.extend(["--candidate", str(candidate)])
    command.extend(["--output-json", str(output_json), "--output-md", str(output_md)])
    subprocess.run(command, cwd=ROOT, check=True)
    return output_json, output_md


def _historical_report(path: Path, corpus_sha256: str) -> Path:
    _write_json(
        path,
        {
            "schema_version": 1,
            "algorithm_id": "phase3-replay-v1",
            "audit_status_at_start": "pending",
            "audit_status": "pass",
            "provisional": False,
            "corpus_sha256": corpus_sha256,
            "policy": "historical-one-shot",
            "budget_s": 10.0,
            "summary": {"turns": 10, "completion_preservation_percent": 20.0},
            "per_scenario": [],
            "rows": [],
        },
    )
    return path


def test_shortlist_cli_selects_all_passing_candidates_deterministically(
    tmp_path: Path,
):
    corpus_path, corpus_sha256, rows = _corpus(tmp_path)
    candidates = _candidate_set(tmp_path, corpus_sha256, rows)

    first_json, first_md = _run_shortlist_cli(
        tmp_path, corpus_path, candidates, "shortlist-first"
    )
    second_json, second_md = _run_shortlist_cli(
        tmp_path, corpus_path, candidates, "shortlist-second"
    )

    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_md.read_bytes() == second_md.read_bytes()
    payload = json.loads(first_json.read_text(encoding="utf-8"))
    assert payload["live_candidates"] == ["C120", "C300"]
    assert payload["preferred_live_candidate"] == "C120"
    assert payload["rejected_candidates"] == [
        {
            "candidate": "C600",
            "budget_s": 600.0,
            "failed_gates": ["gate_4_repeated_wait_burden_reduction"],
        }
    ]
    assert payload["open_evidence_limitations"] == []
    assert payload["production_budget_declared"] is False


def test_shortlist_rejects_unpromoted_candidate(tmp_path: Path):
    corpus_path, corpus_sha256, rows = _corpus(tmp_path)
    candidates = _candidate_set(tmp_path, corpus_sha256, rows)
    payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    payload["provisional"] = True
    _write_json(candidates[0], payload)

    with pytest.raises(ValueError, match="remains provisional"):
        build_shortlist(corpus_path, candidates)


def test_shortlist_gate_five_rejects_missing_positive_wait_evidence(tmp_path: Path):
    corpus_path, corpus_sha256, rows = _corpus(tmp_path, missing_state=True)
    candidates = _candidate_set(tmp_path, corpus_sha256, rows)

    result = build_shortlist(corpus_path, candidates)

    assert result["live_candidates"] == []
    assert result["preferred_live_candidate"] is None
    assert result["verdict"] == "NO_LIVE_CANDIDATE"
    assert all(
        "gate_5_evidence_completeness" in candidate["failed_gates"]
        for candidate in result["rejected_candidates"]
    )


def test_final_cli_copies_frozen_shortlist_selection_without_recomputation(
    tmp_path: Path,
):
    corpus_path, corpus_sha256, rows = _corpus(tmp_path)
    candidates = _candidate_set(tmp_path, corpus_sha256, rows)
    shortlist_json, _ = _run_shortlist_cli(
        tmp_path, corpus_path, candidates, "shortlist"
    )
    historical = _historical_report(tmp_path / "h10.json", corpus_sha256)
    output_json = tmp_path / "final.json"
    output_md = tmp_path / "final.md"

    subprocess.run(
        [
            sys.executable,
            "scripts/chat_scheduling_phase3_report.py",
            "final",
            "--shortlist",
            str(shortlist_json),
            "--historical",
            str(historical),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        cwd=ROOT,
        check=True,
    )

    shortlist = json.loads(shortlist_json.read_text(encoding="utf-8"))
    final = json.loads(output_json.read_text(encoding="utf-8"))
    for field in (
        "rejected_candidates",
        "live_candidates",
        "preferred_live_candidate",
        "open_evidence_limitations",
        "phase4_targeted_calibration_requirements",
        "verdict",
    ):
        assert final[field] == shortlist[field]
    assert (
        final["candidate_shortlist_sha256"]
        == hashlib.sha256(shortlist_json.read_bytes()).hexdigest()
    )
    assert final["historical_comparator"]["policy"] == "historical-one-shot"
    assert final["historical_comparator"]["budget_s"] == 10.0
    assert final["production_budget_declared"] is False


def test_final_rejects_h10_from_different_corpus(tmp_path: Path):
    shortlist_path = tmp_path / "shortlist.json"
    _write_json(
        shortlist_path,
        {
            "report_kind": "phase3-candidate-shortlist",
            "corpus_sha256": "a" * 64,
            "rejected_candidates": [],
            "live_candidates": ["C120"],
            "preferred_live_candidate": "C120",
            "open_evidence_limitations": [],
            "phase4_targeted_calibration_requirements": [],
            "verdict": "LIVE_CANDIDATES_AVAILABLE",
        },
    )
    historical = _historical_report(tmp_path / "h10.json", "b" * 64)

    with pytest.raises(ValueError, match="does not match shortlist"):
        build_final(shortlist_path, historical)

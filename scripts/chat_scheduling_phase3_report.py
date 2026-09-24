"""Build deterministic Phase-3 shortlist and final replay reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.chat_scheduling_phase3_report_render import (
    _write_outputs,
    render_final_markdown,
    render_shortlist_markdown,
)

SCHEMA_VERSION = 1
COMPLETION_MIN_PERCENT = 95.0
EXHAUSTION_MAX_PERCENT = 10.0
BURDEN_REDUCTION_MIN_PERCENT = 70.0
EARLY_EXHAUSTION_MARGIN_S = 1.0
CANDIDATE_NAMES = {120.0: "C120", 300.0: "C300", 600.0: "C600"}
EPSILON = 1e-9


def _load_object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} root must be a JSON object")
    return payload, raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


def _percent(numerator: int, denominator: int, field: str) -> float:
    if denominator <= 0:
        raise ValueError(f"{field} denominator must be positive")
    return round(100.0 * numerator / denominator, 6)


def _row_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_id")),
        str(row.get("trial_id")),
        str(row.get("base_turn")),
    )


def _corpus_row_ids(corpus: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    rows = corpus.get("rows")
    if not isinstance(rows, list):
        raise TypeError("replay corpus rows must be a list")
    identities: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"corpus row {index} must be an object")
        identities.append(_row_identity(row))
    if len(set(identities)) != len(identities):
        raise ValueError("replay corpus row identities are not unique")
    return sorted(identities)


def _positive_wait_evidence_issues(corpus: Mapping[str, Any]) -> list[str]:
    rows = corpus.get("rows")
    if not isinstance(rows, list):
        raise TypeError("replay corpus rows must be a list")
    issues: list[str] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"corpus row {row_index} must be an object")
        waits = row.get("waits")
        if not isinstance(waits, list):
            raise TypeError(f"corpus row {row_index} waits must be a list")
        for wait_index, wait in enumerate(waits):
            if not isinstance(wait, Mapping):
                raise TypeError(
                    f"corpus row {row_index} wait {wait_index} must be an object"
                )
            requested = _number(
                wait.get("requested_wait_s"),
                f"corpus row {row_index} wait {wait_index} requested_wait_s",
            )
            if requested <= EPSILON:
                continue
            missing: list[str] = []
            for field in (
                "call_start_offset_s",
                "call_end_offset_s",
                "waited_s",
                "state",
            ):
                if wait.get(field) is None:
                    missing.append(field)
            waited = wait.get("waited_s")
            if waited is not None:
                waited_s = _number(
                    waited, f"corpus row {row_index} wait {wait_index} waited_s"
                )
                if waited_s > EPSILON:
                    for field in (
                        "blocking_start_offset_s",
                        "blocking_end_offset_s",
                    ):
                        if wait.get(field) is None:
                            missing.append(field)
            if (
                bool(wait.get("required_completion"))
                and bool(wait.get("observed_completion"))
                and wait.get("job_exit_offset_s") is None
            ):
                missing.append("job_exit_offset_s")
            state = wait.get("state")
            if state is not None and (not isinstance(state, str) or not state.strip()):
                missing.append("state")
            if missing:
                source_id, trial_id, base_turn = _row_identity(row)
                issues.append(
                    f"{source_id}/{trial_id}/{base_turn} wait {wait_index}: "
                    + ", ".join(sorted(set(missing)))
                )
    return issues


def _validate_promoted_candidate(
    report: Mapping[str, Any],
    *,
    path: Path,
    corpus_sha256: str,
    corpus_row_ids: Sequence[tuple[str, str, str]],
) -> tuple[str, float]:
    if report.get("corpus_sha256") != corpus_sha256:
        raise ValueError(f"{path} corpus_sha256 does not match the frozen corpus")
    if report.get("audit_status") != "pass":
        raise ValueError(f"{path} is not promoted with audit_status=pass")
    if report.get("provisional") is not False:
        raise ValueError(f"{path} remains provisional")
    if report.get("policy") != "cumulative":
        raise ValueError(f"{path} is not a cumulative C-candidate report")
    budget = _number(report.get("budget_s"), f"{path} budget_s")
    candidate = CANDIDATE_NAMES.get(budget)
    if candidate is None:
        raise ValueError(f"{path} has unsupported C-candidate budget {budget}")
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise TypeError(f"{path} rows must be a list")
    report_ids = sorted(_row_identity(row) for row in rows if isinstance(row, Mapping))
    if len(report_ids) != len(rows):
        raise TypeError(f"{path} contains a non-object replay row")
    if report_ids != list(corpus_row_ids):
        raise ValueError(
            f"{path} replay rows do not match the frozen corpus population"
        )
    return candidate, budget


def _evaluate_candidate(
    report: Mapping[str, Any],
    *,
    candidate: str,
    budget_s: float,
    report_path: Path,
    report_sha256: str,
    evidence_issues: Sequence[str],
) -> dict[str, Any]:
    summary = report.get("summary")
    rows = report.get("rows")
    if not isinstance(summary, Mapping):
        raise TypeError(f"{report_path} summary must be an object")
    if not isinstance(rows, list):
        raise TypeError(f"{report_path} rows must be a list")

    observed_required = _integer(
        summary.get("observed_required_completions"),
        f"{report_path} observed_required_completions",
    )
    preserved = _integer(
        summary.get("required_completions_preserved"),
        f"{report_path} required_completions_preserved",
    )
    completion_percent = _percent(
        preserved, observed_required, "completion preservation"
    )

    positive_turns = _integer(
        summary.get("turns_with_positive_waits"),
        f"{report_path} turns_with_positive_waits",
    )
    exhausted_turns = _integer(
        summary.get("turns_exhausted"), f"{report_path} turns_exhausted"
    )
    exhaustion_percent = _percent(
        exhausted_turns, positive_turns, "candidate exhaustion"
    )

    observed_wall = _number(
        summary.get("observed_blocking_wall_s"),
        f"{report_path} observed_blocking_wall_s",
    )
    candidate_wall = _number(
        summary.get("candidate_blocking_wall_s"),
        f"{report_path} candidate_blocking_wall_s",
    )
    if observed_wall <= EPSILON:
        raise ValueError("historical burden-reduction denominator must be positive")
    burden_reduction_percent = round(
        100.0 * (observed_wall - candidate_wall) / observed_wall, 6
    )

    early_exhaustion_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"{report_path} row {index} must be an object")
        exhausted = row.get("candidate_exhaustion_offset_s") is not None
        observed = _number(
            row.get("observed_blocking_wall_s"),
            f"{report_path} row {index} observed_blocking_wall_s",
        )
        if exhausted and observed <= budget_s - EARLY_EXHAUSTION_MARGIN_S + EPSILON:
            early_exhaustion_count += 1

    gates: dict[str, dict[str, Any]] = {
        "gate_1_completion_preservation": {
            "passed": completion_percent + EPSILON >= COMPLETION_MIN_PERCENT,
            "value_percent": completion_percent,
            "minimum_percent": COMPLETION_MIN_PERCENT,
        },
        "gate_2_exhaustion": {
            "passed": exhaustion_percent <= EXHAUSTION_MAX_PERCENT + EPSILON,
            "value_percent": exhaustion_percent,
            "maximum_percent": EXHAUSTION_MAX_PERCENT,
            "denominator_turns_with_positive_waits": positive_turns,
        },
        "gate_3_no_early_exhaustion": {
            "passed": early_exhaustion_count == 0,
            "early_exhaustion_turns": early_exhaustion_count,
            "margin_s": EARLY_EXHAUSTION_MARGIN_S,
        },
        "gate_4_repeated_wait_burden_reduction": {
            "passed": burden_reduction_percent + EPSILON
            >= BURDEN_REDUCTION_MIN_PERCENT,
            "value_percent": burden_reduction_percent,
            "minimum_percent": BURDEN_REDUCTION_MIN_PERCENT,
        },
        "gate_5_evidence_completeness": {
            "passed": not evidence_issues,
            "missing_evidence_count": len(evidence_issues),
            "examples": list(evidence_issues[:5]),
        },
    }
    failed_gates = [name for name, result in gates.items() if not result["passed"]]
    return {
        "candidate": candidate,
        "budget_s": budget_s,
        "report_path": str(report_path),
        "report_sha256": report_sha256,
        "passed": not failed_gates,
        "failed_gates": failed_gates,
        "gates": gates,
    }


def build_shortlist(
    corpus_path: Path, candidate_paths: Sequence[Path]
) -> dict[str, Any]:
    corpus, corpus_raw = _load_object(corpus_path)
    if corpus.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported replay corpus schema_version")
    corpus_sha256 = _sha256(corpus_raw)
    corpus_row_ids = _corpus_row_ids(corpus)
    evidence_issues = _positive_wait_evidence_issues(corpus)

    evaluations: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    source_reports: dict[str, dict[str, Any]] = {}
    for path in candidate_paths:
        report, raw = _load_object(path)
        candidate, budget_s = _validate_promoted_candidate(
            report,
            path=path,
            corpus_sha256=corpus_sha256,
            corpus_row_ids=corpus_row_ids,
        )
        if candidate in seen_candidates:
            raise ValueError(f"duplicate candidate report for {candidate}")
        seen_candidates.add(candidate)
        report_sha256 = _sha256(raw)
        source_reports[candidate] = {
            "path": str(path),
            "sha256": report_sha256,
            "budget_s": budget_s,
        }
        evaluations.append(
            _evaluate_candidate(
                report,
                candidate=candidate,
                budget_s=budget_s,
                report_path=path,
                report_sha256=report_sha256,
                evidence_issues=evidence_issues,
            )
        )
    expected = set(CANDIDATE_NAMES.values())
    if seen_candidates != expected:
        missing = sorted(expected - seen_candidates)
        extra = sorted(seen_candidates - expected)
        raise ValueError(
            f"shortlist requires C120/C300/C600; missing={missing}, extra={extra}"
        )

    evaluations.sort(key=lambda item: float(item["budget_s"]))
    live_candidates = [
        str(item["candidate"]) for item in evaluations if bool(item["passed"])
    ]
    rejected_candidates = [
        {
            "candidate": item["candidate"],
            "budget_s": item["budget_s"],
            "failed_gates": item["failed_gates"],
        }
        for item in evaluations
        if not bool(item["passed"])
    ]
    preferred = live_candidates[0] if live_candidates else None
    if live_candidates:
        calibration_requirements = [
            (
                "Exercise every live C candidate during targeted live calibration; "
                "do not collapse the shortlist to the preferred candidate."
            ),
            (
                "Exercise the R12 budget-edge runtime for each live C budget while "
                "preserving the canonical A/B/C/H arm vocabulary."
            ),
            (
                "Treat preferred_live_candidate as the smallest offline-passing "
                "budget, not as a declared production budget."
            ),
        ]
        verdict = "LIVE_CANDIDATES_AVAILABLE"
    else:
        calibration_requirements = [
            (
                "Do not start Phase-4 targeted calibration: no C120/C300/C600 "
                "candidate passed every Phase-3 offline gate."
            )
        ]
        verdict = "NO_LIVE_CANDIDATE"

    return {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "phase3-candidate-shortlist",
        "corpus_path": str(corpus_path),
        "corpus_sha256": corpus_sha256,
        "candidate_gate_thresholds": {
            "completion_preservation_min_percent": COMPLETION_MIN_PERCENT,
            "exhaustion_max_percent": EXHAUSTION_MAX_PERCENT,
            "early_exhaustion_margin_s": EARLY_EXHAUSTION_MARGIN_S,
            "repeated_wait_burden_reduction_min_percent": BURDEN_REDUCTION_MIN_PERCENT,
        },
        "source_reports": source_reports,
        "candidate_evaluations": evaluations,
        "rejected_candidates": rejected_candidates,
        "live_candidates": live_candidates,
        "preferred_live_candidate": preferred,
        "open_evidence_limitations": [],
        "phase4_targeted_calibration_requirements": calibration_requirements,
        "production_budget_declared": False,
        "verdict": verdict,
    }


def build_final(shortlist_path: Path, historical_path: Path) -> dict[str, Any]:
    shortlist, shortlist_raw = _load_object(shortlist_path)
    historical, historical_raw = _load_object(historical_path)
    if shortlist.get("report_kind") != "phase3-candidate-shortlist":
        raise ValueError("final mode requires a Phase-3 candidate shortlist")
    corpus_sha256 = shortlist.get("corpus_sha256")
    if historical.get("corpus_sha256") != corpus_sha256:
        raise ValueError("historical H10 corpus_sha256 does not match shortlist")
    if historical.get("policy") != "historical-one-shot":
        raise ValueError("historical comparator must use historical-one-shot policy")
    if abs(_number(historical.get("budget_s"), "historical budget_s") - 10.0) > EPSILON:
        raise ValueError("historical comparator must use the frozen H10 budget")
    if historical.get("audit_status") != "pass":
        raise ValueError("historical H10 is not promoted with audit_status=pass")
    if historical.get("provisional") is not False:
        raise ValueError("historical H10 remains provisional")
    for field in (
        "rejected_candidates",
        "live_candidates",
        "preferred_live_candidate",
        "open_evidence_limitations",
        "phase4_targeted_calibration_requirements",
        "verdict",
    ):
        if field not in shortlist:
            raise ValueError(f"shortlist is missing {field}")

    return {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "phase3-policy-replay",
        "corpus_sha256": corpus_sha256,
        "candidate_shortlist_path": str(shortlist_path),
        "candidate_shortlist_sha256": _sha256(shortlist_raw),
        "rejected_candidates": shortlist["rejected_candidates"],
        "live_candidates": shortlist["live_candidates"],
        "preferred_live_candidate": shortlist["preferred_live_candidate"],
        "open_evidence_limitations": shortlist["open_evidence_limitations"],
        "phase4_targeted_calibration_requirements": shortlist[
            "phase4_targeted_calibration_requirements"
        ],
        "production_budget_declared": False,
        "verdict": shortlist["verdict"],
        "historical_comparator": {
            "path": str(historical_path),
            "sha256": _sha256(historical_raw),
            "policy": historical["policy"],
            "budget_s": historical["budget_s"],
            "summary": historical.get("summary"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="chat-scheduling-phase3-report")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    shortlist_parser = subparsers.add_parser("shortlist")
    shortlist_parser.add_argument("--corpus", type=Path, required=True)
    shortlist_parser.add_argument(
        "--candidate", type=Path, action="append", required=True
    )
    shortlist_parser.add_argument("--output-json", type=Path, required=True)
    shortlist_parser.add_argument("--output-md", type=Path, required=True)

    final_parser = subparsers.add_parser("final")
    final_parser.add_argument("--shortlist", type=Path, required=True)
    final_parser.add_argument("--historical", type=Path, required=True)
    final_parser.add_argument("--output-json", type=Path, required=True)
    final_parser.add_argument("--output-md", type=Path, required=True)

    args = parser.parse_args()
    if args.mode == "shortlist":
        report = build_shortlist(args.corpus, args.candidate)
        _write_outputs(
            report,
            json_path=args.output_json,
            md_path=args.output_md,
            markdown=render_shortlist_markdown(report),
        )
    else:
        report = build_final(args.shortlist, args.historical)
        _write_outputs(
            report,
            json_path=args.output_json,
            md_path=args.output_md,
            markdown=render_final_markdown(report),
        )


if __name__ == "__main__":
    main()

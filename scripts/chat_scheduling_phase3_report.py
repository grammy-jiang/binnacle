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

from scripts.chat_scheduling_phase3_report_populations import (
    burden_reduction_metrics,
    completion_metrics,
    corpus_row_ids,
    early_exhaustion_count,
    exhaustion_metrics,
    optional_exhaustion_metrics,
    positive_wait_evidence_issues,
    row_identity,
    split_rows,
)
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
    report_ids = sorted(row_identity(row) for row in rows if isinstance(row, Mapping))
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
    canonical_evidence_issues: Sequence[str],
    all_evidence_issues: Sequence[str],
) -> dict[str, Any]:
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise TypeError(f"{report_path} rows must be a list")
    canonical_rows, operational_rows = split_rows(rows, field=str(report_path))
    all_rows = [*canonical_rows, *operational_rows]

    canonical_completion = completion_metrics(
        canonical_rows, field=f"{report_path} canonical completion"
    )
    canonical_exhaustion = exhaustion_metrics(
        canonical_rows, field=f"{report_path} canonical exhaustion"
    )
    canonical_early = early_exhaustion_count(
        canonical_rows,
        budget_s=budget_s,
        margin_s=EARLY_EXHAUSTION_MARGIN_S,
        field=f"{report_path} canonical early exhaustion",
    )
    gate4_rows = operational_rows if operational_rows else canonical_rows
    gate4_population = (
        "operational_journal" if operational_rows else "canonical_phase1_fallback"
    )
    gate4_burden = burden_reduction_metrics(
        gate4_rows, field=f"{report_path} gate 4 burden"
    )

    prior_completion = completion_metrics(
        all_rows, field=f"{report_path} prior combined completion"
    )
    prior_exhaustion = exhaustion_metrics(
        all_rows, field=f"{report_path} prior combined exhaustion"
    )
    prior_early = early_exhaustion_count(
        all_rows,
        budget_s=budget_s,
        margin_s=EARLY_EXHAUSTION_MARGIN_S,
        field=f"{report_path} prior combined early exhaustion",
    )
    prior_burden = burden_reduction_metrics(
        all_rows, field=f"{report_path} prior combined burden"
    )
    operational_exhaustion = optional_exhaustion_metrics(
        operational_rows, field=f"{report_path} operational exhaustion"
    )

    gates: dict[str, dict[str, Any]] = {
        "gate_1_completion_preservation": {
            "passed": canonical_completion["value_percent"] + EPSILON
            >= COMPLETION_MIN_PERCENT,
            "value_percent": canonical_completion["value_percent"],
            "minimum_percent": COMPLETION_MIN_PERCENT,
            "observed_required_completions": canonical_completion[
                "observed_required_completions"
            ],
            "required_completions_preserved": canonical_completion[
                "required_completions_preserved"
            ],
        },
        "gate_2_exhaustion": {
            "passed": canonical_exhaustion["value_percent"]
            <= EXHAUSTION_MAX_PERCENT + EPSILON,
            "value_percent": canonical_exhaustion["value_percent"],
            "maximum_percent": EXHAUSTION_MAX_PERCENT,
            "denominator_turns_with_positive_waits": canonical_exhaustion[
                "turns_with_positive_waits"
            ],
            "turns_exhausted": canonical_exhaustion["turns_exhausted"],
        },
        "gate_3_no_early_exhaustion": {
            "passed": canonical_early == 0,
            "early_exhaustion_turns": canonical_early,
            "margin_s": EARLY_EXHAUSTION_MARGIN_S,
        },
        "gate_4_repeated_wait_burden_reduction": {
            "passed": gate4_burden["value_percent"] + EPSILON
            >= BURDEN_REDUCTION_MIN_PERCENT,
            "value_percent": gate4_burden["value_percent"],
            "minimum_percent": BURDEN_REDUCTION_MIN_PERCENT,
            "observed_blocking_wall_s": gate4_burden["observed_blocking_wall_s"],
            "candidate_blocking_wall_s": gate4_burden["candidate_blocking_wall_s"],
        },
        "gate_5_evidence_completeness": {
            "passed": not canonical_evidence_issues,
            "missing_evidence_count": len(canonical_evidence_issues),
            "examples": list(canonical_evidence_issues[:5]),
        },
    }
    gate_populations = {
        "gate_1_completion_preservation": {
            "population": "canonical_phase1_observed_valid_completion",
            "canonical_turns": len(canonical_rows),
            "turns_with_observed_required_completions": sum(
                int(row.get("observed_required_completions", 0)) > 0
                for row in canonical_rows
            ),
        },
        "gate_2_exhaustion": {
            "population": "canonical_phase1_positive_wait_turns",
            "turns": canonical_exhaustion["turns_with_positive_waits"],
        },
        "gate_3_no_early_exhaustion": {
            "population": "canonical_phase1_turns",
            "turns": len(canonical_rows),
        },
        "gate_4_repeated_wait_burden_reduction": {
            "population": gate4_population,
            "turns": len(gate4_rows),
            "fallback_used": not bool(operational_rows),
        },
        "gate_5_evidence_completeness": {
            "population": "canonical_phase1_positive_wait_turns",
            "turns": canonical_exhaustion["turns_with_positive_waits"],
        },
    }
    correction_before_after = {
        "gate_1_completion_preservation": {
            "metric": "value_percent",
            "before": prior_completion["value_percent"],
            "after": canonical_completion["value_percent"],
            "before_population": "canonical_plus_operational_required_completions",
            "after_population": "canonical_phase1_observed_valid_completion",
        },
        "gate_2_exhaustion": {
            "metric": "value_percent",
            "before": prior_exhaustion["value_percent"],
            "after": canonical_exhaustion["value_percent"],
            "before_population": "canonical_plus_operational_positive_wait_turns",
            "after_population": "canonical_phase1_positive_wait_turns",
        },
        "gate_3_no_early_exhaustion": {
            "metric": "early_exhaustion_turns",
            "before": prior_early,
            "after": canonical_early,
            "before_population": "canonical_plus_operational_turns",
            "after_population": "canonical_phase1_turns",
        },
        "gate_4_repeated_wait_burden_reduction": {
            "metric": "value_percent",
            "before": prior_burden["value_percent"],
            "after": gate4_burden["value_percent"],
            "before_population": "canonical_plus_operational_turns",
            "after_population": gate4_population,
        },
        "gate_5_evidence_completeness": {
            "metric": "missing_evidence_count",
            "before": len(all_evidence_issues),
            "after": len(canonical_evidence_issues),
            "before_population": "canonical_plus_operational_positive_wait_turns",
            "after_population": "canonical_phase1_positive_wait_turns",
        },
    }
    diagnostics = {
        "operational_exhaustion": {
            "population": "operational_journal_positive_wait_turns",
            **operational_exhaustion,
        },
        "combined_exhaustion": {
            "population": "canonical_plus_operational_positive_wait_turns",
            **prior_exhaustion,
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
        "gate_populations": gate_populations,
        "diagnostics": diagnostics,
        "correction_before_after": correction_before_after,
    }


def build_shortlist(
    corpus_path: Path, candidate_paths: Sequence[Path]
) -> dict[str, Any]:
    corpus, corpus_raw = _load_object(corpus_path)
    if corpus.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported replay corpus schema_version")
    corpus_sha256 = _sha256(corpus_raw)
    frozen_row_ids = corpus_row_ids(corpus)
    corpus_rows = corpus.get("rows")
    if not isinstance(corpus_rows, list):
        raise TypeError("replay corpus rows must be a list")
    canonical_corpus_rows, _ = split_rows(corpus_rows, field="replay corpus")
    canonical_evidence_issues = positive_wait_evidence_issues(
        canonical_corpus_rows, field="canonical replay corpus"
    )
    all_evidence_issues = positive_wait_evidence_issues(
        corpus_rows, field="combined replay corpus"
    )

    evaluations: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    source_reports: dict[str, dict[str, Any]] = {}
    for path in candidate_paths:
        report, raw = _load_object(path)
        candidate, budget_s = _validate_promoted_candidate(
            report,
            path=path,
            corpus_sha256=corpus_sha256,
            corpus_row_ids=frozen_row_ids,
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
                canonical_evidence_issues=canonical_evidence_issues,
                all_evidence_issues=all_evidence_issues,
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

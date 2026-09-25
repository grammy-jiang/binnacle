"""Candidate gate evaluation for Phase-3 shortlist reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.chat_scheduling_phase3_report_populations import (
    burden_reduction_metrics,
    completion_metrics,
    early_exhaustion_count,
    exhaustion_metrics,
    optional_exhaustion_metrics,
    repeated_wait_burden_reduction_metrics,
    row_identity,
    split_rows,
)

COMPLETION_MIN_PERCENT = 95.0
EXHAUSTION_MAX_PERCENT = 10.0
REPEATED_WAIT_BURDEN_REDUCTION_MIN_PERCENT = 60.0
DEFINITION_A_NON_GATING_REFERENCE_PERCENT = 70.0
EARLY_EXHAUSTION_MARGIN_S = 1.0
EPSILON = 1e-9


def _evaluate_candidate(
    report: Mapping[str, Any],
    *,
    candidate: str,
    budget_s: float,
    report_path: Path,
    report_sha256: str,
    canonical_evidence_issues: Sequence[str],
    all_evidence_issues: Sequence[str],
    corpus_rows_by_id: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise TypeError(f"{report_path} rows must be a list")
    canonical_rows, operational_rows = split_rows(rows, field=str(report_path))
    all_rows = [*canonical_rows, *operational_rows]
    canonical_source_rows = [
        corpus_rows_by_id[row_identity(row)] for row in canonical_rows
    ]
    operational_source_rows = [
        corpus_rows_by_id[row_identity(row)] for row in operational_rows
    ]
    all_source_rows = [*canonical_source_rows, *operational_source_rows]

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
    gate4_total_burden = burden_reduction_metrics(
        gate4_rows, field=f"{report_path} gate 4 definition-a burden"
    )
    gate4_source_rows = (
        operational_source_rows if operational_rows else canonical_source_rows
    )
    gate4_repeated_burden = repeated_wait_burden_reduction_metrics(
        gate4_source_rows,
        budget_s=budget_s,
        field=f"{report_path} gate 4 definition-b burden",
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
    prior_total_burden = burden_reduction_metrics(
        all_rows, field=f"{report_path} prior combined definition-a burden"
    )
    prior_repeated_burden = repeated_wait_burden_reduction_metrics(
        all_source_rows,
        budget_s=budget_s,
        field=f"{report_path} prior combined definition-b burden",
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
            "passed": gate4_repeated_burden["value_percent"] + EPSILON
            >= REPEATED_WAIT_BURDEN_REDUCTION_MIN_PERCENT,
            "value_percent": gate4_repeated_burden["value_percent"],
            "minimum_percent": REPEATED_WAIT_BURDEN_REDUCTION_MIN_PERCENT,
            "definition": "b_repeat_per_turn_job_union",
            "observed_repeated_wait_burden_s": gate4_repeated_burden[
                "observed_repeated_wait_burden_s"
            ],
            "candidate_repeated_wait_burden_s": gate4_repeated_burden[
                "candidate_repeated_wait_burden_s"
            ],
            "repeated_wait_burden_reduction_percent": gate4_repeated_burden[
                "repeated_wait_burden_reduction_percent"
            ],
            "observed_blocking_wall_s": gate4_total_burden["observed_blocking_wall_s"],
            "candidate_blocking_wall_s": gate4_total_burden[
                "candidate_blocking_wall_s"
            ],
            "burden_reduction_percent": gate4_total_burden["value_percent"],
            "definition_a_non_gating_reference_percent": (
                DEFINITION_A_NON_GATING_REFERENCE_PERCENT
            ),
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
            "metric": "repeated_wait_burden_reduction_percent",
            "before": prior_repeated_burden["value_percent"],
            "after": gate4_repeated_burden["value_percent"],
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
        "gate_4_definition_a_non_gating": {
            "population": gate4_population,
            "observed_blocking_wall_s": gate4_total_burden["observed_blocking_wall_s"],
            "candidate_blocking_wall_s": gate4_total_burden[
                "candidate_blocking_wall_s"
            ],
            "burden_reduction_percent": gate4_total_burden["value_percent"],
            "reference_percent": DEFINITION_A_NON_GATING_REFERENCE_PERCENT,
        },
        "combined_definition_a_non_gating": {
            "population": "canonical_plus_operational_turns",
            "observed_blocking_wall_s": prior_total_burden["observed_blocking_wall_s"],
            "candidate_blocking_wall_s": prior_total_burden[
                "candidate_blocking_wall_s"
            ],
            "burden_reduction_percent": prior_total_burden["value_percent"],
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

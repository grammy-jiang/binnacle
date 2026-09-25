"""Population metrics for Phase-3 offline candidate gates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.chat_scheduling_replay import repeated_wait_burden

OPERATIONAL_SOURCE_ID = "operational-journal"
EPSILON = 1e-9


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


def row_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_id")),
        str(row.get("trial_id")),
        str(row.get("base_turn")),
    )


def corpus_row_ids(corpus: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    rows = corpus.get("rows")
    if not isinstance(rows, list):
        raise TypeError("replay corpus rows must be a list")
    identities: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"corpus row {index} must be an object")
        identities.append(row_identity(row))
    if len(set(identities)) != len(identities):
        raise ValueError("replay corpus row identities are not unique")
    return sorted(identities)


def split_rows(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    canonical: list[Mapping[str, Any]] = []
    operational: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"{field} row {index} must be an object")
        if row.get("source_id") == OPERATIONAL_SOURCE_ID:
            operational.append(row)
        else:
            canonical.append(row)
    if not canonical:
        raise ValueError(f"{field} has no canonical Phase-1 rows")
    return canonical, operational


def completion_metrics(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> dict[str, Any]:
    observed = sum(
        _integer(row.get("observed_required_completions"), f"{field} observed_required")
        for row in rows
    )
    preserved = sum(
        _integer(row.get("required_completions_preserved"), f"{field} preserved")
        for row in rows
    )
    if observed <= 0:
        raise ValueError(
            f"{field} completion-preservation denominator must be positive"
        )
    return {
        "observed_required_completions": observed,
        "required_completions_preserved": preserved,
        "value_percent": round(100.0 * preserved / observed, 6),
    }


def exhaustion_metrics(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> dict[str, Any]:
    positive = [
        row
        for row in rows
        if _integer(row.get("positive_waits_observed"), f"{field} positive_waits") > 0
    ]
    if not positive:
        raise ValueError(f"{field} exhaustion denominator must be positive")
    exhausted = sum(
        row.get("candidate_exhaustion_offset_s") is not None for row in positive
    )
    return {
        "turns_with_positive_waits": len(positive),
        "turns_exhausted": exhausted,
        "value_percent": round(100.0 * exhausted / len(positive), 6),
    }


def optional_exhaustion_metrics(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "turns_with_positive_waits": 0,
            "turns_exhausted": 0,
            "value_percent": None,
        }
    result = exhaustion_metrics(rows, field=field)
    return {"available": True, **result}


def burden_reduction_metrics(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"{field} burden population must not be empty")
    observed = sum(
        _number(row.get("observed_blocking_wall_s"), f"{field} observed wall")
        for row in rows
    )
    candidate = sum(
        _number(row.get("candidate_blocking_wall_s"), f"{field} candidate wall")
        for row in rows
    )
    if observed <= EPSILON:
        raise ValueError(f"{field} burden-reduction denominator must be positive")
    return {
        "turns": len(rows),
        "observed_blocking_wall_s": round(observed, 6),
        "candidate_blocking_wall_s": round(candidate, 6),
        "value_percent": round(100.0 * (observed - candidate) / observed, 6),
    }


def repeated_wait_burden_reduction_metrics(
    rows: Sequence[Mapping[str, Any]], *, budget_s: float, field: str
) -> dict[str, Any]:
    """Aggregate repeated-wait definition (b) over source rows."""

    if not rows:
        raise ValueError(f"{field} repeated-wait burden population must not be empty")
    metrics = [
        repeated_wait_burden(row, policy="cumulative", budget_s=budget_s)
        for row in rows
    ]
    observed = sum(
        _number(
            item.get("observed_repeated_wait_burden_s"),
            f"{field} observed repeated-wait burden",
        )
        for item in metrics
    )
    candidate = sum(
        _number(
            item.get("candidate_repeated_wait_burden_s"),
            f"{field} candidate repeated-wait burden",
        )
        for item in metrics
    )
    if observed <= EPSILON:
        raise ValueError(
            f"{field} repeated-wait burden-reduction denominator must be positive"
        )
    reduction = round(100.0 * (observed - candidate) / observed, 6)
    return {
        "turns": len(rows),
        "observed_repeated_wait_burden_s": round(observed, 6),
        "candidate_repeated_wait_burden_s": round(candidate, 6),
        "repeated_wait_burden_reduction_percent": reduction,
        "value_percent": reduction,
    }


def early_exhaustion_count(
    rows: Sequence[Mapping[str, Any]],
    *,
    budget_s: float,
    margin_s: float,
    field: str,
) -> int:
    count = 0
    for index, row in enumerate(rows):
        exhausted = row.get("candidate_exhaustion_offset_s") is not None
        observed = _number(
            row.get("observed_blocking_wall_s"),
            f"{field} row {index} observed_blocking_wall_s",
        )
        if exhausted and observed <= budget_s - margin_s + EPSILON:
            count += 1
    return count


def positive_wait_evidence_issues(
    rows: Sequence[Mapping[str, Any]], *, field: str
) -> list[str]:
    issues: list[str] = []
    for row_index, row in enumerate(rows):
        waits = row.get("waits")
        if not isinstance(waits, list):
            raise TypeError(f"{field} row {row_index} waits must be a list")
        for wait_index, wait in enumerate(waits):
            if not isinstance(wait, Mapping):
                raise TypeError(
                    f"{field} row {row_index} wait {wait_index} must be an object"
                )
            requested = _number(
                wait.get("requested_wait_s"),
                f"{field} row {row_index} wait {wait_index} requested_wait_s",
            )
            if requested <= EPSILON:
                continue
            missing: list[str] = []
            for name in (
                "call_start_offset_s",
                "call_end_offset_s",
                "waited_s",
                "state",
            ):
                if wait.get(name) is None:
                    missing.append(name)
            waited = wait.get("waited_s")
            if (
                waited is not None
                and _number(
                    waited, f"{field} row {row_index} wait {wait_index} waited_s"
                )
                > EPSILON
            ):
                for name in ("blocking_start_offset_s", "blocking_end_offset_s"):
                    if wait.get(name) is None:
                        missing.append(name)
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
                ident = (
                    str(row.get("source_id")),
                    str(row.get("trial_id")),
                    str(row.get("base_turn")),
                )
                issues.append(
                    f"{'/'.join(ident)} wait {wait_index}: "
                    + ", ".join(sorted(set(missing)))
                )
    return issues

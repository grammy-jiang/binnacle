"""Analysis and rendering for the search_text adaptive-discovery A/B."""

from __future__ import annotations

import statistics
from typing import Any

from fastmcp.exceptions import ToolError

from scripts.search_text_ab_dataset import (
    DEFAULT_HORIZON,
    extract_cases,
    median_search_or_read_tokens,
)
from scripts.search_text_ab_replay import (
    DEFAULT_DETAILED,
    DEFAULT_REPRESENTATIVES,
    DEFAULT_SNIPPET_CHARS,
    DEFAULT_TOTAL,
    build_b,
    collect_matches,
    replay_a,
)

REPLAY_ERRORS = (OSError, ValueError, KeyError, TypeError, ToolError)


def recall(candidate_files: set[str], evidence: set[str]) -> dict[str, Any]:
    if not evidence:
        return {"hit": 0, "total": 0, "recall": None, "all_recalled": None}
    hit = len(candidate_files & evidence)
    return {
        "hit": hit,
        "total": len(evidence),
        "recall": hit / len(evidence),
        "all_recalled": hit == len(evidence),
    }


def distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        index = min(len(ordered) - 1, int((len(ordered) - 1) * q + 0.5))
        return float(ordered[index])

    return {
        "mean": statistics.mean(values),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "max": float(max(values)),
    }


def _case_row(case: Any, a: dict[str, Any], b: dict[str, Any], files: set[str]) -> dict:
    evidence = set(case.evidence_files) & files
    a_recall = recall(set(a["candidate_files"]), evidence)
    b_recall = recall(set(b["candidate_files"]), evidence)
    b_detail_recall = recall(set(b["detailed_files"]), evidence)
    evidence_ranks = {
        file: b["ranked_files"].index(file) + 1
        for file in sorted(evidence)
        if file in b["ranked_files"]
    }
    misses = [
        {
            "file": file,
            "rank": evidence_ranks[file],
            "count": b["facts"][file].count,
            "breadth": len(b["facts"][file].branches),
            "path_hits": b["facts"][file].path_hits,
        }
        for file in sorted(evidence)
        if evidence_ranks[file] > b["candidate_file_count"]
    ]
    return {
        "call": case.call,
        "turn": case.turn,
        "path": str(case.args["path"]),
        "pattern": str(case.args["pattern"]),
        "historical_tokens": case.historical_tokens,
        "current_matches": b["count"],
        "current_match_files": b["file_count"],
        "observed_evidence_files": len(case.evidence_files),
        "matched_evidence_files": len(evidence),
        "a": {**a, "evidence": a_recall},
        "b": {
            key: value
            for key, value in b.items()
            if key not in {"ranked_files", "facts"}
        }
        | {
            "evidence": b_recall,
            "detailed_evidence": b_detail_recall,
            "evidence_ranks": evidence_ranks,
            "ranking_misses": misses,
        },
        "token_saving": a["tokens"] - b["tokens"],
        "token_saving_fraction": (
            (a["tokens"] - b["tokens"]) / a["tokens"] if a["tokens"] else 0.0
        ),
    }


def _sensitivity(
    cache: list[tuple[Any, Any, dict[str, Any]]],
    *,
    detailed: int,
    representatives: int,
    snippet_chars: int,
    evidence_total: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for total in (100, 150, 200):
        hits = 0
        all_recalled = 0
        evidence_cases = 0
        tokens: list[float] = []
        for case, root, files in cache:
            variant = build_b(
                case,
                root,
                files,
                detailed=detailed,
                total_candidates=total,
                representatives=representatives,
                snippet_chars=snippet_chars,
            )
            evidence = set(case.evidence_files) & set(files)
            candidate_recall = recall(set(variant["candidate_files"]), evidence)
            tokens.append(float(variant["tokens"]))
            if evidence:
                evidence_cases += 1
                hits += candidate_recall["hit"]
                all_recalled += int(bool(candidate_recall["all_recalled"]))
        output[str(total)] = {
            "tokens": distribution(tokens),
            "evidence_file_recall": hits / evidence_total if evidence_total else None,
            "queries_all_evidence_recalled": (
                all_recalled / evidence_cases if evidence_cases else None
            ),
        }
    return output


def analyze(
    log_text: str,
    *,
    horizon: int = DEFAULT_HORIZON,
    detailed: int = DEFAULT_DETAILED,
    total_candidates: int = DEFAULT_TOTAL,
    representatives: int = DEFAULT_REPRESENTATIVES,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> dict[str, Any]:
    cases = extract_cases(log_text, horizon)
    rows: list[dict[str, Any]] = []
    cache: list[tuple[Any, Any, dict[str, Any]]] = []
    skipped: list[dict[str, str]] = []

    for case in cases:
        try:
            a = replay_a(case)
            root, files = collect_matches(case)
            b = build_b(
                case,
                root,
                files,
                detailed=detailed,
                total_candidates=total_candidates,
                representatives=representatives,
                snippet_chars=snippet_chars,
            )
        except REPLAY_ERRORS as exc:
            skipped.append({"call": case.call, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(_case_row(case, a, b, set(files)))
        cache.append((case, root, files))

    comparable = [row for row in rows if row["matched_evidence_files"]]
    evidence_total = sum(row["matched_evidence_files"] for row in comparable)
    a_hits = sum(row["a"]["evidence"]["hit"] for row in comparable)
    b_hits = sum(row["b"]["evidence"]["hit"] for row in comparable)
    detail_hits = sum(row["b"]["detailed_evidence"]["hit"] for row in comparable)
    token_savings = [float(row["token_saving"]) for row in rows]
    median_followup = median_search_or_read_tokens(log_text)
    historical_pairs = [
        (row["historical_tokens"], row["a"]["tokens"])
        for row in rows
        if row["historical_tokens"]
    ]
    replay_drift = [
        (current - historical) / historical
        for historical, current in historical_pairs
        if historical
    ]

    return {
        "config": {
            "horizon": horizon,
            "detailed_files": detailed,
            "total_candidates": total_candidates,
            "representative_matches": representatives,
            "snippet_chars": snippet_chars,
            "size_estimate_formula": "(content_chars + compact_structured_json_chars) // 4",
        },
        "historical_budget_hit_cases": len(cases),
        "replayed_cases": len(rows),
        "skipped_cases": skipped,
        "cases_with_matched_evidence": len(comparable),
        "matched_evidence_files": evidence_total,
        "a_tokens": distribution([float(row["a"]["tokens"]) for row in rows]),
        "b_tokens": distribution([float(row["b"]["tokens"]) for row in rows]),
        "historical_a_tokens": distribution(
            [float(historical) for historical, _ in historical_pairs]
        ),
        "a_replay_relative_drift_mean": (
            statistics.mean(replay_drift) if replay_drift else 0.0
        ),
        "a_replay_relative_drift_median_abs": (
            statistics.median(abs(value) for value in replay_drift)
            if replay_drift
            else 0.0
        ),
        "a_candidate_files": distribution(
            [float(row["a"]["candidate_file_count"]) for row in rows]
        ),
        "b_candidate_files": distribution(
            [float(row["b"]["candidate_file_count"]) for row in rows]
        ),
        "current_match_files": distribution(
            [float(row["current_match_files"]) for row in rows]
        ),
        "a_entries": distribution([float(row["a"]["entry_count"]) for row in rows]),
        "token_saving": distribution(token_savings),
        "mean_token_saving_fraction": (
            statistics.mean(row["token_saving_fraction"] for row in rows)
            if rows
            else 0.0
        ),
        "a_evidence_file_recall": a_hits / evidence_total if evidence_total else None,
        "b_detailed_evidence_file_recall": (
            detail_hits / evidence_total if evidence_total else None
        ),
        "b_total_evidence_file_recall": b_hits / evidence_total
        if evidence_total
        else None,
        "a_queries_all_evidence_recalled": (
            sum(bool(row["a"]["evidence"]["all_recalled"]) for row in comparable)
            / len(comparable)
            if comparable
            else None
        ),
        "b_queries_all_evidence_recalled": (
            sum(bool(row["b"]["evidence"]["all_recalled"]) for row in comparable)
            / len(comparable)
            if comparable
            else None
        ),
        "median_search_or_read_result_tokens": median_followup,
        "mean_break_even_extra_followups": (
            statistics.mean(token_savings) / median_followup
            if token_savings and median_followup
            else None
        ),
        "sensitivity_total_candidates": _sensitivity(
            cache,
            detailed=detailed,
            representatives=representatives,
            snippet_chars=snippet_chars,
            evidence_total=evidence_total,
        ),
        "rows": rows,
    }


def render(report: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "-" if value is None else f"{value:.1%}"

    lines = [
        "# search_text adaptive discovery A/B",
        "",
        f"Historical budget-hit cases: {report['historical_budget_hit_cases']}",
        f"Replayed cases: {report['replayed_cases']}",
        f"Cases with matched observed evidence: {report['cases_with_matched_evidence']}",
        f"Matched observed evidence files: {report['matched_evidence_files']}",
        "",
        "## Replay sanity",
        "",
        (
            "A replay vs historical production token drift: "
            f"mean {report['a_replay_relative_drift_mean']:.1%}, "
            f"median absolute {report['a_replay_relative_drift_median_abs']:.1%}."
        ),
        (
            f"A candidate files mean/p50: {report['a_candidate_files']['mean']:.1f}/"
            f"{report['a_candidate_files']['p50']:.0f}; "
            f"A entries mean: {report['a_entries']['mean']:.1f}."
        ),
        (
            f"Current matching files mean/p50: {report['current_match_files']['mean']:.1f}/"
            f"{report['current_match_files']['p50']:.0f}."
        ),
        "",
        "## Primary A/B",
        "",
        "| Metric | A: current 64 KiB prefix | B: adaptive discovery |",
        "| --- | ---: | ---: |",
        (
            f"| Estimated tokens, mean | {report['a_tokens']['mean']:.0f} | "
            f"{report['b_tokens']['mean']:.0f} |"
        ),
        (
            f"| Estimated tokens, p50 | {report['a_tokens']['p50']:.0f} | "
            f"{report['b_tokens']['p50']:.0f} |"
        ),
        (
            f"| Estimated tokens, p90 | {report['a_tokens']['p90']:.0f} | "
            f"{report['b_tokens']['p90']:.0f} |"
        ),
        (
            f"| Observed evidence-file recall | {pct(report['a_evidence_file_recall'])} | "
            f"{pct(report['b_total_evidence_file_recall'])} |"
        ),
        (
            f"| Queries recalling all observed evidence | "
            f"{pct(report['a_queries_all_evidence_recalled'])} | "
            f"{pct(report['b_queries_all_evidence_recalled'])} |"
        ),
        "",
        f"Mean first-hop token reduction: {report['mean_token_saving_fraction']:.1%}.",
        (
            "Mean break-even extra search/read follow-ups: "
            f"{report['mean_break_even_extra_followups']:.1f}."
            if report["mean_break_even_extra_followups"] is not None
            else "Mean break-even extra search/read follow-ups: -."
        ),
        "",
        (
            "B detailed-only evidence recall: "
            f"{pct(report['b_detailed_evidence_file_recall'])}."
        ),
        "",
        "## Candidate-tail sensitivity",
        "",
        "| Total candidates | Mean tokens | Evidence recall | All-evidence queries |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for total, data in report["sensitivity_total_candidates"].items():
        lines.append(
            f"| {total} | {data['tokens']['mean']:.0f} | "
            f"{pct(data['evidence_file_recall'])} | "
            f"{pct(data['queries_all_evidence_recalled'])} |"
        )

    misses = [
        (row["call"], miss)
        for row in report["rows"]
        for miss in row["b"]["ranking_misses"]
    ]
    lines += ["", "## Primary-B ranking misses", ""]
    if not misses:
        lines.append("None.")
    else:
        lines.append("| Call | Rank | Matches | Breadth | Path hits | File |")
        lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
        for call, miss in misses:
            lines.append(
                f"| {call} | {miss['rank']} | {miss['count']} | {miss['breadth']} | "
                f"{miss['path_hits']} | {miss['file']} |"
            )
    return "\n".join(lines) + "\n"

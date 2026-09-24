"""Rendering helpers for deterministic Phase-3 reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_shortlist_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase-3 candidate shortlist",
        "",
        f"- Corpus SHA-256: {report['corpus_sha256']}",
        f"- Verdict: {report['verdict']}",
        "- Production budget declared: false",
        "",
        "## Candidate gates",
        "",
        (
            "| Candidate | Budget (s) | Completion % | Exhaustion % | "
            "Early exhaustions | Burden reduction % | Evidence complete | Result |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in report["candidate_evaluations"]:
        gates = item["gates"]
        lines.append(
            f"| {item['candidate']} | {item['budget_s']} | "
            f"{gates['gate_1_completion_preservation']['value_percent']} | "
            f"{gates['gate_2_exhaustion']['value_percent']} | "
            f"{gates['gate_3_no_early_exhaustion']['early_exhaustion_turns']} | "
            f"{gates['gate_4_repeated_wait_burden_reduction']['value_percent']} | "
            f"{gates['gate_5_evidence_completeness']['passed']} | "
            f"{'PASS' if item['passed'] else 'REJECT'} |"
        )
    lines.extend(["", "## Rejected candidates", ""])
    if report["rejected_candidates"]:
        for item in report["rejected_candidates"]:
            lines.append(
                f"- {item['candidate']} ({item['budget_s']} s): "
                + ", ".join(item["failed_gates"])
            )
    else:
        lines.append("- None.")
    live = report["live_candidates"]
    lines.extend(
        [
            "",
            "## Live candidates",
            "",
            "- Live candidates: " + (", ".join(live) if live else "none"),
            "- Preferred live candidate: "
            + (str(report["preferred_live_candidate"]) if live else "none"),
            "",
            "## Open evidence limitations",
            "",
        ]
    )
    limitations = report["open_evidence_limitations"]
    lines.extend([f"- {item}" for item in limitations] if limitations else ["- None."])
    lines.extend(["", "## Phase-4 targeted calibration requirements", ""])
    lines.extend(
        f"- {item}" for item in report["phase4_targeted_calibration_requirements"]
    )
    return "\n".join([*lines, ""])


def render_final_markdown(report: Mapping[str, Any]) -> str:
    historical = report["historical_comparator"]
    live = report["live_candidates"]
    lines = [
        "# Phase-3 policy replay",
        "",
        f"- Corpus SHA-256: {report['corpus_sha256']}",
        f"- Candidate shortlist: {report['candidate_shortlist_path']}",
        f"- Candidate shortlist SHA-256: {report['candidate_shortlist_sha256']}",
        f"- Verdict: {report['verdict']}",
        "- Production budget declared: false",
        "",
        "## Candidate selection",
        "",
        "- Live candidates: " + (", ".join(live) if live else "none"),
        "- Preferred live candidate: "
        + (
            str(report["preferred_live_candidate"])
            if report["preferred_live_candidate"] is not None
            else "none"
        ),
        "",
        "## Historical H10 comparator",
        "",
        f"- Path: {historical['path']}",
        f"- SHA-256: {historical['sha256']}",
        f"- Policy: {historical['policy']}",
        f"- Budget: {historical['budget_s']} s",
        "",
        (
            "The H10 result is historical-comparator evidence only and is not eligible "
            "for the live candidate shortlist."
        ),
        "",
    ]
    return "\n".join(lines)


def _write_outputs(
    payload: Mapping[str, Any], *, json_path: Path, md_path: Path, markdown: str
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(canonical_json(payload), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

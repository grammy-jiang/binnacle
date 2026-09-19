#!/usr/bin/env python3
"""Detailed JSON/text view of the indexed-context section from ``binnacle stats``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from binnacle import logstats


def main() -> None:
    ap = argparse.ArgumentParser(description="Indexed @context pilot statistics.")
    ap.add_argument("--since", default="24 hours ago")
    ap.add_argument("--until")
    ap.add_argument("--input", type=Path, help="Analyze a saved journal text file.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    text = (
        args.input.read_text(errors="replace")
        if args.input
        else logstats.fetch_journal("binnacle-mcp", args.since, args.until)
    )
    records, _ = logstats.parse(text)
    report = logstats.indexed_context_report(logstats.analyze_indexed_context(records))
    if args.as_json:
        print(json.dumps(report, indent=2))
        return

    print(f"Indexed successes: {report['indexed_successes']}")
    print(f"Indexed errors:    {report['indexed_errors']} {report['error_phases']}")
    print(f"Pilot versions:    {report['pilot_versions']}")
    print(f"Cold opens:        {report['cold_opens']}")
    print(f"Changed files:     {report['changed_files']}")
    print(f"Evidence opened:   {report['evidence_open_conversion']:.1%}")
    for title, key in (
        ("Result tokens", "result_tokens"),
        ("Package bytes", "package_bytes"),
        ("Total latency ms", "latency_total_ms"),
        ("Reconcile ms", "latency_reconcile_ms"),
        ("Query ms", "latency_query_ms"),
        ("Follow-up calls", "followup_calls"),
        ("Follow-up exact", "followup_exact_searches"),
        ("Follow-up reads", "followup_reads"),
        ("Follow-up tokens", "followup_result_tokens"),
        ("Investigation tokens", "investigation_result_tokens"),
    ):
        q = report[key]
        print(
            f"{title:20s} mean={q['mean']:.1f} p50={q['p50']:.1f} "
            f"p90={q['p90']:.1f} max={q['max']:.1f}"
        )


if __name__ == "__main__":
    main()

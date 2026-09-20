#!/usr/bin/env python3
"""Run the offline search_text adaptive-discovery A/B replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binnacle import logstats
from scripts.search_text_ab_dataset import DEFAULT_HORIZON
from scripts.search_text_ab_replay import (
    DEFAULT_DETAILED,
    DEFAULT_REPRESENTATIVES,
    DEFAULT_SNIPPET_CHARS,
    DEFAULT_TOTAL,
)
from scripts.search_text_ab_report import analyze, render


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2 days ago")
    parser.add_argument("--until")
    parser.add_argument("--input", type=Path, help="Use a saved binnacle-mcp journal.")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--detailed", type=int, default=DEFAULT_DETAILED)
    parser.add_argument("--total", type=int, default=DEFAULT_TOTAL)
    parser.add_argument("--representatives", type=int, default=DEFAULT_REPRESENTATIVES)
    parser.add_argument("--snippet-chars", type=int, default=DEFAULT_SNIPPET_CHARS)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.detailed < 1 or args.total < args.detailed:
        parser.error("--total must be >= --detailed >= 1")
    if args.representatives < 1:
        parser.error("--representatives must be >= 1")
    if args.snippet_chars < 1:
        parser.error("--snippet-chars must be >= 1")

    text = (
        args.input.read_text(errors="replace")
        if args.input
        else logstats.fetch_journal("binnacle-mcp", args.since, args.until)
    )
    report = analyze(
        text,
        horizon=args.horizon,
        detailed=args.detailed,
        total_candidates=args.total,
        representatives=args.representatives,
        snippet_chars=args.snippet_chars,
    )
    rendered = render(report)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered)

    print(
        json.dumps(report, indent=2, default=str) if args.as_json else rendered, end=""
    )


if __name__ == "__main__":
    main()

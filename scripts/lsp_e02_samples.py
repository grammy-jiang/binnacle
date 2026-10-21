"""E2: select host-local historical candidate and negative-control request groups.

No historic commands are executed; no user text, paths, commands, source,
per-call digests or original group identifiers appear on stdout. A private,
optional metadata manifest enables later E3 review only on the same host.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path

if __package__:
    from .lsp_e01_trace import Corpus, _events, _observer, _resolve_terminals, _time
    from .lsp_e02_private import write_document
    from .lsp_e02_selection import episodes, sample, summary
else:
    from lsp_e01_trace import Corpus, _events, _observer, _resolve_terminals, _time
    from lsp_e02_private import write_document
    from lsp_e02_selection import episodes, sample, summary

REPORT_SCHEMA = "binnacle-development-intelligence-e2-local-manifest/1"


def write_private_manifest(
    private_dir: Path,
    selected: list,
    *,
    cohort_end: dt.datetime,
    seed: int,
    name: str,
) -> None:
    """Privately persist opaque evidence pointers; no original values."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name):
        raise ValueError("invalid private batch name")
    records = []
    for i, entry in enumerate(selected, start=1):
        records.append(
            {
                "schema": REPORT_SCHEMA,
                "batch": name,
                "case_index": i,
                "_host_private_lookup_material": [entry.group, entry.calls[0].key],
                "stratum": entry.stratum,
                "group_call_count": len(entry.calls),
                "call_start_windows": dict(entry.window_counts),
                "source_quality": entry.source_quality,
                "result_quality": entry.outcome_quality,
                "partial_subgoal_hint": entry.partial_goal_hint,
                "actual_user_task_verified": False,
                "independent_gold_verified": False,
                "original_source_snapshot_verified": False,
                "replayability": "R0_unverified",
                "annotation_status": "pending_independent_review",
                "evaluation_role": (
                    "negative_control"
                    if entry.stratum.startswith("negative_")
                    else "candidate"
                ),
            }
        )
    write_document(
        private_dir,
        name,
        {
            "schema": REPORT_SCHEMA,
            "cutoff_utc": cohort_end.isoformat(),
            "seed": seed,
            "cases": records,
        },
    )


def run(
    capture_dir: Path,
    observer_db: Path | None,
    *,
    until: dt.datetime,
    limit: int = 20,
    seed: int = 20261021,
    minimum_negatives: int = 4,
    private_dir: Path | None = None,
    batch: str = "pilot-20261021-noon",
) -> dict:
    if until.tzinfo is None:
        raise ValueError("E2 requires UTC-aware cutoff")
    until = until.astimezone(dt.timezone.utc)
    mapping, ambiguous = _observer(observer_db)
    corpus = Corpus()
    _events(capture_dir, corpus, mapping, ambiguous, until)
    _resolve_terminals(corpus)
    population, missing = episodes(corpus)
    selected = sample(
        population,
        limit=limit,
        seed=seed,
        minimum_negatives=minimum_negatives,
    )
    out = summary(population, selected, missing)
    out["cohort_cutoff_utc"] = until.isoformat()
    out["sample_seed"] = seed
    out["sampling_limit_per_host"] = limit
    out["negative_target_per_host"] = minimum_negatives
    out["capture_tool_calls"] = len(corpus.calls)
    out["capture_quality"] = {
        key: corpus.counts[key]
        for key in (
            "files",
            "rows",
            "invalid_json",
            "incomplete_lines",
            "invalid_record_shape",
            "invalid_request_payload",
            "invalid_tool_call_payload",
            "after_cutoff_excluded",
            "unknown_timestamp_excluded",
            "orphan_terminals",
            "calls_without_identity",
            "requests_without_identity",
        )
    }
    out["excluded_malformed_rows"] = (
        corpus.counts["invalid_json"]
        + corpus.counts["invalid_record_shape"]
        + corpus.counts["invalid_tool_call_payload"]
        + corpus.counts["invalid_request_payload"]
    )
    out["group_count_not_manual_tasks"] = True
    out["private_manifest_created"] = private_dir is not None
    if private_dir is not None:
        write_private_manifest(
            private_dir, selected, cohort_end=until, seed=seed, name=batch
        )
    return out


class SafeParser(argparse.ArgumentParser):
    """Never echo an untrusted command-line value in parser errors."""

    def error(self, message: str) -> None:
        self.exit(2, "E02_ARGUMENT_ERROR\n")


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--observer-db", type=Path)
    parser.add_argument("--until-utc", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--minimum-negatives", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--private-dir", type=Path)
    parser.add_argument("--batch", default="pilot-20261021-noon")
    args = parser.parse_args()
    cutoff = _time(args.until_utc)
    if cutoff is None:
        parser.error("invalid aware cutoff")
    try:
        if not args.capture_dir.is_dir():
            raise ValueError("capture directory missing")
        result = run(
            args.capture_dir,
            args.observer_db,
            until=cutoff,
            limit=args.limit,
            seed=args.seed,
            minimum_negatives=args.minimum_negatives,
            private_dir=args.private_dir,
            batch=args.batch,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Only an error category; no host-specific private paths or payloads.
        print(f"E02_SAMPLING_FAILED:{type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

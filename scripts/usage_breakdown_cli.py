#!/usr/bin/env python3
"""CLI rendering for usage_breakdown.py."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import usage_breakdown as analysis


def main() -> None:
    ap = argparse.ArgumentParser(description="ChatGPT-attributed usage breakdown.")
    ap.add_argument("--since", required=True)
    ap.add_argument("--until")
    ap.add_argument(
        "--all-clients", action="store_true", help="do not filter to ChatGPT"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--keep-tests", action="store_true", help="keep nonce-marked e2e test commands"
    )
    a = ap.parse_args()

    journal = analysis.logstats.fetch_journal("binnacle-mcp", a.since, a.until)
    records, _ = analysis.logstats.parse(journal)
    rep = analysis.build_report(
        records,
        journal,
        analysis.tunnel_dispatch_times(),
        a.since,
        a.until,
        all_clients=a.all_clients,
        keep_tests=a.keep_tests,
    )
    if a.json:
        print(json.dumps(rep, indent=2))
        return
    total = rep["tool_calls"]
    print(f"{rep['scope']}, since {a.since}" + (f" until {a.until}" if a.until else ""))
    print(f"tool calls: {total}")
    for t, n in rep["tools"].items():
        print(f"  {n:5d} {100 * n / max(total, 1):5.1f}%  {t}")
    js = rep["job_status"]
    print(
        f"\njob_status: {js['calls']} calls on {js['jobs']} jobs; "
        f"per job median={js['median_per_job']} max={js['max_per_job']}"
    )
    print("new-parameter uptake:", rep["param_uptake"] or "none")
    print("read_file:", rep["read_file"])
    print(
        f"job_status listings without a job_id: {js['listings']}; "
        f"run_command background=true: {rep['run_command']['background']}"
    )
    print("turns:", rep["turns"])
    n_run = rep["run_command"]["calls"]
    print(f"\nrun_command traits ({n_run} calls with a visible command):")
    for k, n in rep["run_command"]["traits"].items():
        print(f"  {n:5d} {100 * n / max(n_run, 1):5.1f}%  {k}")
    print(f"grep: {rep['grep']}")
    print(
        "git subcommands:",
        ", ".join(f"{k}={v}" for k, v in list(rep["git_subcommands"].items())[:8]),
    )
    res = rep["results"]
    if res["calls_with_sizes"]:
        print(
            f"\nresults (2026-09-13 on): {res['calls_with_sizes']} sized calls, "
            f"est_tokens total {res['est_tokens_total']} (chars/4); "
            f"{res['became_jobs']} run_commands became jobs; job exits {res['job_exits']}"
        )
        print(
            "  tool                      calls  tok p50  tok p90  tok max  truncated  errors"
        )
        for t, d in res["by_tool"].items():
            print(
                f"  {t:24s} {d['calls']:6d} {d['est_tokens_median']:8.0f} "
                f"{d['est_tokens_p90']:8.0f} {d['est_tokens_max']:8.0f} "
                f"{d['truncated']:10d} {d['errors']:7d}"
            )
        if res["errors_by_class"]:
            print("  errors by class:", res["errors_by_class"])
        print("  latency_ms:", res["latency_ms"])
        tj = rep["turns_journal"]
        print(
            f"  turns from the journal's turn= field: {tj['turns']} turns, "
            f"{tj['calls']} tool calls, per turn median={tj['calls_per_turn_median']} "
            f"max={tj['calls_per_turn_max']}"
        )
    print(
        "\nBaseline 09-01..09-02 by this script's own definitions "
        "(--since 2026-09-01 --until 2026-09-03): 2250 calls; run_command 62.9%, "
        "job_status 26.6% (591 polls/117 jobs, median 3, max 33), read_file 8.7%, "
        "search_text 1.2%; traits of 1415 run_commands: python-heredoc 655, grep 367 "
        "(363 on files), git 339, hand-tail/head 233, ps/pgrep 165. Narrative "
        "figures in docs/usage-analysis-2026-09-03.md use wider regexes."
    )


if __name__ == "__main__":
    main()

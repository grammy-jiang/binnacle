#!/usr/bin/env python3
"""The week's production numbers (scripts/weekly_quality.py).

    scripts/weekly_usage.py --since "YYYY-MM-DD HH:MM:SS" --until "..." --out <json>

Run as a program inside its scope, it reads the production journal of the
window once (read-only) and writes two things to ``--out``:

- the p50 and p95 of each tool's ``duration_ms`` (the tool_result lines),
  without the calls whose arguments carry an ``e2e-`` nonce (the smokes'
  test traffic);
- the model-step and job-polling metrics of scripts/usage_breakdown.py for
  ChatGPT (the same code the usage reviews use).

The runner side (``usage_checks``) compares them. Journal latency: with the
week's first run as the baseline (state directory), a WARN only for the
tools whose time the server decides (read_file, edit_file, write_file) and
only with 30 calls on both sides. list_files and search_text take as long
as the tree the model chose (a p95 of 3.6 s and 1.0 s on 2026-09-27), and
run_command, job_status and stop_job as long as the commands and the waits
it asked for, so they are reported, never judged; the fixed benchmark
covers list_files and search_text. Usage: against the latest
docs/usage-baselines/ file that has step metrics, else the 2026-09-27
figures in docs/usage-analysis-2026-09-27.md; a WARN when solo job_status
polls take 25 % more of the steps, or excess polls per 1000 steps rise by
25 %, with at least 300 steps in the week. Steps per turn depend on the
week's work, so they are reported only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make `scripts` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smoke_checks import Check
from scripts.weekly_bench_checks import percentile
from scripts.weekly_scope import Runner

USAGE_TIMEOUT_S = 1800
SERVER_BOUND = ("read_file", "edit_file", "write_file")
#: The report's lines; the journal also holds old experiments' names
#: (async_probe_*, measured 2026-09-28), which stay in usage.json only.
TOOLS = (
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
)
MIN_CALLS = 30
LATENCY_RATIO = 1.25
LATENCY_SLACK_MS = 50.0
MIN_STEPS = 300
USAGE_RATIO = 1.25
# docs/usage-analysis-2026-09-27.md, section 9: 2026-09-14 .. 2026-09-27 09:22.
DOCUMENTED = {
    "source": "docs/usage-analysis-2026-09-27.md",
    "steps": 33407,
    "solo_share_of_steps": 0.1698,
    "solo_at_max_share": 0.5889,
    "excess_per_1k_steps": 29.5,
}
_CALL = re.compile(r"event=tool_call call=(\S+) tool=(\S+).*?args=(.*)$")
_RESULT = re.compile(r"event=tool_result call=(\S+) tool=(\S+).* duration_ms=([\d.]+)")


def journal_latency(lines: list[str]) -> tuple[dict[str, dict[str, float]], int]:
    """Per tool {n, p50_ms, p95_ms} without nonce-marked calls; and how many
    such test calls were left out."""
    tests: set[str] = set()
    durations: dict[str, list[float]] = {}
    pending: dict[str, tuple[str, float]] = {}
    for line in lines:
        if m := _CALL.search(line):
            if "e2e-" in m.group(3):
                tests.add(m.group(1))
        elif m := _RESULT.search(line):
            pending[m.group(1)] = (m.group(2), float(m.group(3)))
    for call, (tool, ms) in pending.items():
        if call not in tests:
            durations.setdefault(tool, []).append(ms)
    table = {
        tool: {
            "n": len(ms),
            "p50_ms": round(percentile(ms, 0.50), 1),
            "p95_ms": round(percentile(ms, 0.95), 1),
        }
        for tool, ms in sorted(durations.items())
    }
    return table, len(tests)


def collect(since: str, until: str) -> dict[str, Any]:
    from scripts import usage_breakdown as analysis

    journal = analysis.logstats.fetch_journal(
        ("binnacle-mcp", "binnacle-jobs"), since, until
    )
    latency, tests = journal_latency(journal.splitlines())
    records, _ = analysis.logstats.parse(journal)
    rep = analysis.build_report(
        records, journal, analysis.tunnel_dispatch_times(), since, until
    )
    return {
        "window": [since, until],
        "journal": latency,
        "test_calls_excluded": tests,
        "usage": {k: rep.get(k) for k in ("tool_calls", "steps", "job_polling")},
    }


def latest_usage_baseline(clone: Path) -> dict[str, Any]:
    """The newest docs/usage-baselines/ file with step metrics, flattened;
    else the documented 2026-09-27 figures."""
    for path in sorted(
        (clone / "docs" / "usage-baselines").glob("*.json"), reverse=True
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        steps, polling = data.get("steps") or {}, data.get("job_polling") or {}
        if steps.get("steps") and "solo_share_of_steps" in polling:
            return {
                "source": str(path.relative_to(clone)),
                "steps": steps["steps"],
                "solo_share_of_steps": polling["solo_share_of_steps"],
                "solo_at_max_share": polling.get("solo_at_max_share"),
                "excess_per_1k_steps": 1000
                * polling["excess_over_minimum"]
                / steps["steps"],
            }
    return dict(DOCUMENTED)


def latency_checks(now: dict, base: dict) -> list[Check]:
    checks = []
    for tool, row in now.items():
        if tool not in TOOLS:
            continue
        text = (
            f"{row['n']} calls, p50 {row['p50_ms']:.0f} ms, p95 {row['p95_ms']:.0f} ms"
        )
        old = base.get(tool)
        if not (
            tool in SERVER_BOUND
            and old
            and row["n"] >= MIN_CALLS
            and old["n"] >= MIN_CALLS
        ):
            checks.append(Check(f"journal {tool}", "ok", text))
            continue
        limit = old["p95_ms"] * LATENCY_RATIO + LATENCY_SLACK_MS
        level = "warn" if row["p95_ms"] > limit else "ok"
        checks.append(
            Check(
                f"journal {tool}", level, f"{text} (baseline p95 {old['p95_ms']:.0f})"
            )
        )
    return checks


def usage_check(usage: dict, base: dict) -> Check:
    steps, polling = usage.get("steps") or {}, usage.get("job_polling") or {}
    n = steps.get("steps") or 0
    if n < MIN_STEPS:
        return Check(
            "usage", "ok", f"too little ChatGPT traffic to judge ({n} model steps)"
        )
    share = polling.get("solo_share_of_steps") or 0.0
    excess = 1000 * (polling.get("excess_over_minimum") or 0) / n
    text = (
        f"{n} steps, {steps.get('calls_per_step')} calls per step, steps per turn "
        f"median {steps.get('steps_per_turn_median')} p90 {steps.get('steps_per_turn_p90')}; "
        f"solo polls {share:.1%} of steps (baseline {base['solo_share_of_steps']:.1%}), "
        f"excess {excess:.1f}/1k steps (baseline {base['excess_per_1k_steps']:.1f}); "
        f"baseline {base['source']}"
    )
    worse = share > base["solo_share_of_steps"] * USAGE_RATIO or excess > (
        base["excess_per_1k_steps"] * USAGE_RATIO
    )
    return Check("usage", "warn" if worse else "ok", text)


def usage_checks(
    runner: Runner, clone: Path, state_dir: Path, since: str, until: str
) -> list[Check]:
    out = runner.run_dir / "usage.json"
    argv = [sys.executable, str(clone / "scripts" / "weekly_usage.py")]
    argv += ["--since", since, "--until", until, "--out", str(out)]
    outcome = runner.execute("usage", argv, USAGE_TIMEOUT_S, clone)
    if outcome.status in ("skipped", "aborted"):  # a week without the check
        return [Check("usage", "warn", f"{outcome.status} ({outcome.detail})")]
    if outcome.status != "ok" or not out.exists():
        return [
            Check(
                "usage",
                "warn",
                f"{outcome.status} ({outcome.detail}); see {runner.run_dir / 'usage.log'}",
            )
        ]
    data = json.loads(out.read_text(encoding="utf-8"))
    base_file = state_dir / "journal-baseline.json"
    if base_file.exists():
        base = json.loads(base_file.read_text(encoding="utf-8")).get("journal", {})
    else:
        base = {}
        record = {
            "run": runner.run_id,
            "window": data["window"],
            "journal": data["journal"],
        }
        base_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    checks = latency_checks(data["journal"], base)
    note = (
        "journal baseline recorded"
        if not base
        else "journal compared with the recorded baseline"
    )
    checks.append(
        Check(
            "journal",
            "ok",
            f"{note}; {data['test_calls_excluded']} e2e- test calls left out",
        )
    )
    checks.append(usage_check(data["usage"], latest_usage_baseline(clone)))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The week's production numbers.")
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    data = collect(args.since, args.until)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

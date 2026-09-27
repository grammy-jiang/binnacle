"""The benchmark's runner side (scripts/weekly_quality.py).

Runs scripts/weekly_bench.py in the benchmark's scope and compares p50 and
p95 per case with the baseline in the state directory. The first run, or a
run with ``--rebaseline``, records the baseline. WARN when a case's p95 is
above 1.25 times its baseline p95 plus ``SLACK_MS`` (the slack keeps a
small baseline from turning noise into a warning), or when a call failed.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

from scripts.smoke_checks import Check
from scripts.weekly_bench import BENCH_TIMEOUT_S, SLACK_MS, WARN_RATIO
from scripts.weekly_scope import Runner


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile; 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def summarize(cases: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    return {
        case: {
            "p50_ms": round(percentile(ms, 0.50), 2),
            "p95_ms": round(percentile(ms, 0.95), 2),
            "n": len(ms),
        }
        for case, ms in cases.items()
    }


def compare(
    summary: dict[str, dict[str, float]], baseline: dict[str, dict[str, float]]
) -> list[Check]:
    checks = []
    for case, now in summary.items():
        base = baseline.get(case)
        text = f"p50 {now['p50_ms']:.1f} ms, p95 {now['p95_ms']:.1f} ms"
        if base is None:
            checks.append(
                Check(f"bench {case}", "ok", f"{text} (no baseline for this case)")
            )
            continue
        limit = base["p95_ms"] * WARN_RATIO + SLACK_MS
        level = "warn" if now["p95_ms"] > limit else "ok"
        checks.append(
            Check(
                f"bench {case}",
                level,
                f"{text} (baseline p95 {base['p95_ms']:.1f}, limit {limit:.1f})",
            )
        )
    return checks


def bench_checks(
    runner: Runner, clone: Path, state_dir: Path, reps: int, rebaseline: bool
) -> list[Check]:
    work = Path("/tmp") / f"binnacle-bench-{runner.run_id}"  # nosec B108 - its own unique dir
    out = runner.run_dir / "bench.json"
    argv = [sys.executable, str(clone / "scripts" / "weekly_bench.py")]
    argv += ["--workdir", str(work), "--reps", str(reps), "--out", str(out)]
    outcome = runner.execute("bench", argv, BENCH_TIMEOUT_S, clone)
    shutil.rmtree(work, ignore_errors=True)  # a stopped run could not clean up
    if outcome.status in ("skipped", "aborted"):  # a week without the check
        return [
            Check(
                "bench",
                "warn",
                f"{outcome.status} ({outcome.detail}); no numbers this week",
            )
        ]
    if outcome.status != "ok" or not out.exists():
        log = runner.run_dir / "bench.log"
        return [
            Check("bench", "warn", f"{outcome.status} ({outcome.detail}); see {log}")
        ]
    data = json.loads(out.read_text(encoding="utf-8"))
    summary = summarize(data.get("cases", {}))
    base_file = state_dir / "bench-baseline.json"
    checks = [
        Check("bench", "warn", f"{case} failed: {msg}")
        for case, msg in sorted(data.get("errors", {}).items())
    ]
    info = f"{data.get('reps')} rounds; server start-up {data.get('startup_s')} s, RSS {data.get('rss_kb', 0) // 1024} MiB"
    if rebaseline or not base_file.exists():
        record = {
            "run": runner.run_id,
            "cases": summary,
            "startup_s": data.get("startup_s"),
            "rss_kb": data.get("rss_kb"),
        }
        base_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        checks.append(
            Check("bench", "ok", f"baseline recorded ({len(summary)} cases); {info}")
        )
        checks += compare(summary, summary)
        return checks
    baseline = json.loads(base_file.read_text(encoding="utf-8"))
    checks.append(
        Check("bench", "ok", f"{info}; baseline from run {baseline.get('run')}")
    )
    checks += compare(summary, baseline.get("cases", {}))
    return checks

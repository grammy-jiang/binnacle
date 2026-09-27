"""The weekly mutation rotation (scripts/weekly_quality.py).

Two core modules a week from quality-policy.json (``coverage.core_modules``),
in rotation, so with today's eight each comes round every four weeks.
mutmut runs in the weekly clone with the pyproject configuration
(``source_paths``, ``also_copy``), both modules in one ``mutmut run`` so the
suite's stats pass runs once. The clone's ``mutants/`` is removed first:
every week starts clean, because a cached result can predate a test change.
The run writes ``only_mutate`` with the week's modules into the clone's
pyproject.toml (the next prepare resets the file): without it mutmut 3.7
generates mutants for all 95 source files before it runs the chosen ones.

``--max-children 1``: the scope has one CPU, so more children would only
share it, and their slower mutant runs would then hit mutmut's per-mutant
timeout, which mutmut counts as a kill.

A busy server stops mutmut like any other job (abort, not pause: a paused
mutant run would time out and count as killed). mutmut records results as
it goes, so a stopped or timed-out run still reports what it checked:
"incomplete", with the partial numbers, never a failure. The rotation moves
on after a complete or timed-out run; after a skip, a stop for production
calls or a mutmut failure the same modules come again next week.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from scripts.smoke_checks import Check
from scripts.weekly_scope import Outcome, Runner

KILL_TARGET = 0.80
TIMEOUT_S = 3600
PER_WEEK = 2
DETECTED = {"killed", "timeout", "segfault", "caught by type check"}
UNDETECTED = {"survived", "no tests", "suspicious"}
_RESULT = re.compile(r"^\s+(\S+): (.+?)\s*$")


def core_modules(clone: Path) -> list[str]:
    policy = json.loads((clone / "quality-policy.json").read_text(encoding="utf-8"))
    return list(policy["coverage"]["core_modules"])


def _load(state_file: Path) -> dict:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def pick(state_file: Path, modules: list[str], count: int) -> list[str]:
    """This week's modules; the rotation restarts when the core list changed."""
    state = _load(state_file)
    start = state.get("next", 0) if state.get("modules") == modules else 0
    return [
        modules[(start + k) % len(modules)] for k in range(min(count, len(modules)))
    ]


def advance(state_file: Path, modules: list[str], count: int, run_id: str) -> None:
    state = _load(state_file)
    start = state.get("next", 0) if state.get("modules") == modules else 0
    state.update(modules=modules, next=(start + count) % len(modules), last_run=run_id)
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def mutant_prefix(module: str) -> str:
    """src/binnacle/textio.py -> binnacle.textio. (mutmut's mutant names)"""
    rel = Path(module).relative_to("src").with_suffix("")
    return ".".join(rel.parts) + "."


def parse_results(text: str) -> dict[str, str]:
    """``mutmut results --all true``: one '    <mutant>: <status>' per line."""
    return {
        m.group(1): m.group(2)
        for line in text.splitlines()
        if (m := _RESULT.match(line))
    }


def module_counts(results: dict[str, str], prefix: str) -> dict[str, int]:
    counts = {"detected": 0, "undetected": 0, "pending": 0, "survived": 0}
    for name, status in results.items():
        if not name.startswith(prefix):
            continue
        if status in DETECTED:
            counts["detected"] += 1
        elif status in UNDETECTED:
            counts["undetected"] += 1
            counts["survived"] += status == "survived"
        else:  # not checked, skipped, interrupted
            counts["pending"] += 1
    return counts


def module_check(module: str, counts: dict[str, int], outcome: Outcome) -> Check:
    name = f"mutation {mutant_prefix(module).rstrip('.')}"
    checked = counts["detected"] + counts["undetected"]
    total = checked + counts["pending"]
    if not total:
        return Check(name, "ok", f"no mutants ({outcome.status})")
    rate = counts["detected"] / checked if checked else 0.0
    numbers = (
        f"{rate:.0%} killed ({counts['detected']}/{checked}), "
        f"{counts['survived']} survived"
    )
    if outcome.status != "ok" or counts["pending"]:
        why = outcome.detail or outcome.status
        return Check(
            name,
            "ok",
            f"incomplete ({why}): {checked} of {total} checked, {numbers} so far",
        )
    level = "ok" if rate >= KILL_TARGET else "warn"
    return Check(name, level, f"{numbers}; target {KILL_TARGET:.0%}")


def restrict_to(clone: Path, modules: list[str]) -> str:
    """Limit mutant generation to ``modules`` in the clone's pyproject.toml:
    '' when done, else the problem."""
    path = clone / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    header = "[tool.mutmut]\n"
    if text.count(header) != 1:
        return "pyproject.toml has no single [tool.mutmut] table"
    table = text.split(header, 1)[1].split("\n[", 1)[0]
    if re.search(r"^only_mutate\s*=", table, re.MULTILINE):
        return "pyproject.toml sets only_mutate already"
    line = f"only_mutate = {json.dumps(modules)}\n"  # a JSON string list is TOML
    path.write_text(text.replace(header, header + line), encoding="utf-8")
    return ""


def _mutmut(clone: Path) -> str:
    return str(clone / ".venv" / "bin" / "mutmut")


def mutation_rotation(
    runner: Runner, clone: Path, state_dir: Path, per_week: int = PER_WEEK
) -> list[Check]:
    modules = core_modules(clone)
    state_file = state_dir / "mutation-rotation.json"
    chosen = pick(state_file, modules, per_week)
    shutil.rmtree(clone / "mutants", ignore_errors=True)
    problem = restrict_to(clone, chosen)
    if problem:
        return [Check("mutation", "warn", f"not run: {problem}")]
    globs = [mutant_prefix(m) + "*" for m in chosen]
    argv = [_mutmut(clone), "run", "--max-children", "1", *globs]
    outcome = runner.execute("mutation", argv, TIMEOUT_S, clone, min_s=900)
    if outcome.status == "skipped":  # a week without the check
        return [
            Check(
                "mutation",
                "warn",
                f"skipped ({outcome.detail}); {', '.join(chosen)} next week",
            )
        ]
    log = runner.run_dir / "mutation.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if outcome.status == "failed" and "failed to collect stats" in text:
        return [
            Check(
                "mutation",
                "warn",
                f"mutmut could not collect stats (a test failed under mutmut); see {log}",
            )
        ]
    rc, out = runner.host.run(
        [
            "nice",
            "-n",
            "19",
            "env",
            "-C",
            str(clone),
            _mutmut(clone),
            "results",
            "--all",
            "true",
        ],
        300,
    )
    results = parse_results(out) if rc == 0 else {}
    checks = [
        module_check(m, module_counts(results, mutant_prefix(m)), outcome)
        for m in chosen
    ]
    if outcome.status in ("ok", "timeout"):
        advance(state_file, modules, len(chosen), runner.run_id)
    if outcome.status == "failed":
        checks.append(
            Check("mutation", "warn", f"mutmut exited {outcome.rc}; see {log}")
        )
    return checks

"""scripts/weekly_mutation.py: the rotation, mutmut's result lines, the kill
rate and when the rotation moves on, with a fake host and a fake clone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.weekly_mutation import (
    advance,
    module_check,
    module_counts,
    mutant_prefix,
    mutation_rotation,
    parse_results,
    pick,
)
from scripts.weekly_scope import Limits, Outcome, Runner
from tests.scripts.weekly_fakes import T0, FakeHost, inner

CORE = [
    "src/binnacle/mcp/callctx.py",
    "src/binnacle/config.py",
    "src/binnacle/mcp/identity.py",
    "src/binnacle/features/files/textio.py",
]
RESULTS = """\
    binnacle.mcp.callctx.x_get__mutmut_1: killed
    binnacle.mcp.callctx.x_get__mutmut_2: survived
    binnacle.mcp.callctx.x_get__mutmut_3: timeout
    binnacle.mcp.callctx.x_get__mutmut_4: killed
    binnacle.mcp.callctx.x_get__mutmut_5: killed
    binnacle.config.x_load__mutmut_1: killed
    binnacle.config.x_load__mutmut_2: not checked
    binnacle.configx.x_other__mutmut_1: survived"""


PYPROJECT = """\
[project]
name = "x"

[tool.mutmut]
source_paths = ["src"]

[tool.other]
only_mutate = "not this table"
"""


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    root = tmp_path / "clone"
    root.mkdir()
    policy = {"coverage": {"core_modules": CORE}}
    (root / "quality-policy.json").write_text(json.dumps(policy), encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "mutants").mkdir()  # last week's leftovers
    return root


def test_mutant_prefix() -> None:
    assert (
        mutant_prefix("src/binnacle/features/files/textio.py")
        == "binnacle.features.files.textio."
    )
    assert (
        mutant_prefix("src/binnacle/ops/watchdog/model.py")
        == "binnacle.ops.watchdog.model."
    )


def test_parse_and_count_results_per_module() -> None:
    results = parse_results(RESULTS + "\nnoise line\n")
    assert len(results) == 8
    assert module_counts(results, "binnacle.mcp.callctx.") == {
        "detected": 4,
        "undetected": 1,
        "pending": 0,
        "survived": 1,
    }
    counts = module_counts(results, "binnacle.config.")  # not binnacle.configx
    assert counts == {"detected": 1, "undetected": 0, "pending": 1, "survived": 0}


@pytest.mark.parametrize(
    ("counts", "outcome", "level", "text"),
    [
        (
            {"detected": 9, "undetected": 1, "pending": 0, "survived": 1},
            Outcome("ok", 0, 1.0),
            "ok",
            "90% killed (9/10), 1 survived; target 80%",
        ),
        (
            {"detected": 7, "undetected": 3, "pending": 0, "survived": 3},
            Outcome("ok", 0, 1.0),
            "warn",
            "70% killed (7/10), 3 survived; target 80%",
        ),
        (
            {"detected": 3, "undetected": 1, "pending": 6, "survived": 1},
            Outcome("timeout", 124, 1.0),
            "warn",
            "incomplete (timeout): 4 of 10 checked, 75% killed (3/4), 1 survived so far",
        ),
        (
            {"detected": 0, "undetected": 0, "pending": 0, "survived": 0},
            Outcome("ok", 0, 1.0),
            "warn",
            "no mutation results (ok); unverified",
        ),
    ],
)
def test_module_check_levels(
    counts: dict, outcome: Outcome, level: str, text: str
) -> None:
    check = module_check("src/binnacle/features/files/textio.py", counts, outcome)
    assert (check.name, check.level, check.detail) == (
        "mutation binnacle.features.files.textio",
        level,
        text,
    )


def test_the_rotation_moves_two_at_a_time_and_wraps(tmp_path: Path) -> None:
    state = tmp_path / "rot.json"
    assert pick(state, CORE, 2) == CORE[:2]
    advance(state, CORE, 2, "r1")
    assert pick(state, CORE, 2) == CORE[2:]
    advance(state, CORE, 2, "r2")
    assert pick(state, CORE, 2) == CORE[:2]
    assert pick(state, CORE[:3], 2) == CORE[:2]  # a changed core list restarts


def runner(host: FakeHost, tmp_path: Path) -> Runner:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    return Runner(host.as_host(), Limits(), "r", run_dir, {}, deadline=T0 + 10_800)


def test_a_complete_run_reports_each_module_and_advances(
    tmp_path: Path, clone: Path
) -> None:
    host = FakeHost(
        plans=[(600.0, 0, None)], run_results={"results --all true": (0, RESULTS)}
    )
    complete_results = RESULTS.replace(
        "binnacle.config.x_load__mutmut_2: not checked",
        "binnacle.config.x_load__mutmut_2: killed",
    )
    host.run_results["results --all true"] = (0, complete_results)
    checks = mutation_rotation(runner(host, tmp_path), clone, tmp_path, 2)
    argv = inner(host.spawned[0])
    assert argv[1:] == [
        "run",
        "--max-children",
        "1",
        "binnacle.mcp.callctx.*",
        "binnacle.config.*",
    ]
    assert not (clone / "mutants").exists()  # every week starts clean
    assert [c.name for c in checks] == [
        "mutation binnacle.mcp.callctx",
        "mutation binnacle.config",
    ]
    assert checks[0].level == "ok" and checks[0].detail.startswith("80% killed (4/5)")
    assert checks[1].level == "ok"
    assert pick(tmp_path / "mutation-rotation.json", CORE, 2) == CORE[2:]


def test_a_skipped_run_keeps_the_rotation(tmp_path: Path, clone: Path) -> None:
    host = FakeHost(load=3.0)
    run = runner(host, tmp_path)
    run.gate_wait_s = 60
    checks = mutation_rotation(run, clone, tmp_path, 2)
    assert checks[0].level == "warn" and checks[0].detail.startswith(
        "skipped (no quiet moment"
    )
    assert pick(tmp_path / "mutation-rotation.json", CORE, 2) == CORE[:2]


def test_a_stats_failure_is_a_warning_and_keeps_the_rotation(
    tmp_path: Path, clone: Path
) -> None:
    run = runner(FakeHost(plans=[(300.0, 1, None)]), tmp_path)
    (run.run_dir / "mutation.log").write_text(
        "failed to collect stats. runner returned 1\n"
    )
    checks = mutation_rotation(run, clone, tmp_path, 2)
    assert checks[0].level == "warn" and "could not collect stats" in checks[0].detail
    assert pick(tmp_path / "mutation-rotation.json", CORE, 2) == CORE[:2]


def test_a_timeout_reports_partial_numbers_and_moves_on(
    tmp_path: Path, clone: Path
) -> None:
    host = FakeHost(
        plans=[(3600.0, 124, None)], run_results={"results --all true": (0, RESULTS)}
    )
    checks = mutation_rotation(runner(host, tmp_path), clone, tmp_path, 2)
    assert all(c.level == "warn" for c in checks)
    assert checks[0].detail.startswith("incomplete (timeout)")
    assert pick(tmp_path / "mutation-rotation.json", CORE, 2) == CORE[:2]


def test_generation_is_limited_to_the_weeks_modules(
    tmp_path: Path, clone: Path
) -> None:
    host = FakeHost(
        plans=[(60.0, 0, None)], run_results={"results --all true": (0, "")}
    )
    mutation_rotation(runner(host, tmp_path), clone, tmp_path, 2)
    tomllib = pytest.importorskip("tomllib")
    config = tomllib.loads((clone / "pyproject.toml").read_text())["tool"]["mutmut"]
    assert config["only_mutate"] == CORE[:2]
    assert config["source_paths"] == ["src"]


def test_an_only_mutate_of_the_repo_is_not_overwritten(
    tmp_path: Path, clone: Path
) -> None:
    text = PYPROJECT.replace(
        'source_paths = ["src"]', 'source_paths = ["src"]\nonly_mutate = ["x.py"]'
    )
    (clone / "pyproject.toml").write_text(text, encoding="utf-8")
    host = FakeHost()
    checks = mutation_rotation(runner(host, tmp_path), clone, tmp_path, 2)
    assert checks[0].level == "warn" and "sets only_mutate already" in checks[0].detail
    assert host.spawned == []


def test_module_check_never_marks_pending_or_empty_results_green() -> None:
    cases = [
        (
            {"detected": 0, "undetected": 0, "pending": 10, "survived": 0},
            Outcome("ok", 0, 1.0),
        ),
        (
            {"detected": 8, "undetected": 0, "pending": 2, "survived": 0},
            Outcome("ok", 0, 1.0),
        ),
        (
            {"detected": 8, "undetected": 0, "pending": 0, "survived": 0},
            Outcome("timeout", 124, 1.0),
        ),
        (
            {"detected": 0, "undetected": 0, "pending": 0, "survived": 0},
            Outcome("failed", 3, 1.0),
        ),
    ]
    for counts, outcome in cases:
        check = module_check(CORE[0], counts, outcome)
        assert check.level == "warn"


def test_success_with_partial_results_keeps_mutation_rotation(
    tmp_path: Path, clone: Path
) -> None:
    host = FakeHost(
        plans=[(600.0, 0, None)], run_results={"results --all true": (0, RESULTS)}
    )
    checks = mutation_rotation(runner(host, tmp_path), clone, tmp_path, 2)
    assert checks[1].level == "warn"
    assert "incomplete (ok)" in checks[1].detail
    assert pick(tmp_path / "mutation-rotation.json", CORE, 2) == CORE[:2]

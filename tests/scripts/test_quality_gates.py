"""Tests for the repository's static quality-policy gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module_size = _load("check_module_size")
architecture = _load("check_architecture")
coverage_policy = _load("check_coverage_policy")


def test_module_size_ratchet_blocks_growth_and_new_oversize():
    policy = {
        "module_size": {
            "warning_lines": 450,
            "max_lines": 500,
            "legacy_oversize": {"legacy.py": 700},
        }
    }
    errors, debts, warnings = module_size.evaluate(
        {"legacy.py": 700, "near.py": 475, "small.py": 50},
        policy,
    )
    assert not errors
    assert debts == [
        "legacy.py: 700 lines remains above target 500 (legacy ceiling 700)"
    ]
    assert warnings == ["near.py: 475 lines is above warning threshold 450"]

    errors, _, _ = module_size.evaluate(
        {"legacy.py": 701, "new.py": 501},
        policy,
    )
    assert any("grew beyond legacy baseline" in item for item in errors)
    assert any("has no legacy baseline" in item for item in errors)


def test_module_size_ratchet_requires_retiring_paid_down_debt():
    policy = {
        "module_size": {
            "warning_lines": 450,
            "max_lines": 500,
            "legacy_oversize": {"legacy.py": 700},
        }
    }
    errors, _, _ = module_size.evaluate({"legacy.py": 499}, policy)
    assert errors == ["legacy.py: now 499 lines; remove the obsolete legacy baseline"]


def test_architecture_allows_watchdog_to_depend_on_core_but_not_reverse(tmp_path):
    core = tmp_path / "core.py"
    core.write_text("from binnacle import watchdog\n")
    companion = tmp_path / "watchdog.py"
    companion.write_text("from binnacle import uplink\n")

    imports = {
        "binnacle.core": architecture.imports_of(core, "binnacle.core"),
        "binnacle.watchdog": architecture.imports_of(companion, "binnacle.watchdog"),
    }
    policy = {
        "architecture": {
            "watchdog_companion_modules": [
                "binnacle.watchdog",
                "binnacle.watchdog_cli",
                "binnacle.watchlog",
            ]
        }
    }
    errors = architecture.evaluate(imports, policy)
    assert errors == [
        (
            "binnacle.core -> binnacle.watchdog: Binnacle core must not depend on "
            "the watchdog companion"
        )
    ]


def test_architecture_resolves_relative_watchdog_import(tmp_path):
    path = tmp_path / "core.py"
    path.write_text("from . import watchdog\n")
    targets = architecture.imports_of(path, "binnacle.core")
    assert "binnacle.watchdog" in targets


def _coverage_report(values: dict[str, float]) -> dict:
    return {
        "files": {
            path: {"summary": {"percent_covered": value}}
            for path, value in values.items()
        }
    }


def test_coverage_policy_is_per_module_and_uses_correct_scope():
    policy = {
        "coverage": {
            "core_unit_target": 95.0,
            "other_full_target": 90.0,
            "core_modules": ["src/binnacle/core.py"],
            "temporary_floors": {
                "unit": {"src/binnacle/core.py": 80.0},
                "full": {"src/binnacle/edge.py": 70.0},
            },
        }
    }
    unit = _coverage_report({"src/binnacle/core.py": 81.0})
    full = _coverage_report(
        {
            "src/binnacle/core.py": 99.0,
            "src/binnacle/edge.py": 71.0,
        }
    )

    errors, debts = coverage_policy.evaluate(unit, full, policy)
    assert not errors
    assert len(debts) == 2
    assert "unit branch coverage 81.00%" in debts[0]
    assert "full branch coverage 71.00%" in debts[1]

    errors, _ = coverage_policy.evaluate(unit, full, policy, strict=True)
    assert len(errors) == 2


def test_coverage_policy_requires_floor_cleanup_once_target_is_reached():
    policy = {
        "coverage": {
            "core_unit_target": 95.0,
            "other_full_target": 90.0,
            "core_modules": ["src/binnacle/core.py"],
            "temporary_floors": {
                "unit": {"src/binnacle/core.py": 80.0},
                "full": {},
            },
        }
    }
    report = _coverage_report({"src/binnacle/core.py": 96.0})
    errors, _ = coverage_policy.evaluate(report, report, policy)
    assert errors == [
        (
            "src/binnacle/core.py: coverage reached 96.00% target; "
            "remove obsolete temporary unit floor 80.00%"
        )
    ]


def test_architecture_treats_companion_submodules_as_one_way_boundary():
    policy = {"architecture": {"watchdog_companion_modules": ["binnacle.ops.watchdog"]}}
    imports = {
        "binnacle.core": {"binnacle.ops.watchdog.policy"},
        "binnacle.ops.watchdog.policy": {"binnacle.uplink"},
    }

    errors = architecture.evaluate(imports, policy)

    assert errors == [
        (
            "binnacle.core -> binnacle.ops.watchdog.policy: "
            "Binnacle core must not depend on the watchdog companion"
        )
    ]


def test_module_size_file_discovery_ignores_deleted_tracked_paths(
    tmp_path, monkeypatch
):
    root = tmp_path
    existing = root / "src" / "kept.py"
    existing.parent.mkdir()
    existing.write_text("x\n")

    class Proc:
        stdout = "src/kept.py\nsrc/deleted.py\n"

    monkeypatch.setattr(module_size.subprocess, "run", lambda *a, **k: Proc())

    assert module_size.tracked_python_files(root, ("src",)) == [existing]

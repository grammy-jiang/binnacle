"""Tests for the repository's static quality-policy gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


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


def test_architecture_groups_allow_only_declared_companion_dependencies():
    imports = {
        "binnacle.core": {"binnacle.tunnel_cli"},
        "binnacle.watchdog": {"binnacle.tunnel_cli", "binnacle.uplink"},
        "binnacle.tunnel_cli": {"binnacle.watchdog"},
    }
    policy = {
        "architecture": {
            "companions": {
                "watchdog": ["binnacle.watchdog"],
                "tunnel": ["binnacle.tunnel_cli"],
            },
            "companion_dependencies": {"watchdog": ["tunnel"]},
        }
    }
    assert architecture.evaluate(imports, policy) == [
        (
            "binnacle.core -> binnacle.tunnel_cli: Binnacle core must not depend "
            "on the tunnel companion"
        ),
        (
            "binnacle.tunnel_cli -> binnacle.watchdog: the tunnel companion must "
            "not depend on the watchdog companion"
        ),
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


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("from . import watchdog_cli", "binnacle.companions.watchdog.watchdog_cli"),
        ("from ..tunnel import tunnel_log", "binnacle.companions.tunnel.tunnel_log"),
        ("from .ops import policy", "binnacle.companions.watchdog.ops.policy"),
    ],
)
def test_architecture_resolves_imports_in_package_initializers(
    tmp_path, relative, expected
):
    from scripts import check_architecture as architecture

    pkg = tmp_path / "binnacle" / "companions" / "watchdog"
    pkg.mkdir(parents=True)
    source_file = pkg / "__init__.py"
    source_file.write_text(relative + "\n")
    resolved = architecture.imports_of(source_file, "binnacle.companions.watchdog")
    assert expected in resolved


def test_architecture_detects_core_package_relative_companion_import(tmp_path):
    from scripts import check_architecture as architecture

    path = tmp_path / "binnacle" / "diagnostics" / "__init__.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ..companions import watchdog\n")
    source = "binnacle.diagnostics"
    imports = architecture.imports_of(path, source)
    assert "binnacle.companions.watchdog" in imports
    assert architecture.evaluate({source: imports}, architecture.load_policy())


def test_architecture_root_package_relative_import(tmp_path):
    from scripts import check_architecture as architecture

    source_file = tmp_path / "binnacle" / "__init__.py"
    source_file.parent.mkdir()
    source_file.write_text("from . import server\n")
    assert "binnacle.server" in architecture.imports_of(source_file, "binnacle")


@pytest.mark.parametrize(
    ("import_statement", "allowed"),
    [
        ("from ..tunnel.tunnel_unit import TUNNEL_UNIT", True),
        ("from ..tunnel import tunnel_unit", False),
        ("from ..tunnel.tunnel_unit import render_tunnel_unit", False),
    ],
)
def test_package_initializer_public_contract_uses_correct_relative_base(
    tmp_path, import_statement, allowed
):
    from scripts import check_architecture as architecture

    source = "binnacle.companions.watchdog"
    pkg = tmp_path / "binnacle" / "companions" / "watchdog"
    pkg.mkdir(parents=True)
    path = pkg / "__init__.py"
    path.write_text(import_statement + "\n")
    policy = {
        "architecture": {
            "companion_public_imports": {
                source: {"binnacle.companions.tunnel.tunnel_unit": ["TUNNEL_UNIT"]}
            }
        }
    }
    assert (architecture.public_import_errors(path, source, policy) == []) == allowed


def test_coverage_source_inventory_includes_every_current_noninitializer(tmp_path):
    root = tmp_path / "binnacle"
    nested = root / "feature"
    nested.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "entry.py").write_text("x = 1\\n")
    (nested / "__init__.py").write_text("")
    (nested / "implementation.py").write_text("x = 2\\n")
    assert coverage_policy.expected_source_modules(root) == {
        "src/binnacle/entry.py",
        "src/binnacle/feature/implementation.py",
    }
    assert coverage_policy.expected_source_modules(root / "missing") == set()


@pytest.mark.parametrize(
    ("expected", "reported", "message"),
    [
        (
            {"src/binnacle/core.py", "src/binnacle/extra.py"},
            {"src/binnacle/core.py": 100.0},
            "src/binnacle/extra.py: missing from full coverage report",
        ),
        (
            {"src/binnacle/core.py"},
            {"src/binnacle/core.py": 100.0, "src/binnacle/obsolete.py": 100.0},
            "src/binnacle/obsolete.py: coverage report has no corresponding source file",
        ),
        (
            set(),
            {"src/binnacle/core.py": 100.0},
            "production Python inventory is empty or unreadable",
        ),
    ],
)
def test_coverage_inventory_disagrees_fail_closed(expected, reported, message):
    policy = {
        "coverage": {
            "core_unit_target": 95,
            "other_full_target": 90,
            "core_modules": [],
        }
    }
    full = _coverage_report(reported)
    errors, _ = coverage_policy.evaluate(full, full, policy, expected_modules=expected)
    assert message in errors


def test_complete_inventory_preserves_per_module_thresholds():
    policy = {
        "coverage": {
            "core_unit_target": 95,
            "other_full_target": 90,
            "core_modules": ["src/binnacle/core.py"],
        }
    }
    full = _coverage_report(
        {"src/binnacle/core.py": 95.0, "src/binnacle/other.py": 90.0}
    )
    errors, debts = coverage_policy.evaluate(
        full, full, policy, expected_modules=set(full["files"])
    )
    assert errors == []
    assert debts == []


def test_repository_script_inventory_is_complete(tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "__init__.py").write_text("")
    (script_dir / "guard.py").write_text("x = 1\\n")
    assert coverage_policy.expected_script_modules(script_dir) == {"scripts/guard.py"}
    assert coverage_policy.expected_script_modules(script_dir / "not-present") == set()


@pytest.mark.parametrize(
    ("reported", "inventory", "floors", "expected"),
    [
        (
            {"scripts/guard.py": 100.0},
            {"scripts/guard.py", "scripts/other.py"},
            {"scripts/guard.py": 90},
            "scripts/other.py: missing from script coverage report",
        ),
        (
            {"scripts/guard.py": 100.0, "scripts/deleted.py": 100.0},
            {"scripts/guard.py"},
            {"scripts/guard.py": 90},
            "scripts/deleted.py: script coverage has no corresponding source file",
        ),
        (
            {"scripts/guard.py": 79.0},
            {"scripts/guard.py"},
            {"scripts/guard.py": 80},
            "scripts/guard.py: script branch coverage 79.00% is below reviewed floor 80.00%",
        ),
        (
            {"scripts/guard.py": 100.0},
            {"scripts/guard.py"},
            {"scripts/removed.py": 80},
            "scripts/removed.py: critical coverage floor references absent source",
        ),
        (
            {"scripts/guard.py": 100.0},
            set(),
            {"scripts/guard.py": 90},
            "repository script inventory is empty or unreadable",
        ),
    ],
)
def test_infrastructure_coverage_is_fail_closed(reported, inventory, floors, expected):
    policy = {
        "infrastructure_coverage": {
            "eventual_target": 90,
            "critical_minimums": floors,
        }
    }
    errors, _ = coverage_policy.evaluate_script_coverage(
        _coverage_report(reported), policy, expected_modules=inventory
    )
    assert expected in errors


def test_critical_script_floor_and_eventual_target_are_separate():
    policy = {
        "infrastructure_coverage": {
            "eventual_target": 90,
            "critical_minimums": {"scripts/guard.py": 70},
        }
    }
    errors, debt = coverage_policy.evaluate_script_coverage(
        _coverage_report({"scripts/guard.py": 85}),
        policy,
        expected_modules={"scripts/guard.py"},
    )
    assert not errors
    assert len(debt) == 1
    assert "85.00% below eventual target 90.00%" in debt[0]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, 101.0])
def test_invalid_coverage_percentages_are_not_accepted(invalid):
    product = _coverage_report({"src/binnacle/core.py": invalid})
    policy = {
        "coverage": {
            "core_unit_target": 95,
            "other_full_target": 90,
            "core_modules": ["src/binnacle/core.py"],
        }
    }
    errors, _ = coverage_policy.evaluate(
        product, product, policy, expected_modules={"src/binnacle/core.py"}
    )
    assert errors == ["src/binnacle/core.py: invalid unit coverage percentage"]

    infra = _coverage_report({"scripts/guard.py": invalid})
    infra_policy = {
        "infrastructure_coverage": {
            "critical_minimums": {"scripts/guard.py": 70},
            "eventual_target": 90,
        }
    }
    errors, _ = coverage_policy.evaluate_script_coverage(
        infra, infra_policy, expected_modules={"scripts/guard.py"}
    )
    assert errors == ["scripts/guard.py: invalid script coverage percentage"]

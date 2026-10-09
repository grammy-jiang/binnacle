"""Keep the retired G0-G6 compatibility paths from returning in G7+."""

from __future__ import annotations

from scripts import check_architecture
from scripts import g7_legacy_gate as gate
from scripts.gate_a_manifest import compatibility_facades


def test_historical_retirement_manifest_is_complete_and_immutable_in_scope():
    assert len(gate.RETIRED_FILES) == 94
    assert len(gate.RETIRED_MODULES) >= 90
    assert compatibility_facades() == set()


def test_no_retired_runtime_files_or_direct_dynamic_imports():
    assert gate.existing_retired_files() == []
    assert gate.legacy_imports() == []


def test_reintroducing_old_paths_is_rejected(tmp_path):
    root = tmp_path / "binnacle"
    root.mkdir()
    (root / "jobs.py").write_text("legacy module\n")
    (root / "example.py").write_text(
        "import binnacle.jobs\n"
        "from binnacle import doctor\n"
        "from binnacle.ops import watchdog\n"
        "import importlib; importlib.import_module('binnacle.tools.run_command')\n"
    )
    found = gate.failures(root)
    assert any("legacy file remains: jobs.py" in line for line in found)
    for expected in (
        "binnacle.jobs",
        "binnacle.doctor",
        "binnacle.ops.watchdog",
        "binnacle.tools.run_command",
    ):
        assert any(expected in line for line in found)


def test_canonical_module_imports_remain_allowed(tmp_path):
    root = tmp_path / "binnacle"
    root.mkdir()
    source = root / "example.py"
    source.write_text(
        "from binnacle.features.commands import jobs\n"
        "from binnacle.companions.watchdog import watchdog\n"
        "from binnacle.mcp import visibility\n"
        "from binnacle.doctor_contracts import Check\n"
    )
    assert gate.failures(root) == []
    imported = check_architecture.imports_of(source, "binnacle.example")
    assert "binnacle.features.commands.jobs" in imported

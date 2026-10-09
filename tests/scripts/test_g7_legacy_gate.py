"""Keep the retired G0-G6 compatibility paths from returning in G7+."""

from __future__ import annotations

import pytest

from scripts import check_architecture
from scripts import g7_legacy_gate as gate


def test_historical_retirement_manifest_is_complete_and_immutable_in_scope():
    assert len(gate.RETIRED_FILES) == 94
    assert len(gate.RETIRED_MODULES) >= 90


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


@pytest.mark.parametrize(
    "source",
    [
        'from importlib import import_module as load\nload("binnacle.jobs")\n',
        'import importlib as il\nil.import_module("binnacle.doctor")\n',
        'import importlib as il\ngetattr(il, "import_module")("binnacle.jobs")\n',
        'from builtins import __import__ as load\nload("binnacle.jobs")\n',
        'import importlib\nimportlib.import_module(".jobs", package="binnacle")\n',
        'from importlib import import_module as load\nload(".doctor", "binnacle")\n',
        'import importlib\nimportlib.import_module(name=".jobs", package="binnacle")\n',
    ],
)
def test_import_aliases_cannot_restore_retired_modules(tmp_path, source):
    root = tmp_path / "binnacle"
    root.mkdir()
    (root / "candidate.py").write_text(source)
    assert any("legacy import remains:" in failure for failure in gate.failures(root))


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nsys.modules[__name__] = object()\n",
        'import sys as runtime\nruntime.modules["binnacle.old"] = object()\n',
        "from sys import modules as registry\nregistry[__name__] = object()\n",
        "import sys\nsys.modules.setdefault(__name__, object())\n",
        "from sys import modules as m\nm.update({__name__: object()})\n",
        "import sys\nregistry = sys.modules\nregistry[__name__] = object()\n",
        "import sys\nregistry = sys.modules\nregistry |= {__name__: object()}\n",
        "import sys\ndel sys.modules[__name__]\n",
        'import sys\nsys.modules.pop("binnacle.jobs", None)\n',
        "from sys import modules as registry\nregistry.clear()\n",
        "from binnacle.features.commands.jobs import *\n",
        "def __getattr__(name):\n    return name\n",
    ],
)
def test_new_identity_facades_are_rejected_even_with_new_names(tmp_path, source):
    root = tmp_path / "binnacle"
    root.mkdir()
    (root / "unexpected_alias.py").write_text(source)
    assert any("identity facade remains:" in failure for failure in gate.failures(root))


def test_readonly_module_introspection_is_not_an_identity_facade(tmp_path):
    root = tmp_path / "binnacle"
    root.mkdir()
    (root / "legitimate.py").write_text(
        "import sys\n"
        "from importlib import import_module as load\n"
        'present = sys.modules.get("unrelated")\n'
        "alias = sys.modules\n"
        'also_present = alias.get("unrelated")\n'
        'current = load("binnacle.features.commands.jobs")\n'
        'canonical = load(".features.commands.jobs", "binnacle")\n'
    )
    assert gate.failures(root) == []


def test_no_new_module_identity_facades_in_current_source():
    assert gate.facade_forwarders() == []

"""G5-stable neutral Check contract and diagnostics alias compatibility."""

import dataclasses
import importlib
import json
import pickle
import subprocess
import sys

from binnacle.doctor_contracts import Check, fail, ok, warn


def test_neutral_check_contract_roundtrip():
    assert Check.__module__ == "binnacle.doctor_contracts"
    checks = [ok("a", "good"), warn("b", "warning", "hint"), fail("c", "bad")]
    assert [c.status for c in checks] == ["ok", "warn", "fail"]
    for check in checks:
        assert pickle.loads(pickle.dumps(check)) == check
        assert json.loads(json.dumps(dataclasses.asdict(check))) == dataclasses.asdict(
            check
        )
    assert list(dataclasses.asdict(checks[0])) == ["group", "status", "detail", "hint"]


def test_neutral_contract_keeps_canonical_pickle_identity():
    code = """import importlib, pickle, sys
from binnacle import doctor_contracts
a = importlib.import_module('binnacle.doctor_contracts')
assert a is doctor_contracts
assert sys.modules['binnacle.doctor_contracts'] is a
assert a.Check.__module__ == 'binnacle.doctor_contracts'
assert pickle.loads(pickle.dumps(a.ok('group', 'good'))) == a.ok('group', 'good')
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_neutral_contract_has_no_platform_or_diagnostics_imports():
    import ast
    from pathlib import Path

    source = Path(
        importlib.import_module("binnacle.doctor_contracts").__file__
    ).read_text()
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any(
        name.startswith(("binnacle.diagnostics", "binnacle.platform"))
        for name in imported
    )
    units = Path(
        importlib.import_module("binnacle.deployment.units").__file__
    ).read_text()
    assert "binnacle.diagnostics.doctor_contracts" not in units

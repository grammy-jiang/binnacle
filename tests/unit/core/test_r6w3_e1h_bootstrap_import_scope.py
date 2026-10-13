"""SD-90 import-authority rule for the newly added bootstrap target source.

Only two reviewed literal module names may pass into _required_import,
selected solely by the fixed platform/process condition. A missing contract
cannot be hidden by relying on the general import graph linter.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[3] / "src/binnacle/manager_bootstrap.py"
APPROVED = frozenset({"binnacle.config", "binnacle.platform.darwin.job_manager_config"})


def _assert_reviewed_bootstrap_source(source: str) -> None:
    tree = ast.parse(source, filename=str(BOOTSTRAP))
    function = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "capture_startup_root"
    )
    assigned = [
        item
        for item in function.body
        if isinstance(item, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "name"
            for target in item.targets
        )
    ]
    assert len(assigned) == 1, "exactly one approved import selector"
    selector = assigned[0].value
    assert isinstance(selector, ast.IfExp), (
        "the module target must be an explicit conditional"
    )
    assert isinstance(selector.body, ast.Constant)
    assert isinstance(selector.orelse, ast.Constant)
    assert {
        selector.body.value,
        selector.orelse.value,
    } == APPROVED
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_required_import"
    ]
    assert len(calls) == 1
    assert len(calls[0].args) == 1
    assert isinstance(calls[0].args[0], ast.Name)
    assert calls[0].args[0].id == "name"
    assert assigned[0].lineno < calls[0].lineno


def test_capture_import_targets_are_both_pinned_literals():
    _assert_reviewed_bootstrap_source(BOOTSTRAP.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "replacement",
    [
        'os.environ["UNREVIEWED_MODULE"]',
        'sys.modules["binnacle.config"]',
        'f"binnacle.{process}"',
    ],
)
def test_dynamic_target_mutation_cannot_pass_literal_source_gate(replacement):
    source = BOOTSTRAP.read_text(encoding="utf-8")
    anchor = '"binnacle.config"'
    assert source.count(anchor) == 1
    mutated = source.replace(anchor, replacement)
    with pytest.raises(AssertionError):
        _assert_reviewed_bootstrap_source(mutated)

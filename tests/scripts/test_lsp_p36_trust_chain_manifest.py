"""The P3.6 trust-chain modules stay offline, shell-free and manifest-bound."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (
        ROOT
        / "docs/lsp-development-intelligence/p3-6-trust-chain-modules-2026-10-23.json"
    ).read_text()
)
MODULES = sorted(MANIFEST["modules"])
FORBIDDEN = tuple(MANIFEST["forbidden_imports"])


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_match_manifest_and_stay_offline(module):
    tree = ast.parse((ROOT / module).read_text())
    imports = _imports(tree)
    spec = MANIFEST["modules"][module]
    first = {name for name in imports if name.startswith("scripts.")}
    assert first == set(spec["first_party_imports"])
    for name in imports:
        assert not name.startswith(FORBIDDEN), name
    third = {
        name.split(".")[0]
        for name in imports
        if name.split(".")[0] in {"pydantic", "cryptography"}
    }
    assert third == set(spec["third_party_imports"])


@pytest.mark.parametrize("module", MODULES)
def test_module_never_calls_process_network_or_key_generation(module):
    tree = ast.parse((ROOT / module).read_text())
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute | ast.Name)
    }
    assert not called.intersection(MANIFEST["forbidden_calls"])


def test_manifest_covers_every_trust_chain_module_and_invariants():
    on_disk = {
        f"scripts/{path.name}"
        for path in (ROOT / "scripts").glob("lsp_p36_*.py")
        if path.name
        in {"lsp_p36_secure_io.py", "lsp_p36_trust_registry.py", "lsp_p36_link.py"}
    }
    assert on_disk <= set(MODULES)
    invariants = MANIFEST["invariants"]
    assert invariants["authority_granted"] is False
    assert invariants["read"] == "NO-GO"
    assert invariants["selection"] == "REWORK"

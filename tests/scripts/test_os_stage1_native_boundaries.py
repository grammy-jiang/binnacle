"""OS6 OI-01/OI-11 and FM-02/FM-04/FM-07 source boundary assertions."""

import ast
from pathlib import Path

from scripts import check_architecture
from scripts.os_independence import inspect_imports

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/binnacle"


def _module_targets(path: Path) -> set[str]:
    return check_architecture.imports_of(
        path, check_architecture.module_name(path, ROOT / "src")
    )


def test_platform_contracts_and_concrete_adapters_never_import_mcp_framework():
    modules = [
        path
        for path in SOURCE.rglob("*.py")
        if "platform" in path.relative_to(SOURCE).parts
    ]
    assert modules
    for path in modules:
        targets = _module_targets(path)
        assert not any(
            target == framework or target.startswith(framework + ".")
            for target in targets
            for framework in ("fastmcp", "mcp", "mcp_types")
        ), path


def test_one_way_companion_imports_and_no_core_companion_selection():
    modules = {
        check_architecture.module_name(path, ROOT / "src"): _module_targets(path)
        for path in SOURCE.rglob("*.py")
    }
    companions = "binnacle.companions"
    for owner, deps in modules.items():
        if owner.startswith(companions):
            continue
        assert not any(
            target == companions or target.startswith(companions + ".")
            for target in deps
        ), owner


def test_native_linux_imports_appear_only_on_approved_boundaries():
    policy = check_architecture.load_policy()
    exceptions = set(policy["os_independence"]["native_adapter_boundary_modules"])
    imports = {
        check_architecture.module_name(path, ROOT / "src"): _module_targets(path)
        for path in SOURCE.rglob("*.py")
    }
    assert inspect_imports(imports, allowed_native_owners=exceptions) == []


def test_no_shadow_mcp_registry_or_extra_public_tool_registration():
    text = {
        path: ast.parse(path.read_text(), filename=str(path))
        for path in SOURCE.rglob("*.py")
    }
    for path, tree in text.items():
        assert not any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and node.name in {"FeatureRegistry", "ServerBuilder", "ProviderRouter"}
            for node in ast.walk(tree)
        ), path
    server = SOURCE / "application.py"
    roots = [
        node
        for node in ast.walk(text[server])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FastMCP"
    ]
    assert len(roots) == 1
    mounts = [
        node
        for node in ast.walk(text[server])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mount"
    ]
    assert len(mounts) == 3

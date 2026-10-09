#!/usr/bin/env python3
"""Check one-way dependency boundaries that are not expressed by packaging."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality-policy.json"


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def module_name(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _from_targets(
    node: ast.ImportFrom, source: str, *, is_package: bool = False
) -> set[str]:
    # In __init__.py the source is already the containing package.  For
    # ordinary modules, the containing package is its dotted parent.
    source_package = source if is_package else source.rpartition(".")[0]
    if node.level:
        relative = "." * node.level + (node.module or "")
        try:
            base = importlib.util.resolve_name(relative, source_package)
        except (ImportError, ValueError):
            return set()
    else:
        base = node.module or ""

    targets: set[str] = set()
    if base:
        targets.add(base)
    for alias in node.names:
        if alias.name == "*":
            continue
        if base:
            targets.add(f"{base}.{alias.name}")
        elif source_package:
            targets.add(f"{source_package}.{alias.name}")
    return targets


def _import_loader_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Recognize explicit importlib/builtins bindings without executing code."""
    importlib_names: set[str] = {"importlib"}
    loader_names: set[str] = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or "importlib")
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "importlib":
                loader_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
            elif node.module == "builtins":
                loader_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "__import__"
                )
    return importlib_names, loader_names


def _is_import_loader(
    func: ast.expr, importlib_names: set[str], loader_names: set[str]
) -> bool:
    if isinstance(func, ast.Name):
        return func.id in loader_names
    if isinstance(func, ast.Attribute):
        # Keep the existing conservative detection of literal .import_module
        # calls even when the importlib binding is indirect.
        return func.attr == "import_module"
    if (
        isinstance(func, ast.Call)
        and isinstance(func.func, ast.Name)
        and func.func.id == "getattr"
        and len(func.args) == 2
        and isinstance(func.args[0], ast.Name)
        and func.args[0].id in importlib_names
        and isinstance(func.args[1], ast.Constant)
    ):
        return func.args[1].value == "import_module"
    return False


def imports_of(path: Path, source: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    importlib_names, loader_names = _import_loader_aliases(tree)
    is_package = path.name == "__init__.py"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.update(_from_targets(node, source, is_package=is_package))
        elif (
            isinstance(node, ast.Call)
            and _is_import_loader(node.func, importlib_names, loader_names)
            and node.args
        ):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                targets.add(arg.value)
    return targets


def _companion_groups(cfg: dict[str, Any]) -> dict[str, list[str]]:
    """Companion groups: {group: [module prefixes]}. The pre-2026-09-21 key
    `watchdog_companion_modules` still reads as the single `watchdog` group."""
    if "companions" in cfg:
        return {name: list(mods) for name, mods in cfg["companions"].items()}
    return {"watchdog": list(cfg.get("watchdog_companion_modules", []))}


def evaluate(
    imports: dict[str, set[str]],
    policy: dict[str, Any],
) -> list[str]:
    cfg = policy["architecture"]
    groups = _companion_groups(cfg)
    allowed = {k: set(v) for k, v in cfg.get("companion_dependencies", {}).items()}
    errors: list[str] = []

    def group_of(module: str) -> str | None:
        for name, prefixes in groups.items():
            if any(module == p or module.startswith(p + ".") for p in prefixes):
                return name
        return None

    public = cfg.get("companion_public_imports", {})
    for source, targets in sorted(imports.items()):
        for forbidden in cfg.get("forbidden_direct_imports", {}).get(source, []):
            if any(t == forbidden or t.startswith(forbidden + ".") for t in targets):
                errors.append(
                    f"{source} -> {forbidden}: forbidden aggregate dependency"
                )
        source_group = group_of(source)
        for target in sorted(targets):
            target_group = group_of(target)
            if target_group is None or target_group == source_group:
                continue
            if source_group is None:
                errors.append(
                    f"{source} -> {target}: Binnacle core must not depend on "
                    f"the {target_group} companion"
                )
            elif target_group not in allowed.get(source_group, set()):
                errors.append(
                    f"{source} -> {target}: the {source_group} companion must "
                    f"not depend on the {target_group} companion"
                )
            elif "companion_public_imports" in cfg:
                exports = {
                    f"{module}.{symbol}"
                    for module, symbols in public.get(source, {}).items()
                    for symbol in symbols
                }
                if not any(
                    target == export
                    or (export in targets and export.startswith(target + "."))
                    for export in exports
                ):
                    errors.append(
                        f"{source} -> {target}: not a public companion contract"
                    )
    return errors


def public_import_errors(path: Path, source: str, policy: dict[str, Any]) -> list[str]:
    """Require the declared symbol imports, rejecting whole-module access too."""
    contracts = (
        policy["architecture"].get("companion_public_imports", {}).get(source, {})
    )
    if not contracts:
        return []
    seen: set[str] = set()
    errors = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            if any(alias.name in contracts for alias in node.names):
                errors.append(f"{source}: whole-module companion import is forbidden")
        elif isinstance(node, ast.ImportFrom):
            targets = _from_targets(node, source, is_package=path.name == "__init__.py")
            for module, symbols in contracts.items():
                if module not in targets:
                    continue
                expected = {f"{module}.{name}" for name in symbols}
                if not all(
                    f"{module}.{alias.name}" in expected for alias in node.names
                ):
                    errors.append(f"{source}: companion import widens {module}")
                seen.update(targets & expected)
    missing = {
        f"{module}.{name}" for module, names in contracts.items() for name in names
    } - seen
    if missing:
        errors.append(f"{source}: missing public companion imports {sorted(missing)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    src_root = ROOT / policy["architecture"].get("src_root", "src")
    package_root = src_root / "binnacle"
    imports: dict[str, set[str]] = {}
    symbol_errors: list[str] = []

    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = module_name(path, src_root)
        imports[source] = imports_of(path, source)
        symbol_errors.extend(public_import_errors(path, source, policy))

    errors = evaluate(imports, policy) + symbol_errors
    for line in errors:
        print(f"ERROR: {line}", file=sys.stderr)
    print(
        f"architecture: {len(imports)} modules checked; "
        f"{len(errors)} forbidden reverse dependencies"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

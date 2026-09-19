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


def _from_targets(node: ast.ImportFrom, source: str) -> set[str]:
    source_package = source.rpartition(".")[0]
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


def imports_of(path: Path, source: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.update(_from_targets(node, source))
        elif isinstance(node, ast.Call):
            fn = node.func
            dynamic = (isinstance(fn, ast.Name) and fn.id == "__import__") or (
                isinstance(fn, ast.Attribute) and fn.attr == "import_module"
            )
            if dynamic and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    targets.add(arg.value)
    return targets


def evaluate(
    imports: dict[str, set[str]],
    policy: dict[str, Any],
) -> list[str]:
    cfg = policy["architecture"]
    companion = set(cfg["watchdog_companion_modules"])
    forbidden = tuple(sorted(companion))
    errors: list[str] = []

    def is_companion(module: str) -> bool:
        return any(
            module == item or module.startswith(item + ".") for item in forbidden
        )

    for source, targets in sorted(imports.items()):
        if is_companion(source):
            continue
        for target in sorted(targets):
            if is_companion(target):
                errors.append(
                    f"{source} -> {target}: Binnacle core must not depend on "
                    "the watchdog companion"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    src_root = ROOT / policy["architecture"].get("src_root", "src")
    package_root = src_root / "binnacle"
    imports: dict[str, set[str]] = {}

    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = module_name(path, src_root)
        imports[source] = imports_of(path, source)

    errors = evaluate(imports, policy)
    for line in errors:
        print(f"ERROR: {line}", file=sys.stderr)
    print(
        f"architecture: {len(imports)} modules checked; "
        f"{len(errors)} forbidden reverse dependencies"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

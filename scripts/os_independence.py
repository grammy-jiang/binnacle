"""OS-independence static checks; supplements Import Linter and runtime probes.

This is deliberately narrow: literal direct/dynamic imports are checked using
the existing architecture import graph; executable native commands and paths
are checked only in modules that promise to be pure.  No static scanner can
rule out every computed dynamic import, so OI-03 uses runtime import blocking.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

NATIVE_PREFIXES = (
    "binnacle.platform.linux",
    "binnacle.observability.linux",
    "binnacle.deployment.linux",
)
BANNED_COMMANDS = {"systemctl", "journalctl", "loginctl"}
HOST_PATHS = ("/proc", "/sys/fs/cgroup", "/run/user/")


def _belongs(module: str, namespace: str) -> bool:
    return module == namespace or module.startswith(namespace + ".")


def inspect_imports(
    imports: dict[str, set[str]], *, allowed_native_owners: set[str]
) -> list[str]:
    """Catch imports of a concrete native adapter, including alias and literal dynamic."""
    errors = []
    for owner, targets in sorted(imports.items()):
        if not owner.startswith("binnacle."):
            continue
        if (
            owner in allowed_native_owners
            or any(_belongs(owner, native) for native in NATIVE_PREFIXES)
            or _belongs(owner, "binnacle.companions")
        ):
            continue
        for target in sorted(targets):
            if any(_belongs(target, native) for native in NATIVE_PREFIXES):
                errors.append(f"{owner} -> {target}: direct Linux adapter dependency")
    return errors


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _strings(node: ast.AST) -> list[str]:
    return [
        part.value
        for part in ast.walk(node)
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
    ]


def inspect_executable_source(source: str, *, owner: str) -> list[str]:
    """Reject executable native mechanisms in pure modules, not documentation."""
    tree = ast.parse(source, filename=owner)
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = _name(node.func)
        args = [*node.args, *(kw.value for kw in node.keywords)]
        strs = [txt for arg in args for txt in _strings(arg)]
        if func in {
            "os.kill",
            "os.killpg",
            "os.fork",
            "os.posix_spawn",
            "os.posix_spawnp",
        }:
            errors.append(f"{owner}:{node.lineno}: OS process control {func}")
        if func in {"Path", "pathlib.Path", "open", "io.open"} and any(
            path == anchor or path.startswith(anchor + "/")
            for path in strs
            for anchor in HOST_PATHS[:2]
        ):
            errors.append(f"{owner}:{node.lineno}: Linux host path {strs}")
        if func in {
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.check_output",
            "subprocess.call",
            "subprocess.check_call",
            "os.system",
        } and any(cmd in strs for cmd in BANNED_COMMANDS):
            errors.append(f"{owner}:{node.lineno}: Linux service process {strs}")
    return errors


def inspect_source_tree(
    package_root: Path, *, policy: dict[str, Any], imports: dict[str, set[str]]
) -> list[str]:
    """One fail-closed policy entry point for the existing check_architecture hook."""
    cfg = policy["os_independence"]
    exceptions = set(cfg.get("native_adapter_boundary_modules", []))
    errors = inspect_imports(imports, allowed_native_owners=exceptions)
    for name in cfg["pure_module_prefixes"]:
        for owner in sorted(imports):
            if not _belongs(owner, name):
                continue
            path = package_root.parent.joinpath(*owner.split(".")).with_suffix(".py")
            if not path.exists():
                path = package_root.parent.joinpath(*owner.split("."), "__init__.py")
            if path.is_file():
                errors.extend(
                    inspect_executable_source(
                        path.read_text(encoding="utf-8"), owner=owner
                    )
                )
    return errors

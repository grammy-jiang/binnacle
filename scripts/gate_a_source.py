"""Small static source readers for the preparation report, not runtime policy."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path


def imported_symbols(path: Path):
    """Yield canonical (module, symbol), with None denoting a module import."""
    parts = path.parent.parts
    package = "binnacle"
    if "binnacle" in parts:
        package = ".".join(parts[parts.index("binnacle") :])
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from ((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            for alias in node.names:
                yield module, alias.name


def imports_for(path: Path) -> set[str]:
    out = set()
    for module, symbol in imported_symbols(path):
        out.add(module)
        if symbol:
            out.add(f"{module}.{symbol}")
    return out


def imported_names_from(path: Path, module: str) -> tuple[set[str], bool]:
    if not path.exists():
        return set(), False
    names, direct = set(), False
    for base, symbol in imported_symbols(path):
        if base == module:
            if symbol is None:
                direct = True
            else:
                names.add(symbol)
        elif symbol and f"{base}.{symbol}" == module:
            direct = True
    return names, direct


def has_root_health_route(path: Path) -> bool:
    """Prove literal root registration only; response/auth need runtime evidence."""
    if not path.exists():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for factory in tree.body:
        if not isinstance(factory, ast.FunctionDef) or factory.name != "create_server":
            continue
        roots = {
            n.targets[0].id
            for n in factory.body
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "FastMCP"
        }
        returned = {
            n.value.id
            for n in factory.body
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
        }
        for handler in factory.body:
            if not isinstance(handler, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in handler.decorator_list:
                if not isinstance(call, ast.Call) or not isinstance(
                    call.func, ast.Attribute
                ):
                    continue
                fn = call.func
                if (
                    fn.attr != "custom_route"
                    or not isinstance(fn.value, ast.Name)
                    or fn.value.id not in roots & returned
                ):
                    continue
                try:
                    values = {
                        kw.arg: ast.literal_eval(kw.value) for kw in call.keywords
                    }
                    route = (
                        ast.literal_eval(call.args[0])
                        if call.args
                        else values.get("path")
                    )
                except (ValueError, TypeError):
                    continue
                if (
                    route == "/healthz"
                    and values.get("methods") == ["GET"]
                    and values.get("include_in_schema") is False
                ):
                    return True
    return False

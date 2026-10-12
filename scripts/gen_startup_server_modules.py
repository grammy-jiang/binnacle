#!/usr/bin/env python3
"""Generate the frozen server module set of ``binnacle.startup_imports``.

The MCP server imports exactly the literal ``SERVER_MODULES`` at start (E1,
SD-90); it never walks the installed package directory. This script is the one
place that walks the binnacle source tree: it lists every module and package
under ``src/binnacle`` minus the pinned exclusions of ``startup_imports``
(``_ALWAYS_EXCLUDED`` and the other OS's adapters in ``_EXCLUDED_BY_OS``),
without importing any of them, and renders the literal.

    uv run python scripts/gen_startup_server_modules.py           # print it
    uv run python scripts/gen_startup_server_modules.py --check   # exit 1 on drift
    uv run python scripts/gen_startup_server_modules.py --write   # rewrite it

``--write`` regenerates ``src/binnacle/startup_server_modules.py`` (the whole
file, which holds nothing else). A new, renamed or removed runtime module makes
the drift test fail until this script is run and the result committed.
"""

from __future__ import annotations

import argparse
import os
import pkgutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "binnacle" / "startup_server_modules.py"
SYSTEMS = ("Linux", "Darwin")
NAME = "SERVER_MODULES"
COMMAND = "uv run python scripts/gen_startup_server_modules.py --write"


def _excluded(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def _walk(directory: Path, prefix: str, prefixes: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for info in pkgutil.iter_modules([str(directory)], prefix):
        if _excluded(info.name, prefixes):
            continue
        names.append(info.name)
        if info.ispkg:  # recurse by path: nothing is imported
            leaf = info.name.rsplit(".", 1)[1]
            names += _walk(directory / leaf, info.name + ".", prefixes)
    return names


def walk_server_modules(system: str) -> tuple[str, ...]:
    """The runtime modules of ``system``: the source tree minus the exclusions."""
    from binnacle import startup_imports

    prefixes = startup_imports._ALWAYS_EXCLUDED + startup_imports._EXCLUDED_BY_OS.get(
        system, ()
    )
    package = ROOT / "src" / "binnacle"
    return tuple(sorted(_walk(package, "binnacle.", prefixes)))


def _tuple(name: str, names: tuple[str, ...], indent: str = "") -> list[str]:
    lines = [f"{indent}{name} = ("]
    lines += [f'{indent}    "{item}",' for item in names]
    lines.append(f"{indent})")
    return lines


HEADER = f'''"""The server's frozen REQUIRED module set (E1, SD-90). GENERATED.

Do not edit by hand; regenerate with:

    {COMMAND}

The MCP server imports exactly these names at start and never walks the
installed package directory (a stray file there must not be imported).
``tests/unit/core/test_r6w3_e1g_server_set.py`` fails with the command above
when this file drifts from the source tree minus the exclusions pinned in
``binnacle.startup_imports``.
"""

'''


def render(walked: dict[str, tuple[str, ...]] | None = None) -> str:
    """The whole generated file, formatted as ruff would."""
    walked = walked or {system: walk_server_modules(system) for system in SYSTEMS}
    common = tuple(sorted(set.intersection(*(set(v) for v in walked.values()))))
    lines = ["# Common to both OSes, then each OS's own adapters."]
    lines += _tuple("_SERVER_COMMON", common)
    for system in SYSTEMS:
        extra = tuple(sorted(set(walked[system]) - set(common)))
        lines += _tuple(f"_SERVER_EXTRA_{system.upper()}", extra)
    lines.append(f"{NAME} = {{")
    for system in SYSTEMS:
        lines.append(
            f'    "{system}": tuple(sorted(_SERVER_COMMON + _SERVER_EXTRA_{system.upper()})),'
        )
    lines.append("}")
    return HEADER + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if the file drifted")
    mode.add_argument("--write", action="store_true", help="rewrite the generated file")
    args = parser.parse_args(argv)
    block = render()
    text = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if args.check:
        if text != block:
            print(f"{NAME} drifted from the source tree; regenerate with: {COMMAND}")
            return 1
        return 0
    if args.write:
        if block != text:
            handle, tmp = tempfile.mkstemp(dir=TARGET.parent, suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(block)
            os.replace(tmp, TARGET)
        return 0
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

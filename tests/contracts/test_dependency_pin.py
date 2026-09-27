"""The runtime dependency list of pyproject.toml, pinned.

Every runtime dependency is code that runs inside the live server, so a new
one, a removed one or a changed version specifier is a decision, not a side
effect of a lock update. RUNTIME_DEPENDENCIES holds the ``[project]
dependencies`` list exactly as declared, each entry with the reason it is a
dependency. To change the list on purpose, edit pyproject.toml and this
mapping in the same commit, give the new entry its reason, and say why in the
commit message. deptry (pre-commit) checks the other direction: that the
code imports only what is declared.

The file is read with tomllib, which the standard library has from Python
3.11; on 3.10 the module is skipped (the list is the same on every Python).
"""

from pathlib import Path

import pytest

tomllib = pytest.importorskip(
    "tomllib", reason="tomllib is in the standard library from Python 3.11"
)

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

RUNTIME_DEPENDENCIES = {
    "cyclopts>=4.23.3": "the CLI framework of binnacle, binnacle-tunnel and binnacle-watchdog",
    "fastmcp==4.0.0b5": "the MCP server framework; a beta pin, revisit when 4.0 goes stable",
    "orjson>=3.11.3": "search_text parses ripgrep's JSON stream and sizes results with it",
    "pydantic>=2.13.5": "the settings models and the tool parameter validation",
    "pydantic-settings>=2.15.0": "loads config.toml and the BINNACLE_ environment variables",
    "tiktoken>=0.14.0": "the tokenizer telemetry (telemetry.tokenizer)",
    "uvicorn[standard]>=0.52.4": "the ASGI server of binnacle serve and of the dev unit",
}


def test_runtime_dependencies_are_pinned():
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    assert declared == list(RUNTIME_DEPENDENCIES)


def test_every_runtime_dependency_has_a_reason():
    assert all(reason.strip() for reason in RUNTIME_DEPENDENCIES.values())

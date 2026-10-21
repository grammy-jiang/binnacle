"""Real Pyright feature-level acceptance (opt-in; no production process startup).

Requires explicitly pinned PYRIGHT_LSP_TEST_BIN and multilspy, otherwise skips.
A disposable canonical workspace avoids macOS /var vs /private/var URI aliases.
Rename edits are NEVER applied. CLI variants remain separate from LSP tests.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from binnacle.features.development_intelligence.lsp_session import utf16_offset
from binnacle.features.development_intelligence.multilspy_pyright import (
    PyrightOptions,
    create_pyright_adapter,
)
from tests.integration.test_lsp_multilspy_pyright import _optional_upstream


@pytest.fixture
def pyright_executable() -> Path:
    value = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    if not value:
        pytest.skip("PYRIGHT_LSP_TEST_BIN missing; never auto-discover binaries")
    executable = Path(value)
    if not executable.is_absolute() or not executable.is_file():
        pytest.skip("Pinned Pyright server binary unavailable")
    return executable


@pytest.fixture
def pyright_cli() -> Path:
    value = os.environ.get("PYRIGHT_CLI_TEST_BIN")
    if not value:
        pytest.skip("PYRIGHT_CLI_TEST_BIN not set: never install or locate implicitly")
    candidate = Path(value)
    if not candidate.is_absolute() or not candidate.is_file():
        pytest.skip("explicit pinned Pyright CLI is unavailable")
    return candidate


@pytest.fixture
def python_workspace(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    content = {
        "lib": (
            "class Calculator:\n"
            "    def add(self, left: int, right: int) -> int:\n"
            "        return left + right\n\n"
            "def format_name(name: str, greeting: str = 'Hi') -> str:\n"
            "    return f'{greeting}, {name}'\n"
        ),
        "app": (
            "from lib import Calculator, format_name\n\n"
            "calc = Calculator()\n"
            "answer = calc.add(2, 3)\n"
            "message = format_name('Ada', 'Hello')\n"
            "again = format_name('Lin')\n"
        ),
        "signature": (
            "from lib import format_name\nresult = format_name('Ada', 'Hello')\n"
        ),
        "bad_types": (
            "def wrong() -> str:\n"
            "    return 42\n\n"
            "number: int = 'bad'\n\n"
            "def unannotated(value):\n"
            "    return value\n"
        ),
        "bad_syntax": "def broken(:\n    return 1\n",
        "undefined": (
            "import definitely_nonexistent_binnacle_test_module\n"
            "value = variable_that_does_not_exist\n"
        ),
        "unicode": (
            'from lib import format_name\nmarker = "🧭"; value = format_name("Test")\n'
        ),
    }
    paths = {}
    for key, value in content.items():
        path = root / f"{key}.py"
        path.write_text(value, encoding="utf-8")
        paths[key] = path
    (root / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "include": ["."],
                "typeCheckingMode": "standard",
                "reportMissingImports": "error",
            }
        )
    )
    return root, paths


def _params(path: Path, line: int, col: int, **more) -> dict:
    return {
        "textDocument": {"uri": path.as_uri()},
        "position": {"line": line, "character": col},
        **more,
    }


def _adapter(root: Path, executable: Path):
    config, logger = _optional_upstream()
    return create_pyright_adapter(
        config,
        logger,
        root,
        executable=executable,
        options=PyrightOptions(diagnostic_mode="openFilesOnly"),
    )


def test_navigation_completion_signatures_and_workspace_symbols(
    python_workspace, pyright_executable: Path
) -> None:
    root, f = python_workspace
    adapter = _adapter(root, pyright_executable)

    async def run() -> None:
        async with adapter.start_server():
            assert adapter.capabilities.get("positionEncoding", "utf-16") == "utf-16"
            needed = (
                "definitionProvider",
                "referencesProvider",
                "hoverProvider",
                "completionProvider",
                "signatureHelpProvider",
                "documentSymbolProvider",
                "workspaceSymbolProvider",
                "typeDefinitionProvider",
            )
            assert all(adapter.capabilities.get(key) for key in needed)
            app_lines = f["app"].read_text().splitlines()
            with (
                adapter.open_file("lib.py"),
                adapter.open_file("app.py"),
                adapter.open_file("signature.py"),
                adapter.open_file("unicode.py"),
            ):
                definitions = await adapter.request_definition(
                    "app.py", 4, app_lines[4].index("format_name") + 2
                )
                assert len(definitions) == 1
                assert definitions[0]["relativePath"] == "lib.py"
                assert definitions[0]["range"]["start"]["line"] == 4

                methods = await adapter.request_definition(
                    "app.py", 3, app_lines[3].index("add") + 1
                )
                assert len(methods) == 1
                assert methods[0]["relativePath"] == "lib.py"

                references = await adapter.request_references("lib.py", 4, 6)
                assert len(references) >= 2
                assert {"app.py", "signature.py"} <= {
                    item["relativePath"] for item in references
                }
                assert all(
                    Path(item["absolutePath"]).is_relative_to(root)
                    for item in references
                )

                hover = await adapter.request_hover("app.py", 4, 13)
                assert hover is not None
                assert "contents" in hover
                symbols, _tree = await adapter.request_document_symbols("lib.py")
                assert {"Calculator", "format_name"} <= {
                    item["name"] for item in symbols
                }

                completion = await adapter.server.send.completion(
                    _params(f["app"], 3, len("answer = calc."))
                )
                assert isinstance(completion, dict)
                assert any(
                    item["label"] == "add" for item in completion.get("items", [])
                )

                import_completion = await adapter.server.send.completion(
                    _params(f["app"], 0, len("from lib import Calc"))
                )
                assert any(
                    item["label"] == "Calculator"
                    for item in import_completion.get("items", [])
                )

                signature = await adapter.server.send.signature_help(
                    _params(f["signature"], 1, len("result = format_name('Ada', "))
                )
                assert isinstance(signature, dict)
                assert signature["signatures"]
                label = signature["signatures"][0]["label"]
                assert "name: str" in label and "greeting: str" in label
                assert signature["signatures"][0]["activeParameter"] == 1

                typedef = await adapter.server.send.type_definition(
                    _params(f["app"], 3, len("answer = c"))
                )
                assert isinstance(typedef, list) and typedef
                assert all(
                    Path(item["uri"][7:]).resolve().is_relative_to(root)
                    for item in typedef
                )

                declaration = await adapter.server.send.declaration(
                    _params(f["app"], 3, len("answer = calc.a"))
                )
                assert isinstance(declaration, list) and declaration

                highlights = await adapter.server.send.document_highlight(
                    _params(f["app"], 4, len("message = forma"))
                )
                assert isinstance(highlights, list) and len(highlights) >= 2

                names = []
                for _ in range(20):
                    names = await adapter.request_workspace_symbol("format_name")
                    if names:
                        break
                    await asyncio.sleep(0.1)
                assert any(item["name"] == "format_name" for item in names)

                line = f["unicode"].read_text().splitlines()[1]
                utf16_column = utf16_offset(line, line.index("format_name"))
                assert utf16_column == line.index("format_name") + 1
                unicode_defs = await adapter.request_definition(
                    "unicode.py", 1, utf16_column
                )
                assert len(unicode_defs) == 1
                assert unicode_defs[0]["relativePath"] == "lib.py"

    asyncio.run(asyncio.wait_for(run(), timeout=28))
    assert adapter.server.process is None


def test_rename_preview_and_call_hierarchy_are_read_only(
    python_workspace, pyright_executable: Path
) -> None:
    root, files = python_workspace
    original = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    adapter = _adapter(root, pyright_executable)

    async def run() -> None:
        async with adapter.start_server():
            with (
                adapter.open_file("lib.py"),
                adapter.open_file("app.py"),
                adapter.open_file("signature.py"),
                adapter.open_file("unicode.py"),
            ):
                position = _params(files["lib"], 4, len("def forma"))
                prepared = await adapter.server.send.prepare_rename(position)
                assert isinstance(prepared, dict)
                proposal = await adapter.server.send.rename(
                    {**position, "newName": "renamed_format"}
                )
                assert isinstance(proposal, dict)
                edits = proposal.get("documentChanges", [])
                assert len(edits) >= 2
                targets = {
                    Path(change["textDocument"]["uri"][7:]).resolve()
                    for change in edits
                }
                assert {
                    files["app"],
                    files["lib"],
                    files["signature"],
                    files["unicode"],
                } <= targets
                assert all(path.is_relative_to(root) for path in targets)
                assert sum(len(change.get("edits", [])) for change in edits) >= 5

                prepare = await adapter.server.send.prepare_call_hierarchy(position)
                assert isinstance(prepare, list) and prepare
                incoming = await adapter.server.send.incoming_calls(
                    {"item": prepare[0]}
                )
                assert isinstance(incoming, list) and incoming

    asyncio.run(asyncio.wait_for(run(), timeout=22))
    assert adapter.server.process is None
    assert all(
        p.read_bytes() == original[p.name] for p in root.iterdir() if p.is_file()
    )


def test_diagnostic_push_identifies_syntax_semantic_and_type_errors(
    python_workspace, pyright_executable: Path
) -> None:
    root, paths = python_workspace
    adapter = _adapter(root, pyright_executable)

    async def run() -> None:
        async with adapter.start_server():
            expect = {
                "bad_types": "reportReturnType",
                "undefined": "reportUndefinedVariable",
            }
            for key in ("bad_types", "bad_syntax", "undefined"):
                while not adapter.diagnostics.empty():
                    adapter.diagnostics.get_nowait()
                with adapter.open_file(paths[key].name):
                    entries = []
                    for _ in range(12):
                        incoming = await adapter.next_diagnostics(timeout_s=2)
                        if incoming.get("uri") != paths[key].as_uri():
                            continue
                        entries = incoming.get("diagnostics", [])
                        if entries:
                            break
                    assert entries, f"no diagnostic for synthetic {key}"
                    assert any(entry.get("severity") == 1 for entry in entries)
                    if key in expect:
                        assert expect[key] in {entry.get("code") for entry in entries}
                    else:
                        # Parsing errors often have no rule/code field.
                        assert any(entry.get("code") is None for entry in entries)

    asyncio.run(asyncio.wait_for(run(), timeout=28))
    assert adapter.server.process is None


def test_cli_workspace_off_basic_standard_strict_modes(
    python_workspace, pyright_cli: Path
) -> None:
    root, _files = python_workspace
    (root / "untyped.py").write_text("def untyped(param):\n    return param\n")
    (root / "ignored.py").write_text("answer: int = 'ignored'\n")
    rows: dict[str, dict] = {}
    for mode in ("off", "basic", "standard", "strict"):
        (root / "pyrightconfig.json").write_text(
            json.dumps(
                {
                    "include": ["."],
                    "exclude": ["ignored.py"],
                    "typeCheckingMode": mode,
                    "reportMissingImports": "error",
                }
            )
        )
        completed = subprocess.run(
            [str(pyright_cli), "--project", str(root), "--outputjson"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        data = json.loads(completed.stdout)
        found = data["generalDiagnostics"]
        rules = {item.get("rule") for item in found}
        impacted = {Path(item["file"]).name for item in found}
        assert completed.returncode == 1
        assert "ignored.py" not in impacted
        assert "bad_syntax.py" in impacted
        assert "undefined.py" in impacted
        assert "reportMissingImports" in rules
        assert "lib.py" not in impacted and "app.py" not in impacted
        if mode == "off":
            assert "reportReturnType" not in rules
            assert "reportAssignmentType" not in rules
        else:
            assert "reportReturnType" in rules
            assert "reportAssignmentType" in rules
        if mode == "strict":
            assert "untyped.py" in impacted
            assert len(found) > len(rows["standard"]["generalDiagnostics"])
        rows[mode] = data
    assert len(rows) == 4

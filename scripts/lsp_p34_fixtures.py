"""Fixed public synthetic inputs and conservative P3.4 launch descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    key: str
    executable: str
    args: tuple[str, ...]
    language: str
    filename: str
    text: str
    symbol: str
    adapter_language: str | None = None


CASES = (
    Case(
        "typescript",
        "typescript-language-server",
        ("--stdio",),
        "typescript",
        "main.ts",
        'import { twice } from "./lib";\nexport const answer = twice(21);\n',
        "answer",
        "typescript",
    ),
    Case(
        "javascript",
        "typescript-language-server",
        ("--stdio",),
        "javascript",
        "main.js",
        'import { twice } from "./lib.js";\nexport const answer = twice(21);\n',
        "answer",
        "javascript",
    ),
    Case(
        "c",
        "clangd",
        (
            "--background-index=false",
            "--clang-tidy=false",
            "--enable-config=false",
            "--pch-storage=memory",
            "-j=1",
        ),
        "c",
        "main.c",
        "int twice(int x) { return x * 2; }\nint main(void) { return twice(21); }\n",
        "twice",
        "cpp",
    ),
    Case(
        "cpp",
        "clangd",
        (
            "--background-index=false",
            "--clang-tidy=false",
            "--enable-config=false",
            "--pch-storage=memory",
            "-j=1",
        ),
        "cpp",
        "main.cpp",
        "int twice(int x) { return x * 2; }\nint main() { return twice(21); }\n",
        "twice",
        "cpp",
    ),
    Case(
        "rust",
        "rust-analyzer",
        (),
        "rust",
        "main.rs",
        "fn twice(x: i32) -> i32 { x * 2 }\nfn main() { let _answer = twice(21); }\n",
        "twice",
        "rust",
    ),
    Case(
        "markdown",
        "marksman",
        ("server",),
        "markdown",
        "main.md",
        "# Probe\n\n[Target](target.md#target)\n",
        "Probe",
    ),
    Case(
        "bash",
        "bash-language-server",
        ("start",),
        "shellscript",
        "main.sh",
        "#!/bin/bash\nsource ./lib.sh\nanswer() { twice 21; }\n",
        "answer",
    ),
    Case("make", "make-language-server", (), "makefile", "Makefile", "all:\n", "all"),
    Case(
        "yaml",
        "yaml-language-server",
        ("--stdio",),
        "yaml",
        "main.yaml",
        "answer: 42\n",
        "answer",
    ),
    Case(
        "json",
        "vscode-json-language-server",
        ("--stdio",),
        "json",
        "main.json",
        '{"answer": 42}\n',
        "answer",
    ),
)


def fixture(case: Case, root: Path):
    files = {case.filename: case.text}
    if case.key in {"typescript", "javascript"}:
        ext = "ts" if case.key == "typescript" else "js"
        argument = "x: number" if ext == "ts" else "x"
        files[f"lib.{ext}"] = f"export function twice({argument}) {{ return x * 2; }}\n"
        files["tsconfig.json" if ext == "ts" else "jsconfig.json"] = (
            '{"compilerOptions":{"allowJs":true,"noEmit":true,"types":[]},'
            '"typeAcquisition":{"enable":false}}\n'
        )
    elif case.key == "markdown":
        files.update({".marksman.toml": "", "target.md": "# Target\n"})
    elif case.key == "bash":
        files["lib.sh"] = 'twice() { printf "%s\\n" "$1"; }\n'
    elif case.key in {"c", "cpp"}:
        files["compile_flags.txt"] = "-std=c11\n" if case.key == "c" else "-std=c++17\n"
    for name, content in files.items():
        (root / name).write_text(content)
    return files


def settings(case: Case):
    if case.key == "bash":
        return {
            "bashIde": {
                "shellcheckPath": "",
                "shfmt": {"path": ""},
                "explainshellEndpoint": "",
                "backgroundAnalysisMaxFiles": 0,
            }
        }
    if case.key == "yaml":
        return {
            "yaml": {
                "schemaStore": {"enable": False},
                "kubernetesCRDStore": {"enable": False},
                "schemas": {},
                "validate": True,
                "format": {"enable": False},
            },
            "http": {"proxy": "", "proxyStrictSSL": True},
        }
    if case.key == "json":
        return {
            "json": {
                "schemas": [],
                "schemaDownload": {"enable": False},
                "format": {"enable": False},
            }
        }
    return {}


def options(case: Case, root: Path):
    if case.key in {"typescript", "javascript"}:
        return {
            "disableAutomaticTypingAcquisition": True,
            "plugins": [],
            "tsserver": {"useSyntaxServer": "never"},
        }
    if case.key == "rust":
        return {
            "cargo": {"buildScripts": {"enable": False}, "sysroot": None},
            "checkOnSave": False,
            "check": {"enable": False},
            "procMacro": {"enable": False},
            "linkedProjects": [],
            "detachedFiles": [str(root / case.filename)],
        }
    return {}


def definition_gold(case: Case):
    """Known ASCII use position and exact declaration start (zero-based)."""
    if case.key in {"typescript", "javascript"}:
        return (1, 22, "lib.ts" if case.key == "typescript" else "lib.js", 0, 16)
    if case.key in {"c", "cpp"}:
        line = case.text.splitlines()[1]
        return (1, line.index("twice") + 1, case.filename, 0, 4)
    return None

"""FDW-B1-a3: shared error text must have exactly one production owner."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from binnacle.platform.contracts.special_file_contracts import (
    PATH_CHANGED_CODE,
    PATH_IS_DIRECTORY_CODE,
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    path_changed_text,
    path_is_directory_text,
)


@pytest.mark.parametrize(
    "tool", ["read_file", "edit_file", "write_file", "list_files", "search_text"]
)
def test_canonical_directory_and_changed_words_are_stable(tool: str):
    directory = path_is_directory_text("/r/a", tool)
    assert directory == "Path is a directory, not a file: /r/a." + (
        "" if tool == "edit_file" else " Use list_files to browse it."
    )
    changed = path_changed_text("/r/a", tool)
    assert "/r/a" in changed
    assert changed.endswith(
        ("Read it again.", "Write it again.", "list it again.", "search it again.")
    )
    assert (PATH_CHANGED_CODE, PATH_IS_DIRECTORY_CODE, SPECIAL_FILE_CODE) == (
        "path_changed",
        "path_is_directory",
        "special_file_unsupported",
    )
    assert SPECIAL_FILE_TEXT.startswith("special_file_unsupported:")


def test_no_other_production_module_duplicates_refusal_literals():
    root = Path(__file__).resolve().parents[3]
    owner = root / "src/binnacle/platform/contracts/special_file_contracts.py"
    beginnings = (
        "Path is a directory, not a file",
        "File changed while it was opened",
        "Directory changed during the listing",
        "Directory changed during the search",
    )
    duplicates = []
    for source in (root / "src/binnacle").rglob("*.py"):
        if source == owner:
            continue
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(word in node.value for word in beginnings)
            ):
                duplicates.append(f"{source.relative_to(root)}:{node.lineno}")
    assert duplicates == []

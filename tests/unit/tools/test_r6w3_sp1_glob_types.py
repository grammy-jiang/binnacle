"""list_files GLOB mode types only regular files as 'file' (r6 W3 SP1).

SRC-W2-12: glob omitted a listed name only when its no-follow lstat showed
a symlink, so a name replaced by a directory or a FIFO after rg listed it
was typed 'file' with the size of that object. A listed entry is now kept
with bytes only when lstat shows a regular file, the rule search_text
applies (search_text_verify.is_regular).
"""

import os
import shutil
from pathlib import Path

import pytest

from binnacle.features.files.tools import list_files as lf

RG = shutil.which("rg") or "rg"


def race(tmp: Path, after: str) -> str:
    """An rg stand-in: the real rg, then 'after', then rg's output."""
    script = tmp / "rg-race.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'out=$("{RG}" "$@"); code=$?\n'
        f"{after}\n"
        'printf "%s\\n" "$out"\n'
        "exit $code\n"
    )
    script.chmod(0o700)
    return str(script)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path.resolve() / "root"
    (root / "d").mkdir(parents=True)
    (root / "a.txt").write_text("a" * 10)
    (root / "d" / "b.txt").write_text("b" * 20)
    return root


def sizes(root: Path, rg: str) -> dict:
    result = lf._glob_mode(root, "*.txt", 100, False, rg_bin=rg, timeout_s=30)
    payload = result.structured_content
    assert payload is not None
    assert payload["count"] == len(payload["entries"])
    assert all(e["type"] == "file" for e in payload["entries"])
    return {
        os.path.relpath(e["path"], root): e.get("bytes") for e in payload["entries"]
    }


def test_a_name_replaced_by_a_directory_is_omitted(root, tmp_path):
    rg = race(tmp_path, f'rm "{root}/a.txt"; mkdir "{root}/a.txt"')
    assert sizes(root, rg) == {"d/b.txt": 20}


def test_a_name_replaced_by_a_fifo_is_omitted(root, tmp_path):
    rg = race(tmp_path, f'rm "{root}/a.txt"; mkfifo "{root}/a.txt"')
    assert sizes(root, rg) == {"d/b.txt": 20}


def test_a_regular_file_replaced_by_another_regular_file_is_sized(root, tmp_path):
    rg = race(tmp_path, f'rm "{root}/a.txt"; printf 12345 > "{root}/a.txt"')
    assert sizes(root, rg) == {"a.txt": 5, "d/b.txt": 20}


def test_benign_glob_entries_are_unchanged(root):
    assert sizes(root, RG) == {"a.txt": 10, "d/b.txt": 20}

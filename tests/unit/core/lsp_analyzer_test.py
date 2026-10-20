"""Pure P1.6 fixture audit checks; not production result normalization."""

import json
import os

import pytest

from tests.fixtures.lsp.analyzer_audit import classify
from tests.fixtures.lsp.side_effects import differences, manifest


@pytest.mark.parametrize(
    "result",
    [
        {},
        [],
        {"complete": True, "diagnostics": []},
        {"complete": True, "analyzed": [], "diagnostics": []},
        {"complete": 1, "analyzed": ["fixture.py"], "diagnostics": []},
        {"complete": True, "analyzed": ["fixture.py"], "diagnostics": [{}]},
    ],
)
def test_incomplete_or_invalid_schema_is_not_clean(result):
    assert classify(json.dumps(result).encode(), 0) == ("invalid", [])


def test_nonzero_empty_diagnostics_is_not_clean():
    data = {"complete": True, "analyzed": ["fixture.py"], "diagnostics": []}
    assert classify(json.dumps(data).encode(), 1) == ("invalid", [])
    assert classify(json.dumps(data).encode(), 23) == ("crash", [])


def test_missing_range_is_never_fabricated():
    diagnostic = {
        "path": "fixture.py",
        "severity": "error",
        "code": "FIX001",
        "message": "synthetic",
    }
    result = {"complete": True, "analyzed": ["fixture.py"], "diagnostics": [diagnostic]}
    assert classify(json.dumps(result).encode(), 0) == ("invalid", [])
    assert "range" not in diagnostic


@pytest.mark.skipif(os.name != "posix", reason="POSIX file types and modes")
def test_manifest_file_types_size_and_directory_mode(tmp_path):
    file = tmp_path / "data"
    file.write_bytes(b"a")
    directory = tmp_path / "directory"
    directory.mkdir(mode=0o700)
    os.mkfifo(tmp_path / "fifo")
    before = manifest(tmp_path)  # Must not block opening the FIFO.
    assert before["fifo"].kind == "special"
    assert before["directory"].mode == 0o700
    file.write_bytes(b"longer")
    directory.chmod(0o755)
    changed = differences(before, manifest(tmp_path))
    assert changed["data"][0].size == 1
    assert changed["data"][1].size == 6
    assert changed["directory"][1].mode == 0o755
    file.unlink()
    file.mkdir()
    assert manifest(tmp_path)["data"].kind == "directory"

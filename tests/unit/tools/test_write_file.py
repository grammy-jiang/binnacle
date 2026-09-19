"""Implementation gate for tools/write_file.py (docs/tools/write_file.md §4)."""

import os

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import write_file as wf


def write(path: str, content: str) -> dict:
    payload = wf.write_file_impl(path, content).structured_content
    assert payload is not None
    return payload


def test_create_with_nested_parents(tmp_path):
    target = tmp_path / "a" / "b" / "new.txt"
    p = write(str(target), "hello\n")
    assert p["action"] == "created" and p["bytes"] == 6
    assert target.read_text() == "hello\n"


def test_content_byte_verbatim_crlf_no_bom(tmp_path):
    # Copilot #1148 (CRLF conversion) and #3389 (BOM) regressions.
    target = tmp_path / "crlf.txt"
    write(str(target), "a\r\nb\r\n")
    assert target.read_bytes() == b"a\r\nb\r\n"


def test_overwrite_reports_previous(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("old content here")
    p = write(str(target), "new")
    assert p["action"] == "overwritten"
    assert p["previous_bytes"] == 16 and p["bytes"] == 3
    assert target.read_text() == "new"


def test_empty_content(tmp_path):
    target = tmp_path / "empty.txt"
    p = write(str(target), "")
    assert p["bytes"] == 0 and target.read_bytes() == b""


def test_unicode_content(tmp_path):
    target = tmp_path / "u.txt"
    write(str(target), "héllo 你好\n")
    assert target.read_text(encoding="utf-8") == "héllo 你好\n"


def test_directory_target_errors(tmp_path):
    with pytest.raises(ToolError, match="Use list_files"):
        wf.write_file_impl(str(tmp_path), "x")


def test_outside_roots():
    with pytest.raises(ToolError, match="outside allowed roots"):
        wf.write_file_impl("/etc/evil.txt", "x")


def test_permission_denied_surfaces_strerror(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o555)
    try:
        with pytest.raises(ToolError, match="Could not write"):
            wf.write_file_impl(str(locked / "f.txt"), "x")
    finally:
        os.chmod(locked, 0o755)

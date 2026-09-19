"""Implementation gate for tools/edit_file.py (docs/tools/edit_file.md §4)."""

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import edit_file as ef
from binnacle.tools import read_file as rf


def edit(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    payload = ef.edit_file_impl(path, old, new, replace_all).structured_content
    assert payload is not None
    return payload


def test_exact_single_replace_with_snippet(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\ntarget = 1\nline4\nline5\n")
    p = edit(str(f), "target = 1", "target = 2")
    assert p["replacements"] == 1 and p["match"] == "exact"
    assert p["first_change_line"] == 3
    assert f.read_text() == "line1\nline2\ntarget = 2\nline4\nline5\n"
    assert "target = 2" in p["snippet"] and p["snippet_first_line"] == 1


def test_delete_via_empty_new_string(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("keep DELETEME keep\n")
    edit(str(f), "DELETEME ", "")
    assert f.read_text() == "keep keep\n"


def test_replace_all_counts(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x=1\ny=1\nz=1\n")
    p = edit(str(f), "=1", "=9", replace_all=True)
    assert p["replacements"] == 3
    assert f.read_text() == "x=9\ny=9\nz=9\n"


def test_read_to_edit_roundtrip_on_crlf(tmp_path):
    # The cross-tool guarantee: a slice of read_file's content is a valid
    # old_string, byte-for-byte, even on CRLF files.
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
    content = rf.read_file_impl(str(f), 1, None).structured_content["content"]
    old = content.splitlines(keepends=True)[1]  # "beta\r\n"
    p = edit(str(f), old, "BETA\r\n")
    assert p["match"] == "exact"
    assert f.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"


def test_utf8_bom_preserved(tmp_path):
    f = tmp_path / "bom.txt"
    f.write_bytes(b"\xef\xbb\xbfhello world\n")
    edit(str(f), "world", "there")
    assert f.read_bytes() == b"\xef\xbb\xbfhello there\n"


def test_curly_quotes_match_exactly(tmp_path):
    # Anti-normalization: Copilot #3254's failure class must not exist here.
    f = tmp_path / "q.txt"
    f.write_text("say “hello” now\n")
    edit(str(f), "“hello”", "“bye”")
    assert f.read_text() == "say “bye” now\n"


def test_whitespace_normalized_tier(tmp_path):
    f = tmp_path / "w.py"
    f.write_text("def f():\n        x = 1\n        return x\n")
    # old_string carries the wrong indentation.
    p = edit(str(f), "x = 1\nreturn x", "x = 2\nreturn x")
    assert p["match"] == "whitespace_normalized"
    assert f.read_text() == "def f():\n        x = 2\n        return x\n"


def test_whitespace_tier_ambiguity_errors(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("  a\n  b\n\n    a\n    b\n")
    with pytest.raises(ToolError, match="whitespace-normalized matches"):
        edit(str(f), "a\nb", "c")


def test_no_match_mentions_read_and_prefixes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("content\n")
    with pytest.raises(ToolError, match="line-number prefixes"):
        edit(str(f), "absent", "x")


def test_multi_match_lists_line_numbers(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("dup\nother\ndup\n")
    with pytest.raises(ToolError, match=r"lines 1, 3"):
        edit(str(f), "dup", "x")


def test_identical_strings_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n")
    with pytest.raises(ToolError, match="identical"):
        edit(str(f), "x", "x")


def test_missing_file_points_at_write_file(tmp_path):
    with pytest.raises(ToolError, match="write_file"):
        edit(str(tmp_path / "nope.txt"), "a", "b")


def test_directory_errors(tmp_path):
    with pytest.raises(ToolError, match="directory"):
        edit(str(tmp_path), "a", "b")


def test_binary_refused(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01\x02abc")
    with pytest.raises(ToolError, match="Binary file"):
        edit(str(f), "abc", "xyz")


def test_lossy_refused(tmp_path):
    f = tmp_path / "l.txt"
    f.write_bytes(b"ok \xf1 bad\n")
    with pytest.raises(ToolError, match="do not decode"):
        edit(str(f), "ok", "OK")


def test_outside_roots():
    with pytest.raises(ToolError, match="outside allowed roots"):
        ef.edit_file_impl("/etc/passwd", "a", "b", False)

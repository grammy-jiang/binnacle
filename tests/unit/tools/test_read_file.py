"""Implementation gate for tools/read_file.py (docs/tools/read_file.md §5)."""

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import read_file as rf


def read(path: str, start: int = 1, end: int | None = None) -> dict:
    payload = rf.read_file_impl(path, start, end).structured_content
    assert payload is not None
    return payload


# -- happy paths -----------------------------------------------------------


def test_crlf_byte_fidelity(tmp_path):
    raw = b"alpha\r\nbeta\r\ngamma"
    f = tmp_path / "crlf.txt"
    f.write_bytes(raw)
    p = read(str(f))
    assert p["content"].encode() == raw
    assert p["total_lines"] == 3 and not p["truncated"]


def test_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    p = read(str(f))
    assert p["kind"] == "empty" and p["content"] == ""


def test_utf16_bom_decode(tmp_path):
    f = tmp_path / "utf16.txt"
    f.write_bytes("héllo\nworld".encode("utf-16"))
    p = read(str(f))
    assert p["content"] == "héllo\nworld" and not p.get("lossy")


def test_lossy_decode_flagged(tmp_path):
    f = tmp_path / "lossy.txt"
    f.write_bytes(b"ok \xf1 bad\n")
    p = read(str(f))
    assert p.get("lossy") is True and "�" in p["content"]


def test_single_huge_line_clipped_not_empty(tmp_path):
    # Copilot v1.0.5 case: single-line files must not yield empty output.
    f = tmp_path / "one-line.txt"
    f.write_bytes(b"x" * 500_000)
    p = read(str(f))
    assert p["kind"] == "text" and p["content"].startswith("x" * 100)
    assert p.get("lines_clipped") == 1 and rf.LINE_CLIP_MARK in p["content"]
    assert "run_command" in p.get("note", "")


def test_small_many_line_file_untruncated(tmp_path):
    # Copilot #4633 case: a small file must be served whole.
    f = tmp_path / "small.txt"
    f.write_bytes(b"line\n" * 1720)  # ~8.6 KB
    p = read(str(f))
    assert p["total_lines"] == 1720 and p["end_line"] == 1720
    assert not p["truncated"]


def test_known_text_extension_beats_mime(tmp_path):
    # Gemini's .ts MPEG-TS MIME trap.
    f = tmp_path / "fake.ts"
    f.write_text("export const x = 1;\n")
    assert read(str(f))["kind"] == "text"


def test_binary_is_note_not_error(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    p = read(str(f))
    assert p["kind"] == "binary" and "png" in p["mime_guess"]


# -- windowing -------------------------------------------------------------


@pytest.fixture()
def big(tmp_path) -> Path:
    f = tmp_path / "big.txt"
    f.write_text("".join(f"line {i}\n" for i in range(1, 2501)))
    return f


def test_line_ceiling_and_continuation(big):
    p = read(str(big))
    assert p["end_line"] == rf.READ_MAX_LINES and p["truncated"]
    assert p["next_start_line"] == rf.READ_MAX_LINES + 1
    p = read(str(big), rf.READ_MAX_LINES + 1)
    assert p["end_line"] == 2500 and not p["truncated"]


def test_explicit_range_exact(big):
    p = read(str(big), 10, 20)
    assert p["start_line"] == 10 and p["end_line"] == 20
    assert p["content"].splitlines()[0] == "line 10" and not p["truncated"]


def test_end_clamped_with_note(big):
    p = read(str(big), 2490, 99999)
    assert p["end_line"] == 2500 and "clamped" in p["note"]


def test_char_cap_stops_early(tmp_path):
    f = tmp_path / "wide.txt"
    f.write_text(("y" * 1000 + "\n") * 100)
    p = read(str(f))
    assert p["truncated"] and p["end_line"] < 100
    assert p["next_start_line"] == p["end_line"] + 1
    assert len(p["content"]) <= rf.READ_MAX_CHARS


# -- path handling ---------------------------------------------------------


def test_nul_and_at_prefix_sanitized(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi\n")
    assert read("@" + str(f) + "\0")["path"] == str(f)


def test_relative_resolves_against_default_root():
    p = read("binnacle/README.md", 1, 3)
    assert p["path"] == str(Path.home() / "Projects/binnacle/README.md")


# -- errors ----------------------------------------------------------------


def test_e1_missing_lists_nearby(tmp_path):
    (tmp_path / "sibling.txt").write_text("x")
    with pytest.raises(ToolError, match="Files in"):
        rf.read_file_impl(str(tmp_path / "nope.txt"), 1, None)


def test_e2_directory(tmp_path):
    with pytest.raises(ToolError, match="Use list_files"):
        rf.read_file_impl(str(tmp_path), 1, None)


def test_e3_too_large(tmp_path):
    f = tmp_path / "huge.bin"
    f.write_bytes(b"a")
    with open(f, "r+b") as fh:
        fh.truncate(21 * 1024 * 1024)
    with pytest.raises(ToolError, match="run_command"):
        rf.read_file_impl(str(f), 1, None)


def test_e4_start_past_eof(tmp_path):
    f = tmp_path / "three.txt"
    f.write_text("a\nb\nc\n")
    with pytest.raises(ToolError, match="exceeds total_lines"):
        rf.read_file_impl(str(f), 99, None)


def test_e5_bad_range(tmp_path):
    f = tmp_path / "three.txt"
    f.write_text("a\nb\nc\n")
    with pytest.raises(ToolError, match="greater than end_line"):
        rf.read_file_impl(str(f), 5, 2)


def test_e6_symlink_escape(tmp_path):
    link = tmp_path / "escape"
    link.symlink_to("/etc/passwd")
    with pytest.raises(ToolError, match="outside allowed roots"):
        rf.read_file_impl(str(link), 1, None)


def test_e6_plain_outside_roots():
    with pytest.raises(ToolError, match="outside allowed roots"):
        rf.read_file_impl("/etc/passwd", 1, None)


# -- fits-in-one-call nudge (2026-09-06; docs/usage-analysis-2026-09-06.md §6) --


def test_partial_read_of_small_file_says_it_fits(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("".join(f"line {i}\n" for i in range(1, 101)))
    p = read(str(f), 10, 35)
    assert p["fits_in_one_call"] is True
    assert "fits in one call" in p["note"]
    assert "fits in one call" in rf.read_file_impl(str(f), 10, 35).content[0].text


def test_whole_file_read_has_no_nudge(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("a\nb\nc\n")
    p = read(str(f))
    assert "fits_in_one_call" not in p and "note" not in p


def test_partial_read_of_oversized_file_has_no_nudge(big):
    # 2,500 lines exceeds READ_MAX_LINES: a range is the right call here.
    p = read(str(big), 10, 20)
    assert "fits_in_one_call" not in p and "note" not in p


def test_description_states_the_window_in_chars():
    assert f"{rf.READ_MAX_CHARS // 1000}k chars" in rf.DESCRIPTION
    assert "lines of prose" in rf.DESCRIPTION and "2,000 lines" not in rf.DESCRIPTION
    assert "start narrow" not in rf.DESCRIPTION

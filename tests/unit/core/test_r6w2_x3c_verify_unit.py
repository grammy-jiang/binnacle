"""Unit cases for search_text_verify (r6 W2 X3c, SD-76)."""

import os
from contextlib import ExitStack
from pathlib import Path

import pytest

from binnacle.features.search import search_text_verify as verify


def lines_of(path: Path, wanted) -> dict:
    fd = os.open(path, os.O_RDONLY)
    try:
        return verify.fd_lines(fd, wanted)
    finally:
        os.close(fd)


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 1 << 20])
def test_fd_lines_across_chunk_boundaries(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(verify, "_CHUNK", chunk)
    path = tmp_path / "f"
    path.write_bytes(b"\xef\xbb\xbfone\ntwo\r\n\nfour \xff\nfive")
    assert lines_of(path, [1, 2, 3, 4, 5, 6]) == {
        1: "one",
        2: "two\r",
        3: "",
        4: "",
        5: "five",
    }


def test_fd_lines_utf16_splits_on_newline_only(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "_CHUNK", 3)
    path = tmp_path / "f"
    path.write_bytes("a\rb\r\nc\n".encode("utf-16"))
    assert lines_of(path, [1, 2]) == {1: "a\rb\r", 2: "c"}


def test_fd_lines_without_wanted_lines_reads_nothing(tmp_path):
    path = tmp_path / "f"
    path.write_text("x\n")
    assert lines_of(path, []) == {}


def open_one(path: str):
    with ExitStack() as stack:
        fd = verify.open_regular(verify.DirectoryCache(stack), path)
        if fd is not None:
            os.close(fd)
            return "fd"
        return None


def test_open_regular_refuses_every_non_regular_or_followed_object(tmp_path):
    (tmp_path / "f").write_text("x")
    (tmp_path / "d").mkdir()
    os.mkfifo(tmp_path / "p")
    (tmp_path / "l").symlink_to(tmp_path / "f")
    (tmp_path / "ld").symlink_to(tmp_path / "d")
    (tmp_path / "d" / "g").write_text("y")
    assert open_one(str(tmp_path / "f")) == "fd"
    assert open_one(str(tmp_path / "d" / "g")) == "fd"
    for refused in ("d", "p", "l", "ld/g", "missing", "f/x"):
        assert open_one(str(tmp_path / refused)) is None, refused
    assert open_one("relative/f") is None
    assert open_one(f"{tmp_path}/d/../f") is None
    assert open_one("/") is None


def test_verify_scan_keeps_the_same_objects_when_every_file_verifies(tmp_path):
    path = tmp_path / "f"
    path.write_text("needle\n")
    matches = [{"file": str(path), "line": 1, "text": "needle"}]
    line_map = {str(path): {1: "needle"}}
    kept = verify.verify_scan(matches, line_map, 5)
    assert kept[0] is matches and kept[1] is line_map and kept[2] == 5


def test_verify_scan_drops_a_changed_file_and_its_count(tmp_path):
    good, bad = tmp_path / "g", tmp_path / "b"
    good.write_text("needle\n")
    bad.write_text("changed\n")
    matches = [
        {"file": str(good), "line": 1, "text": "needle"},
        {"file": str(bad), "line": 1, "text": "needle"},
    ]
    line_map = {str(good): {1: "needle"}, str(bad): {1: "needle"}}
    kept, kept_map, total = verify.verify_scan(matches, line_map, 9)
    assert kept == matches[:1]
    assert set(kept_map) == {str(good)}
    assert total == 8


def test_verify_adaptive_accepts_a_clipped_snippet_only_as_a_prefix(tmp_path):
    path = tmp_path / "f"
    path.write_text("needle abcdef\n")
    entry = {"file": str(path), "line": 1, "count": 1}
    good = {"entries": [{**entry, "text": "needle ab…"}]}
    assert verify.verify_adaptive(good) is good
    bad = {"entries": [{**entry, "text": "needle zz…"}]}
    assert verify.verify_adaptive(bad)["entries"] == []
    tail = {"entries": [{"file": str(tmp_path / "missing"), "count": 3}]}
    assert verify.verify_adaptive(tail)["entries"] == []

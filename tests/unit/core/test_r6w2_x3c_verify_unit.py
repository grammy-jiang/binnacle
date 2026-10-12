"""Unit cases for search_text_verify (r6 W2 X3c, SD-76; X3c-a3, SD-78).

X3c-a3 removed the per-match content re-read (fd_lines); the checks that
remain are the base prefix and the no-follow walk to a regular file.
"""

import os
from pathlib import Path

from binnacle.features.files.fd_chain import DirectoryChain
from binnacle.features.search import search_text_verify as verify


def check_one(path: str) -> bool:
    parts = verify.components(path)
    if parts is None:
        return False
    with DirectoryChain() as chain:
        return verify.is_regular(chain, parts)


def test_is_regular_refuses_every_non_regular_or_followed_object(tmp_path):
    (tmp_path / "f").write_text("x")
    (tmp_path / "d").mkdir()
    os.mkfifo(tmp_path / "p")
    (tmp_path / "l").symlink_to(tmp_path / "f")
    (tmp_path / "ld").symlink_to(tmp_path / "d")
    (tmp_path / "d" / "g").write_text("y")
    assert check_one(str(tmp_path / "f"))
    assert check_one(str(tmp_path / "d" / "g"))
    for refused in ("d", "p", "l", "ld/g", "missing", "f/x"):
        assert not check_one(str(tmp_path / refused)), refused
    assert not check_one("relative/f")
    assert not check_one(f"{tmp_path}/d/../f")
    assert not check_one("/")


def test_verify_scan_keeps_the_same_objects_when_every_file_verifies(tmp_path):
    path = tmp_path / "f"
    path.write_text("needle\n")
    matches = [{"file": str(path), "line": 1, "text": "needle"}]
    line_map = {str(path): {1: "needle"}}
    kept = verify.verify_scan(matches, line_map, 5, tmp_path)
    assert kept[0] is matches and kept[1] is line_map and kept[2] == 5


def test_verify_scan_drops_a_non_regular_file_and_its_count(tmp_path):
    good, bad = tmp_path / "g", tmp_path / "b"
    good.write_text("needle\n")
    bad.mkdir()  # rg read a file here; it is now a directory
    matches = [
        {"file": str(good), "line": 1, "text": "needle"},
        {"file": str(bad), "line": 1, "text": "needle"},
    ]
    line_map = {str(good): {1: "needle"}, str(bad): {1: "needle"}}
    kept, kept_map, total = verify.verify_scan(matches, line_map, 9, tmp_path)
    assert kept == matches[:1]
    assert set(kept_map) == {str(good)}
    assert total == 8


def test_verify_scan_reports_rg_text_without_reading_the_file(tmp_path):
    path = tmp_path / "f"
    path.write_text("changed\n")  # the content race is a residual (SD-78)
    matches = [{"file": str(path), "line": 1, "text": "needle"}]
    kept = verify.verify_scan(matches, {str(path): {1: "needle"}}, 1, tmp_path)
    assert kept[0] == matches


def test_verify_adaptive_drops_a_missing_file_and_keeps_snippets(tmp_path):
    path = tmp_path / "f"
    path.write_text("needle abcdef\n")
    entry = {"file": str(path), "line": 1, "count": 1, "text": "needle zz…"}
    good = {"entries": [entry]}
    assert verify.verify_adaptive(good, tmp_path) is good
    tail = {"entries": [entry, {"file": str(tmp_path / "missing"), "count": 3}]}
    assert verify.verify_adaptive(tail, tmp_path)["entries"] == [entry]


def test_below_base_compares_components(tmp_path: Path):
    def below(path: Path | str, is_file: bool) -> bool:
        parts = verify.components(str(path))
        base = verify.components(str(tmp_path / "root"))
        assert base is not None
        return parts is not None and verify.below_base(parts, base, is_file)

    base = tmp_path / "root"
    assert below(base / "a", False)
    assert below(base / "a" / "b", False)
    assert not below(base, False)
    assert not below(tmp_path / "rootx" / "a", False)
    assert not below(tmp_path / "a", False)
    assert not below(f"{base}/../root/a", False)
    assert not below(f"{base}//a", False)
    assert not below(f"{base}/./a", False)
    assert below(base, True)
    assert not below(base / "a", True)

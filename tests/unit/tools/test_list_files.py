"""Implementation gate for tools/list_files.py (docs/tools/list_files.md §4)."""

import os

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import list_files as lf


def ls(
    path: str,
    glob: str | None = None,
    max_results: int = 200,
    include_hidden: bool = False,
) -> dict:
    payload = lf.list_files_impl(
        path, glob, max_results, include_hidden
    ).structured_content
    assert payload is not None
    return payload


# -- listing mode ----------------------------------------------------------


def test_list_dirs_first_then_alphabetical_with_sizes(tmp_path):
    (tmp_path / "b.txt").write_text("12345")
    (tmp_path / "a_dir").mkdir()
    (tmp_path / "C.txt").write_text("x")
    p = ls(str(tmp_path))
    kinds = [(e["type"], e["path"].rsplit("/", 1)[-1]) for e in p["entries"]]
    assert kinds == [("dir", "a_dir"), ("file", "b.txt"), ("file", "C.txt")]
    assert p["entries"][1]["bytes"] == 5
    assert "bytes" not in p["entries"][0]
    assert p["mode"] == "list" and not p["truncated"]


def test_list_hidden_excluded_then_included_git_never(tmp_path):
    (tmp_path / ".secret").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / "seen.txt").write_text("x")
    names = [e["path"].rsplit("/", 1)[-1] for e in ls(str(tmp_path))["entries"]]
    assert names == ["seen.txt"]
    names = [
        e["path"].rsplit("/", 1)[-1]
        for e in ls(str(tmp_path), include_hidden=True)["entries"]
    ]
    assert ".secret" in names and "seen.txt" in names and ".git" not in names


def test_list_cap_and_truncated(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")
    p = ls(str(tmp_path), max_results=3)
    assert p["count"] == 3 and p["truncated"] and "5" in p["note"]


# -- glob mode -------------------------------------------------------------


def test_glob_finds_nested_absolute(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "c.py").write_text("x")
    (tmp_path / "top.py").write_text("x")
    p = ls(str(tmp_path), glob="*.py")
    paths = {e["path"] for e in p["entries"]}
    assert str(nested / "c.py") in paths and str(tmp_path / "top.py") in paths
    assert p["mode"] == "glob" and all(e["path"].startswith("/") for e in p["entries"])


def test_glob_respects_gitignore(tmp_path):
    (tmp_path / ".git").mkdir()  # rg honors .gitignore only inside a repo
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("x")
    (tmp_path / "kept.py").write_text("x")
    names = [
        e["path"].rsplit("/", 1)[-1] for e in ls(str(tmp_path), glob="*.py")["entries"]
    ]
    assert names == ["kept.py"]


def test_glob_newest_first(tmp_path):
    old = tmp_path / "old.py"
    new = tmp_path / "new.py"
    old.write_text("x")
    new.write_text("x")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    p = ls(str(tmp_path), glob="*.py")
    assert p["entries"][0]["path"].endswith("new.py")


def test_glob_character_class_uses_stdlib_semantics(tmp_path):
    (tmp_path / "^").write_text("hit\n")
    (tmp_path / "a").write_text("hit\n")
    p = ls(str(tmp_path), glob="[^]")
    names = [e["path"].rsplit("/", 1)[-1] for e in p["entries"]]
    assert names == ["^"]


def test_glob_no_match_is_note_not_error(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    p = ls(str(tmp_path), glob="*.zzz")
    assert p["count"] == 0 and not p["truncated"] and "No files match" in p["note"]


def test_glob_cap_and_truncated(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("x")
    p = ls(str(tmp_path), glob="*.py", max_results=2)
    assert p["count"] == 2 and p["truncated"] and "of 5" in p["note"]


# -- errors ----------------------------------------------------------------


def test_missing_dir_lists_nearby(tmp_path):
    (tmp_path / "real").mkdir()
    with pytest.raises(ToolError, match="Directory not found"):
        lf.list_files_impl(str(tmp_path / "nope"), None, 200, False)


def test_path_is_file_hints_read_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(ToolError, match="Use read_file"):
        lf.list_files_impl(str(f), None, 200, False)


def test_outside_roots():
    with pytest.raises(ToolError, match="outside allowed roots"):
        lf.list_files_impl("/etc", None, 200, False)


def test_file_entry_tolerates_a_vanished_path():
    class Vanished:
        def is_dir(self):
            raise OSError("gone")

    assert lf._file_entry(Vanished()) is None


def test_glob_reports_missing_ripgrep(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("rg")

    monkeypatch.setattr(lf.subprocess, "run", missing)

    with pytest.raises(ToolError, match="ripgrep"):
        lf._glob_mode(tmp_path, "*.py", 20, False)


def test_glob_reports_ripgrep_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise lf.subprocess.TimeoutExpired(["rg"], 1)

    monkeypatch.setattr(lf.subprocess, "run", timeout)

    with pytest.raises(ToolError, match="timed out"):
        lf._glob_mode(tmp_path, "*.py", 20, False)


def test_glob_reports_ripgrep_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lf.subprocess,
        "run",
        lambda *a, **k: lf.subprocess.CompletedProcess(
            ["rg"], 2, stdout="", stderr="synthetic failure"
        ),
    )

    with pytest.raises(ToolError, match="synthetic failure"):
        lf._glob_mode(tmp_path, "*.py", 20, False)


def test_glob_translates_invalid_pattern_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lf.subprocess,
        "run",
        lambda *a, **k: lf.subprocess.CompletedProcess(
            ["rg"], 0, stdout="one.py\n", stderr=""
        ),
    )
    monkeypatch.setattr(
        lf,
        "full_match",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad glob")),
    )

    with pytest.raises(ToolError, match="Invalid glob pattern"):
        lf._glob_mode(tmp_path, "*.py", 20, False)


def test_glob_hidden_mode_passes_hidden_switch(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return lf.subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(lf.subprocess, "run", fake_run)

    lf._glob_mode(tmp_path, "*.py", 20, True)

    assert "--hidden" in seen[0]
    assert "!**/.git/**" in seen[0]

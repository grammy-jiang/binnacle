"""Stable low-cardinality error codes keep user ToolError text unchanged."""

import subprocess

import pytest
from fastmcp.exceptions import ToolError

from binnacle.errors import CodedToolError
from binnacle.tools import list_files as lf
from binnacle.tools import read_file as rf
from binnacle.tools import search_text as st


def _code(exc: pytest.ExceptionInfo[ToolError]) -> str:
    assert isinstance(exc.value, CodedToolError)
    return exc.value.telemetry_code


def test_read_file_error_codes(tmp_path):
    with pytest.raises(ToolError, match="File not found") as exc:
        rf.read_file_impl(str(tmp_path / "missing"), 1, None)
    assert _code(exc) == "file_not_found"

    with pytest.raises(ToolError, match="directory") as exc:
        rf.read_file_impl(str(tmp_path), 1, None)
    assert _code(exc) == "path_is_directory"

    path = tmp_path / "a.txt"
    path.write_text("a\nb\n")
    with pytest.raises(ToolError, match="greater than end_line") as exc:
        rf.read_file_impl(str(path), 2, 1)
    assert _code(exc) == "range_invalid"
    with pytest.raises(ToolError, match="exceeds total_lines") as exc:
        rf.read_file_impl(str(path), 99, None)
    assert _code(exc) == "range_past_end"


def test_common_path_error_code_is_shared():
    with pytest.raises(ToolError, match="outside allowed roots") as exc:
        rf.read_file_impl("/etc/passwd", 1, None)
    assert _code(exc) == "path_outside_root"


def test_list_files_error_codes(tmp_path, monkeypatch):
    with pytest.raises(ToolError, match="Directory not found") as exc:
        lf.list_files_impl(str(tmp_path / "missing"), None, 10, False)
    assert _code(exc) == "directory_not_found"

    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(ToolError, match="not a directory") as exc:
        lf.list_files_impl(str(file), None, 10, False)
    assert _code(exc) == "path_is_file"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("rg", 20)

    monkeypatch.setattr(lf.subprocess, "run", timeout)
    with pytest.raises(ToolError, match="timed out") as exc:
        lf._glob_mode(tmp_path, "*.py", 10, False)
    assert _code(exc) == "rg_timeout"


def test_search_text_error_codes(tmp_path):
    with pytest.raises(ToolError, match="non-empty") as exc:
        st.search_text_impl("", str(tmp_path), None, False, None, False, 10)
    assert _code(exc) == "empty_pattern"

    with pytest.raises(ToolError, match="Path not found") as exc:
        st.search_text_impl(
            "x", str(tmp_path / "missing"), None, False, None, False, 10
        )
    assert _code(exc) == "path_not_found"

    (tmp_path / "a.txt").write_text("foo\n")
    with pytest.raises(ToolError, match="ripgrep rejected") as exc:
        st.search_text_impl("f(oo", str(tmp_path), None, False, None, False, 10)
    assert _code(exc) == "rg_rejected"


def test_read_file_large_file_code(tmp_path, monkeypatch):
    path = tmp_path / "large.txt"
    path.write_text("xx")
    monkeypatch.setattr(rf, "READ_MAX_FILE_BYTES", 1)
    with pytest.raises(ToolError, match="limit") as exc:
        rf.read_file_impl(str(path), 1, None)
    assert _code(exc) == "file_too_large"


def test_list_files_rg_and_glob_error_codes(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("rg")

    monkeypatch.setattr(lf.subprocess, "run", missing)
    with pytest.raises(ToolError, match="ripgrep") as exc:
        lf._glob_mode(tmp_path, "*.py", 10, False)
    assert _code(exc) == "rg_missing"

    monkeypatch.setattr(
        lf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout="", stderr="boom"),
    )
    with pytest.raises(ToolError, match="boom") as exc:
        lf._glob_mode(tmp_path, "*.py", 10, False)
    assert _code(exc) == "rg_failed"

    monkeypatch.setattr(
        lf, "full_match", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    monkeypatch.setattr(
        lf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="a.py\n", stderr=""),
    )
    with pytest.raises(ToolError, match="Invalid glob") as exc:
        lf._glob_mode(tmp_path, "*.py", 10, False)
    assert _code(exc) == "invalid_glob"


def test_search_text_runtime_error_codes(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("foo\n")

    def missing(*args, **kwargs):
        raise FileNotFoundError("rg")

    monkeypatch.setattr(st.subprocess, "run", missing)
    with pytest.raises(ToolError, match="ripgrep") as exc:
        st._run_rg(tmp_path, "foo", False, 0)
    assert _code(exc) == "rg_missing"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("rg", 20)

    monkeypatch.setattr(st.subprocess, "run", timeout)
    with pytest.raises(ToolError, match="timed out") as exc:
        st._run_rg(tmp_path, "foo", False, 0)
    assert _code(exc) == "rg_timeout"

    monkeypatch.setattr(
        st, "full_match", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    with pytest.raises(ToolError, match="Invalid glob") as exc:
        st._matches_glob(str(tmp_path / "a.txt"), tmp_path, "*.txt")
    assert _code(exc) == "invalid_glob"


def test_search_text_indexed_args_and_budget_codes(tmp_path, monkeypatch):
    with pytest.raises(ToolError, match="fixed bounded context package") as exc:
        st.search_text_impl("@context x", str(tmp_path), "*.py", False, None, False, 10)
    assert _code(exc) == "indexed_args_invalid"

    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 8)
    payload = {
        "path": "/tmp",
        "pattern": "x",
        "entries": [],
        "count": 0,
        "truncated": False,
    }
    with pytest.raises(ToolError, match="metadata exceeds") as exc:
        st._enforce_result_budget(payload, names_only=False)
    assert _code(exc) == "response_budget_exceeded"

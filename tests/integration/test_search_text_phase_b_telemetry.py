"""Terminal exact-search telemetry covers success, strategy and error paths."""

import re

import pytest
from fastmcp.exceptions import ToolError

from binnacle.callctx import current_call
from binnacle.tools import search_text as st


def fields(message: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", message))


def exact_line(caplog) -> str:
    lines = [
        record.getMessage()
        for record in caplog.records
        if "event=search_exact " in record.getMessage()
    ]
    assert len(lines) == 1
    return lines[0]


def run_exact(tmp_path, pattern: str, **kwargs):
    return st.search_text_impl(
        pattern,
        str(tmp_path),
        kwargs.pop("glob", None),
        kwargs.pop("fixed_strings", False),
        kwargs.pop("context_lines", 0),
        kwargs.pop("names_only", False),
        kwargs.pop("max_results", 100),
        kwargs.pop("line_numbers", False),
        **kwargs,
    )


def test_normal_exact_emits_one_terminal_summary(tmp_path, caplog):
    (tmp_path / "a.py").write_text("alpha\nbeta\n")
    token = current_call.set("exact-normal")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "alpha", glob="*.py")
    finally:
        current_call.reset(token)

    assert result.structured_content["count"] == 1
    f = fields(exact_line(caplog))
    assert f["call"] == "exact-normal"
    assert f["outcome"] == "ok" and f["strategy"] == "normal"
    assert f["budget_outcome"] == "none"
    assert f["scope"] == "dir" and f["rg_calls"] == "1"
    assert f["rg_match_events"] == "1"
    assert int(f["collect_glob_checks"]) >= 1
    assert f["accepted_matches"] == "1"
    assert f["returned_entries"] == "1"
    assert int(f["result_bytes"]) > 0


def test_auto_context_records_second_rg_and_cumulative_work(tmp_path, caplog):
    (tmp_path / "a.py").write_text("before\nunique-hit\nafter\n")
    token = current_call.set("exact-auto")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "unique-hit", context_lines=None)
    finally:
        current_call.reset(token)

    assert "context" in result.structured_content["entries"][0]
    f = fields(exact_line(caplog))
    assert f["auto_context"] == "true"
    assert f["rg_calls"] == "2"
    assert f["context_requested"] == "omitted"
    assert int(f["effective_context"]) == st.AUTO_CONTEXT_SINGLE
    assert int(f["rg_events"]) > int(f["rg_match_events"])


def test_names_only_and_budget_outcome_are_orthogonal(tmp_path, caplog, monkeypatch):
    for index in range(20):
        directory = tmp_path / (f"dir-{index:02d}-" + "x" * 20)
        directory.mkdir()
        (directory / "a.txt").write_text("hit\n")
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 1_024)
    token = current_call.set("exact-names")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "hit", names_only=True, max_results=100)
    finally:
        current_call.reset(token)

    assert result.structured_content["truncated"] is True
    f = fields(exact_line(caplog))
    assert f["strategy"] == "names_only"
    assert f["budget_outcome"] == "entries_trimmed"
    assert int(f["pre_budget_bytes"]) > int(f["result_bytes"])


def test_adaptive_summary_includes_second_scan_work(tmp_path, caplog, monkeypatch):
    (tmp_path / "a.py").write_text(("hit " + "x" * 200 + "\n") * 80)
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 2_048)
    token = current_call.set("exact-adaptive")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "hit", context_lines=1, max_results=100)
    finally:
        current_call.reset(token)

    assert "Adaptive discovery" in result.structured_content["note"]
    f = fields(exact_line(caplog))
    assert f["strategy"] == "adaptive"
    assert f["adaptive_attempted"] == "true"
    assert f["adaptive_selected"] == "true"
    assert int(f["adaptive_match_events"]) == 80
    assert float(f["adaptive_ms"]) >= 0


def test_exact_error_still_emits_terminal_summary(tmp_path, caplog):
    (tmp_path / "a.py").write_text("alpha\n")
    token = current_call.set("exact-error")
    try:
        with (
            caplog.at_level("INFO", logger="binnacle.search_text"),
            pytest.raises(ToolError, match="ripgrep rejected"),
        ):
            run_exact(tmp_path, "(")
    finally:
        current_call.reset(token)

    f = fields(exact_line(caplog))
    assert f["call"] == "exact-error"
    assert f["outcome"] == "error"
    assert f["error_code"] == "rg_rejected"
    assert f["rg_calls"] == "1"

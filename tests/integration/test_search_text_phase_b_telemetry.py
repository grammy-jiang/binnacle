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


def test_no_match_fixed_string_and_file_scope_are_summarized(tmp_path, caplog):
    path = tmp_path / "one.txt"
    path.write_text("alpha\n")
    token = current_call.set("exact-file")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = st.search_text_impl(
                "missing literal",
                str(path),
                None,
                True,
                0,
                False,
                10,
                False,
            )
    finally:
        current_call.reset(token)
    assert result.structured_content["count"] == 0
    f = fields(exact_line(caplog))
    assert f["scope"] == "file"
    assert f["strategy"] == "normal"
    assert f["outcome"] == "ok"
    assert f["accepted_matches"] == "0"
    assert f["returned_entries"] == "0"


def test_context_omission_is_a_machine_readable_budget_outcome(
    tmp_path, caplog, monkeypatch
):
    (tmp_path / "wide.txt").write_text(
        "before " + "a" * 1500 + "\nneedle\nafter " + "b" * 1500 + "\n"
    )
    monkeypatch.setattr(
        st,
        "SEARCH_SETTINGS",
        st.SEARCH_SETTINGS.model_copy(update={"adaptive_discovery_enabled": False}),
    )
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 1024)
    token = current_call.set("exact-context-budget")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "needle", context_lines=1, line_numbers=True)
    finally:
        current_call.reset(token)
    assert "context" not in result.structured_content["entries"][0]
    f = fields(exact_line(caplog))
    assert f["strategy"] == "normal"
    assert f["budget_outcome"] == "context_omitted"
    assert int(f["pre_budget_bytes"]) > int(f["result_bytes"])


def test_adaptive_attempt_can_fall_back_to_ordinary_budget(
    tmp_path, caplog, monkeypatch
):
    (tmp_path / "many.txt").write_text(("hit " + "x" * 100 + "\n") * 80)
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 2048)
    monkeypatch.setattr(st, "build_adaptive_result", lambda *a, **k: None)
    token = current_call.set("exact-adaptive-fallback")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            result = run_exact(tmp_path, "hit", context_lines=0, max_results=80)
    finally:
        current_call.reset(token)
    assert "response budget reached" in result.structured_content["note"]
    f = fields(exact_line(caplog))
    assert f["adaptive_attempted"] == "true"
    assert f["adaptive_selected"] == "false"
    assert f["strategy"] == "normal"
    assert f["budget_outcome"] == "entries_trimmed"


@pytest.mark.parametrize("code", ["rg_missing", "rg_timeout", "invalid_glob"])
def test_coded_exact_failures_emit_one_correlated_terminal_summary(
    tmp_path, caplog, monkeypatch, code
):
    (tmp_path / "a.txt").write_text("alpha\n")

    if code in {"rg_missing", "rg_timeout"}:

        def fail_rg(*args, **kwargs):
            raise st.CodedToolError(code, f"synthetic {code}")

        monkeypatch.setattr(st, "_run_rg", fail_rg)
    else:

        def fail_collect(*args, **kwargs):
            raise st.CodedToolError(code, "synthetic invalid glob")

        monkeypatch.setattr(st, "_collect", fail_collect)

    token = current_call.set(f"exact-{code}")
    try:
        with (
            caplog.at_level("INFO", logger="binnacle.search_text"),
            pytest.raises(ToolError),
        ):
            run_exact(tmp_path, "alpha", context_lines=0)
    finally:
        current_call.reset(token)
    f = fields(exact_line(caplog))
    assert f["outcome"] == "error"
    assert f["error_code"] == code
    assert f["call"] == f"exact-{code}"


def test_impossible_budget_is_reported_as_metadata_error(tmp_path, caplog, monkeypatch):
    (tmp_path / "a.txt").write_text("alpha\n")
    monkeypatch.setattr(
        st,
        "SEARCH_SETTINGS",
        st.SEARCH_SETTINGS.model_copy(update={"adaptive_discovery_enabled": False}),
    )
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 8)
    token = current_call.set("exact-budget-error")
    try:
        with (
            caplog.at_level("INFO", logger="binnacle.search_text"),
            pytest.raises(ToolError, match="metadata exceeds"),
        ):
            run_exact(tmp_path, "alpha", context_lines=0)
    finally:
        current_call.reset(token)
    f = fields(exact_line(caplog))
    assert f["outcome"] == "error"
    assert f["error_code"] == "response_budget_exceeded"
    assert f["budget_outcome"] == "metadata_error"


def test_terminal_summary_does_not_repeat_path_pattern_or_match_text(tmp_path, caplog):
    secret_pattern = "phase-b-secret-pattern"
    secret_text = secret_pattern + "-matched-text"
    secret_path = tmp_path / "phase-b-secret-file.txt"
    secret_path.write_text(secret_text + "\n")
    token = current_call.set("exact-privacy")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            st.search_text_impl(
                secret_pattern,
                str(secret_path),
                None,
                True,
                0,
                False,
                10,
                False,
            )
    finally:
        current_call.reset(token)
    line = exact_line(caplog)
    assert secret_pattern not in line
    assert secret_text not in line
    assert str(secret_path) not in line

"""Implementation gate for tools/search_text.py (docs/tools/search_text.md §4)."""

import json
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from binnacle.callctx import current_call
from binnacle.tools import search_text as st


def search(pattern: str, path: str, **kw) -> dict:
    args: dict[str, Any] = {
        "glob": None,
        "fixed_strings": False,
        "context_lines": None,
        "names_only": False,
        "max_results": 100,
    }
    args.update(kw)
    payload = st.search_text_impl(pattern, path, **args).structured_content
    assert payload is not None
    return payload


@pytest.fixture()
def proj(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n\nWIDGET = 9\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("def beta():\n    return WIDGET\n")
    (tmp_path / "notes.txt").write_text("widget notes\n")
    return tmp_path


# -- basics ----------------------------------------------------------------


def test_match_shape_no_line_prefix(proj):
    p = search("def alpha", str(proj), context_lines=0)
    assert p["count"] == 1
    e = p["entries"][0]
    assert e["file"].endswith("a.py") and e["line"] == 1
    assert e["text"] == "def alpha():"  # bare line, edit_file-safe


def test_smart_case(proj):
    # lowercase pattern matches uppercase text …
    assert search("widget", str(proj), context_lines=0)["count"] == 3
    # … but an uppercase pattern is strict
    assert search("WIDGET", str(proj), context_lines=0)["count"] == 2


def test_fixed_strings_literal(tmp_path):
    (tmp_path / "x.txt").write_text("a.*b\nfoo\n")
    assert (
        search("a.*b", str(tmp_path), fixed_strings=True, context_lines=0)["count"] == 1
    )


def test_glob_filter_nested_convenience(proj):
    p = search("widget", str(proj), glob="*.py", context_lines=0)
    files = {e["file"].rsplit("/", 1)[-1] for e in p["entries"]}
    assert files == {"a.py", "b.py"}  # notes.txt filtered; nested b.py kept


def test_glob_character_class_uses_stdlib_semantics(tmp_path):
    (tmp_path / "^").write_text("needle\n")
    (tmp_path / "a").write_text("needle\n")
    p = search("needle", str(tmp_path), glob="[^]", context_lines=0)
    assert p["count"] == 1
    assert p["entries"][0]["file"].endswith("/^")


def test_gitignore_respected(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("secret.txt\n")
    (tmp_path / "secret.txt").write_text("token\n")
    (tmp_path / "open.txt").write_text("token\n")
    p = search("token", str(tmp_path), context_lines=0)
    assert p["count"] == 1 and p["entries"][0]["file"].endswith("open.txt")


def test_max_results_truncated(tmp_path):
    (tmp_path / "many.txt").write_text("hit\n" * 10)
    p = search("hit", str(tmp_path), max_results=4, context_lines=0)
    assert p["count"] == 10 and len(p["entries"]) == 4 and p["truncated"]
    assert "of 10" in p["note"]


def test_names_only_counts(proj):
    p = search("widget", str(proj), names_only=True)
    by_name = {e["file"].rsplit("/", 1)[-1]: e["count"] for e in p["entries"]}
    assert by_name == {"a.py": 1, "b.py": 1, "notes.txt": 1}


# -- context ---------------------------------------------------------------


def test_explicit_context(proj):
    p = search("return 1", str(proj), context_lines=1)
    e = p["entries"][0]
    assert e["context_first_line"] == 1
    assert e["context"] == "def alpha():\n    return 1\n"
    assert "1:" not in e["context"].splitlines()[0]  # no number prefixes


def test_auto_context_single_match(proj):
    p = search("def beta", str(proj))
    e = p["entries"][0]
    assert "context" in e and "return WIDGET" in e["context"]


def test_auto_context_off_at_four_matches(tmp_path):
    (tmp_path / "f.txt").write_text("hit\nx\nhit\nx\nhit\nx\nhit\n")
    p = search("hit", str(tmp_path))
    assert p["count"] == 4
    assert all("context" not in e for e in p["entries"])


def test_long_match_line_clipped(tmp_path):
    (tmp_path / "wide.txt").write_text("needle " + "z" * 5000 + "\n")
    e = search("needle", str(tmp_path), context_lines=0)["entries"][0]
    assert st.LINE_CLIP_MARK in e["text"]
    assert len(e["text"]) <= st.SEARCH_MAX_LINE_CHARS + len(st.LINE_CLIP_MARK)


# -- files as path ---------------------------------------------------------


def test_path_may_be_a_file(proj):
    p = search("alpha", str(proj / "a.py"), context_lines=0)
    assert p["count"] == 1


# -- errors ----------------------------------------------------------------


def test_invalid_regex_surfaces_rg_diagnostic(proj):
    with pytest.raises(ToolError, match="ripgrep rejected"):
        search("f(oo", str(proj))


def test_empty_pattern(proj):
    with pytest.raises(ToolError, match="non-empty"):
        search("", str(proj))


def test_missing_path(tmp_path):
    with pytest.raises(ToolError, match="Path not found"):
        search("x", str(tmp_path / "nope"))


def test_outside_roots():
    with pytest.raises(ToolError, match="outside allowed roots"):
        search("x", "/etc")


# -- line_numbers (2026-09-03; grep -n parity) ------------------------------


def test_context_line_numbers_prefix(proj):
    e = search("return 1", str(proj), context_lines=1, line_numbers=True)["entries"][0]
    assert e["context"] == "1: def alpha():\n2:     return 1\n3: "
    assert e["context_first_line"] == 1
    assert e["text"] == "    return 1"  # the match line itself stays prefix-free


def test_context_line_numbers_default_off(proj):
    e = search("return 1", str(proj), context_lines=1)["entries"][0]
    assert not e["context"].startswith("1:")


def test_line_numbers_apply_to_auto_context(proj):
    e = search("return WIDGET", str(proj), line_numbers=True)["entries"][0]
    assert e["context"].splitlines()[0].startswith("1: ")


# -- structured result budget (2026-09-19 usage review) ---------------------


def compact_bytes(payload: dict) -> int:
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _disable_adaptive(monkeypatch) -> None:
    # These tests exercise the ordinary response-budget path. Keep them isolated
    # from deployment-local adaptive-discovery configuration.
    monkeypatch.setattr(st.SEARCH_SETTINGS, "adaptive_discovery_enabled", False)


def test_result_budget_truncates_complete_entries_in_order(
    tmp_path, monkeypatch, caplog
):
    lines = [f"hit {i:03d} " + ("x" * 120) for i in range(80)]
    (tmp_path / "many.txt").write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    _disable_adaptive(monkeypatch)

    token = current_call.set("budget-test-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            p = search("hit", str(tmp_path), context_lines=1, line_numbers=True)
    finally:
        current_call.reset(token)

    assert p["count"] == 80
    assert 0 < len(p["entries"]) < 80
    assert p["truncated"] is True
    assert "response budget reached" in p["note"]
    assert "names_only" in p["note"]
    assert compact_bytes(p) <= 4_096
    assert [e["line"] for e in p["entries"]] == list(range(1, len(p["entries"]) + 1))
    assert "event=search_budget_hit" in caplog.text
    assert "call=budget-test-call" in caplog.text
    assert "result_budget_bytes=4096" in caplog.text


def test_result_budget_counts_utf8_bytes_not_characters(tmp_path, monkeypatch):
    (tmp_path / "unicode.txt").write_text(("hit 中文🙂" + "界" * 80 + "\n") * 40)
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    _disable_adaptive(monkeypatch)
    p = search("hit", str(tmp_path), context_lines=0)

    assert p["count"] == 40
    assert p["truncated"] is True
    assert compact_bytes(p) <= 4_096


def test_result_budget_keeps_first_match_when_context_alone_is_too_large(
    tmp_path, monkeypatch
):
    (tmp_path / "wide.txt").write_text(
        ("before " + "a" * 1_500 + "\n") + "needle\n" + ("after " + "c" * 1_500 + "\n")
    )
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 1_024)
    _disable_adaptive(monkeypatch)
    p = search("needle", str(tmp_path), context_lines=1, line_numbers=True)

    assert p["count"] == 1
    assert len(p["entries"]) == 1
    assert p["entries"][0]["line"] == 2
    assert "needle" in p["entries"][0]["text"]
    assert "context" not in p["entries"][0]
    assert p["truncated"] is True
    assert "without context" in p["note"]
    assert "read_file" in p["note"]
    assert compact_bytes(p) <= 1_024


def test_result_budget_does_not_change_small_result(tmp_path, monkeypatch):
    (tmp_path / "small.txt").write_text("alpha\nhit\nomega\n")
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 65_536)
    p = search("hit", str(tmp_path), context_lines=1)

    assert p["count"] == 1
    assert p["truncated"] is False
    assert "note" not in p
    assert p["entries"][0]["context"] == "alpha\nhit\nomega"


def test_result_budget_and_max_results_keep_true_total(tmp_path, monkeypatch):
    (tmp_path / "many.txt").write_text(("hit " + "z" * 200 + "\n") * 100)
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 2_048)
    _disable_adaptive(monkeypatch)
    p = search("hit", str(tmp_path), max_results=25, context_lines=0)

    assert p["count"] == 100
    assert 0 < len(p["entries"]) < 25
    assert p["truncated"] is True
    assert "response budget reached" in p["note"]
    assert compact_bytes(p) <= 2_048


def test_names_only_result_budget_is_bounded(tmp_path, monkeypatch):
    for i in range(80):
        d = tmp_path / (f"directory-{i:03d}-" + "x" * 30)
        d.mkdir()
        (d / ("file-" + "y" * 30 + ".txt")).write_text("hit\n")
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    p = search("hit", str(tmp_path), names_only=True, max_results=100)

    assert p["count"] == 80
    assert 0 < len(p["entries"]) < 80
    assert p["truncated"] is True
    assert "response budget reached" in p["note"]
    assert compact_bytes(p) <= 4_096


def test_budget_errors_if_required_metadata_cannot_fit(monkeypatch):
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    payload = {
        "path": "/tmp/x",
        "pattern": "p" * 5_000,
        "entries": [],
        "count": 1,
        "truncated": True,
    }
    with pytest.raises(ToolError, match="metadata exceeds"):
        st._enforce_result_budget(payload, names_only=False)


# -- adaptive broad-result discovery (development pilot) -------------------


def _enable_adaptive(monkeypatch, **overrides):
    values = {
        "adaptive_discovery_enabled": True,
        "adaptive_detailed_files": 30,
        "adaptive_total_files": 200,
        "adaptive_representative_matches": 2,
        "adaptive_snippet_chars": 180,
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(st.SEARCH_SETTINGS, name, value)


def test_adaptive_enabled_does_not_change_small_payload(tmp_path, monkeypatch):
    (tmp_path / "small.txt").write_text("alpha\nhit\nomega\n")
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 65_536)

    monkeypatch.setattr(st.SEARCH_SETTINGS, "adaptive_discovery_enabled", False)
    before = search("hit", str(tmp_path), context_lines=1)

    _enable_adaptive(monkeypatch)
    after = search("hit", str(tmp_path), context_lines=1)

    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_adaptive_discovery_replaces_only_budget_bound_content_result(
    tmp_path, monkeypatch, caplog
):
    for file_index in range(40):
        lines = [
            f"alpha beta file={file_index} line={line} " + "x" * 180
            for line in range(5)
        ]
        (tmp_path / f"f{file_index:02d}.txt").write_text("\n".join(lines) + "\n")

    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 8_192)
    _enable_adaptive(
        monkeypatch,
        adaptive_detailed_files=5,
        adaptive_total_files=40,
        adaptive_representative_matches=2,
        adaptive_snippet_chars=80,
    )

    token = current_call.set("adaptive-tool-test")
    try:
        with caplog.at_level("INFO", logger="binnacle.search_text"):
            payload = search(
                "alpha|beta",
                str(tmp_path),
                context_lines=1,
                max_results=100,
            )
    finally:
        current_call.reset(token)

    detailed = [entry for entry in payload["entries"] if "line" in entry]
    tail = [entry for entry in payload["entries"] if "line" not in entry]
    assert payload["count"] == 200
    assert payload["truncated"] is True
    assert "Adaptive discovery" in payload["note"]
    assert len(detailed) == 10
    assert len(tail) == 35
    assert all({"file", "line", "text", "count"} <= entry.keys() for entry in detailed)
    assert all(set(entry) == {"file", "count"} for entry in tail)
    assert compact_bytes(payload) <= 8_192
    assert "event=search_adaptive_discovery" in caplog.text
    assert "call=adaptive-tool-test" in caplog.text
    assert "candidate_files=40" in caplog.text
    assert "budget_trimmed=false" in caplog.text
    assert "candidate_hashes=" in caplog.text
    assert "detailed_hashes=" in caplog.text


def test_adaptive_discovery_keeps_max_results_as_detailed_match_cap(
    tmp_path, monkeypatch
):
    for file_index in range(12):
        (tmp_path / f"f{file_index:02d}.txt").write_text(
            "\n".join(
                f"alpha beta gamma {file_index} {line} " + "z" * 250
                for line in range(4)
            )
            + "\n"
        )

    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    _enable_adaptive(
        monkeypatch,
        adaptive_detailed_files=10,
        adaptive_total_files=12,
        adaptive_representative_matches=2,
        adaptive_snippet_chars=60,
    )

    payload = search(
        "alpha|beta|gamma",
        str(tmp_path),
        context_lines=3,
        max_results=3,
    )

    detailed = [entry for entry in payload["entries"] if "line" in entry]
    assert len(detailed) <= 3
    assert payload["count"] == 48
    assert any("line" not in entry for entry in payload["entries"])
    assert compact_bytes(payload) <= 4_096

"""Search settings use existing scan seams without global construction state."""

import pytest
from fastmcp.exceptions import ToolError

from binnacle import paths
from binnacle.config import RootsSettings, SearchTextSettings
from binnacle.tools import search_text


def fail_global():
    raise AssertionError("explicit Search settings must not load global configuration")


@pytest.mark.parametrize("mode", ["streaming", "materialized"])
def test_explicit_search_limits_roots_and_pipeline_without_global_reads(
    tmp_path, monkeypatch, mode
):
    (tmp_path / "file").write_text("needle long text\nneedle second\n")
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    settings = SearchTextSettings(
        exact_execution=mode, max_results_cap=1, max_line_chars=6
    )
    monkeypatch.setattr(paths, "get_settings", fail_global)
    monkeypatch.setattr(search_text, "get_settings", fail_global)
    result = search_text.search_text_impl(
        "needle",
        ".",
        None,
        False,
        0,
        False,
        100,
        roots=roots,
        settings=settings,
        rg_bin="rg",
    ).structured_content
    assert result["path"] == str(tmp_path)
    assert result["count"] == 2 and result["truncated"]
    assert len(result["entries"]) == 1
    assert result["entries"][0]["text"] == "needle… [line truncated]"


def test_search_missing_root_hint_stays_inside_explicit_policy(tmp_path, monkeypatch):
    (tmp_path / "private-sibling").write_text("secret")
    roots = RootsSettings(default_root=tmp_path / "missing", extra_roots=())
    monkeypatch.setattr(paths, "get_settings", fail_global)
    monkeypatch.setattr(search_text, "get_settings", fail_global)
    with pytest.raises(ToolError, match="Path not found") as exc:
        search_text.search_text_impl(
            "x",
            ".",
            None,
            False,
            0,
            False,
            10,
            roots=roots,
            settings=SearchTextSettings(),
            rg_bin="rg",
        )
    assert "private-sibling" not in str(exc.value)
    assert "Files in" not in str(exc.value)


@pytest.mark.parametrize("mode", ["streaming", "materialized"])
def test_explicit_search_auto_context_and_binary(tmp_path, monkeypatch, mode):
    (tmp_path / "file").write_text("before\nneedle\nafter\n")
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    settings = SearchTextSettings(exact_execution=mode, auto_context_single=1)
    monkeypatch.setattr(search_text, "get_settings", fail_global)
    result = search_text.search_text_impl(
        "needle",
        ".",
        None,
        False,
        None,
        False,
        10,
        roots=roots,
        settings=settings,
        rg_bin="rg",
    ).structured_content
    assert result["entries"][0]["context"] == "before\nneedle\nafter"
    with pytest.raises(ToolError, match="ripgrep"):
        search_text.search_text_impl(
            "needle",
            ".",
            None,
            False,
            0,
            False,
            10,
            roots=roots,
            settings=settings,
            rg_bin=str(tmp_path / "no-rg"),
        )

"""Search settings use existing scan seams without global construction state."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from binnacle import search_server
from binnacle.config import RootsSettings, SearchTextSettings
from binnacle.features.files import paths
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


def test_search_factory_snapshots_caps_roots_and_path_literals(tmp_path, monkeypatch):
    children = []
    for index, cap in enumerate((1, 2)):
        directory = tmp_path / str(index)
        directory.mkdir()
        (directory / "file").write_text("needle\n" * 3)
        roots = RootsSettings(default_root=directory, extra_roots=())
        settings = SearchTextSettings(max_results_default=cap, max_results_cap=cap)
        children.append(
            search_server.create_search_server(
                roots=roots, search_settings=settings, rg_bin="rg"
            )
        )
        roots.default_root = tmp_path / "changed"
        settings.max_results_default = settings.max_results_cap = 99
    for module in (paths, search_server, search_text):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        for index, (child, cap) in enumerate(zip(children, (1, 2), strict=True)):
            async with Client(child, cache=False) as client:
                tool = (await client.list_tools())[0]
                parameter = tool.input_schema["properties"]["max_results"]
                assert parameter["default"] == parameter["maximum"] == cap
                assert (
                    tool.input_schema["properties"]["path"]["default"] == "~/Projects"
                )
                assert "~/Projects" in str(tool.input_schema["properties"]["path"])
                omitted = await client.call_tool(
                    "search_text", {"pattern": "needle"}, raise_on_error=False
                )
                assert (
                    omitted.is_error
                    and "outside allowed roots" in omitted.content[0].text
                )
                for path in (".", str(tmp_path / str(index))):
                    result = (
                        await client.call_tool(
                            "search_text",
                            {"pattern": "needle", "path": path, "context_lines": 0},
                        )
                    ).structured_content
                    assert result["count"] == 3 and result["truncated"]
                    assert len(result["entries"]) == cap
                excessive = await client.call_tool(
                    "search_text",
                    {"pattern": "needle", "path": ".", "max_results": cap + 1},
                    raise_on_error=False,
                )
                assert excessive.is_error

    asyncio.run(go())


def test_fully_supplied_search_factory_has_no_hidden_loads_on_error_paths(
    tmp_path, monkeypatch
):
    (tmp_path / "private-sibling").write_text("secret")
    for module in (paths, search_server, search_text):
        monkeypatch.setattr(module, "get_settings", fail_global)
    missing = search_server.create_search_server(
        roots=RootsSettings(default_root=tmp_path / "missing", extra_roots=()),
        search_settings=SearchTextSettings(),
        rg_bin="rg",
    )
    unavailable = search_server.create_search_server(
        roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        search_settings=SearchTextSettings(),
        rg_bin=str(tmp_path / "no-rg"),
    )

    async def go():
        async with Client(missing) as client:
            result = await client.call_tool(
                "search_text", {"pattern": "x", "path": "."}, raise_on_error=False
            )
            assert result.is_error and "Path not found" in result.content[0].text
            assert "private-sibling" not in result.content[0].text
        async with Client(unavailable) as client:
            result = await client.call_tool(
                "search_text", {"pattern": "x", "path": "."}, raise_on_error=False
            )
            assert result.is_error and "ripgrep" in result.content[0].text

    asyncio.run(go())

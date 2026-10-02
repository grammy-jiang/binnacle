"""Files adapter snapshots isolate policy without changing MCP path literals."""

import asyncio

import pytest
from fastmcp import Client

from binnacle import files_server, paths
from binnacle.config import (
    EditFileSettings,
    ListFilesSettings,
    ReadFileSettings,
    RootsSettings,
)
from binnacle.tools import edit_file, list_files, read_file, write_file


def fail_global():
    raise AssertionError("fully supplied Files inputs must not load settings")


def test_read_write_factories_copy_roots_limits_and_description(tmp_path, monkeypatch):
    roots, settings, servers = [], [], []
    for index, cap in enumerate((1, 3)):
        directory = tmp_path / str(index)
        directory.mkdir()
        (directory / "data").write_text("a\nb\nc\n")
        roots.append(RootsSettings(default_root=directory, extra_roots=()))
        settings.append(ReadFileSettings(max_lines=cap, max_chars=(index + 1) * 4000))
        servers.append(
            files_server.create_files_server(
                roots=roots[-1], read_settings=settings[-1]
            )
        )
    for model in roots:
        model.default_root = tmp_path / "changed"
    for model in settings:
        model.max_lines = 999
        model.max_chars = 999999
    for module in (files_server, paths, read_file, write_file):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        for index, root in enumerate(servers):
            async with Client(root, cache=False) as client:
                tools = {t.name: t for t in await client.list_tools()}
                assert f"{(index + 1) * 4}k chars" in tools["read_file"].description
                result = (
                    await client.call_tool("read_file", {"path": "data"})
                ).structured_content
                assert result["end_line"] == (1 if index == 0 else 3)
                assert result["path"] == str(tmp_path / str(index) / "data")
                raw = "\ufeffalpha\r\nbeta\n"
                await client.call_tool("write_file", {"path": "new", "content": raw})
                assert (tmp_path / str(index) / "new").read_bytes() == raw.encode()
                denied = await client.call_tool(
                    "read_file",
                    {"path": str(tmp_path / str(1 - index) / "data")},
                    raise_on_error=False,
                )
                assert (
                    denied.is_error
                    and "outside allowed roots" in denied.content[0].text
                )
                missing = await client.call_tool(
                    "read_file", {"path": "missing"}, raise_on_error=False
                )
                assert missing.is_error and "data" in missing.content[0].text

    asyncio.run(go())


def test_read_missing_custom_root_never_hints_global_siblings(tmp_path, monkeypatch):
    (tmp_path / "private-sibling").write_text("secret")
    root = files_server.create_files_server(
        roots=RootsSettings(default_root=tmp_path / "missing", extra_roots=()),
        read_settings=ReadFileSettings(),
    )
    for module in (files_server, paths, read_file, write_file):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        async with Client(root) as client:
            result = await client.call_tool(
                "read_file", {"path": "."}, raise_on_error=False
            )
            assert result.is_error
            assert "File not found" in result.content[0].text
            assert "private-sibling" not in result.content[0].text
            assert "Files in" not in result.content[0].text

    asyncio.run(go())


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("max_chars", 2, "a\n"),
        ("max_line_chars", 1, "a… [line truncated]\n"),
    ],
)
def test_direct_explicit_read_limits(tmp_path, monkeypatch, field, value, expected):
    path = tmp_path / "file"
    path.write_text("abc\nsecond\n" if field == "max_line_chars" else "a\nb\n")
    settings = ReadFileSettings(**{field: value}, max_lines=1)
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    monkeypatch.setattr(read_file, "get_settings", fail_global)
    monkeypatch.setattr(paths, "get_settings", fail_global)
    result = read_file.read_file_impl("file", 1, None, roots=roots, settings=settings)
    assert result.structured_content["content"] == expected


def explicit_files(roots, **overrides):
    inputs = {
        "roots": roots,
        "read_settings": ReadFileSettings(),
        "list_settings": ListFilesSettings(),
        "edit_settings": EditFileSettings(),
        "rg_bin": "rg",
    }
    inputs.update(overrides)
    return files_server.create_files_server(**inputs)


def test_fully_supplied_files_never_load_settings_and_preserve_path_metadata(
    tmp_path, monkeypatch
):
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    for module in (files_server, paths, read_file, write_file, list_files, edit_file):
        monkeypatch.setattr(module, "get_settings", fail_global)
    child = explicit_files(roots)

    async def go():
        async with Client(child, cache=False) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert (
                tools["list_files"].input_schema["properties"]["path"]["default"]
                == "~/Projects"
            )
            for tool in tools.values():
                assert "~/Projects" in str(tool.input_schema["properties"]["path"])
            omitted = await client.call_tool("list_files", {}, raise_on_error=False)
            assert (
                omitted.is_error and "outside allowed roots" in omitted.content[0].text
            )
            for path in (".", str(tmp_path)):
                assert not (
                    await client.call_tool("list_files", {"path": path})
                ).is_error

    asyncio.run(go())


def test_list_and_edit_snapshots_control_schema_cap_and_snippet(tmp_path, monkeypatch):
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    for i in range(4):
        (tmp_path / f"{i}.txt").write_text("before\nneedle\nafter\n")
    children = []
    for cap, snippet in [(1, 0), (3, 1)]:
        listing = ListFilesSettings(max_results_default=cap, max_results_cap=cap)
        editing = EditFileSettings(snippet_context_lines=snippet)
        children.append(
            explicit_files(roots, list_settings=listing, edit_settings=editing)
        )
        listing.max_results_default = listing.max_results_cap = 99
        editing.snippet_context_lines = 99
    for module in (files_server, paths, list_files, edit_file):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        for i, (child, cap, snippet) in enumerate(
            zip(
                children, [1, 3], ["changed\n", "before\nchanged\nafter\n"], strict=True
            )
        ):
            async with Client(child) as client:
                tools = {t.name: t for t in await client.list_tools()}
                parameter = tools["list_files"].input_schema["properties"][
                    "max_results"
                ]
                assert parameter["default"] == parameter["maximum"] == cap
                listing = await client.call_tool("list_files", {"path": "."})
                assert listing.structured_content["count"] == cap
                assert listing.structured_content["truncated"]
                result = await client.call_tool(
                    "edit_file",
                    {
                        "path": f"{i}.txt",
                        "old_string": "needle",
                        "new_string": "changed",
                    },
                )
                assert result.structured_content["snippet"] == snippet
                excessive = await client.call_tool(
                    "list_files",
                    {"path": ".", "max_results": cap + 1},
                    raise_on_error=False,
                )
                assert excessive.is_error
        direct = list_files.list_files_impl(
            ".",
            None,
            99,
            False,
            roots=roots,
            settings=ListFilesSettings(max_results_cap=2),
            rg_bin="rg",
        )
        assert direct.structured_content["count"] == 2

    asyncio.run(go())


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("list_files", {"path": "."}),
        ("edit_file", {"path": ".", "old_string": "old", "new_string": "new"}),
    ],
)
def test_remaining_files_error_hints_use_captured_roots(
    tmp_path, monkeypatch, tool, arguments
):
    (tmp_path / "private-sibling").write_text("secret")
    child = explicit_files(
        RootsSettings(default_root=tmp_path / "missing", extra_roots=())
    )
    for module in (files_server, paths, list_files, edit_file):
        monkeypatch.setattr(module, "get_settings", fail_global)

    async def go():
        async with Client(child) as client:
            result = await client.call_tool(tool, arguments, raise_on_error=False)
            assert result.is_error
            assert "not found" in result.content[0].text
            assert "private-sibling" not in result.content[0].text
            assert "Files in" not in result.content[0].text

    asyncio.run(go())


def test_list_binary_and_timeout_are_captured(tmp_path, monkeypatch):
    import subprocess

    (tmp_path / "a.py").write_text("x")
    child = explicit_files(
        RootsSettings(default_root=tmp_path, extra_roots=()),
        list_settings=ListFilesSettings(rg_timeout_s=7),
        rg_bin="selected-rg",
    )
    seen = []

    def run(command, **kwargs):
        seen.append((command[0], kwargs["timeout"]))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(list_files.subprocess, "run", run)
    monkeypatch.setattr(list_files, "get_settings", fail_global)

    async def go():
        async with Client(child) as client:
            result = await client.call_tool(
                "list_files", {"path": ".", "glob": "*.py"}, raise_on_error=False
            )
            assert result.is_error and "timed out after 7 s" in result.content[0].text
        assert seen == [("selected-rg", 7)]

    asyncio.run(go())

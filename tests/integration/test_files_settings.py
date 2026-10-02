"""Files adapter snapshots isolate policy without changing MCP path literals."""

import asyncio

import pytest
from fastmcp import Client

from binnacle import files_server, paths
from binnacle.config import ReadFileSettings, RootsSettings
from binnacle.tools import read_file, write_file


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

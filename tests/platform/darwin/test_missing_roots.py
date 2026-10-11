"""Darwin lifespan root grants: missing roots are skipped, never fatal (SD-24)."""

import asyncio
import platform

import pytest
from fastmcp import Client

from tests.contracts.test_darwin_interface import (
    _both_tools_succeed,
    _generation_app,
)

_DARWIN_ONLY = pytest.mark.skipif(
    platform.system() != "Darwin", reason="native Files lifecycle"
)


_ALL_FILE_TOOLS = ("read_file", "list_files", "search_text")


async def _error_text(client, tool, arguments):
    result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error, result
    return result.content[0].text


@_DARWIN_ONLY
def test_missing_extra_root_is_skipped_with_linux_texts(tmp_path, monkeypatch, caplog):
    missing = tmp_path / "missing"
    app, _access, root = _generation_app(
        tmp_path, monkeypatch, (missing,), _ALL_FILE_TOOLS
    )
    canonical = missing.resolve()

    async def exercise():
        async with Client(app) as client:
            await _both_tools_succeed(client, root)
            target = str(missing / "a.txt")
            assert await _error_text(client, "read_file", {"path": target}) == (
                f"File not found: {canonical / 'a.txt'}."
            )
            assert await _error_text(client, "list_files", {"path": str(missing)}) == (
                f"Directory not found: {canonical}."
            )
            assert (
                await _error_text(
                    client, "search_text", {"path": str(missing), "pattern": "x"}
                )
                == f"Path not found: {canonical}."
            )
            # Outside every configured root stays the ordinary refusal.
            assert (
                "outside"
                in (
                    await _error_text(client, "read_file", {"path": "/untrusted"})
                ).lower()
            )

    with caplog.at_level("WARNING"):
        asyncio.run(exercise())
    assert any(
        "event=root_skipped" in r.getMessage() and str(canonical) in r.getMessage()
        for r in caplog.records
    )


@_DARWIN_ONLY
def test_all_roots_missing_starts_with_linux_outside_roots_text(tmp_path, monkeypatch):
    missing = (tmp_path / "gone").resolve()
    other = (tmp_path / "gone2").resolve()
    app, access, root = _generation_app(
        tmp_path, monkeypatch, (other,), _ALL_FILE_TOOLS
    )
    root.rename(missing)  # the only real root disappears before the lifespan
    app2_roots = f"{root}, {other}"

    async def exercise():
        async with Client(app) as client:
            assert not access.grants
            for tool, args in (
                ("read_file", {"path": str(missing / "file")}),
                ("list_files", {"path": str(other)}),
                ("search_text", {"path": "/untrusted", "pattern": "x"}),
            ):
                text = await _error_text(client, tool, args)
                assert text.startswith(
                    f"Path outside allowed roots ({app2_roots}): "
                ), text
            text = await _error_text(client, "read_file", {"path": str(other / "f")})
            assert text == f"Path outside allowed roots ({app2_roots}): {other / 'f'}"

    asyncio.run(exercise())


@_DARWIN_ONLY
def test_root_created_between_lifespans_is_picked_up_next_entry(tmp_path, monkeypatch):
    later = tmp_path / "later"
    app, _access, root = _generation_app(
        tmp_path, monkeypatch, (later,), _ALL_FILE_TOOLS
    )

    async def exercise():
        async with Client(app) as client:
            await _both_tools_succeed(client, root)
            later.mkdir()  # appears mid-lifespan: no live re-resolution
            (later / "b.txt").write_text("late")
            text = await _error_text(
                client, "read_file", {"path": str(later / "b.txt")}
            )
            assert text.startswith("File not found: ")
        async with Client(app) as client:
            read = await client.call_tool("read_file", {"path": str(later / "b.txt")})
            assert read.structured_content["content"] == "late"

    asyncio.run(exercise())

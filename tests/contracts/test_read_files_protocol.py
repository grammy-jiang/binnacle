"""The multi-file read candidates as a client sees them (2026-09-27).

Each test builds a server in one candidate mode ("param" or "tool") with the
production middleware and checks the surface through fastmcp's in-memory
Client: schemas, descriptions, visibility for ChatGPT, results validated
against the advertised output schema (the strict-client lesson of
2026-09-07), and the journal facts an evaluation reads. The "off" surface is
tests/contracts/test_tool_surface_off.py.
"""

import asyncio
import logging

import jsonschema  # type: ignore[import-untyped]
import mcp.types
from fastmcp import Client, FastMCP

from binnacle.config import get_settings
from binnacle.identity import ClientIdentity
from binnacle.logging_middleware import ToolLoggingMiddleware
from binnacle.tools import read_file as rf
from binnacle.tools import read_files as rfs
from binnacle.visibility import ClientToolVisibility

CHATGPT = "openai-mcp(ChatGPT)"


def build(mode: str) -> FastMCP:
    identity = ClientIdentity()
    m = FastMCP("candidate")
    m.add_middleware(ToolLoggingMiddleware(identity))
    allow = rfs.effective_client_tools(get_settings().client_tools, mode)
    m.add_middleware(ClientToolVisibility(allow, identity))
    rf.register(m, mode)
    rfs.register(m, mode)
    return m


def session(mode: str, fn, client: str | None = None):
    async def go():
        kwargs = {}
        if client:
            kwargs["client_info"] = mcp.types.Implementation(name=client, version="1")
        async with Client(build(mode), **kwargs) as c:
            return await fn(c)

    return asyncio.run(go())


def tools(mode: str, client: str | None = None) -> dict:
    return {t.name: t for t in session(mode, lambda c: c.list_tools(), client)}


def call(mode: str, name: str, args: dict, client: str | None = None):
    return session(
        mode, lambda c: c.call_tool(name, args, raise_on_error=False), client
    )


def validated(mode: str, name: str, result) -> dict:
    schema = tools(mode)[name].output_schema
    jsonschema.validate(result.structured_content, schema)
    return result.structured_content


def fixture_files(tmp_path) -> list[dict]:
    good = tmp_path / "mod.py"
    good.write_text("def f():\n    return 1\n")
    test = tmp_path / "test_mod.py"
    test.write_text("".join(f"line {i}\n" for i in range(1, 3000)))
    return [
        {"path": str(good)},
        {"path": str(test), "start_line": 1},
        {"path": str(tmp_path / "missing.md")},
        {"path": str(good)},
    ]


# -- candidate "param" -----------------------------------------------------------


def test_param_schema_offers_files_with_limits():
    t = tools("param")["read_file"]
    files = t.input_schema["properties"]["files"]["anyOf"][0]
    assert files["maxItems"] == rfs.MULTI_MAX_FILES and files["minItems"] == 1
    entry = files["items"]
    assert entry["additionalProperties"] is False and entry["required"] == ["path"]
    assert "path" not in t.input_schema.get("required", [])
    assert t.description == rfs.param_description()
    ann = t.annotations
    assert ann.read_only_hint is True and ann.open_world_hint is False


def test_param_files_call_validates_against_the_advertised_schema(tmp_path):
    r = call("param", "read_file", {"files": fixture_files(tmp_path)})
    assert not r.is_error
    p = validated("param", "read_file", r)
    assert [e["kind"] for e in p["files"]] == ["text", "text", "error", "duplicate"]
    assert (p["files_read"], p["files_failed"], p["files_duplicate"]) == (2, 1, 1)


def test_param_single_path_is_unchanged(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\ny\n")
    r = call("param", "read_file", {"path": str(f), "start_line": 1, "files": None})
    assert (
        validated("param", "read_file", r)
        == rf.read_file_impl(str(f), 1, None).structured_content
    )


def test_param_explicit_default_range_is_accepted_with_files(tmp_path):
    # ChatGPT sends defaults explicitly (process lesson 2026-09-06).
    f = tmp_path / "a.txt"
    f.write_text("x\n")
    r = call(
        "param",
        "read_file",
        {"files": [{"path": str(f)}], "start_line": 1, "end_line": None},
    )
    assert not r.is_error and r.structured_content["files_read"] == 1


def test_param_rejects_both_neither_and_a_range_beside_files(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n")
    one = [{"path": str(f)}]
    for args, text in (
        ({"path": str(f), "files": one}, "not both"),
        ({}, "Give path (one file) or files"),
        ({"files": one, "start_line": 3}, "put the range in each entry"),
    ):
        r = call("param", "read_file", args)
        assert r.is_error and text in r.content[0].text


def test_param_too_many_files_names_the_limit(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n")
    r = call("param", "read_file", {"files": [{"path": str(f)}] * 9})
    assert r.is_error and f"at most {rfs.MULTI_MAX_FILES} items" in r.content[0].text


def test_param_unknown_entry_key_is_rejected(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n")
    r = call("param", "read_file", {"files": [{"path": str(f), "start": 2}]})
    assert r.is_error and "start" in r.content[0].text


# -- candidate "tool" ------------------------------------------------------------


def test_tool_mode_adds_read_files_and_a_pointer():
    t = tools("tool")
    assert t["read_file"].description == rf.DESCRIPTION + rf.TOOL_POINTER
    assert t["read_files"].description == rfs.description()
    ann = t["read_files"].annotations
    assert ann.read_only_hint is True and ann.open_world_hint is False
    assert t["read_files"].input_schema["required"] == ["files"]


def test_tool_mode_serves_read_files_to_chatgpt():
    assert {"read_file", "read_files"} <= set(tools("tool", CHATGPT))
    assert "read_files" not in tools("param", CHATGPT)


def test_tool_call_validates_against_the_advertised_schema(tmp_path):
    r = call("tool", "read_files", {"files": fixture_files(tmp_path)}, CHATGPT)
    assert not r.is_error
    p = validated("tool", "read_files", r)
    big = p["files"][1]  # over one read's window: cut like read_file, not by the budget
    assert big["truncated"] and big["next_start_line"] == big["end_line"] + 1
    assert "budget_cut" not in big and "next_call" not in p


# -- journal facts ---------------------------------------------------------------


def test_journal_carries_the_multi_read_counts(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="binnacle.results"):
        call("tool", "read_files", {"files": fixture_files(tmp_path)}, CHATGPT)
    lines = [r.getMessage() for r in caplog.records if r.name == "binnacle.results"]
    call_line = next(line for line in lines if "event=tool_call" in line)
    result_line = next(line for line in lines if "event=tool_result" in line)
    assert "files_requested=4" in call_line
    for fact in ("files_requested=4", "files_read=2", "files_failed=1"):
        assert fact in result_line
    assert "files_not_read=0" in result_line and "kind=files" in result_line
    assert str(tmp_path) not in result_line  # paths and content are not copied

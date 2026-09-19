"""MCP protocol tests through fastmcp's in-memory client.

Roadmap item 2 of 2026-08-31. `Client(server.mcp)` runs the real protocol
(initialize, tools/list, tools/call, output-schema validation) without a
socket, so this is the one place the *surface* is checked as a client
sees it: the annotations that gate ChatGPT's permission prompts, the
output schemas a strict client validates against, and a few end-to-end
calls through the same code path the tunnel uses.

Per-client visibility (which tools ChatGPT is served) is
tests/unit/core/test_visibility.py; per-state output-schema validity of the job
tools is tests/contracts/test_job_schemas.py. Neither is repeated here.

Sync tests with `asyncio.run()`: pytest-asyncio is deliberately not a
dependency (2026-08-31).
"""

import asyncio
import json

from fastmcp import Client

from binnacle import server

#: The contract each hint carries for ChatGPT's connector UI:
#: The SDK exposes MCP annotation fields as snake_case Python attributes.
EXPECTED_ANNOTATIONS = {
    "read_file": {"read_only_hint": True, "open_world_hint": False},
    "list_files": {"read_only_hint": True, "open_world_hint": False},
    "search_text": {"read_only_hint": True, "open_world_hint": False},
    "job_status": {"read_only_hint": True, "open_world_hint": False},
    "edit_file": {
        "read_only_hint": False,
        "destructive_hint": True,
        "idempotent_hint": False,
        "open_world_hint": False,
    },
    "write_file": {
        "read_only_hint": False,
        "destructive_hint": True,
        "idempotent_hint": True,
        "open_world_hint": False,
    },
    "run_command": {
        "read_only_hint": False,
        "destructive_hint": True,
        "open_world_hint": True,
    },
    "stop_job": {
        "read_only_hint": False,
        "destructive_hint": True,
        "idempotent_hint": True,
        "open_world_hint": False,
    },
}


def run(coro_fn):
    async def go():
        async with Client(server.mcp) as c:
            return await coro_fn(c)

    return asyncio.run(go())


def list_tools():
    return run(lambda c: c.list_tools())


def call(name: str, **args):
    return run(lambda c: c.call_tool(name, args, raise_on_error=False))


def text_of(result) -> str:
    """Everything a client could read from the result: the text parts and
    the structured payload (read_file keeps the body in the latter and
    puts only a summary in the former)."""
    text = "".join(getattr(part, "text", "") for part in result.content)
    if result.structured_content is not None:
        text += "\n" + json.dumps(result.structured_content)
    return text


# -- surface -----------------------------------------------------------------


def test_every_tool_carries_the_expected_annotations():
    """A wrong hint changes what ChatGPT asks the user before calling."""
    tools = {t.name: t for t in list_tools()}
    assert set(tools) == set(EXPECTED_ANNOTATIONS)
    for name, expected in EXPECTED_ANNOTATIONS.items():
        got = tools[name].annotations
        assert got is not None, name
        for hint, value in expected.items():
            assert getattr(got, hint) == value, (name, hint, getattr(got, hint))


def test_read_only_and_destructive_are_never_both_set():
    for t in list_tools():
        a = t.annotations
        assert a is not None
        assert not (a.read_only_hint and a.destructive_hint), t.name


def test_every_tool_publishes_an_input_schema_and_a_description():
    for t in list_tools():
        assert t.description, t.name
        assert t.input_schema.get("type") == "object", t.name
        assert "properties" in t.input_schema, t.name


def test_job_tools_publish_output_schemas_with_nullable_exit_fields():
    """2026-09-07: exit_code/signal are null for running or signal-killed
    jobs; a non-nullable schema made strict clients reject the result."""
    tools = {t.name: t for t in list_tools()}
    for name in ("run_command", "job_status", "stop_job"):
        schema = tools[name].output_schema
        assert schema, name
        props = schema.get("properties", {})
        for field in ("exit_code", "signal"):
            if field not in props:
                continue
            spec = json.dumps(props[field])
            assert '"null"' in spec, (name, field, spec)


def test_server_instructions_are_a_short_self_contained_tool_map():
    """First 512 chars must stand alone (OpenAI guidance); the workflow
    rules live in the ChatGPT Project, not here."""
    text = server.mcp.instructions or ""
    assert "binnacle" in text and "run_command" in text
    assert len(text) <= 1024


# -- end to end through the protocol ----------------------------------------


def test_write_read_edit_search_round_trip(tmp_path):
    path = tmp_path / "note.md"
    body = "alpha nonce-7Q3\nbeta\n"
    w = call("write_file", path=str(path), content=body)
    assert not w.is_error, text_of(w)
    assert path.read_text() == body

    r = call("read_file", path=str(path))
    assert not r.is_error and "nonce-7Q3" in text_of(r)

    e = call("edit_file", path=str(path), old_string="beta", new_string="gamma")
    assert not e.is_error, text_of(e)
    assert path.read_text() == "alpha nonce-7Q3\ngamma\n"

    s = call("search_text", pattern="gamma", path=str(tmp_path))
    assert not s.is_error and "note.md" in text_of(s)

    listing = call("list_files", path=str(tmp_path))
    assert not listing.is_error and "note.md" in text_of(listing)


def test_run_command_synchronous_result_reports_no_job(tmp_path):
    r = call("run_command", command="printf 'hi nonce-7Q3'", workdir=str(tmp_path))
    assert not r.is_error, text_of(r)
    sc = r.structured_content
    assert sc is not None
    assert sc["exit_code"] == 0 and sc["background_job"] is False
    assert "nonce-7Q3" in json.dumps(sc)


def test_path_outside_the_roots_is_a_tool_error_not_a_crash():
    r = call("read_file", path="/etc/passwd")
    assert r.is_error
    assert "allowed roots" in text_of(r)


def test_unknown_tool_is_a_protocol_error():
    r = call("no_such_tool")
    assert r.is_error

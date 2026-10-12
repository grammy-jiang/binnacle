"""Review STRUCT-01 and ADV-STRUCT-01: ambiguous mirror formats; lab key count.

STRUCT-01: a text block that matches more than one pinned mirror format has
no determinable serializer (``{}`` with empty structured content renders
alike in both formats). It is an ambiguous mirror: the whole hint is
suppressed (the original object, ``rendered == ()``), and on the real lab
ledger the job stays ``PENDING``. Single-format mirrors still update.

ADV-STRUCT-01: the lab key extractors count each hinted key once per result,
whatever the position of the STRUCT JSON mirror.
"""

import json
from typing import Any

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import HINT_FIELD
from binnacle.mcp.job_awareness_hint_struct import MIRROR_FORMATS
from tests.contracts.job_awareness.e2_composition import (
    E2Server,
    chat,
    hinted_keys,
    running,
)
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import in_loop

FIELD = {"type": "string", "maxLength": 512}
#: The reviewer's replay schema: closed, only the optional hint field.
EMPTY_SCHEMA = {
    "type": "object",
    "properties": {HINT_FIELD: FIELD},
    "additionalProperties": False,
}
#: A closed schema that admits every candidate below (hint field declared).
OPEN_VALUES = {
    "type": "object",
    "properties": {
        "a": {"type": ["integer", "string", "array", "object"]},
        HINT_FIELD: FIELD,
    },
    "additionalProperties": False,
}
CANDIDATES: list[dict[str, Any]] = [{}, {"a": 1}, {"a": "x"}, {"a": []}, {"a": {}}]


def both_alike(value: dict[str, Any]) -> bool:
    return len({render(value) for render in MIRROR_FORMATS}) == 1


def struct(lab: RoutedLab, schema: dict[str, Any]):
    return lab.routed(schema=schema, enabled=True, carrier=HintCarrier.STRUCT)


def result(*texts: str, structured: dict[str, Any]) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=t) for t in texts],
        structured_content=structured,
    )


def test_only_the_empty_object_renders_alike_in_both_formats():
    assert [v for v in CANDIDATES if both_alike(v)] == [{}]  # nosec B101 - pytest assertion
    assert {render({}) for render in MIRROR_FORMATS} == {"{}"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "texts",
    [("{}",), ("plain", "{}"), ("{}", "plain")],
    ids=["alone", "second", "first"],
)
@in_loop
async def test_a_text_matching_both_formats_suppresses(texts):
    """STRUCT-01 replay: ``{}`` + empty closed structuredContent."""
    with RoutedLab(1) as lab:
        adapter = struct(lab, EMPTY_SCHEMA)
        value = result(*texts, structured={})
        _, outcome = await lab.call(adapter, lab.route(lab.job), value)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert value.structured_content == {}  # nosec B101 - pytest assertion


@pytest.mark.parametrize("render", MIRROR_FORMATS, ids=["stdlib", "compact"])
@pytest.mark.parametrize("structured", CANDIDATES, ids=json.dumps)
@in_loop
async def test_every_alike_rendering_suppresses_and_others_update(structured, render):
    """Any text that serializes identically in both formats is ambiguous."""
    with RoutedLab(1) as lab:
        value = result(render(structured), structured=dict(structured))
        _, outcome = await lab.call(struct(lab, OPEN_VALUES), lab.route(lab.job), value)
    if both_alike(structured):
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        return
    assert outcome.rendered == (lab.job,)  # nosec B101 - pytest assertion
    new = outcome.result.structured_content
    assert new is not None and HINT_FIELD in new  # nosec B101 - pytest assertion
    texts = [getattr(c, "text", None) for c in outcome.result.content]
    assert texts == [render(new)]  # nosec B101 - pytest assertion


@in_loop
async def test_ambiguous_mirror_on_the_ledger_keeps_the_job_pending(tmp_path):
    def empty(note: str) -> ToolResult:
        return result("{}", structured={})

    server = E2Server(
        tmp_path / "phase",
        carrier=HintCarrier.STRUCT,
        note_schema=EMPTY_SCHEMA,
        note_result=empty,
    )
    assert server.adapter.struct_bound is True  # nosec B101 - pytest assertion
    who = chat("struct-01")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        call = await wire.call(who, "fixture_unrelated_read")
        again = await wire.call(who, "fixture_unrelated_read")
    expected = (
        '{"content":[{"text":"{}","type":"text"}],"isError":false,'
        '"structuredContent":{}}'
    )
    assert call.raw.decode() == again.raw.decode() == expected  # nosec B101 - pytest assertion
    assert call.row["ja_hint"] == "0" and call.hints == []  # nosec B101 - pytest assertion
    states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert states == {"PENDING"}  # nosec B101 - pytest assertion


# -- ADV-STRUCT-01 -------------------------------------------------------------

_KEY = (
    "ja1_55555555555555555555555555555555:666666666666:"
    "g1_77777777777777777777777777777777"
)
_HINT = f"[Binnacle job reminder] {_KEY} unconfirmed"


@pytest.mark.parametrize("position", [0, 1, 2])
def test_lab_extractors_count_a_mirrored_key_once(tmp_path, position):
    structured = {"note": "n", HINT_FIELD: _HINT}
    texts = ["plain one", "plain two"]
    texts.insert(position, json.dumps(structured))
    value = result(*texts, structured=structured)
    wire = {
        "content": [{"type": "text", "text": t} for t in texts],
        "isError": False,
        "structuredContent": structured,
    }
    server = E2Server(tmp_path / "phase")
    assert hinted_keys(wire) == [_KEY]  # nosec B101 - pytest assertion
    assert server.handles(value) == ["j_666666666666"]  # nosec B101 - pytest assertion

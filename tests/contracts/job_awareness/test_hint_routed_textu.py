"""E2 g5 §9.2 S-2 (TEXT-U): TEXT on a tool without an output schema.

The routed adapter binds a native tool whose ``output_schema`` is None to the
``NO_STRUCTURE`` sentinel. Only the TEXT carrier may bind it. At render time
the result must have no ``structuredContent`` at all, otherwise the hint is
suppressed. In routed mode, TEXT on a tool that declares an output schema is
rejected at bind time (H-SC: such a text block does not reach the model).
``adapt`` and every adapter-off path stay byte-identical.
"""

import json
from dataclasses import replace
from threading import Event

import pytest
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import (
    META_KEY,
    NO_STRUCTURE,
    RoutedOutcome,
)
from binnacle.mcp.job_awareness_hint_identity import producer_identity
from tests.contracts.job_awareness.routed_support import (
    RoutedLab,
    routed_app,
    text_only,
    wire_call,
)
from tests.contracts.job_awareness.synthetic_app import SCHEMA, in_loop, original
from tests.contracts.job_awareness.test_hint_routed_wire import GOLDEN as MASTER
from tests.contracts.job_awareness.test_hint_schema_support import executed

_JOB = (
    "ja1_55555555555555555555555555555555:666666666666:"
    "g1_77777777777777777777777777777777"
)
_HINT = f"[Binnacle job reminder] {_JOB} unconfirmed"
_STAMP = (
    '"io.modelcontextprotocol/serverInfo":'
    '{"name":"I2-2 synthetic only","version":"synthetic"}'
)
_TEXT = '{"text":"Synthetic result","type":"text"}'
_HINT_TEXT = f'{{"text":"{_HINT}","type":"text"}}'
_LEGACY = "2025-06-18"
_MODERN = "2026-07-28"
#: TEXT-U wire bytes on this branch. "off" equals the bytes that a tool
#: without output schema produced before g5 (no adapter can hint it there).
GOLDEN_U = {
    (_LEGACY, "off"): f'{{"_meta":{{"existing":"kept"}},"content":[{_TEXT}],'
    '"isError":false}',
    (_LEGACY, "text"): f'{{"_meta":{{"existing":"kept"}},"content":[{_TEXT},'
    f'{_HINT_TEXT}],"isError":false}}',
    (_MODERN, "off"): f'{{"_meta":{{"existing":"kept",{_STAMP}}},'
    f'"content":[{_TEXT}],"isError":false,"resultType":"complete"}}',
    (_MODERN, "text"): f'{{"_meta":{{"existing":"kept",{_STAMP}}},'
    f'"content":[{_TEXT},{_HINT_TEXT}],"isError":false,"resultType":"complete"}}',
}


def unstructured_tool() -> Tool:
    return Tool(name="synthetic", parameters={}, output_schema=None)


# -- bind rules ---------------------------------------------------------------


def test_routed_text_on_a_structured_tool_is_rejected_at_bind():
    with RoutedLab(1) as lab:
        with pytest.raises(ValueError, match="TEXT"):
            lab.routed(enabled=True, carrier=HintCarrier.TEXT)
        with pytest.raises(ValueError, match="TEXT"):  # also while disabled
            lab.routed(enabled=False, carrier=HintCarrier.TEXT)
        meta = lab.routed(enabled=True, carrier=HintCarrier.META)
        with pytest.raises(ValueError, match="TEXT"):  # replace re-binds
            replace(meta, carrier=HintCarrier.TEXT)


def test_no_structure_binds_only_the_text_carrier():
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        assert adapter.schema is NO_STRUCTURE  # nosec B101 - pytest assertion
        assert adapter.identity == ("synthetic", None, NO_STRUCTURE)  # nosec B101 - pytest assertion
        with pytest.raises(ValueError, match="TEXT"):
            lab.routed(structured=False, enabled=True, carrier=HintCarrier.META)


def test_non_routed_bindings_are_unchanged():
    """``adapt`` keeps TEXT on structured tools and suppresses NO_STRUCTURE."""
    with RoutedLab(1) as lab:
        text = lab.adapter(enabled=True, carrier=HintCarrier.TEXT)
        assert text.schema is not None and text.schema is not NO_STRUCTURE  # nosec B101 - pytest assertion
        for carrier in (HintCarrier.META, HintCarrier.TEXT):
            plain = replace(
                lab.adapter(enabled=True, carrier=carrier), tool=unstructured_tool()
            )
            assert plain.schema is None and plain.identity is None  # nosec B101 - pytest assertion


def test_producer_identity_marks_no_structure_only_when_asked():
    tool = unstructured_tool()
    assert producer_identity(tool) is None  # nosec B101 - pytest assertion
    assert producer_identity(tool, unstructured=True) == (  # nosec B101 - pytest assertion
        "synthetic",
        None,
        NO_STRUCTURE,
    )
    structured = Tool(name="synthetic", parameters={}, output_schema=SCHEMA)
    marked = producer_identity(structured, unstructured=True)
    assert marked is not None and marked[2].startswith("{")  # nosec B101 - pytest assertion
    assert marked[2] != NO_STRUCTURE  # nosec B101 - pytest assertion


# -- render ---------------------------------------------------------------------


@in_loop
async def test_text_only_result_gets_one_reminder_block():
    with RoutedLab(4) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        for jobs in (lab.jobs[:1], lab.jobs[1:3]):
            value, outcome = await lab.call(adapter, lab.route(*jobs), text_only())
            assert type(outcome) is RoutedOutcome and outcome.result is not value  # nosec B101 - pytest assertion
            result = outcome.result
            assert result.structured_content is None  # nosec B101 - pytest assertion
            assert result.meta == {"existing": "kept"}  # nosec B101 - pytest assertion
            assert [c.text for c in result.content[:1]] == ["Synthetic result"]  # nosec B101 - pytest assertion
            assert len(result.content) == 2  # nosec B101 - pytest assertion
            assert outcome.rendered and set(outcome.rendered) <= set(jobs)  # nosec B101 - pytest assertion
            assert result.content[1].text == "[Binnacle job reminder] " + "; ".join(  # nosec B101 - pytest assertion
                f"{job.canonical_key} unconfirmed" for job in outcome.rendered
            )
            assert len(value.content) == 1 and value.structured_content is None  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "structured",
    [{"ok": True}, {}, {"note": "x"}],
    ids=["schema-shaped", "empty", "other"],
)
@in_loop
async def test_structured_content_at_runtime_suppresses(structured):
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        value = ToolResult(
            content=[TextContent(type="text", text="Synthetic result")],
            structured_content=structured,
        )
        _, outcome = await lab.call(adapter, lab.route(lab.job), value)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@in_loop
async def test_adapt_never_hints_a_no_structure_tool():
    """The non-routed path stays as before g5: a schema-less tool is unknown."""
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        value = text_only()
        receipt = executed(value, adapter.bound_tool)
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - pytest assertion
        # Defense in depth: the render core refuses NO_STRUCTURE outside routing.
        assert adapter._adapt(value, Event()) is value  # nosec B101 - pytest assertion


@in_loop
async def test_carrier_changed_after_bind_suppresses():
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        adapter.carrier = HintCarrier.META  # mutation after the bind check
        value, outcome = await lab.call(adapter, lab.route(lab.job), text_only())
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert META_KEY not in (value.meta or {})  # nosec B101 - pytest assertion


@in_loop
async def test_a_tool_that_gained_a_schema_is_another_producer():
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        object.__setattr__(adapter.bound_tool, "output_schema", SCHEMA)
        value, outcome = await lab.call(adapter, lab.route(lab.job), text_only())
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@in_loop
async def test_growth_cap_applies_to_text_u():
    with RoutedLab(2) as lab:
        adapter = lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT)
        big = ToolResult(content=[TextContent(type="text", text="x" * 262000)])
        _, outcome = await lab.call(adapter, lab.route(*lab.jobs), big)
        assert outcome.result is big and outcome.rendered == ()  # nosec B101 - pytest assertion


# -- wire bytes -----------------------------------------------------------------


def test_off_bytes_differ_from_structured_master_only_by_structure():
    for protocol in (_LEGACY, _MODERN):
        structured = json.loads(MASTER[(protocol, "off")])
        structured.pop("structuredContent")
        assert json.loads(GOLDEN_U[(protocol, "off")]) == structured  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", [_LEGACY, _MODERN])
@pytest.mark.parametrize("case", ["off", "text", "adapt"])
@in_loop
async def test_text_u_wire_bytes(protocol, case):
    """``adapt`` = the non-routed path, which never hints NO_STRUCTURE."""
    with RoutedLab(1) as lab:
        route = lab.route(lab.job)
        adapter = lab.routed(
            structured=False, enabled=case != "off", carrier=HintCarrier.TEXT
        )
        app, outcomes = routed_app(
            adapter,
            text_only(),
            route=None if case == "adapt" else (lambda: route),
            schema=None,
        )
        _, raw = await wire_call(app, protocol)
        expected = GOLDEN_U[(protocol, "text" if case == "text" else "off")]
        assert raw.decode() == expected  # nosec B101 - pytest assertion
        assert (_JOB.encode() in raw) is (case == "text")  # nosec B101 - pytest assertion
        assert b"structuredContent" not in raw  # nosec B101 - pytest assertion
        if case != "adapt":
            (outcome,) = outcomes
            assert outcome.rendered == ((lab.job,) if case == "text" else ())  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", [_LEGACY, _MODERN])
@in_loop
async def test_structured_adapt_bytes_still_equal_master(protocol):
    """TEXT stays legal for ``adapt`` on a structured tool: master bytes."""
    with RoutedLab(1) as lab:
        app, _ = routed_app(
            lab.adapter(enabled=True, carrier=HintCarrier.TEXT), original()
        )
        _, raw = await wire_call(app, protocol)
        assert raw.decode() == MASTER[(protocol, "text")]  # nosec B101 - pytest assertion

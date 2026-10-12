"""E2 g6 §9.2 S-1 (STRUCT): bind rule, insertion, re-validation and mirrors.

STRUCT binds only in routed mode, only when the bound tool's closed output
schema declares the optional ``job_awareness_hint`` string exactly
(``maxLength`` 512, not required, no description). The hint is inserted into
the private structured-content copy and re-validated with the metered
``Schema``. Exactly one JSON mirror text block is re-serialized; two mirrors
or an ambiguous mirror suppress; plain tool text is never rewritten. Every
failure returns the original result object with no rendered job.
"""

import json
from dataclasses import replace
from enum import Enum
from threading import Event
from typing import Any, cast

import pytest
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import (
    HintCarrier,
    JobRef,
    RenderedHint,
    Scope,
)
from binnacle.mcp.job_awareness_hint import (
    HINT_FIELD,
    META_KEY,
    HintAdapter,
    RoutedOutcome,
)
from binnacle.mcp.job_awareness_hint_struct import MIRROR_FORMATS
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import SCHEMA, in_loop, original
from tests.contracts.job_awareness.test_hint_schema_support import executed

FIELD = {"type": "string", "maxLength": 512}
STRUCT_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, HINT_FIELD: FIELD},
    "required": ["ok"],
    "additionalProperties": False,
}
STRUCTURED = {"ok": True}


def struct(lab: RoutedLab, **options: Any) -> HintAdapter:
    options = dict[str, Any](enabled=True, carrier=HintCarrier.STRUCT) | options
    options.setdefault("schema", STRUCT_SCHEMA)
    return lab.routed(**options)


def result(*texts: str, structured: Any = STRUCTURED) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=t) for t in texts],
        structured_content=structured,
    )


def reminder(outcome: RoutedOutcome) -> str:
    return "[Binnacle job reminder] " + "; ".join(
        f"{cast(JobRef, job).canonical_key} unconfirmed" for job in outcome.rendered
    )


def untouched(lab: RoutedLab) -> bool:
    return lab.catalog_reads == lab.queries == 0


def with_schema(**changes: object) -> dict[str, object]:
    return {k: v for k, v in (STRUCT_SCHEMA | changes).items() if v is not None}


def with_field(field: object) -> dict[str, object]:
    return with_schema(properties={"ok": {"type": "boolean"}, HINT_FIELD: field})


# -- bind -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [
        SCHEMA,
        with_schema(required=["ok", HINT_FIELD]),
        with_schema(additionalProperties=True),
        with_schema(additionalProperties=None),
        with_schema(type=None),
        with_schema(type=["object"]),
        with_field({"type": "string"}),
        with_field({"type": "string", "maxLength": 513}),
        with_field({"type": "string", "maxLength": 511}),
        with_field({"type": "string", "maxLength": 512.0}),
        with_field({"type": ["string"], "maxLength": 512}),
        with_field({"type": ["string", "null"], "maxLength": 512}),
        with_field({"type": "string", "maxLength": 512, "minLength": 1}),
        with_field({"type": "string", "maxLength": 512, "description": "x"}),
        with_schema(description="has a description"),
        {"type": "object", "anyOf": [STRUCT_SCHEMA]},
    ],
    ids=[
        "no-field",
        "required",
        "open",
        "additional-absent",
        "type-absent",
        "type-list",
        "no-max",
        "max-513",
        "max-511",
        "max-float",
        "field-type-list",
        "nullable",
        "extra-keyword",
        "field-description",
        "schema-description",
        "nested-only",
    ],
)
def test_struct_bind_requires_the_declared_field_exactly(schema):
    with RoutedLab(1) as lab:
        for enabled in (True, False):  # the bind fails even when disabled
            with pytest.raises(ValueError, match="STRUCT"):
                struct(lab, schema=schema, enabled=enabled)


def test_struct_binds_a_declared_field_and_snapshots_it():
    with RoutedLab(1) as lab:
        adapter = struct(lab)
        assert adapter.struct_bound is True  # nosec B101 - pytest assertion
        assert adapter.identity is not None and HINT_FIELD in adapter.identity[2]  # nosec B101 - pytest assertion
        assert struct(lab, enabled=False).struct_bound is True  # nosec B101 - pytest assertion
        meta = struct(lab, carrier=HintCarrier.META)  # META stays legal here
        assert meta.struct_bound is False  # nosec B101 - pytest assertion
        with pytest.raises(ValueError, match="STRUCT"):  # replace re-binds
            replace(
                meta,
                carrier=HintCarrier.STRUCT,
                tool=Tool(name="x", parameters={}, output_schema=SCHEMA),
            )


def test_struct_on_a_tool_without_schema_is_rejected():
    with RoutedLab(1) as lab, pytest.raises(ValueError, match="STRUCT"):
        lab.routed(structured=False, enabled=True, carrier=HintCarrier.STRUCT)


def test_struct_with_an_unknown_producer_is_rejected():
    with RoutedLab(1) as lab:
        adapter = struct(lab)
        tool = Tool(
            name="synthetic",
            version="v" * 129,
            parameters={},
            output_schema=STRUCT_SCHEMA,
        )
        with pytest.raises(ValueError, match="producer"):
            replace(adapter, tool=tool)


def test_struct_binds_only_in_routed_mode():
    with RoutedLab(1) as lab:
        routed = struct(lab)
        plain = replace(routed.bindings, route_type=None, candidate_type=None)
        with pytest.raises(ValueError, match="routed"):
            replace(routed, bindings=plain)
        # Plain bindings keep META and TEXT exactly as before.
        for carrier in (HintCarrier.META, HintCarrier.TEXT):
            adapter = replace(routed, bindings=plain, carrier=carrier)
            assert adapter.struct_bound is False and adapter.schema is not None  # nosec B101 - pytest assertion


def test_bindings_validate_the_struct_member():
    alien = Enum("AlienCarrier", {"STRUCT": "STRUCT"})
    with RoutedLab(1) as lab:
        bindings = struct(lab).bindings
        assert bindings.struct is HintCarrier.STRUCT  # nosec B101 - pytest assertion
        assert replace(bindings, struct=None).struct is None  # nosec B101 - pytest assertion
        for value in (
            "STRUCT",
            HintCarrier.META,
            HintCarrier.TEXT,
            Scope.READ,
            alien.STRUCT,
        ):
            with pytest.raises(ValueError, match="invalid hint bindings"):
                replace(bindings, struct=value)


@in_loop
async def test_struct_carrier_without_a_struct_binding_suppresses():
    with RoutedLab(1) as lab:
        meta = struct(lab, carrier=HintCarrier.META)
        adapter = replace(
            meta,
            bindings=replace(meta.bindings, struct=None),
            carrier=HintCarrier.STRUCT,
        )
        value, outcome = await lab.call(adapter, lab.route(lab.job))
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


# -- insertion and mirrors ------------------------------------------------------


@in_loop
async def test_plain_text_result_gets_only_the_structured_field():
    with RoutedLab(4) as lab:
        adapter = struct(lab)
        for jobs in (lab.jobs[:1], lab.jobs[1:3]):
            value, outcome = await lab.call(adapter, lab.route(*jobs))
            assert outcome.result is not value and outcome.rendered  # nosec B101 - pytest assertion
            assert set(outcome.rendered) <= set(jobs)  # nosec B101 - pytest assertion
            hinted = outcome.result
            assert hinted.structured_content == {
                "ok": True,
                HINT_FIELD: reminder(outcome),
            }  # nosec B101 - pytest assertion
            assert [c.text for c in hinted.content] == ["Synthetic result"]  # nosec B101 - pytest assertion
            assert hinted.meta == {"existing": "kept"}  # nosec B101 - pytest assertion
            assert (
                value.structured_content == STRUCTURED
            )  # the original is untouched  # nosec B101 - pytest assertion


@pytest.mark.parametrize("render", MIRROR_FORMATS, ids=["stdlib", "compact"])
@in_loop
async def test_one_mirror_is_updated_in_its_own_format(render):
    with RoutedLab(1) as lab:
        value = result("before", render(STRUCTURED), "after")
        _, outcome = await lab.call(struct(lab), lab.route(lab.job), value)
        new = {"ok": True, HINT_FIELD: reminder(outcome)}
        assert outcome.result.structured_content == new  # nosec B101 - pytest assertion
        texts = [c.text for c in outcome.result.content]
        assert texts == ["before", render(new), "after"]  # nosec B101 - pytest assertion
        assert [c.text for c in value.content][1] == render(STRUCTURED)  # nosec B101 - pytest assertion


@in_loop
async def test_unicode_mirror_keeps_its_format():
    with RoutedLab(1) as lab:
        schema = with_schema(properties={"ok": {"type": "string"}, HINT_FIELD: FIELD})
        for render in MIRROR_FORMATS:
            body = {"ok": "é☃"}
            value = result(render(body), structured=body)
            _, outcome = await lab.call(
                struct(lab, schema=schema), lab.route(lab.job), value
            )
            new = body | {HINT_FIELD: reminder(outcome)}
            assert [c.text for c in outcome.result.content] == [render(new)]  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "texts",
    [
        (json.dumps(STRUCTURED), json.dumps(STRUCTURED)),
        (
            json.dumps(STRUCTURED),
            "plain",
            json.dumps(STRUCTURED, separators=(",", ":")),
        ),
        (json.dumps(STRUCTURED, indent=2),),
        (" " + json.dumps(STRUCTURED),),
        ('{"ok":1}',),
    ],
    ids=["two-same", "two-formats", "indented", "leading-space", "equal-value"],
)
@in_loop
async def test_two_or_ambiguous_mirrors_suppress(texts):
    with RoutedLab(1) as lab:
        value = result(*texts)
        _, outcome = await lab.call(struct(lab), lab.route(lab.job), value)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "text",
    [
        '{"ok": false}',
        '{"other": 1}',
        '{"ok": true} trailing',
        "{broken",
        "[true]",
        '{"a":' + "[" * 60000,
        "",
    ],
    ids=["other-value", "other-key", "trailing", "broken", "array", "deep", "empty"],
)
@in_loop
async def test_other_text_is_plain_and_never_rewritten(text):
    with RoutedLab(1) as lab:
        value = result(text)
        _, outcome = await lab.call(struct(lab), lab.route(lab.job), value)
        assert outcome.rendered == (lab.job,)  # nosec B101 - pytest assertion
        assert [c.text for c in outcome.result.content] == [text]  # nosec B101 - pytest assertion
        assert outcome.result.structured_content[HINT_FIELD] == reminder(outcome)  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "structured",
    [None, {"ok": True, HINT_FIELD: "already"}, {"ok": "x"}, {"ok": True, "x": 1}],
    ids=["none", "field-present", "invalid", "extra"],
)
@in_loop
async def test_structured_content_rules_suppress(structured):
    with RoutedLab(1) as lab:
        value = result("Synthetic result", structured=structured)
        _, outcome = await lab.call(struct(lab), lab.route(lab.job), value)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@in_loop
async def test_revalidation_after_insertion_suppresses():
    """The bind rule holds, but another keyword rejects the inserted value."""
    with RoutedLab(1) as lab:
        tight = {"properties": {HINT_FIELD: {"type": "string", "maxLength": 3}}}
        adapter = struct(lab, schema=with_schema(anyOf=[tight]))
        value, outcome = await lab.call(adapter, lab.route(lab.job))
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert adapter.last_meter is not None and adapter.last_meter.predicates  # nosec B101 - pytest assertion


# -- caps and failures ----------------------------------------------------------


def fixed_render(text: str):
    def render(candidates, carrier):
        return RenderedHint(carrier, text, len(text.encode("utf-8")))

    return render


@pytest.mark.parametrize(
    ("hint", "mirror", "hinted"),
    [
        ('"' * 512, False, False),  # sc growth > 1024 by escaping alone
        ("a" * 450, True, True),  # field + mirror within 1024
        ("a" * 512, True, False),  # field + mirror over 1024
        ("a" * 512, False, True),
    ],
)
@in_loop
async def test_growth_cap_counts_field_and_mirror(hint, mirror, hinted):
    with RoutedLab(1) as lab:
        adapter = struct(lab)
        adapter = replace(
            adapter, bindings=replace(adapter.bindings, render=fixed_render(hint))
        )
        texts = (json.dumps(STRUCTURED),) if mirror else ("Synthetic result",)
        value, outcome = await lab.call(adapter, lab.route(lab.job), result(*texts))
        assert (outcome.result is not value) is hinted  # nosec B101 - pytest assertion
        if hinted:
            assert outcome.result.structured_content[HINT_FIELD] == hint  # nosec B101 - pytest assertion


@in_loop
async def test_result_near_the_byte_limit_suppresses():
    with RoutedLab(1) as lab:
        big = result("x" * 262000)
        _, outcome = await lab.call(struct(lab), lab.route(lab.job), big)
        assert outcome.result is big and outcome.rendered == ()  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "render",
    [
        lambda candidates, carrier: None,
        lambda candidates, carrier: RenderedHint(HintCarrier.META, "x", 1),
        lambda candidates, carrier: object(),
    ],
    ids=["none", "other-carrier", "other-type"],
)
@in_loop
async def test_render_failures_suppress(render):
    with RoutedLab(1) as lab:
        adapter = struct(lab)
        adapter = replace(adapter, bindings=replace(adapter.bindings, render=render))
        value, outcome = await lab.call(adapter, lab.route(lab.job))
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@in_loop
async def test_changes_after_bind_suppress():
    with RoutedLab(1) as lab:
        cases = []
        adapter = struct(lab)
        adapter.carrier = HintCarrier.META  # STRUCT-bound, now META
        cases.append(adapter)
        adapter = struct(lab, carrier=HintCarrier.META)
        adapter.carrier = HintCarrier.STRUCT  # META-bound, now STRUCT
        cases.append(adapter)
        adapter = struct(lab)
        adapter.struct_bound = False  # snapshot cleared
        cases.append(adapter)
        adapter = struct(lab)
        object.__setattr__(adapter.bound_tool, "output_schema", SCHEMA)
        cases.append(adapter)  # another producer: the field is gone
        for adapter in cases:
            value, outcome = await lab.call(adapter, lab.route(lab.job))
            assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
            assert META_KEY not in (value.meta or {})  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion


@in_loop
async def test_adapt_never_hints_a_struct_binding():
    with RoutedLab(1) as lab:
        adapter = struct(lab)
        value = original()
        assert (
            await adapter.adapt(value, execution=executed(value, adapter.bound_tool))
            is value
        )  # nosec B101 - pytest assertion
        assert adapter.last_meter is None and untouched(lab)  # nosec B101 - pytest assertion
        assert (
            adapter._adapt(value, Event()) is value
        )  # render core refuses too  # nosec B101 - pytest assertion

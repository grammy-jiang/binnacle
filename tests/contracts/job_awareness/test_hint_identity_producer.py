"""Q0-SEC-03 class: the producer is the resolved native Tool object, never strings.

The adapter proceeds only when the resolved producing Tool is the bound object
with an exact native type and still has the bound name, the bound version and
a canonical-JSON-identical output schema (CHATGPT-POST-01/02). An unavailable,
foreign, malformed or hostile producer returns the original result before any
worker admission, observation read or receipt query.
"""

from copy import deepcopy
from dataclasses import replace

import pytest
from fastmcp.tools.base import Tool

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop, original
from tests.contracts.job_awareness.test_hint_version_identity import NoWorkers

BETA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
    "required": ["ok", "n"],
    "additionalProperties": False,
}


def native(version=None, schema=SCHEMA, name="synthetic"):
    return Tool(name=name, version=version, parameters={}, output_schema=schema)


def bound_adapter(lab, version=None, *, workers=True, carrier=HintCarrier.META):
    adapter = replace(lab.adapter(enabled=True, carrier=carrier), tool=native(version))
    return adapter if workers else replace(adapter, workers=NoWorkers())


async def assert_suppressed(lab, adapter, value, admitted=False, **producer):
    before = value.model_dump_json()
    assert await HintAdapter.adapt(adapter, value, **producer) is value  # nosec B101 - pytest assertion
    assert value.model_dump_json() == before  # nosec B101 - pytest assertion
    assert (adapter.last_meter is not None) is admitted  # nosec B101 - worker admission
    assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


class Duck:
    """Carries the bound identity as plain attributes; it is not a native Tool."""

    name: str = "synthetic"
    version: str | None = None
    output_schema: dict[str, object] = SCHEMA
    parameters: dict[str, object] = {}  # noqa: RUF012 - inert test fixture


@pytest.mark.parametrize(
    "producer",
    [{}, {"tool": None}, {"tool": "synthetic"}, {"tool": ("synthetic", None)}]
    + [{"tool": Duck()}, {"tool": {"name": "synthetic", "output_schema": SCHEMA}}],
    ids=["omitted", "none", "name_string", "name_version_tuple", "duck", "mapping"],
)
@in_loop
async def test_unavailable_or_non_tool_producer_fails_closed(producer):
    with Lab() as lab:
        await assert_suppressed(
            lab, bound_adapter(lab, workers=False), original(), **producer
        )


@pytest.mark.parametrize("version", [None, "1"])
@pytest.mark.parametrize(
    "schema",
    [
        BETA,
        None,
        {"$ref": "https://invalid"},
        {**SCHEMA, "title": "synthetic"},
        {**SCHEMA, "additionalProperties": True},
        {k: v for k, v in SCHEMA.items() if k != "additionalProperties"},
        {**SCHEMA, "type": ["object"]},
        {**SCHEMA, "properties": {"ok": {"type": ["boolean"]}}},
    ],
    ids=[
        "beta",
        "none",
        "unsupported",
        "extra_title",
        "open_object",
        "missing_closed_rule",
        "type_list_spelling",
        "nested_type_list_spelling",
    ],
)
@in_loop
async def test_same_name_and_version_with_other_schema_suppresses(version, schema):
    """Exact canonical schema equality, not semantic equivalence or validation."""
    with Lab() as lab:
        adapter = bound_adapter(lab, version, workers=False)
        producer = native(version, schema)
        await assert_suppressed(lab, adapter, original(), tool=producer)


@pytest.mark.parametrize(
    "bound_version,producer_version",
    [("1", "2"), (None, "1"), ("1", None), ("1", "1.0"), ("1", "x" * 129)],
)
@in_loop
async def test_other_name_or_version_with_same_schema_suppresses(
    bound_version, producer_version
):
    with Lab() as lab:
        adapter = bound_adapter(lab, bound_version, workers=False)
        await assert_suppressed(lab, adapter, original(), tool=native(producer_version))
        for name in ("beta", "Synthetic", "synthetic ", "x" * 129):
            producer = Tool.model_construct(
                name=name, version=bound_version, parameters={}, output_schema=SCHEMA
            )
            await assert_suppressed(lab, adapter, original(), tool=producer)


@pytest.mark.parametrize("missing", ["version", "name", "output_schema"])
@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_missing_producer_field_is_unknown(missing, version):
    """A producer without a version field is unknown, even for unversioned binding."""
    with Lab() as lab:
        adapter = bound_adapter(lab, version, workers=False)
        producer = native(version)
        object.__getattribute__(producer, "__dict__").pop(missing)
        await assert_suppressed(lab, adapter, original(), tool=producer)


@in_loop
async def test_hostile_producer_fields_run_no_callbacks():
    calls: list[str] = []

    class Text(str):
        def __eq__(self, other):
            calls.append("eq")
            return True

        def __ne__(self, other):
            calls.append("ne")
            return False

        __hash__ = str.__hash__

    class Mapping(dict):
        def __eq__(self, other):
            calls.append("schema eq")
            return True

        __hash__ = None

        def items(self):
            calls.append("items")
            return super().items()

    with Lab() as lab:
        adapter = bound_adapter(lab, "1", workers=False)
        hostile = [
            {"name": Text("synthetic")},
            {"version": Text("1")},
            {"output_schema": Mapping(SCHEMA)},
            {"output_schema": {**SCHEMA, "properties": Mapping(SCHEMA["properties"])}},
            {"output_schema": {Text("type"): "object"}},
        ]
        for fields in hostile:
            producer = Tool.model_construct(
                **{
                    "name": "synthetic",
                    "version": "1",
                    "parameters": {},
                    "output_schema": SCHEMA,
                    **fields,
                }
            )
            await assert_suppressed(lab, adapter, original(), tool=producer)
        producer = native("1")
        backing = object.__getattribute__(producer, "__dict__")
        backing[Text("version")] = backing.pop("version")
        await assert_suppressed(lab, adapter, original(), tool=producer)
        assert calls == []  # nosec B101 - pytest assertion


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_control_bound_object_with_canonically_equal_schema_hints(
    carrier, version
):
    """Positive control: the bound object itself keeps exactly one hint, also
    when its schema is a canonically equal spelling (other key order, deep copy).

    CHATGPT-POST-01 (Supervisor decision): this control previously also passed
    a distinct Tool object with an equal triple. Value equality is no longer
    provenance; that case now suppresses in test_hint_identity_provenance.py.
    """
    reordered = {k: deepcopy(SCHEMA[k]) for k in reversed(list(SCHEMA))}
    with Lab() as lab:
        for count, schema in enumerate((SCHEMA, reordered), 1):
            adapter = replace(
                bound_adapter(lab, version, carrier=carrier),
                tool=native(version, schema),
            )
            value = original()
            result = await HintAdapter.adapt(adapter, value, tool=adapter.tool)
            assert result is not value  # nosec B101 - pytest assertion
            text = (
                result.meta[META_KEY]
                if carrier is HintCarrier.META
                else result.content[-1].text
            )
            assert "unconfirmed" in text  # nosec B101 - pytest assertion
            assert lab.catalog_reads == lab.queries == count  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_resolved_bound_tool_still_requires_a_valid_result_and_opt_in():
    with Lab() as lab:
        adapter = bound_adapter(lab, "1")
        value = original()
        value.structured_content = {"ok": True, "n": 1}
        await assert_suppressed(lab, adapter, value, True, tool=adapter.tool)
        adapter = bound_adapter(lab, "1", workers=False)
        adapter.enabled = False
        await assert_suppressed(lab, adapter, original(), tool=adapter.tool)


def test_adapter_has_no_string_identity_entry():
    """Caller-supplied name/version strings are no longer an identity input."""
    import inspect

    params = inspect.signature(HintAdapter.adapt).parameters
    assert "tool" in params  # nosec B101 - pytest assertion
    assert not {"tool_name", "tool_version"} & set(params)  # nosec B101 - pytest assertion

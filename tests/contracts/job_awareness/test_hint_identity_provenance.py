"""CHATGPT-POST-01/02: producer provenance is object identity plus exact type.

Ported from the independent post-release review (OpenAI, REVISE_REQUIRED at
6b50ba5). Equal (name, version, canonical output schema) did not prove that
the result came from the bound registration: FastMCP 4.1.0 ran a different
handler through ToolInjectionMiddleware, a parent local tool that shadows an
unnamespaced mounted child, and a rename transform, and the adapter still read
observations and queried receipts. A hostile native subclass could also report
an effective output schema that differs from its backing field map.

Supervisor decision (final): the adapter proceeds only when the resolved tool
IS the bound registered tool object and its type is exactly a reviewed native
FastMCP class. Every other producer returns the original result with zero
worker admissions, observation reads and receipt queries.
"""

import json

import pytest
from fastmcp import FastMCP
from fastmcp.server.middleware.tool_injection import ToolInjectionMiddleware
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.base import Tool
from fastmcp.tools.function_tool import FunctionTool
from fastmcp.tools.tool_transform import ToolTransformConfig

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import HintAdapter, producer_identity
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop, original
from tests.contracts.job_awareness.test_hint_identity_collisions import (
    BETA,
    _run,
    _tool,
)
from tests.contracts.job_awareness.test_hint_identity_producer import (
    assert_suppressed,
    bound_adapter,
    native,
)

TOPOLOGIES = [
    "injected_same_triple",
    "local_shadows_unnamespaced_child",
    "rename_transform_same_schema",
    "mounted_child_wrapper",
    "hostile_subclass_injected",
]


def hostile_copy(tool, calls, schema=BETA):
    """The reviewer's hostile subclass: an overridden effective output_schema.

    The backing field map still holds the bound schema, so a field-map identity
    equals the bound identity while FastMCP enforces ``schema``.
    """

    class Hostile(type(tool)):
        def __getattribute__(self, key):
            if key == "output_schema":
                calls.append(key)
                return schema
            return super().__getattribute__(key)

    return Hostile.model_construct(**object.__getattribute__(tool, "__dict__"))


def _compose(app, topology, ran, calls):
    """Return (bound registered tool, actually executed handler tag).

    Every producer has the bound name, version "1" and the bound SCHEMA
    (except the hostile subclass's overridden effective schema) and a different
    handler, so value identity cannot tell the producers apart.
    """
    if topology == "local_shadows_unnamespaced_child":
        child = FastMCP("POST-01 child")
        bound = child.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "C"))
        app.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "LOCAL"))
        app.mount(child)
        return bound, "LOCAL"
    if topology == "mounted_child_wrapper":
        # FastMCP serves a new FastMCPProviderTool wrapper on every lookup.
        child = FastMCP("POST-01 child")
        bound = child.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "C"))
        app.mount(child)
        return bound, "C"
    bound = app.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "BOUND"))
    if topology == "rename_transform_same_schema":
        app.add_tool(_tool("beta", "1", SCHEMA, {"ok": True}, ran, "TRANSFORMED_BETA"))
        app.add_transform(
            ToolTransform({"beta": ToolTransformConfig(name="synthetic")})
        )
        return bound, "TRANSFORMED_BETA"
    tag = "HOSTILE" if topology == "hostile_subclass_injected" else "FOREIGN"
    foreign = _tool("synthetic", "1", SCHEMA, {"ok": True}, ran, tag)
    if tag == "HOSTILE":
        foreign = hostile_copy(foreign, calls)
        assert foreign.output_schema != bound.output_schema  # nosec B101 - repro
        calls.clear()
    assert foreign is not bound  # nosec B101 - reviewer precondition
    app.add_middleware(ToolInjectionMiddleware([foreign]))
    return bound, tag


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize("topology", TOPOLOGIES)
@in_loop
async def test_post_01_02_foreign_producer_same_triple_suppresses(
    protocol, carrier, topology
):
    """Native routing ran another handler: no hint, reads or queries."""
    with Lab() as lab:
        app = FastMCP("POST-01 synthetic only", version="synthetic")
        ran: list[str] = []
        calls: list[str] = []
        bound, producer = _compose(app, topology, ran, calls)
        wire, error, seen, middleware, adapter = await _run(
            lab, app, bound, "synthetic", protocol, carrier
        )
        assert ran == [producer]  # nosec B101 - the foreign handler executed
        if topology == "hostile_subclass_injected":
            assert error is not None  # nosec B101 - FastMCP enforces BETA
        else:
            assert error is None  # nosec B101 - pytest assertion
            assert json.loads(wire)["result"]["isError"] is False  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (  # nosec B101 - pytest assertion
            False,
            0,
            0,
        )
        assert seen[0] is middleware.adapted[0]  # nosec B101 - original unchanged
        assert adapter.last_meter is None  # nosec B101 - no worker admitted
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_value_equal_distinct_native_tool_suppresses(carrier, version):
    """A distinct exact-native Tool with the bound triple is not the producer."""
    with Lab() as lab:
        adapter = bound_adapter(lab, version, workers=False, carrier=carrier)
        producer = native(version)
        assert producer_identity(producer) == adapter.identity  # nosec B101 - repro
        await assert_suppressed(lab, adapter, original(), tool=producer)


@pytest.mark.parametrize("base", [Tool, FunctionTool])
@pytest.mark.parametrize("override", [False, True])
@in_loop
async def test_post_02_subclass_of_native_tool_suppresses_without_callbacks(
    base, override
):
    """Any subclass is unreviewed: no field read, getter callback or query."""
    calls: list[str] = []
    with Lab() as lab:
        adapter = bound_adapter(lab, "1", workers=False)
        source = (
            native("1")
            if base is Tool
            else _tool("synthetic", "1", SCHEMA, {"ok": True}, [], "S")
        )
        if override:
            producer = hostile_copy(source, calls, schema=SCHEMA)
        else:

            class Plain(base):
                pass

            producer = Plain.model_construct(
                **object.__getattribute__(source, "__dict__")
            )
        assert producer_identity(producer) is None  # nosec B101 - unreviewed type
        await assert_suppressed(lab, adapter, original(), tool=producer)
        assert calls == []  # nosec B101 - no overridden accessor ran


@in_loop
async def test_post_02_hostile_subclass_cannot_be_bound():
    """Binding reads nothing from a non-native type, so no getter runs."""
    calls: list[str] = []
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        source = _tool("synthetic", "1", SCHEMA, {"ok": True}, [], "S")
        wrappers = [
            hostile_copy(source, calls),
            Tool.from_tool(source, output_schema=SCHEMA),
        ]
        for tool in wrappers:
            with pytest.raises(ValueError, match="explicit native tool binding"):
                HintAdapter(
                    bindings=adapter.bindings,
                    grant=adapter.grant,
                    jobs=adapter.jobs,
                    tool=tool,
                    workers=adapter.workers,
                )
        assert calls == []  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_bound_object_mutated_after_binding_suppresses():
    """Identity is necessary, not sufficient: the triple must still match."""
    with Lab() as lab:
        adapter = bound_adapter(lab, "1", workers=False)
        backing = object.__getattribute__(adapter.tool, "__dict__")
        backing["output_schema"] = BETA
        await assert_suppressed(lab, adapter, original(), tool=adapter.tool)
        backing["output_schema"] = SCHEMA
        backing["version"] = "2"
        await assert_suppressed(lab, adapter, original(), tool=adapter.tool)


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@in_loop
async def test_control_registered_exact_native_object_still_hints(protocol, carrier):
    """Positive control: the registered exact-native object itself hints once."""
    with Lab() as lab:
        app = FastMCP("POST-01 control", version="synthetic")
        ran: list[str] = []
        bound = app.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "B"))
        assert type(bound) is FunctionTool  # nosec B101 - reviewed native class
        wire, error, seen, middleware, _ = await _run(
            lab, app, bound, "synthetic", protocol, carrier
        )
        assert (ran, error) == (["B"], None)  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (  # nosec B101 - pytest assertion
            True,
            1,
            1,
        )
        assert middleware.adapted[0] is not seen[0]  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion

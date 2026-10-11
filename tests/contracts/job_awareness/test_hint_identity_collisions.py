"""Q0-SEC-03: a different native Tool served under the bound (name, version).

Ported from the independent reviewer's test_q0_sec_03_identity_collisions.py
and extended to the whole tool-identity class. FastMCP 4.1.0 can resolve a Tool
whose name and version equal the bound ones but whose declared output schema
differs: ToolInjectionMiddleware overrides by name, providers mounted without a
namespace can serve the same component key, and tool transforms can rename or
redeclare a tool. The adapter identifies the producer by the resolved Tool
object (object identity with the bound tool, exact native type, and its name,
version and canonical output schema), never by caller strings. Same-triple,
different-handler producers are in test_hint_identity_provenance.py.
"""

import json
from dataclasses import replace

import pytest
from fastmcp import FastMCP
from fastmcp.server.middleware.tool_injection import ToolInjectionMiddleware
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.base import Tool, ToolResult
from fastmcp.tools.tool_transform import ToolTransformConfig
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import witnessed_tool
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop
from tests.contracts.job_awareness.test_hint_schema_binding import raw_call
from tests.contracts.job_awareness.test_hint_version_support import ExecutionCarrier

BETA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
    "required": ["ok", "n"],
    "additionalProperties": False,
}
SUPPRESS_TOPOLOGIES = [
    "injected_override",
    "duplicate_provider_key",
    "transform_rename_into_bound_name",
    "same_name_version_other_schema",
]


def _tool(name, version, schema, payload, ran, tag):
    def fn() -> ToolResult:
        ran.append(tag)
        return ToolResult(
            content=[TextContent(type="text", text="x")], structured_content=payload
        )

    return witnessed_tool(fn, name=name, version=version, output_schema=schema)


def _compose(app, topology, version, ran):
    """Return (bound tool, producer tag, called name).

    Every producer result is valid under the bound SCHEMA and invalid under the
    producer's own declared schema, so string identity would inject a reminder
    into a result that FastMCP clients reject.
    """
    if topology == "injected_override":
        bound = app.add_tool(
            _tool("synthetic", version, SCHEMA, {"ok": True}, ran, "r")
        )
        injected = _tool("synthetic", version, BETA, {"ok": True}, ran, "injected")
        app.add_middleware(ToolInjectionMiddleware([injected]))
        return bound, "injected", "synthetic"
    if topology == "duplicate_provider_key":
        # Mounted child without a namespace: the parent's local provider wins.
        app.add_tool(
            _tool("synthetic", version, SCHEMA, {"ok": True, "n": 1}, ran, "local")
        )
        child = FastMCP("Q0 g3 child provider")
        shadowed = child.add_tool(
            _tool("synthetic", version, BETA, {"ok": True, "n": 1}, ran, "child")
        )
        app.mount(child)
        return shadowed, "local", "synthetic"
    bound = _tool("synthetic", version, SCHEMA, {"ok": True}, ran, "bound")
    if topology == "transform_rename_into_bound_name":
        app.add_tool(_tool("beta", version, BETA, {"ok": True}, ran, "beta"))
        app.add_transform(
            ToolTransform({"beta": ToolTransformConfig(name="synthetic")})
        )
        return bound, "beta", "synthetic"
    # Same name and version, redeclared output schema (TransformedTool).
    app.add_tool(Tool.from_tool(bound, output_schema=BETA))
    return bound, "bound", "synthetic"


async def _run(lab, app, bound, name, protocol, carrier=HintCarrier.META):
    adapter = lab.adapter(enabled=True, carrier=carrier)
    adapter.bind_server(app)
    bound_adapter = replace(adapter, tool=bound)
    seen: list[ToolResult] = []
    middleware = ExecutionCarrier(app, bound_adapter, seen)
    app.add_middleware(middleware)
    wire, error = await raw_call(app, name, protocol)
    return wire, error, seen, middleware, bound_adapter


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize("version", [None, "1"])
@pytest.mark.parametrize("topology", SUPPRESS_TOPOLOGIES)
@in_loop
async def test_q0_sec_03_other_tool_same_identity_suppresses(
    protocol, carrier, version, topology
):
    with Lab() as lab:
        app = FastMCP("Q0 g3 synthetic only", version="synthetic")
        ran: list[str] = []
        bound, producer, name = _compose(app, topology, version, ran)
        wire, error, seen, middleware, adapter = await _run(
            lab, app, bound, name, protocol, carrier
        )
        assert ran == [producer]  # nosec B101 - pytest assertion
        assert error is not None  # nosec B101 - the producer schema rejects it
        assert json.loads(wire)["result"]["isError"] is False  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (  # nosec B101 - pytest assertion
            False,
            0,
            0,
        )
        assert seen[0] is middleware.adapted[0]  # nosec B101 - original unchanged
        assert adapter.last_meter is None  # nosec B101 - no worker admitted
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@in_loop
async def test_transform_rename_away_from_bound_name_suppresses(protocol):
    """The bound registration renamed by a transform is a different producer."""
    with Lab() as lab:
        app = FastMCP("Q0 transform", version="synthetic")
        ran: list[str] = []
        bound = app.add_tool(_tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "r"))
        app.add_transform(
            ToolTransform({"synthetic": ToolTransformConfig(name="renamed")})
        )
        wire, error, seen, middleware, adapter = await _run(
            lab, app, bound, "renamed", protocol
        )
        assert (ran, error) == (["r"], None)  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (  # nosec B101 - pytest assertion
            False,
            0,
            0,
        )
        assert seen[0] is middleware.adapted[0]  # nosec B101 - original unchanged
        assert adapter.last_meter is None  # nosec B101 - no worker admitted


def _control(app, kind, ran):
    """Return the bound tool, which is also the tool FastMCP resolves."""
    if kind == "served_local_over_shadowed_child":
        served = app.add_tool(
            _tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "local")
        )
        child = FastMCP("Q0 g3 child provider")
        child.add_tool(
            _tool("synthetic", "1", BETA, {"ok": True, "n": 1}, ran, "child")
        )
        app.mount(child)
        return served, "local"
    injected = _tool("synthetic", "1", SCHEMA, {"ok": True}, ran, "injected")
    app.add_tool(_tool("synthetic", "1", BETA, {"ok": True, "n": 1}, ran, "registered"))
    app.add_middleware(ToolInjectionMiddleware([injected]))
    return injected, "injected"


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize(
    "kind",
    ["served_local_over_shadowed_child", "injected_tool_is_bound"],
)
@in_loop
async def test_control_bound_to_resolved_tool_still_hints(protocol, carrier, kind):
    """Positive control: the resolved producer is the bound tool; hint once.

    CHATGPT-POST-01 (Supervisor decision): "mounted_child_without_namespace"
    was removed from this control. FastMCP resolves a mounted child as a new
    FastMCPProviderTool wrapper, which is not the bound object and not an
    exact reviewed native type, so it now fails closed; the negative case is
    "mounted_child_wrapper" in test_hint_identity_provenance.py.
    """
    with Lab() as lab:
        app = FastMCP("Q0 g3 synthetic only", version="synthetic")
        ran: list[str] = []
        bound, producer = _control(app, kind, ran)
        wire, error, seen, middleware, _ = await _run(
            lab, app, bound, "synthetic", protocol, carrier
        )
        assert (ran, error) == ([producer], None)  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (  # nosec B101 - pytest assertion
            True,
            1,
            1,
        )
        assert middleware.adapted[0] is not seen[0]  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion

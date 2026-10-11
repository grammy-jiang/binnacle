"""Q0-SEC-02: preserve results from another native tool version without reads.

Ported from the independent reviewer's test_q0_sec_02_versions.py.
"""

import json
from dataclasses import replace
from unittest.mock import patch

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import witnessed_tool
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop
from tests.contracts.job_awareness.test_hint_version_support import ExecutionCarrier

BETA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
    "required": ["ok", "n"],
    "additionalProperties": False,
}


def _result(structured):
    return ToolResult(
        content=[TextContent(type="text", text="x")], structured_content=structured
    )


async def _wire(app, protocol, version):
    http_app = app.http_app(stateless_http=True, json_response=True)
    bodies = []

    async def record(response):
        body = await response.aread()
        if body and "content" in json.loads(body).get("result", {}):
            bodies.append(body)

    def factory(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=http_app),
            event_hooks={"response": [record]},
            **kwargs,
        )

    async with http_app.router.lifespan_context(http_app):
        transport = StreamableHttpTransport(
            "http://synthetic/mcp", httpx_client_factory=factory
        )
        with patch("mcp.client.session.LATEST_HANDSHAKE_VERSION", "2025-06-18"):
            async with Client(
                transport,
                mode="legacy" if protocol == "2025-06-18" else protocol,
                cache=False,
            ) as client:
                try:
                    await client.call_tool(
                        "synthetic", {}, raise_on_error=False, version=version
                    )
                except RuntimeError as exc:
                    # FastMCP validates output in the client after recording the body.
                    assert "Invalid structured content" in str(exc)  # nosec B101 - pytest assertion
    assert len(bodies) == 1  # nosec B101 - pytest assertion
    return bodies[0]


def add_other_version(app, bound_version, tool):
    # One local provider forbids mixing versioned and unversioned tools.
    # Native aggregation across mounted providers supports this topology.
    if bound_version is None or tool.version is None:
        child = FastMCP("Q0 unversioned provider")
        child.add_tool(tool)
        app.mount(child)
    else:
        app.add_tool(tool)


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize(
    "bound_version,other_version,selector,payload,bound_schema,other_schema",
    [
        ("1", "2", None, {"ok": True}, SCHEMA, BETA),
        ("2", "1", "1", {"ok": True, "n": 1}, BETA, SCHEMA),
        (None, "2", None, {"ok": True}, SCHEMA, BETA),
        ("2", None, "missing", {"ok": True, "n": 1}, BETA, SCHEMA),
        ("1", "1.0", None, {"ok": True}, SCHEMA, BETA),
    ],
    ids=[
        "bound_v1_default_dispatch_v2",
        "bound_v2_client_pins_v1",
        "unversioned_bound_versioned_producer",
        "versioned_bound_unversioned_fallback",
        "distinct_identity_equivalent_version_spelling",
    ],
)
@in_loop
async def test_q0_sec_02_other_version_suppresses_before_reads(
    protocol,
    carrier,
    bound_version,
    other_version,
    selector,
    payload,
    bound_schema,
    other_schema,
):
    with Lab() as lab:
        app = FastMCP("Q0 g2 synthetic only", version="synthetic")
        adapter = lab.adapter(enabled=True, carrier=carrier)
        adapter.server_info = app._mcp_server.server_info_stamp
        value = _result(payload)
        before = value.model_dump_json()
        produced = []

        def produce(version):
            produced.append(version)
            return value

        tool = app.add_tool(
            witnessed_tool(
                lambda: produce(bound_version),
                name="synthetic",
                version=bound_version,
                output_schema=bound_schema,
            )
        )
        add_other_version(
            app,
            bound_version,
            witnessed_tool(
                lambda: produce(other_version),
                name="synthetic",
                version=other_version,
                output_schema=other_schema,
            ),
        )
        bound = replace(adapter, tool=tool)
        seen = []
        middleware = ExecutionCarrier(app, bound, seen)
        app.add_middleware(middleware)
        wire = await _wire(app, protocol, selector)
        assert produced == [other_version]  # nosec B101 - pytest assertion
        assert json.loads(wire)["result"]["structuredContent"] == payload  # nosec B101 - pytest assertion
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (
            False,
            0,
            0,
        )  # nosec B101 - pytest assertion
        assert seen[0] is middleware.adapted[0] is value  # nosec B101 - pytest assertion
        assert value.model_dump_json() == before  # nosec B101 - pytest assertion
        assert bound.last_meter is None  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize(
    "bound_version,other_version,selector",
    [("1", "2", "1"), ("1", "2", "v1.0"), ("2", "1", None), (None, "2", "missing")],
    ids=["explicit", "normalized_selector", "default_highest", "unversioned_fallback"],
)
@in_loop
async def test_control_bound_version_requested_explicitly_still_hints(
    protocol,
    carrier,
    bound_version,
    other_version,
    selector,
):
    """The selected bound identity keeps a hint under its own valid schema."""
    with Lab() as lab:
        app = FastMCP("Q0 g2 synthetic only", version="synthetic")
        adapter = lab.adapter(enabled=True, carrier=carrier)
        adapter.server_info = app._mcp_server.server_info_stamp
        value = _result({"ok": True})
        before = value.model_dump_json()
        tool = app.add_tool(
            witnessed_tool(
                lambda: value,
                name="synthetic",
                version=bound_version,
                output_schema=SCHEMA,
            )
        )
        add_other_version(
            app,
            bound_version,
            witnessed_tool(
                lambda: _result({"ok": True, "n": 1}),
                name="synthetic",
                version=other_version,
                output_schema=BETA,
            ),
        )
        bound = replace(adapter, tool=tool)
        seen = []
        middleware = ExecutionCarrier(app, bound, seen)
        app.add_middleware(middleware)
        wire = await _wire(app, protocol, selector)
        assert (b"Binnacle job reminder" in wire, lab.catalog_reads, lab.queries) == (
            True,
            1,
            1,
        )  # nosec B101 - pytest assertion
        assert seen[0] is value  # nosec B101 - pytest assertion
        assert middleware.adapted[0] is not value  # nosec B101 - pytest assertion
        assert value.model_dump_json() == before  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion

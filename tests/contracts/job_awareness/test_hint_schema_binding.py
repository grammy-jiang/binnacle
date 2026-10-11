"""Q0-SEC-01: schema validation and reminders belong to one producing tool."""

import json
from dataclasses import replace
from unittest.mock import patch

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.tools.base import Tool, ToolResult

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.synthetic_app import (
    SCHEMA,
    Lab,
    app_for,
    in_loop,
    original,
)

BETA_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
    "required": ["ok", "n"],
    "additionalProperties": False,
}


async def raw_call(app, tool_name, protocol):
    """Capture the server response even when the client rejects its schema."""
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

    error = None
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
                    await client.call_tool(tool_name, {}, raise_on_error=False)
                except RuntimeError as exc:
                    error = str(exc)
    assert len(bodies) == 1  # nosec B101 - pytest assertion
    return bodies[0], error


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize("case", ["foreign_invalid", "foreign_valid", "bound_invalid"])
@in_loop
async def test_q0_sec_01_suppresses_before_reads(protocol, carrier, case):
    """An unrelated or invalid result must stay identical without awareness reads."""
    with Lab() as lab:
        value = original()
        before = value.model_dump_json()
        adapter = lab.adapter(enabled=True, carrier=carrier)
        identities = []
        real_adapt = HintAdapter.adapt

        async def capture(self, result, *args, **kwargs):
            adapted = await real_adapt(self, result, *args, **kwargs)
            identities.append(adapted is result)
            return adapted

        with patch.object(HintAdapter, "adapt", capture):
            app, seen = app_for(
                adapter,
                value,
                schema=BETA_SCHEMA if case == "bound_invalid" else SCHEMA,
            )

            @app.tool(
                name="beta",
                output_schema=BETA_SCHEMA if case == "foreign_invalid" else SCHEMA,
            )
            def beta() -> ToolResult:
                return value

            name = "synthetic" if case == "bound_invalid" else "beta"
            wire, error = await raw_call(app, name, protocol)
        payload = json.loads(wire)["result"]
        assert payload["structuredContent"] == {"ok": True}  # nosec B101 - pytest assertion
        assert payload["isError"] is False  # nosec B101 - pytest assertion
        assert value.model_dump_json() == before  # nosec B101 - pytest assertion
        assert seen == [value]  # nosec B101 - pytest assertion
        if case == "foreign_valid":
            assert error is None  # nosec B101 - pytest assertion
        else:
            assert error and "'n' is a required property" in error  # nosec B101 - pytest assertion
        assert (  # nosec B101 - pytest assertion
            identities,
            lab.catalog_reads,
            lab.queries,
            b"Binnacle job reminder" in wire,
        ) == ([True], 0, 0, False)
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@in_loop
async def test_bound_tool_uses_its_declared_schema(protocol, carrier):
    """The producing tool's closed schema accepts n; the old fixture schema does not."""
    with Lab() as lab:
        value = original()
        value.structured_content = {"ok": True, "n": 1}
        app, _ = app_for(
            lab.adapter(enabled=True, carrier=carrier), value, schema=BETA_SCHEMA
        )
        wire, error = await raw_call(app, "synthetic", protocol)
        assert error is None  # nosec B101 - pytest assertion
        assert b"Binnacle job reminder" in wire  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 1  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "name", [None, "", "beta", "Synthetic", "synthetic ", "x" * 129]
)
@in_loop
async def test_component_rejects_unbound_name_without_admitting_worker(name):
    """A permissive middleware cannot make the component hint another tool."""
    with Lab() as lab:
        adapter, value = lab.adapter(enabled=True), original()
        # Call the production entry directly, without the single-tool fixture shim.
        result = await HintAdapter.adapt(
            adapter, value, tool_name=name, tool_version=None
        )
        assert result is value  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_component_missing_or_hostile_name_fails_closed():
    calls = []

    class Name(str):
        def __eq__(self, other):
            calls.append(other)
            return True

        __hash__ = str.__hash__

    with Lab() as lab:
        adapter, value = lab.adapter(enabled=True), original()
        assert await HintAdapter.adapt(adapter, value) is value  # nosec B101 - pytest assertion
        assert (
            await HintAdapter.adapt(
                adapter, value, tool_name=Name("synthetic"), tool_version=None
            )
            is value
        )  # nosec B101 - pytest assertion
        assert calls == []  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@in_loop
async def test_component_validates_bound_native_tool_without_middleware(carrier):
    with Lab() as lab:
        app = FastMCP("Q0 direct binding")
        tool = app.add_tool(
            Tool.from_function(original, name="beta", output_schema=BETA_SCHEMA)
        )
        adapter = replace(lab.adapter(enabled=True, carrier=carrier), tool=tool)
        value = original()
        # Valid under the previous fixture schema, invalid under beta's schema.
        assert (
            await HintAdapter.adapt(adapter, value, tool_name="beta", tool_version=None)
            is value
        )  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        value.structured_content["n"] = 1
        result = await HintAdapter.adapt(
            adapter, value, tool_name="beta", tool_version=None
        )
        assert result is not value  # nosec B101 - pytest assertion
        assert result.structured_content == {"ok": True, "n": 1}  # nosec B101 - pytest assertion
        text = (
            result.meta[META_KEY]
            if carrier is HintCarrier.META
            else result.content[-1].text
        )
        assert "unconfirmed" in text  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 1  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("schema", [None, {"$ref": "https://invalid"}])
@in_loop
async def test_missing_or_unsupported_native_schema_suppresses(schema):
    with Lab() as lab:
        tool = Tool(name="synthetic", parameters={}, output_schema=schema)
        adapter = replace(lab.adapter(enabled=True), tool=tool)
        value = original()
        assert (
            await HintAdapter.adapt(
                adapter, value, tool_name="synthetic", tool_version=None
            )
            is value
        )  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


def test_schema_cannot_be_supplied_independently_of_native_tool():
    with Lab() as lab:
        adapter = lab.adapter()
        with pytest.raises((TypeError, ValueError), match="init=False"):
            replace(adapter, schema=BETA_SCHEMA)
        with pytest.raises(ValueError, match="explicit native tool binding required"):
            replace(adapter, tool=None)

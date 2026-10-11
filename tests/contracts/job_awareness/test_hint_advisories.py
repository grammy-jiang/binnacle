"""Closed Job Awareness advisories: ADV-G4-03, ADV-G4-05, ADV-G4-06, OBS-01."""

import dataclasses
from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.synthetic_app import Lab, in_loop, original

OBJECT = {"type": "object"}


class _NoStamp:
    _mcp_server = object()


def _padded(size: int) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text="Synthetic result")],
        structured_content={
            "padding": ["a" * 60000] * (size // 60000) + ["a" * (size % 60000)]
        },
        meta={"existing": "kept"},
    )


@in_loop
async def test_adv_g4_03_cheap_mismatch_skips_schema_canonicalization():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        value = original()
        calls = []
        real = identity.canonical_schema

        def counting(schema):
            calls.append(schema)
            return real(schema)

        with patch.object(identity, "canonical_schema", counting):
            # Same object, but the name changed after binding: cheap mismatch.
            object.__setattr__(adapter.tool, "name", "renamed")
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert calls == []  # nosec B101 - no canonicalization before the cheap checks
            object.__setattr__(adapter.tool, "name", "synthetic")
            object.__setattr__(adapter.tool, "version", "2")
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert calls == []  # nosec B101 - a changed version also skips it
            object.__setattr__(adapter.tool, "version", None)
            assert META_KEY in (await adapter.adapt_bound(original())).meta  # nosec B101 - pytest assertion
            assert len(calls) == 1  # nosec B101 - one canonicalization on the matching path


def test_adv_g4_03_expected_identity_keeps_the_result_unchanged():
    with Lab() as lab:
        tool = lab.adapter().tool
        full = identity.producer_identity(tool)
        assert full is not None  # nosec B101 - pytest assertion
        assert identity.producer_identity(tool, full) == full  # nosec B101 - match
        assert identity.producer_identity(tool, ("other", None, full[2])) is None  # nosec B101 - name
        assert identity.producer_identity(tool, (full[0], "9", full[2])) is None  # nosec B101 - version
        # A schema difference still fails closed in the final comparison.
        assert identity.producer_identity(tool, (full[0], full[1], "{}")) == full  # nosec B101 - caller compares


def test_adv_g4_06_adapter_has_no_unused_name_and_version_fields():
    names = {field.name for field in dataclasses.fields(HintAdapter)}
    assert not {"tool_name", "tool_version"} & names  # nosec B101 - pytest assertion
    with Lab() as lab:
        adapter = lab.adapter()
        assert not hasattr(adapter, "tool_name")  # nosec B101 - pytest assertion
        assert not hasattr(adapter, "tool_version")  # nosec B101 - pytest assertion


@in_loop
async def test_adv_g4_05_direct_shim_has_no_default_producer():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        value = original()
        with pytest.raises(TypeError):
            await adapter.adapt(value)
        assert await adapter.adapt(value, tool=None) is value  # nosec B101 - missing producer
        assert META_KEY in (await adapter.adapt_bound(original())).meta  # nosec B101 - explicit bound


def test_obs_01_bind_server_reads_the_dispatching_servers_stamp():
    with Lab() as lab:
        adapter = lab.adapter()
        app = FastMCP("bound-server", version="9.9")
        adapter.bind_server(app)
        assert adapter.server_info == app._mcp_server.server_info_stamp  # nosec B101 - pytest assertion
        assert adapter.server_info["name"] == "bound-server"  # nosec B101 - pytest assertion
        for foreign in (object(), _NoStamp()):
            adapter.bind_server(foreign)
            assert adapter.server_info is None  # nosec B101 - no stamp binds None


@in_loop
async def test_obs_01_missing_stamp_suppresses_and_stale_stamp_is_replaced():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True, schema=OBJECT)
        big = FastMCP("n" * 4000, version="synthetic")
        # Fits with the small hand-written stamp, not with the real, larger stamp.
        value = _padded(260000)
        assert META_KEY in (await adapter.adapt_bound(value)).meta  # nosec B101 - stale stamp hints
        adapter.bind_server(big)
        assert await adapter.adapt_bound(value) is value  # nosec B101 - real stamp suppresses
        adapter.bind_server(object())
        small = original()
        assert await adapter.adapt_bound(small) is small  # nosec B101 - no stamp suppresses

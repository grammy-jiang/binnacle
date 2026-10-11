"""Producer version checks precede workers, callbacks, and awareness reads."""

from collections.abc import Callable
from dataclasses import replace
from threading import Event
from typing import TypeVar

import pytest
from fastmcp.tools.base import Tool

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import HintAdapter
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop, original

T = TypeVar("T")


class NoWorkers:
    async def run(self, action: Callable[[Event], T], busy: T) -> T:
        pytest.fail("A producer mismatch must not admit a worker")


def native_tool(version):
    return Tool(name="synthetic", version=version, parameters={}, output_schema=SCHEMA)


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@pytest.mark.parametrize(
    "bound_version,producer_version",
    [("1", "2"), ("2", "1"), (None, "1"), ("1", None), ("1", "1.0")],
)
@in_loop
async def test_other_version_returns_original_before_worker(
    carrier, bound_version, producer_version
):
    with Lab() as lab:
        adapter = replace(
            lab.adapter(enabled=True, carrier=carrier),
            tool=native_tool(bound_version),
            workers=NoWorkers(),
        )
        value = original()
        before = value.model_dump_json()
        result = await HintAdapter.adapt(
            adapter, value, tool_name="synthetic", tool_version=producer_version
        )
        assert result is value  # nosec B101 - pytest assertion
        assert value.model_dump_json() == before  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_missing_version_is_unknown_even_for_unversioned_binding(version):
    with Lab() as lab:
        adapter = replace(
            lab.adapter(enabled=True), tool=native_tool(version), workers=NoWorkers()
        )
        value = original()
        assert await HintAdapter.adapt(adapter, value, tool_name="synthetic") is value  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("version", [True, 1, {}, [], object()])
@in_loop
async def test_invalid_producer_version_fails_closed(version):
    with Lab() as lab:
        adapter = replace(
            lab.adapter(enabled=True), tool=native_tool("1"), workers=NoWorkers()
        )
        value = original()
        assert (  # nosec B101 - pytest assertion
            await HintAdapter.adapt(
                adapter, value, tool_name="synthetic", tool_version=version
            )
            is value
        )
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@in_loop
async def test_hostile_version_cannot_run_comparison_callbacks():
    calls = []

    class Version(str):
        def __eq__(self, other):
            calls.append("eq")
            return True

        def __ne__(self, other):
            calls.append("ne")
            return False

        __hash__ = str.__hash__

    with Lab() as lab:
        adapter = replace(
            lab.adapter(enabled=True), tool=native_tool("1"), workers=NoWorkers()
        )
        value = original()
        assert (  # nosec B101 - pytest assertion
            await HintAdapter.adapt(
                adapter, value, tool_name="synthetic", tool_version=Version("1")
            )
            is value
        )
        hostile = Tool.model_construct(
            name="synthetic", parameters={}, output_schema=SCHEMA, version=Version("1")
        )
        with pytest.raises(ValueError, match="explicit native tool binding required"):
            replace(adapter, tool=hostile)
        assert calls == []  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_matching_version_keeps_default_off(version):
    with Lab() as lab:
        adapter = replace(lab.adapter(), tool=native_tool(version), workers=NoWorkers())
        value = original()
        assert (  # nosec B101 - pytest assertion
            await HintAdapter.adapt(
                adapter, value, tool_name="synthetic", tool_version=version
            )
            is value
        )
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion

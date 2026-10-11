"""CHATGPT-ADV-G4-01-R3: a receipt belongs to one dispatch and one result.

``witnessed_call`` binds each receipt to the exact ToolResult object its
dispatch returned. ``adapt()`` validates the receipt against ``original`` and
only then consumes it. A receipt from another call, for another (even equal)
result, a reused receipt, and dispatches whose body raised, was cancelled or
completed late give the original result with zero observation reads and
receipt queries. In-process code is trusted: these are controller mis-wiring
cases, not defenses against hostile code in the same interpreter.
"""

import asyncio

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import witnessed_tool
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop
from tests.contracts.job_awareness.test_hint_identity_witness import (
    Keep,
    _app,
    _hinted,
    _sealed,
)


def _fake():
    return ToolResult(
        content=[TextContent(type="text", text="x")], structured_content={"ok": True}
    )


class Rescue(Middleware):
    """An inner middleware that turns a failed dispatch into a valid result."""

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except Exception:  # noqa: BLE001 - the rescue is the scenario
            return _fake()


class Deadline(Middleware):
    """An inner middleware that cancels a slow body and answers instead."""

    async def on_call_tool(self, context, call_next):
        try:
            return await asyncio.wait_for(call_next(context), 0.05)
        except asyncio.TimeoutError:  # not the builtin TimeoutError on 3.10
            return _fake()


class Detach(Middleware):
    """An inner middleware that answers now and lets the body finish later."""

    def __init__(self, tasks):
        self.tasks = tasks

    async def on_call_tool(self, context, call_next):
        self.tasks.append(asyncio.create_task(call_next(context)))
        return _fake()


def _no_reads(lab, adapter):
    assert adapter.last_meter is None  # nosec B101 - no worker admitted
    assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_cross_call_and_cross_result_swaps_are_refused():
    """No inner middleware: two real calls, receipts swapped between them."""
    with Lab() as lab:
        ran: list[str] = []
        bound = _sealed(ran, "bound")
        receipts: list[tuple[ToolResult, object]] = []
        app, _, adapter = _app(lab, bound, Keep(receipts), carrier=False)
        app.add_tool(bound)
        await app.call_tool("synthetic", {})
        await app.call_tool("synthetic", {})
        (a, receipt_a), (b, receipt_b) = receipts
        assert ran == ["bound", "bound"] and a is not b  # nosec B101 - pytest assertion
        for value, receipt in ((b, receipt_a), (a, receipt_b), (_fake(), receipt_a)):
            assert value.structured_content == {"ok": True}  # nosec B101 - equal value
            assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        _no_reads(lab, adapter)
        # Mismatches consumed nothing; each receipt still works once for its own result.
        assert _hinted(await adapter.adapt(a, execution=receipt_a))  # nosec B101 - pytest assertion
        assert await adapter.adapt(a, execution=receipt_a) is a  # nosec B101 - consumed
        assert _hinted(await adapter.adapt(b, execution=receipt_b))  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 2  # nosec B101 - pytest assertion


@in_loop
async def test_hand_built_receipt_was_never_issued():
    """A controller that builds an Execution itself gets no hint."""
    with Lab() as lab:
        bound = _sealed([], "bound")
        _, _, adapter = _app(lab, bound, carrier=False)
        value = _fake()
        receipt = identity.Execution(bound, value)
        assert identity.claim(receipt, value) is None  # nosec B101 - pytest assertion
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        _no_reads(lab, adapter)


@pytest.mark.parametrize("rescued", [False, True])
@in_loop
async def test_body_exception_issues_no_receipt(rescued):
    with Lab() as lab:
        ran: list[str] = []

        def fail() -> ToolResult:
            ran.append("raised")
            raise RuntimeError("synthetic failure")

        bound = witnessed_tool(fail, name="synthetic", output_schema=SCHEMA)
        receipts: list[tuple[ToolResult, object]] = []
        inner = (Keep(receipts), Rescue()) if rescued else (Keep(receipts),)
        app, _, adapter = _app(lab, bound, *inner, carrier=False)
        app.add_tool(bound)
        issued = len(identity._ISSUED)
        if rescued:
            await app.call_tool("synthetic", {})
            assert receipts[0][1] is None  # nosec B101 - pytest assertion
            value = receipts[0][0]
            assert await adapter.adapt(value, execution=receipts[0][1]) is value  # nosec B101 - pytest assertion
        else:
            with pytest.raises(ToolError):
                await app.call_tool("synthetic", {})
            assert receipts == []  # nosec B101 - the exception propagated
        assert ran == ["raised"] and len(identity._ISSUED) == issued  # nosec B101 - pytest assertion
        _no_reads(lab, adapter)


@pytest.mark.parametrize("path", ["inner_deadline", "outer_cancel"])
@in_loop
async def test_cancelled_body_issues_no_receipt(path):
    with Lab() as lab:
        started, release = asyncio.Event(), asyncio.Event()
        ran: list[str] = []

        async def slow() -> ToolResult:
            started.set()
            await release.wait()
            ran.append("completed")
            return _fake()

        bound = witnessed_tool(slow, name="synthetic", output_schema=SCHEMA)
        receipts: list[tuple[ToolResult, object]] = []
        inner = (
            (Keep(receipts), Deadline())
            if path == "inner_deadline"
            else (Keep(receipts),)
        )
        app, _, adapter = _app(lab, bound, *inner, carrier=False)
        app.add_tool(bound)
        issued = len(identity._ISSUED)
        if path == "inner_deadline":
            await app.call_tool("synthetic", {})
            assert receipts[0][1] is None  # nosec B101 - pytest assertion
        else:
            task = asyncio.create_task(app.call_tool("synthetic", {}))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert receipts == []  # nosec B101 - pytest assertion
        assert ran == [] and len(identity._ISSUED) == issued  # nosec B101 - pytest assertion
        _no_reads(lab, adapter)


@in_loop
async def test_late_task_completion_is_not_witnessed():
    """The body completes after its dispatch returned: no receipt, then or later."""
    with Lab() as lab:
        release = asyncio.Event()
        ran: list[str] = []

        async def late() -> ToolResult:
            await release.wait()
            ran.append("late")
            return _fake()

        bound = witnessed_tool(late, name="synthetic", output_schema=SCHEMA)
        receipts: list[tuple[ToolResult, object]] = []
        tasks: list[asyncio.Task] = []
        app, _, adapter = _app(lab, bound, Keep(receipts), Detach(tasks), carrier=False)
        app.add_tool(bound)
        issued = len(identity._ISSUED)
        await app.call_tool("synthetic", {})
        assert receipts[0][1] is None  # nosec B101 - nothing completed in time
        release.set()
        late_result = await tasks[0]
        assert ran == ["late"] and len(identity._ISSUED) == issued  # nosec B101 - pytest assertion
        for value in (receipts[0][0], late_result):
            assert await adapter.adapt(value, execution=receipts[0][1]) is value  # nosec B101 - pytest assertion
        _no_reads(lab, adapter)

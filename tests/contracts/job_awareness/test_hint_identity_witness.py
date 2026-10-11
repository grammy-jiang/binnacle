"""ADV-G4-01: the producer comes only from what ran, never from a lookup.

The independent adversarial review (L4 Q0 g4) found that ``adapt()`` took any
``tool`` object, so a future controller could pass a Tool it looked up by name
(``app.get_tool``) instead of the Tool that ran. With a rerouting or answering
inner middleware that lookup is fail-open. ``adapt()`` now takes only a
single-use ``Execution`` receipt that an ``ExecutionScope`` issues when exactly
one ``witnessed_tool`` body ran on the scope's own server. Tool objects, names,
registry results, value-equal tools and forged or reused receipts suppress with
zero worker admissions, observation reads and receipt queries.
"""

import asyncio

import pytest
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import CallToolRequestParams, TextContent

from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import (
    META_KEY,
    Execution,
    ExecutionScope,
    HintAdapter,
    witnessed_tool,
)
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop
from tests.contracts.job_awareness.test_hint_version_support import ExecutionCarrier


def _body(ran, tag):
    def fn() -> ToolResult:
        ran.append(tag)
        return ToolResult(
            content=[TextContent(type="text", text="x")],
            structured_content={"ok": True},
        )

    return fn


def _sealed(ran, tag, name="synthetic"):
    return witnessed_tool(_body(ran, tag), name=name, output_schema=SCHEMA)


class Reroute(Middleware):
    """Y1: an inner middleware sends the call to another tool."""

    async def on_call_tool(self, context, call_next):
        message = CallToolRequestParams(name="beta", arguments={})
        return await call_next(context.copy(message=message))


class Answer(Middleware):
    """Y2: an inner middleware answers with a result valid under SCHEMA."""

    async def on_call_tool(self, context, call_next):
        return ToolResult(
            content=[TextContent(type="text", text="x")],
            structured_content={"ok": True},
        )


class Keep(Middleware):
    """A controller-shaped middleware that keeps each issued receipt."""

    def __init__(self, receipts):
        self.receipts = receipts

    async def on_call_tool(self, context, call_next):
        with ExecutionScope() as scope:
            result = await call_next(context)
        self.receipts.append(scope.execution())
        return result


def _app(lab, bound, *inner):
    app = FastMCP("ADV-G4-01 synthetic only", version="synthetic")
    adapter = lab.adapter(enabled=True)
    adapter.server_info = app._mcp_server.server_info_stamp
    bound_adapter = HintAdapter(
        bindings=adapter.bindings,
        grant=adapter.grant,
        jobs=adapter.jobs,
        tool=bound,
        workers=adapter.workers,
        server_info=adapter.server_info,
        enabled=True,
        exclusive=True,
    )
    carrier = ExecutionCarrier(app, bound_adapter, [])
    app.add_middleware(carrier)
    for middleware in inner:
        app.add_middleware(middleware)
    return app, carrier, bound_adapter


def _hinted(result):
    return META_KEY in (result.meta or {})


def _untouched(lab, carrier):
    assert carrier.seen[0] is carrier.adapted[0]  # nosec B101 - original returned
    assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_control_bound_witnessed_tool_that_ran_hints_once():
    with Lab() as lab:
        ran: list[str] = []
        bound = _sealed(ran, "bound")
        app, _, _ = _app(lab, bound)
        assert app.add_tool(bound) is bound  # nosec B101 - registration keeps the object
        assert _hinted(await app.call_tool("synthetic", {}))  # nosec B101 - pytest assertion
        assert ran == ["bound"]  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 1  # nosec B101 - pytest assertion


@pytest.mark.parametrize("inner", ["reroute", "answer"])
@in_loop
async def test_y1_y2_lookup_would_name_bound_but_witness_suppresses(inner):
    """A by-name lookup returns the bound object; the witness says otherwise."""
    with Lab() as lab:
        ran: list[str] = []
        bound = _sealed(ran, "bound")
        middleware = Reroute() if inner == "reroute" else Answer()
        app, carrier, adapter = _app(lab, bound, middleware)
        app.add_tool(bound)
        app.add_tool(_sealed(ran, "beta", name="beta"))
        assert await app.get_tool("synthetic") is bound  # nosec B101 - lookup is fail-open
        assert not _hinted(await app.call_tool("synthetic", {}))  # nosec B101 - pytest assertion
        assert ran == (["beta"] if inner == "reroute" else [])  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - no worker admitted
        _untouched(lab, carrier)


@in_loop
async def test_tool_objects_names_and_registry_results_are_refused():
    """No by-name or by-object fallback exists: only a receipt is accepted."""
    with Lab() as lab:
        bound = _sealed([], "bound")
        app, _, adapter = _app(lab, bound)
        app.add_tool(bound)
        value = ToolResult(structured_content={"ok": True})
        with pytest.raises(TypeError):
            await HintAdapter.adapt(adapter, value, tool=bound)
        lookalikes = [
            None,
            bound,
            await app.get_tool("synthetic"),
            "synthetic",
            ("synthetic", None),
            {"synthetic": bound},
            [bound],
            bound.model_copy(),
            Tool(name="synthetic", parameters={}, output_schema=SCHEMA),
        ]
        for lookalike in lookalikes:
            assert await adapter.adapt(value, execution=lookalike) is value  # nosec B101 - pytest assertion
        assert adapter.last_meter is None  # nosec B101 - no worker admitted
        assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("twin", ["same_handler", "other_handler"])
@in_loop
async def test_different_but_equal_witnessed_tool_that_ran_is_refused(twin):
    """An equal triple from another Tool object is not the bound producer."""
    with Lab() as lab:
        ran: list[str] = []
        fn = _body(ran, "shared")
        bound = witnessed_tool(fn, name="synthetic", output_schema=SCHEMA)
        other = (
            witnessed_tool(fn, name="synthetic", output_schema=SCHEMA)
            if twin == "same_handler"
            else _sealed(ran, "twin")
        )
        assert identity.producer_identity(other) == identity.producer_identity(bound)  # nosec B101 - repro
        app, carrier, adapter = _app(lab, bound)
        app.add_tool(other)
        assert not _hinted(await app.call_tool("synthetic", {}))  # nosec B101 - pytest assertion
        assert len(ran) == 1 and adapter.last_meter is None  # nosec B101 - pytest assertion
        _untouched(lab, carrier)


def test_execution_receipt_cannot_be_forged_subclassed_or_changed():
    bound = _sealed([], "bound")
    for key in (None, object(), "mint"):
        with pytest.raises(TypeError, match="issued only by ExecutionScope"):
            Execution(key, bound)
    with pytest.raises(TypeError, match="cannot be subclassed"):
        type("Forged", (Execution,), {})
    receipt = Execution(identity._MINT, bound)  # module-private key only
    with pytest.raises(AttributeError):
        receipt._tool = Tool(name="x", parameters={})
    assert identity.claim(receipt) is bound  # nosec B101 - pytest assertion
    assert identity.claim(receipt) is None  # nosec B101 - single use


@in_loop
async def test_receipt_is_single_use():
    with Lab() as lab:
        bound = _sealed([], "bound")
        app, _, adapter = _app(lab, bound)
        app.add_tool(bound)
        value = ToolResult(
            content=[TextContent(type="text", text="x")],
            structured_content={"ok": True},
        )
        with ExecutionScope() as scope:
            await app.call_tool("synthetic", {}, run_middleware=False)
        assert scope.execution() is None  # nosec B101 - no server outside dispatch
        receipts = []

        app.add_middleware(Keep(receipts))
        await app.call_tool("synthetic", {})
        receipt = receipts[-1]
        assert type(receipt) is Execution  # nosec B101 - pytest assertion
        assert _hinted(await adapter.adapt(value, execution=receipt))  # nosec B101 - pytest assertion
        reads = lab.catalog_reads
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        assert lab.catalog_reads == reads  # nosec B101 - reuse reads nothing


@in_loop
async def test_scope_issues_nothing_while_open_twice_or_after_two_runs():
    with Lab() as lab:
        ran: list[str] = []
        bound = _sealed(ran, "bound")
        app, _, _ = _app(lab, bound)
        app.add_tool(bound)
        issued = []

        class Twice(Middleware):
            async def on_call_tool(self, context, call_next):
                with ExecutionScope() as scope:
                    result = await call_next(context)
                    issued.append(scope.execution())  # still open, one run
                    await call_next(context)
                issued.extend((scope.execution(), scope.execution()))
                with pytest.raises(RuntimeError, match="single-use"):
                    scope.__enter__()
                return result

        app.add_middleware(Twice())
        await app.call_tool("synthetic", {})
        assert ran == ["bound", "bound"]  # nosec B101 - pytest assertion
        assert issued == [None, None, None]  # nosec B101 - pytest assertion


@pytest.mark.parametrize("topology", ["transform_of_bound", "mounted_child_bound"])
@in_loop
async def test_transform_or_mounted_dispatch_of_bound_body_issues_no_receipt(topology):
    """The bound body ran, but through a wrapper: unknown producer."""
    with Lab() as lab:
        ran: list[str] = []
        bound = _sealed(ran, "bound")
        app, carrier, adapter = _app(lab, bound)
        if topology == "transform_of_bound":
            app.add_tool(Tool.from_tool(bound))
        else:
            child = FastMCP("ADV-G4-01 child")
            child.add_tool(bound)
            app.mount(child)
        assert not _hinted(await app.call_tool("synthetic", {}))  # nosec B101 - pytest assertion
        assert ran == ["bound"] and adapter.last_meter is None  # nosec B101 - pytest assertion
        _untouched(lab, carrier)


@in_loop
async def test_async_and_threaded_bodies_are_witnessed():
    ran: list[str] = []

    async def body() -> ToolResult:
        await asyncio.sleep(0)
        ran.append("async")
        return ToolResult(structured_content={"ok": True})

    for tool in (
        witnessed_tool(body, name="synthetic", output_schema=SCHEMA),
        witnessed_tool(
            _body(ran, "thread"),
            name="synthetic",
            output_schema=SCHEMA,
            run_in_thread=True,  # the body runs in a worker thread
        ),
    ):
        app = FastMCP("ADV-G4-01 kinds")
        app.add_tool(tool)
        receipts = []

        app.add_middleware(Keep(receipts))
        await app.call_tool("synthetic", {})
        assert identity.claim(receipts[0]) is tool  # nosec B101 - pytest assertion
    assert ran == ["async", "thread"]  # nosec B101 - pytest assertion


def test_witnessed_tool_needs_a_plain_function():
    def gen():
        yield 1

    async def agen():
        yield 1

    class Callable:
        def __call__(self):
            return None

    for fn in (gen, agen, Callable(), print):
        with pytest.raises(ValueError, match="plain function"):
            witnessed_tool(fn, name="synthetic")


@in_loop
async def test_body_outside_any_scope_records_nothing():
    ran: list[str] = []
    app = FastMCP("ADV-G4-01 no controller")
    app.add_tool(_sealed(ran, "bound"))
    result = await app.call_tool("synthetic", {})
    assert (ran, result.structured_content) == (["bound"], {"ok": True})  # nosec B101 - pytest assertion


def test_witnessed_tool_refuses_a_non_exact_function_tool(monkeypatch):
    class Wrapped(identity.FunctionTool):
        pass

    real = identity.FunctionTool.from_function
    monkeypatch.setattr(
        identity.FunctionTool,
        "from_function",
        lambda fn, **options: Wrapped.model_construct(**vars(real(fn, **options))),
    )
    with pytest.raises(ValueError, match="exact FunctionTool"):
        witnessed_tool(_body([], "x"), name="synthetic")

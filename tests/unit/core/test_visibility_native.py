"""Native Visibility owns marking and filtering; policy remains request-local."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.server.transforms import Visibility
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec

import binnacle.visibility as module
from binnacle.visibility import ClientToolVisibilityTransform


def request_policy(monkeypatch, allowed):
    ctx = SimpleNamespace(
        request_context=object(), get_state=AsyncMock(return_value=allowed)
    )
    monkeypatch.setattr(module, "get_context", lambda: ctx)
    return ctx


@pytest.mark.parametrize(
    "allowed", [None, frozenset(), frozenset({"visible", "absent"})]
)
def test_native_marking_preserves_order_multiplicity_and_shared_components(
    monkeypatch, allowed
):
    request_policy(monkeypatch, allowed)
    visible = Tool(name="visible", parameters={}, meta={"custom": {"v": 1}})
    hidden = Tool(name="hidden", parameters={}, description="unchanged")
    tools = [visible, hidden, visible]
    before = [tool.model_dump() for tool in tools]

    async def go():
        marked = await ClientToolVisibilityTransform().list_tools(tools)
        if allowed is None:
            assert marked is tools
        else:
            native = await Visibility(False, components={"tool"}).list_tools(tools)
            native = await Visibility(
                True, names=set(allowed), components={"tool"}
            ).list_tools(native)
            assert marked == native
        assert [tool.name for tool in marked] == ["visible", "hidden", "visible"]
        assert [tool.model_dump() for tool in tools] == before

    asyncio.run(go())


@pytest.mark.parametrize("allowed", [None, frozenset(), frozenset({"visible"})])
@pytest.mark.parametrize("found", [False, True])
def test_get_delegates_name_version_and_missing_result(monkeypatch, allowed, found):
    request_policy(monkeypatch, allowed)
    tool = Tool(name="visible", parameters={}) if found else None
    call_next = AsyncMock(return_value=tool)
    version = VersionSpec(eq="1")
    before = tool.model_dump() if tool else None

    async def go():
        result = await ClientToolVisibilityTransform().get_tool(
            "visible", call_next, version=version
        )
        call_next.assert_awaited_once_with("visible", version=version)
        if allowed is None or not found:
            assert result is tool
        else:
            expected = await Visibility(
                "visible" in allowed, components={"tool"}
            ).get_tool("visible", AsyncMock(return_value=tool), version=version)
            assert result == expected
        assert (tool.model_dump() if tool else None) == before

    asyncio.run(go())


def test_no_context_and_no_session_introspection_are_unrestricted():
    async def go():
        transform = ClientToolVisibilityTransform()
        tools = [Tool(name="one", parameters={})]
        assert await transform.list_tools(tools) is tools
        async with Context(FastMCP("direct")):
            assert await transform.list_tools(tools) is tools

    asyncio.run(go())


def test_state_failure_is_not_swallowed(monkeypatch):
    ctx = request_policy(monkeypatch, frozenset())
    ctx.get_state.side_effect = RuntimeError("store failure")
    with pytest.raises(RuntimeError, match="store failure"):
        asyncio.run(ClientToolVisibilityTransform().list_tools([]))


def test_unexpected_context_failure_is_not_swallowed(monkeypatch):
    def fail():
        raise RuntimeError("unexpected context failure")

    monkeypatch.setattr(module, "get_context", fail)
    with pytest.raises(RuntimeError, match="unexpected context failure"):
        asyncio.run(ClientToolVisibilityTransform().list_tools([]))


@pytest.mark.parametrize("allowed", [frozenset(), frozenset({"visible"})])
def test_native_get_denies_without_call_error_bridge_and_other_components_survive(
    allowed,
):
    root = FastMCP("native-only")

    class Publish(Middleware):
        async def on_request(self, context, call_next):
            await context.fastmcp_context.set_state(
                module._ALLOWLIST_KEY, allowed, serializable=False
            )
            return await call_next(context)

    root.add_middleware(Publish())
    root.add_transform(ClientToolVisibilityTransform())
    root.tool(lambda: "ok", name="visible")
    root.tool(lambda: "denied", name="hidden")
    root.resource("data://value")(lambda: "value")
    root.prompt(name="prompt")(lambda: "prompt text")

    async def go():
        async with Client(root, cache=False) as client:
            assert [tool.name for tool in await client.list_tools()] == sorted(allowed)
            result = await client.call_tool("hidden", {}, raise_on_error=False)
            assert (
                result.is_error and result.content[0].text == "Unknown tool: 'hidden'"
            )
            assert len(await client.list_resources()) == 1
            assert len(await client.list_prompts()) == 1
            assert (await client.read_resource("data://value"))[0].text == "value"
            assert (await client.get_prompt("prompt")).messages[
                0
            ].content.text == "prompt text"
        assert len(await root.list_tools(run_middleware=False)) == 2

    asyncio.run(go())


@pytest.mark.parametrize("method", ["on_list_tools", "on_call_tool"])
@pytest.mark.parametrize("allowed", [None, frozenset(), frozenset({"visible"})])
def test_middleware_publishes_request_policy_before_delegation(
    monkeypatch, method, allowed
):
    ctx = SimpleNamespace(request_context=object(), set_state=AsyncMock())
    context = SimpleNamespace(
        fastmcp_context=ctx, message=SimpleNamespace(name="visible")
    )
    middleware = module.ClientToolVisibility({})
    monkeypatch.setattr(middleware, "_enabled_for", lambda name: allowed)
    monkeypatch.setattr(middleware._identity, "resolve", lambda context: "client")
    objects = [Tool(name="visible", parameters={}), Tool(name="hidden", parameters={})]

    async def next_step(received):
        assert received is context
        ctx.set_state.assert_awaited_once_with(
            module._ALLOWLIST_KEY, allowed, serializable=False
        )
        return objects

    async def go():
        if method == "on_call_tool" and allowed == frozenset():
            from fastmcp.exceptions import ToolError

            with pytest.raises(ToolError, match="not available"):
                await middleware.on_call_tool(context, next_step)
            ctx.set_state.assert_awaited_once_with(
                module._ALLOWLIST_KEY, allowed, serializable=False
            )
        else:
            assert await getattr(middleware, method)(context, next_step) is objects

    asyncio.run(go())


def test_policy_publication_failure_propagates_before_denied_call():
    context = SimpleNamespace(
        fastmcp_context=SimpleNamespace(
            request_context=object(),
            set_state=AsyncMock(side_effect=RuntimeError("publish failure")),
        ),
        message=SimpleNamespace(name="hidden"),
    )
    middleware = module.ClientToolVisibility({"restricted": ()})
    middleware._identity = SimpleNamespace(resolve=lambda context: "restricted")
    with pytest.raises(RuntimeError, match="publish failure"):
        asyncio.run(middleware.on_call_tool(context, AsyncMock()))

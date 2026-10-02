"""Pinned native request state and dependency ownership; no production resource."""

import asyncio
import threading
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_request_state_inherits_child_but_persistent_state_does_not(mode):
    root, child = FastMCP("root"), FastMCP("child")
    seen = []

    class Publish(Middleware):
        async def on_call_tool(self, context, call_next):
            ctx = context.fastmcp_context
            seen.append(
                (await ctx.get_state("persistent"), await ctx.get_state("request"))
            )
            await ctx.set_state("persistent", "parent")
            await ctx.set_state("request", "shared", serializable=False)
            return await call_next(context)

    root.add_middleware(Publish())

    @child.tool
    async def probe(ctx: Context) -> dict:
        return {
            "request": await ctx.get_state("request"),
            "persistent": await ctx.get_state("persistent"),
        }

    root.mount(child)

    async def go():
        async with Client(root, mode=mode, cache=False) as client:
            for _ in range(2):
                assert (await client.call_tool("probe", {})).data == {
                    "request": "shared",
                    "persistent": None,
                }
        assert seen == [(None, None), ("parent" if mode == "legacy" else None, None)]

    asyncio.run(go())


def test_depends_cache_cleanup_schema_worker_and_child_lifespan():
    events = []
    main_thread = threading.get_ident()

    def make(name):
        @asynccontextmanager
        async def lifespan(server):
            events.append(name + ":enter")
            try:
                yield {"owner": name}
            finally:
                events.append(name + ":exit")

        return FastMCP(name, lifespan=lifespan)

    root, child = make("root"), make("child")

    context_dependency = CurrentContext()

    @asynccontextmanager
    async def dependency(ctx: Context = context_dependency):
        events.append("dependency:enter")
        try:
            yield {"server": ctx.fastmcp.name, "life": ctx.lifespan_context}
        finally:
            events.append("dependency:exit")

    first_dependency, second_dependency = Depends(dependency), Depends(dependency)

    @child.tool
    def probe(fail: bool = False, one=first_dependency, two=second_dependency) -> dict:
        assert one is two
        assert threading.get_ident() != main_thread
        if fail:
            raise ToolError("scope failure")
        return one

    root.mount(child)

    async def go():
        async with Client(root, cache=False) as client:
            schema = (await client.list_tools())[0].input_schema
            assert set(schema["properties"]) == {"fail"}
            assert (await client.call_tool("probe", {})).data == {
                "server": "child",
                "life": {"owner": "child"},
            }
            with pytest.raises(ToolError, match="scope failure"):
                await client.call_tool("probe", {"fail": True})
            assert events.count("dependency:enter") == 2
            assert events.count("dependency:exit") == 2
            result = await client.call_tool("probe", {"one": {}}, raise_on_error=False)
            assert result.is_error
            assert "one" in result.content[0].text
        assert events[:2] == ["root:enter", "child:enter"]
        assert events[-2:] == ["child:exit", "root:exit"]
        assert events.count("dependency:enter") == events.count("dependency:exit")

    asyncio.run(go())

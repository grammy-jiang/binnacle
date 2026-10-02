"""Pinned FastMCP middleware delegation and lifecycle behavior (test-only hooks)."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware


class Trace(Middleware):
    def __init__(self, name, events):
        self.name = name
        self.events = events

    async def on_call_tool(self, context, call_next):
        self.events.append(f"{self.name}:call:enter")
        try:
            return await call_next(context)
        finally:
            self.events.append(f"{self.name}:call:exit")

    async def on_list_tools(self, context, call_next):
        self.events.append(f"{self.name}:list:enter")
        try:
            return await call_next(context)
        finally:
            self.events.append(f"{self.name}:list:exit")


def synthetic_tree(events):
    def make(name):
        @asynccontextmanager
        async def lifespan(server):
            events.append(f"{name}:life:enter")
            try:
                yield {}
            finally:
                events.append(f"{name}:life:exit")

        root = FastMCP(name, lifespan=lifespan)
        root.add_middleware(Trace(name, events))
        return root

    root, first, second = [make(name) for name in ("root", "first", "second")]

    @first.tool
    def probe(fail: bool = False) -> str:
        events.append("first:tool")
        if fail:
            raise ToolError("composition probe failed")
        return "ok"

    @second.tool
    def sibling() -> str:
        events.append("second:tool")
        return "sibling"

    root.mount(first)
    root.mount(second)
    return root


@pytest.mark.parametrize("fail", [False, True])
def test_native_call_runs_root_and_selected_child_once(fail):
    events = []
    root = synthetic_tree(events)

    async def go():
        async with Client(root) as client:
            events.clear()
            result = await client.call_tool(
                "probe", {"fail": fail}, raise_on_error=False
            )
            assert result.is_error is fail
            assert [
                event
                for event in events
                if ":call:" in event or event.endswith(":tool")
            ] == [
                "root:call:enter",
                "first:call:enter",
                "first:tool",
                "first:call:exit",
                "root:call:exit",
            ]
            events.clear()
            assert not (await client.call_tool("sibling", {})).is_error
            assert [
                event
                for event in events
                if ":call:" in event or event.endswith(":tool")
            ] == [
                "root:call:enter",
                "second:call:enter",
                "second:tool",
                "second:call:exit",
                "root:call:exit",
            ]

    asyncio.run(go())


def test_native_listing_aggregates_children_inside_root_middleware():
    events = []
    root = synthetic_tree(events)

    async def go():
        async with Client(root) as client:
            events.clear()
            assert [tool.name for tool in await client.list_tools()] == [
                "probe",
                "sibling",
            ]
            assert events[0] == "root:list:enter"
            assert events[-1] == "root:list:exit"
            for name in ("first", "second"):
                before, after = f"{name}:list:enter", f"{name}:list:exit"
                assert events.count(before) == events.count(after) == 1
                assert events.index(before) < events.index(after)

    asyncio.run(go())


@pytest.mark.parametrize("fail", [False, True])
def test_native_lifespans_enter_and_exit_once_per_active_lifetime(fail):
    events = []
    root = synthetic_tree(events)

    async def go():
        for _ in range(2):
            events.clear()
            try:
                async with Client(root) as client:
                    await client.call_tool("probe", {})
                    await client.call_tool("sibling", {})
                    if fail:
                        raise RuntimeError("client work failed")
            except RuntimeError as exc:
                assert fail and str(exc) == "client work failed"
            assert [event for event in events if ":life:" in event] == [
                "root:life:enter",
                "first:life:enter",
                "second:life:enter",
                "second:life:exit",
                "first:life:exit",
                "root:life:exit",
            ]

    asyncio.run(go())

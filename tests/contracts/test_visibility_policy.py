"""Client-name policy edges pinned before native visibility activation."""

import asyncio

import mcp.types
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from binnacle.visibility import ClientToolVisibility, ClientToolVisibilityTransform


def policy_root(policies):
    root, child = FastMCP("policy-root"), FastMCP("policy-child")
    for name in ("read_file", "edit_file", "future_tool"):
        child.tool(lambda: "ok", name=name)
    root.mount(child)
    root.add_middleware(ClientToolVisibility(policies))
    root.add_transform(ClientToolVisibilityTransform())
    return root


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize(
    ("policies", "expected"),
    [
        ({"openai": (), "openai-mcp": ("read_file",)}, []),
        ({"openai-mcp": ("read_file", "unknown"), "openai": ()}, ["read_file"]),
    ],
)
def test_first_prefix_empty_future_unknown_and_first_call(mode, policies, expected):
    root = policy_root(policies)
    notifications = []

    async def receive(message):
        notifications.append(type(getattr(message, "root", message)).__name__)

    async def go():
        for _ in range(2):  # Reconnect; a root must not leak the previous session.
            async with Client(
                root,
                client_info=mcp.types.Implementation(name="openai-mcp", version="1"),
                mode=mode,
                cache=False,
                message_handler=receive,
            ) as client:
                for name in ("edit_file", "missing"):
                    with pytest.raises(ToolError) as exc:
                        await client.call_tool(name, {"invalid": True})
                    assert str(exc.value) == (
                        f"Tool {name!r} is not available to this client."
                    )
                for _ in range(3):
                    assert [t.name for t in await client.list_tools()] == expected
        assert not any("ListChanged" in name for name in notifications)
        assert [t.name for t in await root.list_tools(run_middleware=False)] == [
            "read_file",
            "edit_file",
            "future_tool",
        ]
        async with Client(root, cache=False) as client:
            assert len(await client.list_tools()) == 3
            error = await client.call_tool("missing", {}, raise_on_error=False)
            assert error.is_error
            assert "Unknown tool: 'missing'" in error.content[0].text

    asyncio.run(go())


def test_concurrent_clients_and_roots_have_independent_policy():
    async def go():
        roots = [policy_root({"restricted": names}) for names in [(), ("read_file",)]]

        async def check(root, name, mode, expected):
            async with Client(
                root,
                cache=False,
                mode=mode,
                client_info=mcp.types.Implementation(name=name, version="1"),
            ) as client:
                lists = await asyncio.gather(*(client.list_tools() for _ in range(3)))
                assert [[t.name for t in tools] for tools in lists] == [expected] * 3

        await asyncio.gather(
            *(
                check(root, name, mode, expected)
                for root, restricted in zip(roots, [[], ["read_file"]], strict=True)
                for mode in ["auto", "legacy"]
                for name, expected in [
                    ("restricted", restricted),
                    ("unrelated", ["read_file", "edit_file", "future_tool"]),
                ]
            )
        )

    asyncio.run(go())

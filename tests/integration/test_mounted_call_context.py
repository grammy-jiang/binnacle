"""Root logging and request context survive real native child delegation."""

import asyncio
import logging
import threading

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from binnacle import callctx, server
from binnacle.tools import read_file
from tests.integration.http_test_support import http_tool_call, with_session


def context_snapshot():
    return (
        callctx.current_call.get(),
        callctx.current_client.get(),
        callctx.current_turn.get(),
        callctx.current_argument_names.get(),
        callctx.current_call_started.get(),
    )


class RestoredContext(Middleware):
    def __init__(self, restored):
        self.restored = restored

    async def on_call_tool(self, context, call_next):
        before = context_snapshot()
        try:
            return await call_next(context)
        finally:
            assert context_snapshot() == before
            self.restored.append(before)


class ChildCalls(Middleware):
    def __init__(self, calls):
        self.calls = calls

    async def on_call_tool(self, context, call_next):
        self.calls.append(context.message.name)
        return await call_next(context)


@pytest.mark.parametrize(
    ("domain", "adapter", "implementation", "tool", "argument"),
    [("files", read_file, "read_file_impl", "read_file", "path")],
)
def test_concurrent_http_context_logging_and_errors_across_child(
    domain, adapter, implementation, tool, argument, tmp_path, monkeypatch, caplog
):
    path = tmp_path / "sample.txt"
    path.write_text("alpha\n")
    arguments = {"path": str(path)}
    original = getattr(adapter, implementation)
    observed, child_calls, restored = [], [], []
    rendezvous = threading.Barrier(2, timeout=15)

    def observe(*args, **kwargs):
        observed.append(context_snapshot())
        rendezvous.wait()
        if str(args[0]).endswith("failure"):
            raise ToolError("composition failure")
        return original(*args, **kwargs)

    # Search's adapter captures its implementation at registration. Always patch
    # the existing lookup point before constructing any root or child.
    monkeypatch.setattr(adapter, implementation, observe)
    factory_name = f"create_{domain}_server"
    factory = getattr(server, factory_name, None)
    assert callable(factory), "domain must be mounted at this checkpoint"

    def traced_child():
        child = factory()
        child.add_middleware(ChildCalls(child_calls))
        return child

    monkeypatch.setattr(server, factory_name, traced_child)
    root = server.create_server()
    # Test-only outer observer verifies restoration in the request task itself.
    root.middleware.insert(0, RestoredContext(restored))
    monkeypatch.setattr(server, "app", root.http_app())

    async def go(client, headers):
        return await asyncio.gather(
            http_tool_call(
                client,
                {**headers, "x-request-id": "wfr_success/call-1"},
                10,
                tool,
                arguments,
            ),
            http_tool_call(
                client,
                {**headers, "x-request-id": "wfr_failure/call-2"},
                11,
                tool,
                {**arguments, argument: str(tmp_path / "failure")},
            ),
        )

    with caplog.at_level(logging.INFO, logger="binnacle.results"):
        success, failure = with_session(go, client_name="composition-http")
    assert success["result"]["isError"] is False
    assert failure["result"]["isError"] is True
    assert "composition failure" in failure["result"]["content"][0]["text"]
    assert child_calls == [tool, tool]
    assert len(observed) == len(restored) == 2
    assert len({snapshot[0] for snapshot in observed}) == 2
    assert {snapshot[2] for snapshot in observed} == {"wfr_success", "wfr_failure"}
    for call, client, turn, explicit, started in observed:
        assert call != "-" and client == "composition-http"
        assert explicit == frozenset(arguments)
        assert started is not None
        lines = [
            record.getMessage()
            for record in caplog.records
            if record.name == "binnacle.results"
            and f"call={call} " in record.getMessage()
        ]
        assert sum("event=tool_call " in line for line in lines) == 1
        assert sum("event=tool_result " in line for line in lines) == 1
        assert all(
            f"tool={tool}" in line and f"turn={turn}/call-" in line for line in lines
        )
    assert all(
        snapshot == ("-", None, None, frozenset(), None) for snapshot in restored
    )
    assert context_snapshot() == ("-", None, None, frozenset(), None)

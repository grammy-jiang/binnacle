"""Failure paths of the production Job Awareness middleware, without HTTP.

The classifier, fence, identity, job-state reader and server are injected
fakes, so each fail-closed branch is driven directly.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.session_fence import FenceSet
from binnacle.features.commands.job_awareness.session_route import (
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
    route,
)
from binnacle.mcp.job_awareness_live import JobAwarenessHints
from binnacle.mcp.job_awareness_live_ledger import MAX_JOBS_PER_KEY

SESSION, SUBJECT = "v1/" + "S" * 76, "v1/" + "T" * 54
SCHEMA = {
    "type": "object",
    "properties": {"job_id": {"type": "string"}, "state": {"type": "string"}},
}
JOB = "a0b0c0d00001"


KEYER = SessionKeyer("e" * 32)  # one epoch key: one stable kd per conversation


def keyed_outcome() -> RouteOutcome:
    meta = {"openai/session": SESSION, "openai/subject": SUBJECT}
    return route(KEYER, [SESSION], [SUBJECT], meta)


class Identity:
    def __init__(self, name="openai-mcp"):
        self.name = name

    def resolve(self, context):
        if self.name is Exception:
            raise RuntimeError("identity failure")
        return self.name


class Server:
    def __init__(self, schema=SCHEMA):
        self.schema = schema
        self._mcp_server = SimpleNamespace(server_info_stamp={"name": "binnacle"})

    async def get_tool(self, name):
        return (
            None if self.schema is None else SimpleNamespace(output_schema=self.schema)
        )


class Unheld:
    @asynccontextmanager
    async def hold(self, kd):
        yield False


def result(**structured):
    return ToolResult(
        content=[TextContent(type="text", text="done")], structured_content=structured
    )


def context(name, **arguments):
    return SimpleNamespace(message=SimpleNamespace(name=name, arguments=arguments))


def middleware(states=None, **overrides):
    states = {} if states is None else states
    options = {
        "classify": lambda *args: keyed_outcome(),
        "fences": FenceSet(1.0),
        "identity": Identity(),
        "client_names": ("openai-mcp",),
        "job_state": states.get,
        "server": Server(),
    }
    options.update(overrides)
    return JobAwarenessHints(**options)


async def call(mw, ctx, res):
    async def call_next(_):
        return res

    return await mw.on_call_tool(ctx, call_next)


@pytest.fixture
def lines(caplog):
    caplog.set_level(logging.INFO, logger="binnacle.job_awareness")
    return lambda: [r.getMessage() for r in caplog.records]


def started(mw):
    return asyncio.run(
        call(mw, context("run_command"), result(job_id=JOB, state="running"))
    )


def test_emits_once_with_a_direct_composition(lines):
    states = {JOB: {"state": "exited", "exit_code": 0, "signal": None}}
    mw = middleware(states)
    started(mw)
    hinted = asyncio.run(
        call(mw, context("list_files"), result(job_id="x", state="ok"))
    )
    assert "job_awareness_hint" in hinted.structured_content
    assert any("outcome=emitted" in line for line in lines())


def test_busy_fence_returns_the_original_and_keeps_the_job(lines):
    states = {JOB: {"state": "exited"}}
    mw = middleware(states)
    started(mw)
    busy = middleware(states, fences=Unheld(), ledger=mw.ledger)
    original = result(state="ok")
    assert asyncio.run(call(busy, context("list_files"), original)) is original
    assert any("reason=busy" in line for line in lines())
    assert mw.ledger.pending(keyed_outcome().key.kd, 0.0) == (JOB,)


def test_internal_failure_returns_the_original(lines):
    mw = middleware({JOB: {"state": "exited"}})
    started(mw)

    class Broken(Server):
        async def get_tool(self, name):
            raise RuntimeError("registry failure")

    broken = middleware({JOB: {"state": "exited"}}, server=Broken(), ledger=mw.ledger)
    original = result(state="ok")
    assert asyncio.run(call(broken, context("list_files"), original)) is original
    assert any("reason=internal" in line for line in lines())


@pytest.mark.parametrize(
    "overrides",
    [
        {"identity": Identity(Exception)},
        {"classify": lambda *args: (_ for _ in ()).throw(RuntimeError("parser"))},
    ],
)
def test_gate_failures_fail_closed(lines, overrides):
    mw = middleware({JOB: {"state": "exited"}}, **overrides)
    started(mw)
    assert len(mw.ledger) == 0
    assert any("event=ja_route status=UNKNOWN" in line for line in lines())


def test_unkeyed_outcome_is_logged_by_status(lines):
    mw = middleware(classify=lambda *args: RouteOutcome(RouteStatus.MISMATCH))
    started(mw)
    assert any("event=ja_route status=MISMATCH" in line for line in lines())


@pytest.mark.parametrize(
    ("server", "reason"),
    [(Server(None), "schema"), (Server({"type": "array"}), "schema")],
)
def test_missing_or_unsupported_tool_schema_suppresses(lines, server, reason):
    mw = middleware({JOB: {"state": "exited"}}, server=server)
    started(mw)
    original = result(state="ok")
    assert asyncio.run(call(mw, context("list_files"), original)) is original
    assert any(f"reason={reason}" in line for line in lines())


def test_unreadable_or_odd_states_are_not_candidates():
    class States(dict):
        def get(self, job):
            return "not a mapping"

    mw = middleware(states=None, job_state=States().get)
    started(mw)
    original = result(state="ok")
    assert asyncio.run(call(mw, context("list_files"), original)) is original


def running(job):
    return {"state": "running"}


def test_a_full_key_refuses_a_new_binding(lines):
    mw = middleware(job_state=running)
    for n in range(MAX_JOBS_PER_KEY + 1):
        asyncio.run(
            call(
                mw, context("run_command"), result(job_id=f"{n:012x}", state="running")
            )
        )
    assert any("outcome=refused reason=key_full" in line for line in lines())


def test_record_ignores_foreign_shapes():
    mw = middleware(job_state=running)
    started(mw)
    for ctx, res in [
        (context("job_status", job_id="b" * 12), result(job_id=JOB, state="exited")),
        (context("job_status", job_id=JOB), result(job_id=JOB, state="running")),
        (context("job_status", job_id=JOB), "not a result"),
        (context("job_status", job_id=JOB), result(job_id=7)),
        (
            context("job_status", job_id=JOB),
            ToolResult(content=[], structured_content=None),
        ),
    ]:
        asyncio.run(call(mw, ctx, res))
    assert mw.ledger.pending(keyed_outcome().key.kd, 0.0) == (JOB,)


def test_a_job_missing_from_the_store_is_forgotten():
    mw = middleware()  # empty store: job_state returns None
    started(mw)
    asyncio.run(call(mw, context("list_files"), result(state="ok")))
    assert len(mw.ledger) == 0


def test_list_failure_keeps_the_original_list(lines):
    mw = middleware()

    async def call_next(_):
        return [SimpleNamespace(output_schema=SCHEMA, model_copy=None)]

    listed = asyncio.run(mw.on_list_tools(context("x"), call_next))
    assert listed[0].model_copy is None
    assert any("event=ja_list outcome=unchanged" in line for line in lines())


def test_list_for_other_clients_is_the_same_object():
    mw = middleware(identity=Identity("claude-code"))
    tools = [SimpleNamespace(output_schema=SCHEMA)]

    async def call_next(_):
        return tools

    assert asyncio.run(mw.on_list_tools(context("x"), call_next)) is tools

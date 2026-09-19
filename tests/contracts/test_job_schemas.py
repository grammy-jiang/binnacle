"""The job tools' structured output must validate against their own
output schemas for every state, as a strict MCP client checks it.

Found 2026-09-07: exit_code/signal were declared plain integers but are
null for a running job (job_status) and for a signal-killed one (all
three), so fastmcp's Client rejected the result. ChatGPT does not
validate; Claude Code, Codex and the in-memory client do.
"""

import asyncio

from fastmcp import Client

from binnacle import server


def call(name: str, **args) -> dict:
    async def run():
        async with Client(server.mcp) as c:
            r = await c.call_tool(name, args)
            assert r.structured_content is not None
            return r.structured_content

    return asyncio.run(run())


def test_running_job_status_validates():
    p = call("run_command", command="sleep 30", workdir="/tmp", background=True)
    s = call("job_status", job_id=p["job_id"])
    assert s["state"] == "running" and s["exit_code"] is None
    call("stop_job", job_id=p["job_id"])


def test_signal_killed_job_validates_in_all_three_tools():
    p = call("run_command", command="sleep 30", workdir="/tmp", background=True)
    r = call("stop_job", job_id=p["job_id"])
    assert r["state"] == "exited" and r["signal"] == 15 and r["exit_code"] is None
    s = call("job_status", job_id=p["job_id"])
    assert s["signal"] == 15 and s["exit_code"] is None
    k = call("run_command", command="kill -TERM $$", workdir="/tmp")
    assert k["signal"] == 15 and k["exit_code"] is None


def test_listing_validates_with_mixed_states():
    p = call("run_command", command="sleep 30", workdir="/tmp", background=True)
    rows = call("job_status")["jobs"]
    assert any(r["job_id"] == p["job_id"] and r["exit_code"] is None for r in rows)
    call("stop_job", job_id=p["job_id"])

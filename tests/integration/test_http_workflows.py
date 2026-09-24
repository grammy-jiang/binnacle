"""Authenticated HTTP MCP tool workflows over the real ASGI app."""

import asyncio
import json
import logging
import threading
from types import SimpleNamespace

import pytest

from binnacle import jobs as jobstore
from binnacle.blocking_wall_guard import BlockingWallTracker
from binnacle.callctx import current_turn
from binnacle.tools import job_status as js
from binnacle.tools import list_files as lf
from tests.integration.http_test_support import (
    http_tool_call,
    sse_json,
    with_session,
)

pytestmark = pytest.mark.usefixtures("_short_job_warmup")


def test_authenticated_http_file_workflow_round_trip(tmp_path):
    path = tmp_path / "http-flow.txt"

    async def go(c, headers):
        written = await http_tool_call(
            c,
            headers,
            10,
            "write_file",
            {"path": str(path), "content": "alpha\nbeta\n"},
        )
        assert written["result"]["isError"] is False
        assert written["result"]["structuredContent"]["action"] == "created"

        read = await http_tool_call(
            c,
            headers,
            11,
            "read_file",
            {"path": str(path)},
        )
        assert read["result"]["isError"] is False
        assert "beta" in json.dumps(read["result"]["structuredContent"])

        edited = await http_tool_call(
            c,
            headers,
            12,
            "edit_file",
            {
                "path": str(path),
                "old_string": "beta",
                "new_string": "gamma",
            },
        )
        assert edited["result"]["isError"] is False

        searched = await http_tool_call(
            c,
            headers,
            13,
            "search_text",
            {"path": str(tmp_path), "pattern": "gamma"},
        )
        assert searched["result"]["isError"] is False
        assert "http-flow.txt" in json.dumps(searched["result"]["structuredContent"])

        listed = await http_tool_call(
            c,
            headers,
            14,
            "list_files",
            {"path": str(tmp_path)},
        )
        assert listed["result"]["isError"] is False
        assert "http-flow.txt" in json.dumps(listed["result"]["structuredContent"])

    with_session(go, client_name="scenario-audit")
    assert path.read_text() == "alpha\ngamma\n"


def test_authenticated_http_background_job_status_and_stop(tmp_path):
    job_id = None

    async def go(c, headers):
        nonlocal job_id
        started = await http_tool_call(
            c,
            headers,
            20,
            "run_command",
            {
                "command": "sleep 30",
                "workdir": str(tmp_path),
                "background": True,
            },
        )
        assert started["result"]["isError"] is False
        payload = started["result"]["structuredContent"]
        job_id = payload["job_id"]
        assert payload["state"] == "running"
        assert payload["background_job"] is True

        status = await http_tool_call(
            c,
            headers,
            21,
            "job_status",
            {"job_id": job_id, "wait_seconds": 1},
        )
        assert status["result"]["isError"] is False
        assert status["result"]["structuredContent"]["state"] == "running"

        stopped = await http_tool_call(
            c,
            headers,
            22,
            "stop_job",
            {"job_id": job_id},
        )
        assert stopped["result"]["isError"] is False
        final = stopped["result"]["structuredContent"]
        assert final["state"] == "exited"
        assert final["signal"] in (15, 9)

        after = await http_tool_call(
            c,
            headers,
            23,
            "job_status",
            {"job_id": job_id},
        )
        assert after["result"]["structuredContent"]["state"] == "exited"

    try:
        with_session(go, client_name="scenario-audit")
    finally:
        if job_id:
            from binnacle import job_owner, jobs

            try:
                state = jobs.job_state(job_id)
                if state.get("state") == "running":
                    job_owner.stop_job(job_id)
            except (KeyError, OSError):
                pass


def test_http_tool_errors_are_results_not_transport_failures():
    async def go(c, headers):
        outside = await http_tool_call(
            c,
            headers,
            30,
            "read_file",
            {"path": "/etc/passwd"},
        )
        assert outside["result"]["isError"] is True
        assert "outside allowed roots" in outside["result"]["content"][0]["text"]

        invalid = await http_tool_call(
            c,
            headers,
            31,
            "read_file",
            {},
        )
        assert invalid["result"]["isError"] is True
        assert "Missing required argument" in invalid["result"]["content"][0]["text"]

    with_session(go, client_name="scenario-audit")


def test_chatgpt_http_session_hides_and_rejects_edit_tools(tmp_path):
    async def go(c, headers):
        tools = await c.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 40,
                "method": "tools/list",
                "params": {},
            },
            headers=headers,
        )
        assert tools.status_code == 200
        names = {item["name"] for item in sse_json(tools.text)["result"]["tools"]}
        assert names == {
            "read_file",
            "list_files",
            "search_text",
            "run_command",
            "job_status",
            "stop_job",
        }

        hidden = await http_tool_call(
            c,
            headers,
            41,
            "edit_file",
            {
                "path": str(tmp_path / "x"),
                "old_string": "a",
                "new_string": "b",
            },
        )
        assert hidden["result"]["isError"] is True
        assert "not available to this client" in hidden["result"]["content"][0]["text"]

        visible = await http_tool_call(
            c,
            headers,
            42,
            "list_files",
            {"path": str(tmp_path)},
        )
        assert visible["result"]["isError"] is False

    with_session(go, client_name="openai-mcp(ChatGPT)")


def test_http_correlation_headers_reach_tool_log(caplog, tmp_path):
    import hashlib
    import logging

    request_id = "wfr_turn-123/call-4"
    openai_session = "opaque-openai-session"
    expected_hash = hashlib.sha256(openai_session.encode()).hexdigest()[:12]

    async def go(c, headers):
        correlated = {
            **headers,
            "x-request-id": request_id,
            "x-openai-session": openai_session,
        }
        result = await http_tool_call(
            c,
            correlated,
            60,
            "list_files",
            {"path": str(tmp_path)},
        )
        assert result["result"]["isError"] is False

    with caplog.at_level(logging.INFO, logger="binnacle.results"):
        with_session(go, client_name="scenario-audit")

    call_line = next(
        record.getMessage()
        for record in caplog.records
        if "event=tool_call" in record.getMessage()
    )
    result_line = next(
        record.getMessage()
        for record in caplog.records
        if "event=tool_result" in record.getMessage()
    )
    for line in (call_line, result_line):
        assert f"turn={request_id}" in line
        assert f"oai_session={expected_hash}" in line
        assert openai_session not in line


def test_http_concurrent_requests_keep_distinct_base_turns(monkeypatch, tmp_path):
    barrier = threading.Barrier(2)
    seen: list[str | None] = []
    original = lf.list_files_impl

    def capture(path, glob, max_results, include_hidden):
        seen.append(current_turn.get())
        barrier.wait(timeout=5)
        return original(path, glob, max_results, include_hidden)

    monkeypatch.setattr(lf, "list_files_impl", capture)

    async def go(c, headers):
        async def one(rpc_id, request_id):
            return await http_tool_call(
                c,
                {**headers, "x-request-id": request_id},
                rpc_id,
                "list_files",
                {"path": str(tmp_path), "max_results": 1},
            )

        first, second = await asyncio.gather(
            one(70, "turn-alpha/call-1"),
            one(71, "turn-beta/call-1"),
        )
        assert first["result"]["isError"] is False
        assert second["result"]["isError"] is False

    with_session(go, client_name="scenario-audit")

    assert sorted(seen) == ["turn-alpha", "turn-beta"]
    assert current_turn.get() is None


def test_http_tracked_job_status_receives_base_turn_and_client(
    monkeypatch, tmp_path, caplog
):
    job_id = None
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs-http-guard")
    monkeypatch.setattr(jobstore, "OWNER_MODE", "embedded")
    tracker = BlockingWallTracker()
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    budget = SimpleNamespace(
        blocking_wall_budget_for_client=lambda client: (
            3 if client and client.startswith("phase2-http") else None
        )
    )
    monkeypatch.setattr(js, "get_settings", lambda: SimpleNamespace(jobs=budget))

    async def go(c, headers):
        nonlocal job_id
        started = await http_tool_call(
            c,
            headers,
            80,
            "run_command",
            {"command": "sleep 5", "workdir": str(tmp_path), "background": True},
        )
        assert started["result"]["isError"] is False
        job_id = started["result"]["structuredContent"]["job_id"]

        request_id = "turn-http-210/call-status"
        status = await http_tool_call(
            c,
            {**headers, "x-request-id": request_id},
            81,
            "job_status",
            {"job_id": job_id, "wait_seconds": 1},
        )
        assert status["result"]["isError"] is False
        payload = status["result"]["structuredContent"]
        assert payload["state"] == "running"
        assert payload["blocking_policy"] == "tracked"
        assert payload["wait_requested_s"] == 1
        assert payload["wait_effective_s"] == 1
        assert payload["blocking_budget_s"] == 3
        assert payload["blocking_budget_exhausted"] is False

        stopped = await http_tool_call(c, headers, 82, "stop_job", {"job_id": job_id})
        assert stopped["result"]["isError"] is False
        assert stopped["result"]["structuredContent"]["state"] == "exited"

    try:
        with caplog.at_level(logging.INFO):
            with_session(go, client_name="phase2-http")
    finally:
        if job_id is not None:
            from binnacle import job_owner

            state = jobstore.job_state(job_id)
            if state is not None and state["state"] == "running":
                job_owner.stop_job(job_id)

    timing = [
        record.getMessage()
        for record in caplog.records
        if "event=job_status_timing" in record.getMessage()
    ]
    assert any(
        "blocking_policy=tracked" in line
        and "turn=turn-http-210" in line
        and "client=phase2-http" in line
        for line in timing
    )
    assert ("phase2-http", "turn-http-210") in tracker._states

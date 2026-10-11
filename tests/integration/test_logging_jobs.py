"""Journal records for durable jobs (split from test_logging; Linux job engine)."""

import re
import sys
import time
from pathlib import Path

import mcp.types
import pytest

from binnacle.config import RunCommandSettings
from binnacle.features.commands import command_status as js
from binnacle.features.commands import jobs
from binnacle.features.commands.tools import stop_job as sj
from binnacle.mcp.callctx import (
    current_argument_names,
    current_client,
)
from tests.integration.test_logging import _fields, _messages, _run

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY


def test_auto_background_policy_uses_middleware_client(monkeypatch, caplog, run_policy):
    info = mcp.types.Implementation(name="openai-mcp-test", version="1")
    run_policy(
        RunCommandSettings(auto_background_patterns={"openai-mcp": (r"\bsleep\b",)}),
    )
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)
    assert current_client.get() is None

    started_at = time.monotonic()
    with caplog.at_level("INFO"):
        (result,) = _run(
            ("run_command", {"command": "sleep 2", "workdir": "/tmp"}),
            client_info=info,
        )
    elapsed = time.monotonic() - started_at
    payload = result.structured_content
    assert payload is not None
    assert payload["state"] == "running" and payload["background_job"] is True
    assert elapsed < 1
    assert current_client.get() is None
    assert current_argument_names.get() == frozenset()
    dispatch = _fields(_messages(caplog, "run_command_dispatch")[-1])
    assert dispatch["job_id"] == payload["job_id"]
    assert dispatch["owner"] == "embedded"
    assert dispatch["requested_wait_s"] == dispatch["bounded_wait_s"] == "30"
    assert float(dispatch["effective_wait_s"]) == 0.05
    assert dispatch["background_arg"] == "omitted"
    assert dispatch["auto_background"] == "true"
    assert dispatch["handoff_reason"] == "auto_background"
    assert float(dispatch["owner_roundtrip_ms"]) > 0
    assert re.fullmatch(r"[0-9a-f]{12}", dispatch["command_hash"])
    sj.stop_job_impl(payload["job_id"])


def test_job_status_timing_receives_call_start_across_thread_hop(caplog, monkeypatch):
    state = {
        "job_id": "timing-job",
        "state": "running",
        "exit_code": None,
        "signal": None,
        "command": "sleep 30",
        "workdir": "/tmp",
        "pid": 123,
        "pgid": 123,
        "started_at": 1.0,
        "ended_at": None,
        "runtime_s": 10.0,
        "last_output_age_s": 10.0,
        "log_bytes": 0,
        "log_path": "/tmp/out.log",
    }
    monkeypatch.setattr(jobs, "job_state", lambda job_id: state)
    monkeypatch.setattr(jobs, "read_log", lambda job_id: b"")
    monkeypatch.setattr(jobs, "job_processes", lambda pgid, max_cmd_chars=200: [])
    monkeypatch.setattr(
        js, "_wait_for_exit", lambda backend, job_id, wait_seconds: (state, 0.1)
    )

    with caplog.at_level("INFO"):
        _run(
            (
                "job_status",
                {"job_id": "timing-job", "tail_lines": 10, "wait_seconds": 1},
            )
        )

    timing = _messages(caplog, "job_status_timing")
    calls = _messages(caplog, "tool_call")
    results = _messages(caplog, "tool_result")
    assert len(timing) == len(calls) == len(results) == 1
    timing_fields = _fields(timing[0])
    call_fields = _fields(calls[0])
    result_fields = _fields(results[0])
    assert timing_fields["call"] == call_fields["call"] == result_fields["call"]
    assert timing_fields["dispatch_ms"] != "na"
    assert float(timing_fields["dispatch_ms"]) >= 0
    assert float(timing_fields["impl_ms"]) >= 0
    assert timing_fields["wait_requested_s"] == "1"
    assert timing_fields["wait_bounded_s"] == "1"
    assert timing_fields["wait_effective_s"] == "1"
    assert timing_fields["waited_s"] == "0.1"
    assert not any(name.startswith("blocking_") for name in timing_fields)
    assert result_fields["waited_s"] == "0.1"
    assert result_fields["wait_requested_s"] == "1"
    assert result_fields["wait_effective_s"] == "1"
    assert not any(name.startswith("blocking_") for name in result_fields)


def test_job_lines_carry_the_call_id_and_the_outcome(caplog, tmp_path):
    with caplog.at_level("INFO"):
        _run(("run_command", {"command": "printf hi", "workdir": str(tmp_path)}))

    def lines(event, key, value):
        # Per-test isolation: an earlier test's job thread (e.g. a stopped
        # background job) may still log into this capture; keep only ours.
        fields = map(_fields, _messages(caplog, event))
        return [f for f in fields if f.get(key) == value]

    (result,) = lines("tool_result", "tool", "run_command")
    (call,) = lines("tool_call", "call", result["call"])
    starts = lines("job_start", "job_id", result["job_id"])
    exits = lines("job_exit", "job_id", result["job_id"])
    assert len(starts) == 1 and len(exits) == 1
    start, exit_ = starts[0], exits[0]
    # the ContextVar crossed fastmcp's thread hop for the sync tool
    assert start["call"] == call["call"]
    assert start["job_id"] == exit_["job_id"] == result["job_id"]
    assert exit_["exit_code"] == result["exit_code"] == "0"
    assert float(exit_["runtime_s"]) >= 0
    assert exit_["log_bytes"] == "2"
    assert result["state"] == "exited"
    assert result["background_job"] == "false"
    assert result["truncated"] == "false"


def test_job_start_outside_a_tool_call_has_no_call_id(caplog, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        job_id, proc = jobs.start_job("true", Path("/tmp"), None)
        proc.wait()
        jobs.record_exit(job_id, proc)  # what the run_command thread does inline
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        f"event=job_start job_id={job_id}" in m and " call=- owner=embedded " in m
        for m in messages
    )
    assert any(f"event=job_exit job_id={job_id} exit_code=0" in m for m in messages)

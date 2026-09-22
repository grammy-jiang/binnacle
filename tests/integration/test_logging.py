"""Implementation gate for the journal records (logging_middleware, jobs, server).

The inventory of every record and field is docs/logging.md. These tests
drive the real middleware chain through fastmcp's in-memory Client, so a
field that goes missing from the live journal fails here first.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import mcp.types
from fastmcp import Client

from binnacle import jobs, logging_middleware, server
from binnacle.callctx import (
    current_argument_names,
    current_call_started,
    current_client,
)
from binnacle.config import RunCommandSettings
from binnacle.tools import run_command as rc
from binnacle.tools import stop_job as sj


def _messages(caplog, event: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if f"event={event} " in r.getMessage()
    ]


def _fields(line: str) -> dict[str, str]:
    """key=value tokens of one single-line record (free-text tail excluded)."""
    head = re.split(r" (?:args|error)=", line, maxsplit=1)[0]
    return dict(re.findall(r"(\w+)=(\S+)", head))


def _run(*calls, client_info=None):
    async def go():
        kw = {"client_info": client_info} if client_info else {}
        async with Client(server.mcp, **kw) as c:
            out = []
            for name, args in calls:
                out.append(await c.call_tool(name, args, raise_on_error=False))
            return out

    return asyncio.run(go())


def test_request_lines_carry_id_client_and_tool(caplog):
    info = mcp.types.Implementation(name="claude-code", version="1")
    with caplog.at_level("INFO"):
        _run(("list_files", {"path": "/tmp"}), client_info=info)
    lines = [
        r.getMessage() for r in caplog.records if "event=request_" in r.getMessage()
    ]
    call_lines = [ln for ln in lines if "method=tools/call" in ln]
    assert call_lines, "no tools/call request lines captured"
    for ln in call_lines:
        assert "request_id=" in ln
        assert "client=claude-code" in ln
        assert "tool=list_files" in ln


def test_tool_call_start_context_is_reset_after_call(caplog):
    assert current_call_started.get() is None
    with caplog.at_level("INFO"):
        _run(("list_files", {"path": "/tmp", "max_results": 1}))
    assert current_call_started.get() is None


def test_auto_background_policy_uses_middleware_client(monkeypatch, caplog):
    info = mcp.types.Implementation(name="openai-mcp-test", version="1")
    monkeypatch.setattr(
        rc,
        "RUN_SETTINGS",
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


def test_explicit_background_false_overrides_auto_policy(monkeypatch):
    info = mcp.types.Implementation(name="openai-mcp-test", version="1")
    monkeypatch.setattr(
        rc,
        "RUN_SETTINGS",
        RunCommandSettings(auto_background_patterns={"openai-mcp": (r"\bsleep\b",)}),
    )
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)

    (result,) = _run(
        (
            "run_command",
            {
                "command": "sleep 0.15; echo done",
                "workdir": "/tmp",
                "background": False,
            },
        ),
        client_info=info,
    )
    payload = result.structured_content
    assert payload is not None
    assert payload["state"] == "exited" and payload["background_job"] is False
    assert payload["output"] == "done\n"


def test_tool_call_and_result_share_a_call_id_and_carry_sizes(caplog):
    with caplog.at_level("INFO"):
        _run(("list_files", {"path": "/tmp", "max_results": 1}))
    calls = _messages(caplog, "tool_call")
    results = _messages(caplog, "tool_result")
    assert len(calls) == 1 and len(results) == 1
    call, result = _fields(calls[0]), _fields(results[0])
    assert call["tool"] == result["tool"] == "list_files"
    assert re.fullmatch(r"[0-9a-f]{12}", call["call"])
    assert call["call"] == result["call"]
    assert call["session"] == result["session"]
    assert call["request_id"] == result["request_id"] != "-"
    # arguments: full length, then the compact JSON with scalars first
    assert call["args_chars"] == str(len('{"max_results":1,"path":"/tmp"}'))
    assert calls[0].endswith(' args={"max_results":1,"path":"/tmp"}')
    # result: outcome, latency, and the size the client receives
    assert result["is_error"] == "False"
    assert float(result["duration_ms"]) > 0
    assert int(result["content_chars"]) > 0
    assert int(result["structured_bytes"]) > int(result["content_chars"])
    assert (
        int(result["est_tokens"])
        == (int(result["content_chars"]) + int(result["structured_bytes"])) // 4
    )
    # the tool's own facts, lifted from structured_content
    assert result["truncated"] in ("true", "false")
    assert result["count"] == result["entries"] == "1"


def test_tool_result_sizes_measure_the_structured_payload(caplog, tmp_path):
    path = tmp_path / "big.txt"
    path.write_text(("x" * 24 + "\n") * 200)  # 5000 chars, no line clipping
    with caplog.at_level("INFO"):
        _run(("read_file", {"path": str(path)}))
    result = _fields(_messages(caplog, "tool_result")[0])
    # The one-line summary is ~100 chars; the payload holds the 5000 chars.
    assert int(result["content_chars"]) < 200
    assert int(result["structured_bytes"]) > 5000
    assert int(result["est_tokens"]) > 1250
    assert result["kind"] == "text"
    assert result["total_lines"] == result["end_line"] == "200"
    assert result["start_line"] == "1"
    assert result["truncated"] == "false"
    assert "lines_clipped" not in result


def test_read_file_line_clipping_is_lifted_into_the_result_line(caplog, tmp_path):
    path = tmp_path / "long-line.txt"
    path.write_text("y" * 5000 + "\n")
    with caplog.at_level("INFO"):
        _run(("read_file", {"path": str(path)}))
    result = _fields(_messages(caplog, "tool_result")[0])
    assert result["lines_clipped"] == "1"
    assert int(result["structured_bytes"]) < 5000


def test_tool_error_is_a_result_line_with_its_class(caplog):
    with caplog.at_level("INFO"):
        _run(("read_file", {"path": "/etc/passwd"}))
    results = _messages(caplog, "tool_result")
    assert len(results) == 1
    result = _fields(results[0])
    assert result["is_error"] == "True"
    assert result["error_class"] == "ToolError"
    assert result["error_code"] == "path_outside_root"
    assert (
        results[0].endswith(
            "error=Path outside allowed roots (/home/grammy-jiang/Projects, /tmp): /etc/passwd"
        )
        or " error=Path outside allowed roots" in results[0]
    )
    assert "content_chars" not in result
    level = next(
        r.levelname for r in caplog.records if "event=tool_result" in r.getMessage()
    )
    assert level == "WARNING"


def test_unknown_tool_error_has_a_class_too(caplog):
    with caplog.at_level("INFO"):
        _run(("no_such_tool", {}))
    result = _fields(_messages(caplog, "tool_result")[0])
    assert result["is_error"] == "True"
    assert result["error_class"] == "NotFoundError"


def test_args_are_clipped_and_never_multi_line(caplog, tmp_path):
    content = "line one\nline two " + "z" * 2000
    with caplog.at_level("INFO"):
        _run(("write_file", {"path": str(tmp_path / "w.txt"), "content": content}))
    line = _messages(caplog, "tool_call")[0]
    assert "\n" not in line
    args = line.split(" args=", 1)[1]
    assert len(args) == logging_middleware.ARGS_MAX_CHARS + len("...")
    assert args.endswith("...")
    # the short value (path) comes before the long one and survives the clip
    assert args.index('"path"') < args.index('"content"')
    assert int(_fields(line)["args_chars"]) > 2000


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
    monkeypatch.setattr(jobs, "job_processes", lambda pgid: [])

    with caplog.at_level("INFO"):
        _run(("job_status", {"job_id": "timing-job", "tail_lines": 10}))

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


def test_job_lines_carry_the_call_id_and_the_outcome(caplog, tmp_path):
    with caplog.at_level("INFO"):
        _run(("run_command", {"command": "printf hi", "workdir": str(tmp_path)}))
    call = _fields(_messages(caplog, "tool_call")[0])
    result = _fields(_messages(caplog, "tool_result")[0])
    starts = _messages(caplog, "job_start")
    exits = _messages(caplog, "job_exit")
    assert len(starts) == 1 and len(exits) == 1
    start, exit_ = _fields(starts[0]), _fields(exits[0])
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


def test_correlation_headers_are_lifted_when_present(monkeypatch):
    def fake_headers(*args, **kwargs):
        return {
            "x-request-id": "wfr_0123abcd/9zq1",
            "x-openai-session": "v1/secret-session-value",
            "mcp-name": "read_file",
        }

    monkeypatch.setattr(logging_middleware, "get_http_headers", fake_headers)
    fields = logging_middleware._header_fields()
    assert fields["turn"] == "wfr_0123abcd/9zq1"
    assert re.fullmatch(r"[0-9a-f]{12}", fields["oai_session"])
    assert "secret" not in json.dumps(fields)
    assert "mcp-name" not in fields and "mcp_name" not in fields


def test_no_correlation_fields_in_memory():
    assert logging_middleware._header_fields() == {}


def test_prune_line(caplog, tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    store.mkdir()
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    for i in range(jobs.KEEP_NEWEST + 3):
        d = store / f"fake{i:08x}0000"
        d.mkdir()
        (d / "meta.json").write_text(
            '{"command": "x", "workdir": "/tmp", "pid": 1,'
            ' "started_at": 1.0, "ended_at": 2.0, "exit_code": 0}'
        )
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        jobs._prune()
    messages = [r.getMessage() for r in caplog.records]
    assert any("event=jobs_pruned removed=3" in m for m in messages)
    line = next(m for m in messages if "event=jobs_pruned" in m)
    assert "keep_newest=50" in line
    assert "reserve=0" in line
    assert "effective_keep=50" in line


def test_effective_config_line(caplog):
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    lines = [r.getMessage() for r in caplog.records if "event=config" in r.getMessage()]
    assert len(lines) == 1
    fields = _fields(lines[0])
    assert fields["pid"].isdigit()
    assert fields["version"] not in ("", "?")
    assert "keep_newest=" in lines[0] and "client_tools=" in lines[0]
    assert "auto_background=" in lines[0] and "indexed_context=" in lines[0]
    assert "indexed_reconcile=" in lines[0]
    assert "indexed_max_open=" in lines[0]
    assert "tokenizer_enabled=" in lines[0]
    assert "tokenizer_encoding=" in lines[0]
    assert "tokenizer_clients=" in lines[0]
    tool_lines = [
        r.getMessage() for r in caplog.records if "event=tool_config" in r.getMessage()
    ]
    assert len(tool_lines) == 6
    by_tool = {_fields(line)["tool"]: _fields(line) for line in tool_lines}
    assert by_tool["read_file"]["max_chars"] == "24000"
    assert by_tool["search_text"]["result_max_bytes"] == "65536"
    assert by_tool["run_command"]["wait_max_s"] == "50"
    assert by_tool["jobs"]["warmup_s"] == "1.0"
    assert by_tool["jobs"]["configured_owner"] in {"auto", "embedded", "manager"}
    assert by_tool["jobs"]["effective_owner"] in {"embedded", "manager"}
    assert by_tool["jobs"]["stop_sigterm_grace_s"] == "5.0"


def test_result_fields_add_configured_tokenizer_measurement():
    from fastmcp.tools.base import ToolResult

    class FakeCounter:
        encoding = "o200k_base"

        def __init__(self):
            self.parts = ()

        def count(self, parts):
            self.parts = tuple(parts)
            return 23

    counter = FakeCounter()
    result = ToolResult(
        content="Read 1 line.",
        structured_content={"content": "alpha"},
    )

    fields = logging_middleware._result_fields(result, counter)

    assert fields["tokenizer_tokens"] == "23"
    assert fields["tokenizer_encoding"] == "o200k_base"
    assert counter.parts[0] == "Read 1 line."
    assert '"content":"alpha"' in counter.parts[1]


def test_result_fields_never_leak_content():
    """Sizes only: the payload text itself must not appear in the line."""
    from fastmcp.tools.base import ToolResult

    secret = "nonce-8F2K-do-not-log"
    result = ToolResult(content="Read 1 line.", structured_content={"content": secret})
    fields = logging_middleware._result_fields(result)
    assert secret not in json.dumps(fields)
    assert fields["content_chars"] == "12"
    assert fields["structured_bytes"] == str(
        len(json.dumps({"content": secret}, separators=(",", ":")))
    )

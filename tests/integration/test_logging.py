"""Implementation gate for the journal records (logging_middleware, jobs, server).

The inventory of every record and field is docs/logging.md. These tests
drive the real middleware chain through fastmcp's in-memory Client, so a
field that goes missing from the live journal fails here first.
"""

import asyncio
import json
import re
import sys

import mcp.types
import pytest
from fastmcp import Client

from binnacle import server
from binnacle.config import RunCommandSettings
from binnacle.features.commands import jobs
from binnacle.features.files.tools import list_files as lf
from binnacle.mcp import logging_middleware
from binnacle.mcp.callctx import (
    current_call_started,
    current_turn,
)


@pytest.fixture
def tmp_path(default_root_tmp_path):
    return default_root_tmp_path


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


def test_explicit_background_false_overrides_auto_policy(monkeypatch, run_policy):
    info = mcp.types.Implementation(name="openai-mcp-test", version="1")
    # This exercises the embedded engine. Darwin auto composes the manager
    # (JCR-2), which no test runs; Linux fixed its owner at import.
    monkeypatch.setattr(server.get_settings().jobs, "owner", "embedded")
    run_policy(
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
        _run(*[("list_files", {"path": "/tmp", "max_results": 1})] * 2)
    calls = _messages(caplog, "tool_call")
    results = _messages(caplog, "tool_result")
    assert len(calls) == 2 and len(results) == 2
    assert {_fields(line)["server_gen"] for line in calls + results} == {
        logging_middleware.SERVER_GEN
    }
    call, result = _fields(calls[0]), _fields(results[0])
    assert call["tool"] == result["tool"] == "list_files"
    assert re.fullmatch(r"[0-9a-f]{12}", call["call"])
    assert call["call"] == result["call"]
    assert call["session"] == result["session"]
    assert call["request_id"] == result["request_id"] != "-"
    assert call["server_gen"] == result["server_gen"] == logging_middleware.SERVER_GEN
    assert re.fullmatch(r"[0-9a-f]{12}", call["server_gen"])
    assert calls[0].index(" server_gen=") < calls[0].index(" args=")
    # arguments: full length, then the compact JSON with scalars first
    assert call["args_chars"] == str(len('{"max_results":1,"path":"/tmp"}'))
    from binnacle.observability.log_safety import safe_path

    assert calls[0].endswith(
        ' args={"max_results":1,"path":"' + safe_path("/tmp") + '"}'
    )
    assert '"/tmp"' not in calls[0]
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
    line = results[0]
    assert result["server_gen"] == logging_middleware.SERVER_GEN
    assert line.index(" server_gen=") < line.index(" error=")
    assert results[0].endswith(" error=[redacted]")
    assert "/etc/passwd" not in results[0]
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
    assert len(args) < logging_middleware.ARGS_MAX_CHARS
    assert not args.endswith("...")
    assert json.loads(args)["content"] == "[redacted]"
    assert content not in line
    assert int(_fields(line)["args_chars"]) > 2000


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


def test_base_turn_extracts_only_reliable_request_ids():
    assert logging_middleware._base_turn("wfr_0123abcd/9zq1") == "wfr_0123abcd"
    assert logging_middleware._base_turn("base/call/more") == "base"
    for malformed in (None, "", "no-slash", "/call", "turn/"):
        assert logging_middleware._base_turn(malformed) is None


def test_missing_turn_is_none_inside_sync_tool(monkeypatch):
    seen: list[str | None] = []
    original = lf.list_files_impl

    def capture(*args, **kwargs):
        seen.append(current_turn.get())
        return original(*args, **kwargs)

    monkeypatch.setattr(lf, "list_files_impl", capture)
    assert current_turn.get() is None
    _run(("list_files", {"path": "/tmp", "max_results": 1}))
    assert seen == [None]
    assert current_turn.get() is None


def test_base_turn_reaches_sync_tool_and_resets_sequentially(monkeypatch):
    seen: list[str | None] = []
    original = lf.list_files_impl
    headers = {"x-request-id": "turn-a/call-1"}

    def capture(*args, **kwargs):
        seen.append(current_turn.get())
        return original(*args, **kwargs)

    monkeypatch.setattr(lf, "list_files_impl", capture)
    monkeypatch.setattr(logging_middleware, "get_http_headers", lambda: dict(headers))

    _run(("list_files", {"path": "/tmp", "max_results": 1}))
    headers["x-request-id"] = "turn-b/call-2"
    _run(("list_files", {"path": "/tmp", "max_results": 1}))

    assert seen == ["turn-a", "turn-b"]
    assert current_turn.get() is None


def test_base_turn_context_resets_after_tool_exception(monkeypatch):
    monkeypatch.setattr(
        logging_middleware,
        "get_http_headers",
        lambda: {"x-request-id": "turn-error/call-1"},
    )
    assert current_turn.get() is None
    _run(("read_file", {"path": "/etc/passwd"}))
    assert current_turn.get() is None


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


def test_effective_config_line(caplog, monkeypatch):
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    lines = [r.getMessage() for r in caplog.records if "event=config" in r.getMessage()]
    assert len(lines) == 1
    fields = _fields(lines[0])
    assert fields["pid"].isdigit()
    assert fields["version"] not in ("", "?") and fields["revision"]
    assert "keep_newest=" in lines[0] and "client_tools=" in lines[0]
    assert "auto_background=" in lines[0]
    # The indexed-context pilot's fields left the line on 2026-09-28.
    assert "indexed_context=" not in lines[0]
    assert "indexed_reconcile=" not in lines[0]
    assert "indexed_max_open=" not in lines[0]
    assert "tokenizer_enabled=" in lines[0]
    assert "tokenizer_encoding=" in lines[0]
    assert "tokenizer_clients=" in lines[0]
    tool_lines = [
        r.getMessage() for r in caplog.records if "event=tool_config" in r.getMessage()
    ]
    if sys.platform != "linux":
        # Darwin (JCR-2): auto and manager compose the manager owner and log
        # its AVAILABLE rows; only an explicit embedded owner logs the
        # LIMITED/UNAVAILABLE foreground rows. Pin each configured owner.
        expected = {
            "auto": ("manager", "AVAILABLE", "AVAILABLE", "AVAILABLE"),
            "manager": ("manager", "AVAILABLE", "AVAILABLE", "AVAILABLE"),
            "embedded": ("embedded", "LIMITED", "LIMITED", "UNAVAILABLE"),
        }
        for owner, (effective, run, status, stop) in expected.items():
            monkeypatch.setattr(server.get_settings().jobs, "owner", owner)
            caplog.clear()
            with caplog.at_level("INFO", logger="binnacle.server"):
                server.log_effective_config()
            parsed = [_fields(line) for line in _messages(caplog, "tool_config")]
            assert [(f["tool"], f.get("capability")) for f in parsed] == [
                ("read_file", None),
                ("list_files", None),
                ("search_text", None),
                ("run_command", None),
                ("run_command", run),
                ("job_status", status),
                ("stop_job", stop),
                ("edit_file", None),
            ], owner
            by_tool = {f["tool"]: f for f in parsed}
            assert by_tool["read_file"]["max_chars"] == "24000"
            assert by_tool["search_text"]["result_max_bytes"] == "65536"
            assert by_tool["search_text"]["exact_execution"] == "streaming"
            assert parsed[3]["wait_max_s"] == "50"
            (owner_line,) = _messages(caplog, "jobs_owner")
            assert _fields(owner_line)["configured_owner"] == owner
            assert _fields(owner_line)["effective_owner"] == effective
        return
    assert len(tool_lines) == 6
    by_tool = {_fields(line)["tool"]: _fields(line) for line in tool_lines}
    assert by_tool["read_file"]["max_chars"] == "24000"
    assert by_tool["search_text"]["result_max_bytes"] == "65536"
    assert by_tool["search_text"]["exact_execution"] == "streaming"
    assert by_tool["run_command"]["wait_max_s"] == "50"
    assert by_tool["jobs"]["warmup_s"] == "1.0"
    assert "blocking_wall_budget_clients" not in by_tool["jobs"]
    assert "blocking_wall_budgets" not in by_tool["jobs"]
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

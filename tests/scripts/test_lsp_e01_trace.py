"""Deterministic E0/E1 capture analysis: exact joins, eras and privacy gates."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import lsp_e01_trace as trace

SECRET = "DO_NOT_EXPORT_PRIVATE_COMMAND_OR_SOURCE_7331"


def _record(
    event: str,
    call: str,
    *,
    timestamp: str = "2026-10-21T01:00:00+00:00",
    tool: str = "search_text",
    arguments: dict | None = None,
    gen: str = "g",
    session: str | None = None,
    turn: str | None = None,
    result: dict | None = None,
) -> dict:
    session = session or f"session-{call}"
    correlation = {
        "server_gen": gen,
        "call": call,
        "session": session,
        "request_id": "2",
        "client": "openai-mcp",
    }
    if turn is not None:
        correlation["turn"] = turn
    obj = {
        "schema": 1,
        "timestamp": timestamp,
        "event": event,
        "correlation": correlation,
    }
    if event == "tool_call":
        obj.update(tool_name=tool, arguments=arguments)
    elif event == "tool_result":
        obj["result"] = {
            "content": [{"text": SECRET}],
            "is_error": False,
            "structured_content": result or {"truncated": False},
        }
    elif event == "mcp_request":
        obj["method"] = "tools/call"
        obj["payload"] = {"name": tool, "arguments": arguments}
    elif event == "tool_error":
        obj["error"] = SECRET
    return obj


def _calls(actions: list[tuple[str, str, dict, dict | None, int, str]]) -> list[dict]:
    rows = []
    for ident, tool, args, result, elapsed, source in actions:
        stamp = f"2026-10-21T01:{elapsed // 60:02d}:{elapsed % 60:02d}+00:00"
        for event in ("mcp_request", "tool_call", "tool_result"):
            rows.append(
                _record(
                    event,
                    ident,
                    tool=tool,
                    arguments=args,
                    result=result,
                    timestamp=stamp,
                    turn=source,
                )
            )
    return rows


def _write(folder: Path, rows: list[dict], *, bad=False, torn=False) -> Path:
    folder.mkdir(exist_ok=True)
    path = folder / "2026-10-21.jsonl"
    with path.open("wb") as stream:
        for record in rows:
            stream.write((json.dumps(record, ensure_ascii=True) + "\n").encode())
        if bad:
            stream.write(b"{not json}\n")
        if torn:
            stream.write(b'{"event":"tool_call","command":"secret')
    return path


def _observer(path: Path, keys: list[tuple[str, str, str, str]]) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE calls (gen TEXT, call TEXT, request_hash TEXT)")
    con.execute("CREATE TABLE tunnel_events (request_hash TEXT, base_hash TEXT)")
    for gen, call, request, base in keys:
        con.execute("INSERT INTO calls VALUES (?,?,?)", (gen, call, request))
        con.execute("INSERT INTO tunnel_events VALUES (?,?)", (request, base))
    con.commit()
    con.close()


def test_complete_group_windows_not_measured_savings(tmp_path):
    actions = [
        ("a", "search_text", {"pattern": r"def " + SECRET}, None, 0, "T/1"),
        ("b", "read_file", {"path": f"/private/{SECRET}"}, None, 4, "T/2"),
        ("c", "run_command", {"command": f"git diff -- {SECRET}"}, None, 8, "T/3"),
        ("d", "read_file", {"path": f"/private/{SECRET}"}, None, 11, "T/4"),
        ("e", "run_command", {"command": "pytest -q"}, {"exit_code": 1}, 15, "T/5"),
        ("f", "read_file", {"path": f"/private/{SECRET}"}, None, 20, "T/6"),
        ("g", "run_command", {"command": "ruff check src"}, None, 25, "T/7"),
        ("h", "search_text", {"pattern": SECRET}, None, 27, "T/8"),
    ]
    capture = tmp_path / "capture"
    _write(capture, _calls(actions))
    observer = tmp_path / "observer.sqlite3"
    _observer(
        observer, [("g", ident, "req" + ident, "base-1") for ident, *_ in actions]
    )
    before = (observer.stat().st_size, observer.stat().st_mtime_ns)
    report = trace.analyze(capture, observer)
    assert before == (observer.stat().st_size, observer.stat().st_mtime_ns)
    assert report["calls"]["total"] == 8
    assert report["request_pairing"]["exact_argument_match"] == 8
    assert report["grouping"]["source_counts"]["observer"] == 8
    assert report["grouping"]["distinct_request_groups"] == 1
    opportunities = report["opportunity_windows"]
    assert opportunities["search_then_read"]["windows"] == 1
    assert opportunities["symbol_query_then_read"]["windows"] == 1
    assert opportunities["git_change_then_inspect"]["windows"] == 1
    assert opportunities["git_change_inspect_then_test"]["windows"] == 1
    assert opportunities["failed_test_then_inspect"]["windows"] == 1
    assert opportunities["lint_then_inspect"]["windows"] == 1
    assert report["candidate_command_labels_nonexclusive"]["test"] == 1
    encoded = json.dumps(report)
    assert SECRET not in encoded
    assert "/private/" not in encoded
    assert "base-1" not in encoded
    assert "reqa" not in encoded
    assert "session-a" not in encoded
    assert "T/1" not in encoded
    assert report["evidence"] == "retrospective_candidates_not_measured_savings"


def test_duplicate_terminal_does_not_enter_windows(tmp_path):
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Foo"}, None, 0, "T/1"),
            ("b", "read_file", {"path": "Foo.py"}, None, 1, "T/2"),
        ]
    )
    rows.append(rows[2])
    root = tmp_path / "capture"
    _write(root, rows)
    db = tmp_path / "observer.sqlite3"
    _observer(db, [("g", "a", "ha", "group"), ("g", "b", "hb", "group")])
    out = trace.analyze(root, db)
    assert out["calls"]["duplicate_terminals_excluded"] == 1
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_ambiguous_observer_cannot_infer_task_base(tmp_path):
    root = tmp_path / "capture"
    _write(
        root,
        _calls(
            [
                ("a", "search_text", {"pattern": "def thing"}, None, 0, ""),
                ("b", "read_file", {"path": "thing.py"}, None, 2, ""),
            ]
        ),
    )
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [
            ("g", "a", "collision", "different-1"),
            ("g", "a", "collision", "different-2"),
            ("g", "b", "request-b", "different-1"),
        ],
    )
    out = trace.analyze(root, db)
    assert out["grouping"]["source_counts"]["ambiguous_observer"] == 1
    assert out["grouping"]["ambiguous_observer_keys"] == 1
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_unsupported_turn_format_and_no_db_are_not_grouped(tmp_path):
    root = tmp_path / "capture"
    _write(
        root,
        _calls(
            [
                ("a", "search_text", {"pattern": SECRET}, None, 0, "unknown/foo"),
                ("b", "read_file", {"path": SECRET}, None, 2, "unknown/bar"),
            ]
        ),
    )
    out = trace.analyze(root)
    assert out["grouping"]["exactly_grouped_calls"] == 0
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_header_turn_fallback_only_with_exact_wfr_shape(tmp_path):
    root = tmp_path / "capture"
    _write(
        root,
        _calls(
            [
                ("a", "search_text", {"pattern": "class"}, None, 0, "wfr_same/1"),
                ("b", "read_file", {"path": "safe"}, None, 1, "wfr_same/2"),
            ]
        ),
    )
    out = trace.analyze(root)
    assert out["grouping"]["source_counts"]["header_turn"] == 2
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 1


@pytest.mark.parametrize("gap", [301, 1000])
def test_time_window_is_bounded(tmp_path, gap):
    # Datetime values must be valid; longer gap means separate exact UTC times.
    rows = [
        _record(
            event,
            "a",
            timestamp="2026-10-21T01:00:00+00:00",
            tool="search_text",
            arguments={"pattern": "def"},
        )
        for event in ("mcp_request", "tool_call", "tool_result")
    ] + [
        _record(
            event,
            "b",
            timestamp=f"2026-10-21T01:{gap // 60:02d}:{gap % 60:02d}+00:00",
            tool="read_file",
            arguments={"path": "foo"},
        )
        for event in ("mcp_request", "tool_call", "tool_result")
    ]
    root = tmp_path / "capture"
    _write(root, rows)
    db = tmp_path / "observer.sqlite3"
    _observer(db, [("g", "a", "a", "one"), ("g", "b", "b", "one")])
    result = trace.analyze(root, db)
    assert result["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_malformed_and_incomplete_lines_are_never_emitted(tmp_path):
    root = tmp_path / "capture"
    _write(root, [], bad=True, torn=True)
    report = trace.analyze(root)
    assert report["coverage"]["invalid_json"] == 1
    assert report["coverage"]["incomplete_lines"] == 1
    assert report["calls"]["total"] == 0
    assert SECRET not in json.dumps(report)


def test_missing_redacted_and_invalid_commands_are_unknown(tmp_path):
    rows = _calls(
        [
            ("a", "run_command", {"command": "[redacted]"}, None, 0, "wfr_t/1"),
            ("b", "run_command", {"command": 18}, None, 1, "wfr_t/2"),
            ("c", "run_command", {"command": "pytest -q"}, None, 2, "wfr_t/3"),
        ]
    )
    root = tmp_path / "capture"
    _write(root, rows)
    out = trace.analyze(root)
    states = out["calls"]["input_states"]
    assert states["run_command:redacted"] == 1
    assert states["run_command:missing"] == 1
    assert states["run_command:present"] == 1
    assert out["candidate_command_labels_nonexclusive"]["test"] == 1


def test_tool_name_payload_unsafe_never_echoed(tmp_path):
    rows = _calls(
        [
            ("a", SECRET, {"command": SECRET, "path": SECRET}, None, 0, "wfr_x/1"),
        ]
    )
    root = tmp_path / "capture"
    _write(root, rows)
    out = trace.analyze(root)
    assert out["calls"]["tools"] == {"other": 1}
    assert SECRET not in json.dumps(out)


def test_request_mismatch_and_duplicate_are_not_trusted(tmp_path):
    rows = _calls(
        [
            ("a", "run_command", {"command": "git diff"}, None, 0, "wfr_x/1"),
            ("b", "read_file", {"path": SECRET}, None, 1, "wfr_x/2"),
        ]
    )
    rows[0]["payload"]["arguments"] = {"command": "different secret command"}
    rows.append(rows[3])
    root = tmp_path / "capture"
    _write(root, rows)
    out = trace.analyze(root)
    assert out["request_pairing"]["request_mismatch"] == 1
    assert out["request_pairing"]["ambiguous_request"] == 1
    assert "different secret" not in json.dumps(out)


def test_tool_error_does_not_count_as_success(tmp_path):
    rows = [
        _record(
            "mcp_request", "a", tool="run_command", arguments={"command": "pytest -q"}
        ),
        _record(
            "tool_call", "a", tool="run_command", arguments={"command": "pytest -q"}
        ),
        _record("tool_error", "a", tool="run_command"),
    ]
    root = tmp_path / "capture"
    _write(root, rows)
    out = trace.analyze(root)
    assert out["calls"]["outcomes"]["error"] == 1
    assert "result" not in out["calls"]["outcomes"]


def test_synthetic_legacy_redaction_cannot_supply_missing_source(tmp_path):
    root = tmp_path / "capture"
    rows = _calls([("a", "search_text", {"pattern": "[redacted]"}, None, 0, "")])
    _write(root, rows)
    out = trace.analyze(root)
    assert out["calls"]["input_states"]["search_text:redacted"] == 1
    assert out["candidate_command_labels_nonexclusive"]["text_search"] == 1
    assert (
        out["candidate_command_labels_nonexclusive"].get("code_structure_query", 0) == 0
    )

"""E0/E1 negative trace evidence: reject false joins, ordering and disclosure."""

from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from scripts import lsp_e01_trace as engine
from scripts.lsp_e01_patterns import _label
from tests.scripts.test_lsp_e01_trace import SECRET, _calls, _observer, _record, _write


def test_no_exact_pair_without_session_and_request_id(tmp_path):
    rows = _calls([("a", "search_text", {"pattern": "def thing"}, None, 0, "")])
    for row in rows:
        row["correlation"].pop("session")
        row["correlation"].pop("request_id")
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["request_pairing"].get("exact_argument_match", 0) == 0
    assert out["request_pairing"]["missing_identity"] == 1
    assert out["calls"]["total"] == 1
    assert out["grouping"]["exactly_grouped_calls"] == 0


def test_request_ids_keep_int_and_string_distinct(tmp_path):
    rows = _calls([("a", "search_text", {"pattern": "class X"}, None, 0, "")])
    rows[0]["correlation"]["request_id"] = 2
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["request_pairing"]["missing_request"] == 1
    assert out["request_pairing"].get("exact_argument_match", 0) == 0


def test_different_invalid_tool_names_cannot_pair_as_other(tmp_path):
    rows = _calls([("a", SECRET + "1", {"command": "hello"}, None, 0, "")])
    rows[0]["payload"]["name"] = SECRET + "2"
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["request_pairing"]["request_mismatch"] == 1
    assert out["calls"]["tools"] == {"other": 1}
    assert SECRET not in json.dumps(out)


def test_mismatched_and_duplicate_requests_are_excluded_from_windows(tmp_path):
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Symbol"}, None, 0, ""),
            ("b", "read_file", {"path": SECRET}, None, 2, ""),
            ("c", "search_text", {"pattern": "def function"}, None, 6, ""),
            ("d", "read_file", {"path": SECRET}, None, 8, ""),
        ]
    )
    rows[0]["payload"]["arguments"] = {"pattern": "different"}
    rows.append(dict(rows[6]))  # duplicate request for c
    root = _write(tmp_path / "capture", rows).parent
    db = tmp_path / "obs.db"
    _observer(db, [("g", ch, f"hash-{ch}", "base") for ch in "abcd"])
    out = engine.analyze(root, db)
    assert out["request_pairing"]["request_mismatch"] == 1
    assert out["request_pairing"]["ambiguous_request"] == 1
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0
    assert out["grouping"]["source_counts"]["excluded_unpaired"] == 2


def test_partial_observer_alternatives_do_not_count_as_exact(tmp_path):
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class"}, None, 0, ""),
            ("b", "read_file", {"path": "x"}, None, 1, ""),
        ]
    )
    root = _write(tmp_path / "capture", rows).parent
    db = tmp_path / "obs.db"
    _observer(
        db,
        [
            ("g", "a", "known-hash", "base"),
            ("g", "b", "other-hash", "base"),
        ],
    )
    con = sqlite3.connect(db)
    con.execute("INSERT INTO calls VALUES (?,?,?)", ("g", "a", "unresolved-hash"))
    con.commit()
    con.close()
    out = engine.analyze(root, db)
    assert out["grouping"]["ambiguous_observer_keys"] == 1
    assert out["grouping"]["source_counts"]["ambiguous_observer"] == 1
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_invalid_event_and_unencodable_command_are_quarantined(tmp_path):
    rows = _calls([("a", "run_command", {"command": "git status"}, None, 0, "")])
    rows.extend(
        [
            {"event": [], "timestamp": "2026-10-21T01:00:00Z"},
            {
                "event": "tool_call",
                "timestamp": "2026-10-21T01:00:00Z",
                "tool_name": "run_command",
                "correlation": {
                    "server_gen": "g",
                    "call": "escaped",
                    "session": "invalid",
                    "request_id": "2",
                },
                "arguments": {"command": "whoops\ud800 secret"},
            },
        ]
    )
    root = _write(tmp_path / "capture", rows).parent
    out = engine.analyze(root)
    assert out["coverage"]["invalid_record_shape"] == 1
    assert out["coverage"]["invalid_tool_call_payload"] == 1
    assert out["calls"]["total"] == 1
    assert "\ud800" not in json.dumps(out)


def test_utc_date_and_z_time_in_python_310(tmp_path):
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Foo"}, None, 0, "wfr_abc/1"),
            ("b", "read_file", {"path": "Foo.py"}, None, 1, "wfr_abc/2"),
        ]
    )
    rows[0]["timestamp"] = "2026-10-21T00:30:00+02:00"
    rows[1]["timestamp"] = "2026-10-21T00:30:00+02:00"
    rows[2]["timestamp"] = "2026-10-21T00:30:00+02:00"
    for row in rows[3:]:
        row["timestamp"] = "2026-10-20T22:30:05Z"
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["coverage"]["days_utc"] == {"2026-10-20": 6}
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 1


def test_terminals_can_precede_calls_in_file_iteration(tmp_path):
    earlier = tmp_path / "2026-10-20.jsonl"
    later = tmp_path / "2026-10-21.jsonl"
    result = _record("tool_result", "a", timestamp="2026-10-21T01:00:01Z")
    earlier.write_text(json.dumps(result) + "\n")
    rows = [
        _record("mcp_request", "a", timestamp="2026-10-21T01:00:00Z"),
        _record("tool_call", "a", timestamp="2026-10-21T01:00:00Z"),
        _record("tool_result", "orphan", timestamp="2026-10-21T01:00:01Z"),
    ]
    later.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = engine.analyze(tmp_path)
    assert out["calls"]["outcomes"]["result"] == 1
    assert out["coverage"]["orphan_terminals"] == 1
    assert out["request_pairing"]["exact_argument_match"] == 1


def test_double_terminals_after_out_of_order_join_are_excluded(tmp_path):
    root = tmp_path / "capture"
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Foo"}, None, 0, "wfr_abc/1"),
            ("b", "read_file", {"path": "Foo.py"}, None, 1, "wfr_abc/2"),
        ]
    )
    rows.insert(0, rows[2])  # duplicate terminal before tool_call
    out = engine.analyze(_write(root, rows).parent)
    assert out["calls"]["duplicate_terminals_excluded"] == 1
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_equal_timestamps_do_not_create_ordered_window(tmp_path):
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Foo"}, None, 0, "wfr_abc/1"),
            ("b", "read_file", {"path": "Foo.py"}, None, 0, "wfr_abc/2"),
        ]
    )
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 0


def test_failed_test_must_have_ended_before_inspection(tmp_path):
    rows = _calls(
        [
            (
                "a",
                "run_command",
                {"command": "pytest -q"},
                {"exit_code": 1},
                0,
                "wfr_abc/1",
            ),
            ("b", "read_file", {"path": "foo.py"}, None, 4, "wfr_abc/2"),
        ]
    )
    rows[2]["timestamp"] = "2026-10-21T01:00:09Z"
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["opportunity_windows"]["failed_test_then_inspect"]["windows"] == 0


@pytest.mark.parametrize(
    ("tool", "arg", "label", "state"),
    [
        ("run_command", {"command": "echo pytest"}, "test", "present"),
        ("run_command", {"command": "/usr/bin/rg symbol"}, "text_search", "present"),
        ("run_command", {"command": "pytest [truncated]"}, "test", "incomplete"),
        (
            "run_command",
            {"command": "uv run --offline python -m pytest -q"},
            "test",
            "present",
        ),
        (
            "run_command",
            {"command": "python3 -m ruff check src"},
            "lint_typecheck",
            "present",
        ),
    ],
)
def test_command_lexical_evidence_is_conservative(tool, arg, label, state):
    labels, actual_state = _label(tool, arg)
    assert actual_state == state
    assert (label in labels) == ("echo" not in arg["command"] and state == "present")


def test_cli_sanitizes_bad_database_error(tmp_path, monkeypatch, capsys):
    root = tmp_path / "captures"
    _write(root, [])
    sentinel = SECRET + "-database"
    db = tmp_path / sentinel
    db.write_bytes(b"not sqlite")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "e01",
            "--capture-dir",
            str(root),
            "--observer-db",
            str(db),
        ],
    )
    assert engine.main() == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "E01_ANALYSIS_FAILED:" in captured.err
    assert sentinel not in captured.err


def test_large_command_is_not_clipped_or_disclosed(tmp_path):
    command = "git diff -- " + SECRET + "x" * 130_000
    rows = _calls([("a", "run_command", {"command": command}, None, 0, "")])
    out = engine.analyze(_write(tmp_path / "captures", rows).parent)
    assert out["request_pairing"]["exact_argument_match"] == 1
    assert out["candidate_command_labels_nonexclusive"]["git_change"] == 1
    assert SECRET not in json.dumps(out)


def test_negative_terminal_chronology_cannot_create_failure_window(tmp_path):
    rows = _calls(
        [
            (
                "a",
                "run_command",
                {"command": "pytest -q"},
                {"exit_code": 1},
                10,
                "wfr_t/1",
            ),
            ("b", "read_file", {"path": "foo.py"}, None, 20, "wfr_t/2"),
        ]
    )
    rows[2]["timestamp"] = "2026-10-21T01:00:05Z"  # before call start
    result = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert result["calls"]["negative_duration_terminals"] == 1
    assert result["calls"]["outcomes"]["invalid_chronology"] == 1
    assert result["opportunity_windows"]["failed_test_then_inspect"]["windows"] == 0
    assert result["grouping"]["source_counts"]["excluded_unreliable_outcome"] == 1


def test_frozen_cutoff_excludes_later_history_but_reports_missingness(tmp_path):
    from datetime import datetime, timezone

    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class A"}, None, 0, "wfr_t/1"),
            ("b", "read_file", {"path": "a.py"}, None, 2, "wfr_t/2"),
            ("c", "run_command", {"command": "pytest -q"}, None, 3, "wfr_t/3"),
        ]
    )
    rows[6]["timestamp"] = "2026-10-21T01:01:00Z"
    rows[7]["timestamp"] = "2026-10-21T01:01:00Z"
    rows[8]["timestamp"] = "2026-10-21T01:01:00Z"
    capture = _write(tmp_path / "capture", rows).parent
    cutoff = datetime(2026, 10, 21, 1, 0, 30, tzinfo=timezone.utc)
    out = engine.analyze(capture, until_utc=cutoff)
    assert out["calls"]["total"] == 2
    assert out["coverage"]["after_cutoff_excluded"] == 3
    assert out["coverage"]["included_rows"] == 6
    assert out["coverage"]["until_utc"] == "2026-10-21T01:00:30+00:00"
    assert out["opportunity_windows"]["search_then_read"]["windows"] == 1

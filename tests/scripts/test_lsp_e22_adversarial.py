"""Adversarial E2.2 source provenance and bounded external-session scanning."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts import lsp_e22_sessions as sessions
from tests.scripts.test_lsp_e22_sessions import (
    _call,
    _codex,
    _file,
    scan_independent_sessions,
)

CUTOFF = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)


def test_other_mcp_server_cannot_create_compatible_call(tmp_path):
    args = {"command": "git status"}
    rows = _codex(args)
    rows[-1]["payload"]["name"] = "mcp__unrelated_service__run_command"
    _file(tmp_path, "codex", rows)
    matches, info = scan_independent_sessions(
        tmp_path,
        [_call(args)],
        CUTOFF,
    )
    assert not matches
    assert info["compatible_agent_tool_signatures"] == 0


def test_time_tolerance_does_not_create_identity_proof(tmp_path):
    args = {"command": "git status"}
    _file(tmp_path, "codex", _codex(args, time="2026-10-21T01:00:12Z"))
    matches, info = scan_independent_sessions(
        tmp_path,
        [_call(args)],
        CUTOFF,
    )
    assert not matches
    assert info["compatible_agent_tool_signatures"] == 0


def test_incomplete_session_read_downgrades_unique_candidate(tmp_path, monkeypatch):
    args = {"command": "git status"}
    rows = _codex(args)
    rows.append(rows[-1])  # duplicate call would invalidate uniqueness
    _file(tmp_path, "codex", rows)
    monkeypatch.setattr(sessions, "MAX_LINES", 2)
    matches, info = scan_independent_sessions(
        tmp_path,
        [_call(args)],
        CUTOFF,
    )
    assert not matches
    assert info["agent_file_read_limit"] == 1
    assert info["candidate_links_downgraded_by_partial_scan"] == 1
    assert info["compatible_agent_tool_signatures"] == 0


def test_symlink_session_not_read_or_counted_as_direct_evidence(tmp_path):
    args = {"command": "git status"}
    external = tmp_path / "elsewhere.jsonl"
    external.write_text("".join(json.dumps(e) + "\n" for e in _codex(args)))
    folder = tmp_path / ".codex" / "sessions" / "a"
    folder.mkdir(parents=True)
    (folder / "synthetic.jsonl").symlink_to(external)
    matches, info = scan_independent_sessions(
        tmp_path,
        [_call(args)],
        CUTOFF,
    )
    assert not matches
    assert info["session_source_incomplete"] >= 1


def test_malformed_session_row_invalidates_candidate_uniqueness(tmp_path):
    args = {"command": "git status"}
    file = _file(tmp_path, "codex", _codex(args))
    with file.open("a") as out:
        out.write('{"timestamp":\n')
    links, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not links
    assert counts["session_source_incomplete"] >= 1
    assert counts["compatible_agent_tool_signatures"] == 0


def test_symlink_ancestor_is_not_an_agent_source(tmp_path):
    args = {"command": "git status"}
    real = tmp_path / "unrelated-session-root"
    folder = real / "sessions" / "a"
    folder.mkdir(parents=True)
    (folder / "sample.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in _codex(args))
    )
    (tmp_path / ".codex").symlink_to(real, target_is_directory=True)
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert counts["session_source_incomplete"] >= 1


def test_embedded_identifier_is_not_a_literal_standalone_task_ref():
    from scripts.lsp_e22_sources import task_refs

    assert task_refs("X.P1.9") == frozenset()
    assert task_refs("X.TASK-12345") == frozenset()
    assert task_refs("P1.2.3.4.5") == frozenset()
    assert task_refs("p1.9") == frozenset()
    assert task_refs("P1.9") == frozenset({"P1.9"})


def test_session_read_failure_does_not_certify_unique_signature(tmp_path, monkeypatch):
    args = {"command": "git status"}
    file = _file(tmp_path, "codex", _codex(args))
    real_open = sessions.os.open

    def denied(path, *other, **options):
        if str(path) == str(file):
            raise PermissionError("synthetic inaccessible source")
        return real_open(path, *other, **options)

    monkeypatch.setattr(sessions.os, "open", denied)
    matched, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matched
    assert counts["session_source_incomplete"] > 0
    assert counts["compatible_agent_tool_signatures"] == 0


def test_unreadable_subdirectory_downgrades_otherwise_unique_match(
    tmp_path, monkeypatch
):
    import os

    args = {"command": "git status"}
    _file(tmp_path, "codex", _codex(args))
    hidden_dir = tmp_path / ".codex" / "sessions" / "unreadable"
    hidden_dir.mkdir(parents=True)
    (hidden_dir / "another.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in _codex(args))
    )
    original_scandir = os.scandir

    def blocked(path):
        if str(path) == str(hidden_dir):
            raise PermissionError("synthetic session subtree unavailable")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", blocked)
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert counts["session_source_incomplete"] >= 1
    assert counts["compatible_agent_tool_signatures"] == 0
    assert counts["candidate_links_downgraded_by_partial_scan"] == 1


def test_old_file_mtime_exclusion_downgrades_unique_match(tmp_path):
    import os
    from datetime import datetime, timezone

    args = {"command": "git status"}
    fresh = _file(tmp_path, "codex", _codex(args))
    historical = fresh.with_name("prior.jsonl")
    historical.write_text(fresh.read_text())
    earlier = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()
    os.utime(historical, (earlier, earlier))
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert counts["mtime_early_session_files_skipped"] == 1
    assert counts["session_source_incomplete"] >= 1
    assert counts["candidate_links_downgraded_by_partial_scan"] == 1
    assert counts["compatible_agent_tool_signatures"] == 0


def test_unknown_tool_message_timestamp_invalidates_uniqueness(tmp_path):
    args = {"command": "git status"}
    rows = _codex(args)
    duplicate = dict(rows[-1])
    duplicate["timestamp"] = "invalid"
    rows.append(duplicate)
    _file(tmp_path, "codex", rows)
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert counts["session_source_incomplete"] >= 1
    assert counts["candidate_links_downgraded_by_partial_scan"] == 1
    assert counts["compatible_agent_tool_signatures"] == 0

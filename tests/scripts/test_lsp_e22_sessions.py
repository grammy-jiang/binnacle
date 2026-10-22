"""Independent agent-session matches require exact tool/arguments and chronology."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lsp_e01_trace import Call, _digest
from scripts.lsp_e22_sessions import scan_independent_sessions as scan_native_sessions


def scan_independent_sessions(home, targets, cutoff, *, server_name="MacBook_Pro_MCP"):
    """Synthetic Codex rows name MacBook_Pro_MCP on ALL test platforms.

    Explicit Raspberry_Pi_MCP overrides in Claude/Pi fixtures are forwarded;
    never choose this test's agent identity from the runner's hostname.
    """
    return scan_native_sessions(home, targets, cutoff, server_name=server_name)


HIDDEN = "DO_NOT_REPRINT_SESSION_PROMPT_777"
TIME = "2026-10-21T01:00:00+00:00"
CUTOFF = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)


def _call(argument: dict, *, call_id="1", moment=TIME) -> Call:
    t = datetime.fromisoformat(moment.replace("Z", "+00:00")).timestamp()
    return Call(
        key=("generation", call_id),
        tool="run_command",
        when=t,
        group=("header_turn", "wfr_t"),
        join_source="header_turn",
        request_key=("session", ("str", call_id)),
        raw_tool_name="run_command",
        arguments_sha=_digest(argument),
        categories=frozenset({"git_read"}),
        raw_state="present",
        status="result",
    )


def _file(home: Path, service: str, rows: list[dict]) -> Path:
    locations = {
        "codex": ".codex/sessions/a",
        "claude": ".claude/projects/a",
        "pi": ".pi/agent/sessions/a",
    }
    folder = home / locations[service]
    folder.mkdir(parents=True)
    path = folder / "synthetic.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def _codex(args: dict, *, with_user=True, time=TIME) -> list[dict]:
    items = []
    if with_user:
        items.append(
            {
                "timestamp": "2026-10-21T00:59:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": HIDDEN}],
                },
            }
        )
    items.append(
        {
            "timestamp": time,
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "mcp__MacBook_Pro_MCP__run_command",
                "arguments": json.dumps(args),
            },
        }
    )
    return items


def test_codex_exact_tool_and_prior_user_role_only_candidate(tmp_path):
    args = {"command": "git status --porcelain", "workdir": "/synthetic"}
    _file(tmp_path, "codex", _codex(args))
    matches, info = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert matches[("generation", "1")]["unique_compatible_invocation"] is True
    assert matches[("generation", "1")]["preceded_by_session_user_role"] is True
    assert info["compatible_agent_tool_signatures"] == 1
    assert info["compatible_signatures_with_prior_user_role"] == 1
    assert HIDDEN not in json.dumps(info)


def test_tool_text_change_cannot_match_generic_command(tmp_path):
    expected = {"command": "git diff -U3"}
    _file(tmp_path, "codex", _codex({"command": "git diff -U0"}))
    matches, report = scan_independent_sessions(tmp_path, [_call(expected)], CUTOFF)
    assert not matches
    assert report["compatible_agent_tool_signatures"] == 0


def test_two_candidate_calls_sharing_same_arguments_cannot_crosslink(tmp_path):
    args = {"command": "git status"}
    _file(tmp_path, "codex", _codex(args))
    second = _call(args, call_id="2", moment="2026-10-21T01:00:01Z")
    matches, counts = scan_independent_sessions(tmp_path, [_call(args), second], CUTOFF)
    assert not matches
    assert counts["ambiguous_agent_tool_signatures"] == 2


def test_missing_prior_user_message_is_not_a_prompt_anchor(tmp_path):
    args = {"command": "git status"}
    _file(tmp_path, "codex", _codex(args, with_user=False))
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert matches[("generation", "1")]["unique_compatible_invocation"] is True
    assert matches[("generation", "1")]["preceded_by_session_user_role"] is False
    assert counts["compatible_signatures_with_prior_user_role"] == 0


def test_tool_message_after_cutoff_not_a_contemporaneous_anchor(tmp_path):
    args = {"command": "git status"}
    _file(tmp_path, "codex", _codex(args, time="2026-10-21T02:01:00Z"))
    matches, counts = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert counts["compatible_agent_tool_signatures"] == 0


def test_claude_native_tool_use_with_user_role_matches(tmp_path):
    args = {"command": "pytest -q"}
    rows = [
        {
            "type": "user",
            "timestamp": "2026-10-21T00:59:00Z",
            "message": {"role": "user", "content": HIDDEN},
        },
        {
            "type": "assistant",
            "timestamp": TIME,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "mcp__Raspberry_Pi_MCP__run_command",
                        "input": args,
                    }
                ],
            },
        },
    ]
    _file(tmp_path, "claude", rows)
    matches, info = scan_independent_sessions(
        tmp_path, [_call(args)], CUTOFF, server_name="Raspberry_Pi_MCP"
    )
    assert matches[("generation", "1")]["preceded_by_session_user_role"] is True
    assert info["compatible_agent_tool_signatures"] == 1


def test_pi_agent_tool_call_with_prior_user_message_is_only_a_lead(tmp_path):
    args = {"command": "git log -1"}
    rows = [
        {
            "type": "message",
            "timestamp": "2026-10-21T00:59:59Z",
            "message": {"role": "user", "content": [{"type": "text", "text": HIDDEN}]},
        },
        {
            "type": "message",
            "timestamp": TIME,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "name": "mcp__Raspberry_Pi_MCP__run_command",
                        "arguments": args,
                    }
                ],
            },
        },
    ]
    _file(tmp_path, "pi", rows)
    matches, info = scan_independent_sessions(
        tmp_path, [_call(args)], CUTOFF, server_name="Raspberry_Pi_MCP"
    )
    assert info["compatible_signatures_with_prior_user_role"] == 1
    assert HIDDEN not in repr(list(matches.values()))


def test_old_session_file_not_scanned_as_contemporaneous(tmp_path):
    args = {"command": "git status"}
    file = _file(tmp_path, "codex", _codex(args))
    previous = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()
    os.utime(file, (previous, previous))
    matches, info = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matches
    assert info["compatible_agent_tool_signatures"] == 0
    assert info["codex_session_files_checked"] == 0


@pytest.mark.parametrize(
    "bad_tool",
    [
        "functions.exec",
        "run_command_extra",
        "mcp__fake__run_command_different",
    ],
)
def test_other_tools_or_wrappers_are_not_false_mcp_correlation(tmp_path, bad_tool):
    args = {"command": "git status"}
    rows = _codex(args)
    rows[-1]["payload"]["name"] = bad_tool
    _file(tmp_path, "codex", rows)
    matched, report = scan_independent_sessions(tmp_path, [_call(args)], CUTOFF)
    assert not matched
    assert report["compatible_agent_tool_signatures"] == 0

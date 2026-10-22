"""Independent local agent-session availability: cross-link exact tool invocations.

Only user-message existence and matched tool arguments are classified. No
original prompt, source, filename, session ID, command or tool result escapes.
"""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import io
import json
import os
import platform
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING or __package__:
    from .lsp_e01_trace import _digest, _time
else:
    from lsp_e01_trace import _digest, _time

SESSION_PATHS = (
    ("codex", ".codex/sessions"),
    ("claude", ".claude/projects"),
    ("pi", ".pi/agent/sessions"),
)
MAX_JSONL_BYTES = 64 * 1024 * 1024
MAX_LINES = 120_000
MAX_CALL_DELAY = 10
MAX_PROMPT_DELAY = 3 * 3600


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


@contextlib.contextmanager
def _read_session_file(path: Path, counts: collections.Counter) -> Iterator:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        counts["session_source_incomplete"] += 1
        yield io.BytesIO(b"")
        return
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            counts["session_source_incomplete"] += 1
            yield io.BytesIO(b"")
            return
        with os.fdopen(fd, "rb", closefd=False) as stream:
            yield stream
    finally:
        os.close(fd)


def _session_files(folder: Path, counts: collections.Counter):
    """Walk session files with explicit missing-directory coverage reporting.

    pathlib.rglob can silently ignore unreadable descendants. A partial
    search cannot establish a unique independent invocation signature.
    """

    def onerror(_exc):
        counts["session_source_incomplete"] += 1

    for directory, dirs, names in os.walk(folder, followlinks=False, onerror=onerror):
        base = Path(directory)
        safe_dirs = []
        for dirname in dirs:
            candidate = base / dirname
            if candidate.is_symlink():
                counts["session_source_incomplete"] += 1
            else:
                safe_dirs.append(dirname)
        dirs[:] = safe_dirs
        for name in names:
            if name.endswith(".jsonl"):
                yield base / name


def _local_server() -> str:
    if platform.system() == "Darwin":
        return "MacBook_Pro_MCP"
    return (
        "sextant" if "sextant" in socket.gethostname().lower() else "Raspberry_Pi_MCP"
    )


def _name_matches(full: Any, tool: str, server: str) -> bool:
    # Only a direct call to this host's configured MCP service is eligible.
    # Matching args/time still provides a *candidate*, not invocation identity.
    return isinstance(full, str) and full == f"mcp__{server}__{tool}"


def _session_events(source: str, item: dict) -> tuple[bool, list[tuple[str, Any]]]:
    """Return user-role presence and native tool-use input structures only."""
    commands: list[tuple[str, Any]] = []
    if source == "codex":
        if item.get("type") != "response_item":
            return False, commands
        payload = item.get("payload")
        if not isinstance(payload, dict):
            return False, commands
        kind = payload.get("type")
        if kind == "message" and payload.get("role") == "user":
            return True, commands
        if kind in ("function_call", "custom_tool_call"):
            arguments = payload.get("arguments", payload.get("input"))
            name = payload.get("name")
            if isinstance(name, str):
                commands.append((name, arguments))
    elif source == "claude":
        typ = item.get("type")
        if typ == "user":
            return True, commands
        if typ == "assistant":
            message = item.get("message")
            blocks = message.get("content") if isinstance(message, dict) else []
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name")
                        if isinstance(name, str):
                            commands.append((name, block.get("input")))
    elif source == "pi" and item.get("type") == "message":
        message = item.get("message")
        if isinstance(message, dict):
            if message.get("role") == "user":
                return True, commands
            blocks = message.get("content")
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        name = block.get("name")
                        if isinstance(name, str):
                            commands.append((name, block.get("arguments")))
    return False, commands


def scan_independent_sessions(
    home: Path,
    target_calls: list[Any],
    cutoff: dt.datetime,
    *,
    server_name: str | None = None,
) -> tuple[dict[tuple, dict], dict[str, int]]:
    """Match only exact tool/args/time from a distinct local agent session.

    A preceding user-role message is still NOT proof of a human-originating
    task or gold; its content remains private and requires later adjudication.
    """
    selected = [c for c in target_calls if c.when is not None]
    if not selected:
        return {}, {}
    server = server_name or _local_server()
    if server not in ("MacBook_Pro_MCP", "Raspberry_Pi_MCP", "sextant"):
        raise ValueError("unrecognized MCP server identity")
    start = min(c.when for c in selected) - MAX_PROMPT_DELAY
    latest = cutoff.timestamp()
    by_kind = collections.defaultdict(list)
    for c in selected:
        by_kind[c.tool].append(c)
    matches: dict[tuple, dict] = collections.defaultdict(
        lambda: {
            "unique_compatible_invocation": False,
            "preceded_by_session_user_role": False,
            "ambiguous_external_match": False,
        }
    )
    counters: collections.Counter[str] = collections.Counter()
    for origin, relative in SESSION_PATHS:
        folder = home / relative
        if _has_symlink_component(folder):
            counters["session_source_incomplete"] += 1
            continue
        if not folder.is_dir():
            counters[origin + "_source_unavailable"] += 1
            continue
        files = 0
        for path in _session_files(folder, counters):
            if _has_symlink_component(path):
                counters["session_source_incomplete"] += 1
                continue
            try:
                meta = path.stat()
            except OSError:
                counters["session_source_incomplete"] += 1
                continue
            if meta.st_mtime < start:
                # A file timestamp is an IO heuristic, not proof about its
                # internal event timestamps. Skipping it makes global
                # uniqueness unprovable. Preserve this exclusion explicitly.
                counters["mtime_early_session_files_skipped"] += 1
                counters["session_source_incomplete"] += 1
                continue
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_JSONL_BYTES:
                counters["session_source_incomplete"] += 1
                continue
            files += 1
            counters["candidate_session_files"] += 1
            last_user_at = None
            with _read_session_file(path, counters) as stream:
                for line_number, line in enumerate(stream):
                    if line_number >= MAX_LINES:
                        counters["agent_file_read_limit"] += 1
                        counters["session_source_incomplete"] += 1
                        break
                    try:
                        item = json.loads(line)
                    except (UnicodeDecodeError, ValueError):
                        counters["session_source_incomplete"] += 1
                        continue
                    if not isinstance(item, dict):
                        continue
                    when = _time(item.get("timestamp"))
                    if when is None:
                        # A message/tool invocation with an unreadable clock
                        # could be a duplicate of an observed invocation.
                        # Never certify uniqueness by silently dropping it.
                        possible = (
                            (origin == "codex" and item.get("type") == "response_item")
                            or (
                                origin == "claude"
                                and item.get("type") in ("user", "assistant")
                            )
                            or (origin == "pi" and item.get("type") == "message")
                        )
                        if possible:
                            counters["session_source_incomplete"] += 1
                        continue
                    t = when.timestamp()
                    if not start <= t < latest:
                        continue
                    has_user, invocations = _session_events(origin, item)
                    if has_user:
                        last_user_at = t
                        counters["user_role_messages_in_range"] += 1
                    for name, arguments in invocations:
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except ValueError:
                                continue
                        if not isinstance(arguments, dict):
                            continue
                        # Avoid emitting any source argument values or names.
                        for tool, candidates in by_kind.items():
                            if not _name_matches(name, tool, server):
                                continue
                            try:
                                digest = _digest(arguments)
                            except ValueError:
                                continue
                            exact = [
                                c
                                for c in candidates
                                if c.arguments_sha == digest
                                and abs(c.when - t) <= MAX_CALL_DELAY
                            ]
                            if len(exact) == 1:
                                c = exact[0]
                                row = matches[c.key]
                                if row["unique_compatible_invocation"]:
                                    row["ambiguous_external_match"] = True
                                row["unique_compatible_invocation"] = True
                                prior = (
                                    last_user_at is not None
                                    and 0 <= (t - last_user_at) <= MAX_PROMPT_DELAY
                                )
                                row["preceded_by_session_user_role"] |= prior
                            elif len(exact) > 1:
                                for c in exact:
                                    matches[c.key]["ambiguous_external_match"] = True
        counters[origin + "_session_files_checked"] += files

    if counters["session_source_incomplete"]:
        counters["candidate_links_downgraded_by_partial_scan"] = len(matches)
        matches.clear()

    clean_matches = {
        key: value
        for key, value in matches.items()
        if value["unique_compatible_invocation"]
        and not value["ambiguous_external_match"]
    }
    counters["compatible_agent_tool_signatures"] = len(clean_matches)
    counters["compatible_signatures_with_prior_user_role"] = sum(
        x["preceded_by_session_user_role"] for x in clean_matches.values()
    )
    counters["ambiguous_agent_tool_signatures"] = sum(
        value["ambiguous_external_match"] for value in matches.values()
    )
    return clean_matches, dict(sorted(counters.items()))

"""E2.1 private on-host evidence presence classification, never raw content.

No original commands are executed or emitted; Git SHA/output is reduced to
boolean evidence and user-task metadata is counted without reading values.
"""

from __future__ import annotations

import collections
import datetime as dt
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

if __package__:
    from .lsp_e01_trace import _request_key, _time
else:
    from lsp_e01_trace import _request_key, _time

GIT_HEAD = re.compile(r"[ \t]*git[ \t]+rev-parse[ \t]+HEAD[ \t]*")
GIT_STATUS = re.compile(r"[ \t]*git[ \t]+status[ \t]+--porcelain(?:=v1)?[ \t]*")
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\s*")


def _task_fields(
    root: Path, request_keys: set, cutoff: dt.datetime
) -> tuple[dict, dict]:
    """Inspect only presence of task metadata; never copy its value."""
    counts = collections.Counter()
    timestamps: dict = {}
    for file in sorted(root.glob("*.jsonl")):
        if file.is_symlink() or not file.is_file():
            continue
        with file.open("rb") as source:
            for line in source:
                if not line.endswith(b"\n"):
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(item, dict) or item.get("event") != "mcp_request":
                    continue
                when = _time(item.get("timestamp"))
                if when is None or when >= cutoff:
                    continue
                if item.get("method") != "tools/call":
                    continue
                corr = item.get("correlation")
                req_key = _request_key(corr) if isinstance(corr, dict) else None
                if req_key not in request_keys:
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                counts["requests_checked"] += 1
                if req_key in timestamps:
                    counts["duplicated_timestamp_key"] += 1
                    timestamps[req_key] = None
                else:
                    timestamps[req_key] = when.timestamp()
                for field in ("task", "requestState", "inputResponses"):
                    if payload.get(field):
                        counts[f"nonempty_{field}"] += 1
    return dict(sorted(counts.items())), timestamps


def _content_commitments(
    root: Path,
    call_keys: set,
    request_keys: set,
    cutoff: dt.datetime,
    secret: bytes,
) -> tuple[dict, dict]:
    """HMAC complete captured result/error and MCP request payloads, privately.

    The returned digests remain in local file-only evidence; no plaintext,
    raw SHA, request identifier or digest is emitted on stdout.
    """
    result_commitments: dict = {}
    request_commitments: dict = {}
    for file in sorted(root.glob("*.jsonl")):
        if file.is_symlink() or not file.is_file():
            continue
        with file.open("rb") as source:
            for line in source:
                if not line.endswith(b"\n"):
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(item, dict):
                    continue
                when = _time(item.get("timestamp"))
                if when is None or when >= cutoff:
                    continue
                event = item.get("event")
                corr = item.get("correlation")
                if not isinstance(corr, dict):
                    continue
                target, fields = None, None
                if event == "mcp_request" and item.get("method") == "tools/call":
                    request_key = _request_key(corr)
                    if request_key in request_keys:
                        target, fields = (
                            request_key,
                            {"event": event, "payload": item.get("payload")},
                        )
                        destination = request_commitments
                elif event in ("tool_result", "tool_error"):
                    call_key = (corr.get("server_gen"), corr.get("call"))
                    if call_key in call_keys:
                        target = call_key
                        fields = {
                            "event": event,
                            "result": item.get("result"),
                            "error_class": item.get("error_class"),
                            "error": item.get("error"),
                            "traceback": item.get("traceback"),
                        }
                        destination = result_commitments
                if target is None:
                    continue
                wire = json.dumps(
                    fields,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                digest = hmac.new(secret, wire, hashlib.sha256).hexdigest()
                if target in destination and destination[target] != digest:
                    raise ValueError("inconsistent private source evidence")
                destination[target] = digest
    return request_commitments, result_commitments


def _git_evidence(
    root: Path, selected: dict[tuple, Any], cutoff: dt.datetime
) -> dict[tuple, dict]:
    """Recognize ONLY exact standalone Git queries plus their captured results.

    No Git command is executed, no repository path/hash stored or printed.
    Even a proven SHA is not an independently verified historic snapshot.
    """
    targets: dict[tuple[str, str], tuple[tuple, str]] = {}
    found: dict[tuple, collections.Counter] = {
        group: collections.Counter() for group in selected
    }
    for group, entry in selected.items():
        for call in entry.calls:
            if call.tool == "run_command":
                targets[call.key] = (group, call.status)
    if not targets:
        return {group: {} for group in selected}
    commands: dict[tuple[str, str], str] = {}
    results: dict[tuple[str, str], tuple[bool, bool]] = {}
    for path in sorted(root.glob("*.jsonl")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as source:
            for line in source:
                if not line.endswith(b"\n"):
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(item, dict):
                    continue
                when = _time(item.get("timestamp"))
                if when is None or when >= cutoff:
                    continue
                event = item.get("event")
                corr = item.get("correlation") or {}
                if not isinstance(corr, dict):
                    continue
                key = (corr.get("server_gen"), corr.get("call"))
                if key not in targets:
                    continue
                group, state = targets[key]
                if event == "tool_call":
                    args = item.get("arguments") or {}
                    if not isinstance(args, dict):
                        continue
                    command = args.get("command")
                    if isinstance(command, str):
                        if GIT_HEAD.fullmatch(command):
                            commands[key] = "head"
                        elif GIT_STATUS.fullmatch(command):
                            commands[key] = "status"
                elif event == "tool_result" and state == "result":
                    result = item.get("result") or {}
                    if not isinstance(result, dict):
                        continue
                    structured = result.get("structured_content") or {}
                    if not isinstance(structured, dict):
                        continue
                    if (
                        structured.get("truncated") is not False
                        or type(structured.get("exit_code")) is not int
                        or structured["exit_code"] != 0
                        or not isinstance(structured.get("output"), str)
                    ):
                        continue
                    output = structured["output"]
                    # Store only two boolean observations, never the Git SHA
                    # or arbitrary stdout from a historical tool result.
                    results[key] = (
                        bool(FULL_SHA.fullmatch(output)),
                        not output.strip(),
                    )
    for key, kind in commands.items():
        if key not in results:
            continue
        group, _ = targets[key]
        is_sha, is_empty = results[key]
        if kind == "head" and is_sha:
            found[group]["standalone_git_head_results"] += 1
        elif kind == "status" and is_empty:
            found[group]["empty_git_porcelain_results"] += 1
    return {group: dict(counter) for group, counter in found.items()}


def _case_fingerprint(
    secret: bytes, calls: list[Any], requests: dict, outcomes: dict
) -> str:
    """Keyed commitment to all restored call inputs, result/error and request.

    Never returns raw tool content or unhashed identifiers. This checkpoint
    starts at E2.1, not at the earlier E2 selection moment.
    """
    material = [
        [
            call.key,
            call.arguments_sha,
            call.status,
            call.when,
            call.end_when,
            call.result_truncated,
            call.result_exit,
            requests.get(call.request_key),
            outcomes.get(call.key),
        ]
        for call in sorted(calls, key=lambda c: c.key)
    ]
    return hmac.new(
        secret,
        json.dumps(material, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]

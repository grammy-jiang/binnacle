"""Privacy-preserving representations for MCP request and journal telemetry.

Journal records are a diagnostic channel, not a repository of user-supplied
commands, file contents, search terms, credentials or arbitrary error messages.
Only an explicit set of diagnostic scalars may be logged verbatim. Keep raw
tool arguments and return values untouched for actual execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REDACTED = "[redacted]"
SMOKE_CORRELATION_FIELD = "binnacle/smoke-correlation"
# A 128-bit generated marker is diagnostic-only, never an authorization claim.
_SMOKE_PROOF = re.compile(r"^[0-9a-f]{32}$")
PUBLIC_TOOLS = frozenset(
    {
        "read_file",
        "list_files",
        "search_text",
        "edit_file",
        "write_file",
        "run_command",
        "job_status",
        "stop_job",
    }
)
_CLIENT_LABELS = frozenset(
    {"openai-mcp", "openai-mcp(ChatGPT)", "claude-code", "codex-mcp-client", "mcp"}
)
# Names are constrained because even an *argument key* may come from untrusted
# JSON; unknown keys are counted, not rendered.
_ARGUMENT_KEYS = frozenset(
    {
        "path",
        "workdir",
        "glob",
        "pattern",
        "command",
        "stdin",
        "content",
        "old",
        "new",
        "old_text",
        "new_text",
        "match",
        "job_id",
        "cursor",
        "start_line",
        "end_line",
        "max_results",
        "include_hidden",
        "fixed_strings",
        "context_lines",
        "names_only",
        "line_numbers",
        "wait_seconds",
        "tail_lines",
        "background",
    }
)
_SAFE_SCALARS = frozenset(
    {
        "start_line",
        "end_line",
        "max_results",
        "include_hidden",
        "fixed_strings",
        "context_lines",
        "names_only",
        "line_numbers",
        "wait_seconds",
        "tail_lines",
        "background",
    }
)
_HASHED_PATH = re.compile(r"^pathhash:([0-9a-f]{12})(?:\.file)?$")
_JOB_ID = re.compile(r"^[0-9a-f]{12}$")
_TURN = re.compile(
    r"^(?:wfr_[A-Za-z0-9_-]{1,70}|turn-[A-Za-z0-9_-]{1,50})/[A-Za-z0-9_.-]{1,60}$"
)


def safe_smoke_proof(meta: object) -> str | None:
    """Only validated opaque probe IDs may enter the journal from request meta."""
    if not isinstance(meta, Mapping):
        return None
    value = meta.get(SMOKE_CORRELATION_FIELD)
    return value if isinstance(value, str) and _SMOKE_PROOF.fullmatch(value) else None


def safe_tool_name(name: object) -> str:
    return name if isinstance(name, str) and name in PUBLIC_TOOLS else "unknown_tool"


def safe_client_name(name: str | None) -> str:
    if not name:
        return "-"
    if name in _CLIENT_LABELS:
        return name
    return "client-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]


def safe_turn_id(value: str) -> str:
    """Keep the tunnel's generated identifier; never print arbitrary headers."""
    if _TURN.fullmatch(value):
        return value
    return "turn-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def path_digest(value: str, *, root: Path | None = None) -> str:
    """Match the existing Binnacle analytics' normalized-path hash semantics."""
    marker = _HASHED_PATH.fullmatch(value)
    if marker:
        return marker.group(1)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.home() / "Projects" if root is None else root) / path
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def safe_path(value: object, *, root: Path | None = None) -> str:
    if not isinstance(value, str):
        return REDACTED
    try:
        # Preserve a boolean file-vs-directory signal for the adaptive reader,
        # but never retain an actual path component or file extension.
        kind = ".file" if Path(value).suffix else ""
        return "pathhash:" + path_digest(value, root=root) + kind
    except (OSError, ValueError, RuntimeError):
        return REDACTED


def safe_arguments(arguments: object, *, root: Path | None = None) -> dict[str, Any]:
    """Log a closed whitelist of benign scalars, pseudonymous paths and IDs."""
    if not isinstance(arguments, Mapping):
        return {}
    result: dict[str, Any] = {}
    unknown = 0
    for key, value in arguments.items():
        if not isinstance(key, str) or key not in _ARGUMENT_KEYS:
            unknown += 1
        elif key in _SAFE_SCALARS and (
            value is None or type(value) in (int, float, bool)
        ):
            result[key] = value
        elif key in {"path", "workdir"}:
            result[key] = safe_path(value, root=root)
        elif (
            key == "job_id" and isinstance(value, str) and _JOB_ID.fullmatch(value)
        ) or (key == "cursor" and value in ("start", "end")):
            result[key] = value
        elif key == "glob" and value == "":
            result[key] = ""
        else:
            result[key] = REDACTED
    if unknown:
        result["unknown_keys"] = unknown
    return result


def safe_request_payload(message: Any, *, root: Path | None = None) -> str:
    """Fail-closed serializer for FastMCP LoggingMiddleware.

    FastMCP's base serializer FALLS BACK TO RAW SERIALIZATION when this
    callable raises. Never let malformed input trigger that fallback.
    """
    try:
        name = getattr(message, "name", None)
        args = getattr(message, "arguments", None)
        if name is None:
            params = getattr(message, "params", None)
            name = getattr(params, "name", None)
            args = getattr(params, "arguments", None)
        if name is not None:
            value: dict[str, Any] = {
                "name": safe_tool_name(name),
                "arguments": safe_arguments(args, root=root),
            }
        else:
            # No arbitrary protocol metadata or other client-authored data.
            value = {"type": type(message).__name__}
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:  # noqa: BLE001 - prevent upstream raw-payload fallback
        return '{"type":"unavailable"}'

"""Non-executing, bounded replies to untrusted LSP server-to-client requests.

Provider requests must never change source, run commands, register arbitrary
capabilities, expose private configuration, or install packages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .lsp_wire import LspProtocolError

_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_READ_ONLY = "Read-only Development Intelligence client"


def _failure(identifier: int | str, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": code, "message": message},
    }


def server_request_reply(
    message: dict[str, Any],
    *,
    configuration: Mapping[str, dict] | None = None,
) -> dict:
    """Apply an exact, read-only allowlist, not arbitrary client extensions."""
    identifier = message.get("id")
    if not isinstance(identifier, (int, str)) or isinstance(identifier, bool):
        raise LspProtocolError("invalid_server_request_id")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise LspProtocolError("invalid_server_request_method")
    params = message.get("params", {})
    if method == "workspace/applyEdit":
        return {
            "jsonrpc": "2.0",
            "id": identifier,
            "result": {"applied": False, "failureReason": _READ_ONLY},
        }
    if method == "workspace/configuration":
        if not isinstance(params, dict):
            return _failure(identifier, _INVALID_PARAMS, "Invalid parameters")
        items = params.get("items")
        if (
            not isinstance(items, list)
            or len(items) > 64
            or not all(isinstance(item, dict) for item in items)
        ):
            return _failure(identifier, _INVALID_PARAMS, "Invalid parameters")
        # No dynamic file/system settings. Configuration must be separately
        # passed from a trusted host profile; defaults leak nothing.
        sections = configuration or {}
        return {
            "jsonrpc": "2.0",
            "id": identifier,
            "result": [
                sections.get(item.get("section"))
                if isinstance(item.get("section"), str)
                else None
                for item in items
            ],
        }
    if method == "window/workDoneProgress/create":
        return {"jsonrpc": "2.0", "id": identifier, "result": None}
    if method == "workspace/workspaceFolders":
        return {"jsonrpc": "2.0", "id": identifier, "result": None}
    if method == "window/showMessageRequest":
        return {"jsonrpc": "2.0", "id": identifier, "result": None}
    # client/registerCapability, workspace/executeCommand, and unknown
    # requests remain explicitly unsupported, never silently accepted.
    return _failure(identifier, _METHOD_NOT_FOUND, "Method not supported")

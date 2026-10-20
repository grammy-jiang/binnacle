"""Deterministic, zero-dependency stdio LSP fixture for Binnacle tests.

Fixture only. It is not a production language server, a public MCP tool, or
proof of model/agent workflow improvement.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _read_message() -> dict[str, Any] | None:
    length: int | None = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    if length is None or length < 0 or length > 1024 * 1024:
        raise ValueError("invalid Content-Length")
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise EOFError("truncated request body")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def _send_message(value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
    sys.stdout.buffer.flush()


def main() -> int:
    while (request := _read_message()) is not None:
        method = request.get("method")
        if method == "exit":
            return 0
        if "id" not in request:
            continue
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
        if method == "initialize":
            response["result"] = {
                "capabilities": {
                    "definitionProvider": True,
                    "textDocumentSync": 1,
                },
                "serverInfo": {"name": "binnacle-fake-lsp", "version": "0"},
            }
        elif method == "textDocument/definition":
            response["result"] = {
                "uri": "file:///fixture.py",
                "range": {
                    "start": {"line": 1, "character": 4},
                    "end": {"line": 1, "character": 10},
                },
            }
        elif method == "shutdown":
            response["result"] = None
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
        _send_message(response)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, TypeError, ValueError, json.JSONDecodeError):
        raise SystemExit(2) from None

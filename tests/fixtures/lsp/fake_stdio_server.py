"""Deterministic, zero-dependency stdio LSP fixture for Binnacle tests.

Fixture only. It is not a production language server, a public MCP tool, or
proof of model/agent workflow improvement.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Any

# The subprocess remains standalone while mypy follows canonical test modules.
if TYPE_CHECKING:
    from tests.fixtures.lsp.lsp_dialogue import Dialogue
    from tests.fixtures.lsp.lsp_payloads import CAPABILITIES, semantic_result
    from tests.fixtures.lsp.lsp_transport import MODES, emit, frame
    from tests.fixtures.lsp.process_faults import MODES as FAULT_MODES
    from tests.fixtures.lsp.process_faults import Faults
else:
    from lsp_dialogue import Dialogue
    from lsp_payloads import CAPABILITIES, semantic_result
    from lsp_transport import MODES, emit, frame
    from process_faults import MODES as FAULT_MODES
    from process_faults import Faults


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
    sys.stdout.buffer.write(frame(value))
    sys.stdout.buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--definition",
        choices=("location", "link", "null", "multiple"),
        default="location",
    )
    parser.add_argument(
        "--disable", action="append", choices=tuple(CAPABILITIES), default=[]
    )
    parser.add_argument("--transport", choices=MODES, default="split")
    parser.add_argument("--fault", choices=FAULT_MODES, default="none")
    parser.add_argument("--trace")
    parser.add_argument("--control-fd", type=int)
    options = parser.parse_args()
    faults = Faults(options.fault, options.trace, options.control_fd)
    delayed: dict[str, Any] | None = None
    dialogue = Dialogue()
    while (request := _read_message()) is not None:
        if faults.accept(request):
            continue
        method = request.get("method")
        if method == "exit":
            return 0
        if dialogue.accept(request):
            continue
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
        if method == "initialize":
            response["result"] = {
                "capabilities": {
                    **{
                        capability: method not in options.disable
                        for method, capability in CAPABILITIES.items()
                    },
                    "textDocumentSync": 1,
                },
                "serverInfo": {"name": "binnacle-fake-lsp", "version": "0"},
            }
        elif method in CAPABILITIES and method not in options.disable:
            response["result"] = semantic_result(method, options.definition)
        elif method == "fixture/transport":
            response["result"] = "wire → 文"
            if options.transport == "late-id":
                delayed = response
            elif emit(sys.stdout.buffer, options.transport, response):
                return 0
            continue
        elif method == "fixture/release":
            if delayed is not None:
                _send_message(delayed)
                delayed = None
            response["result"] = None
        elif method == "fixture/serverRequest":
            _send_message(dialogue.server_request(request["params"]))
            response["result"] = None
        elif method == "fixture/observed":
            response["result"] = dialogue.observed()
        elif method == "shutdown":
            response["result"] = None
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
        _send_message(response)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, TypeError, ValueError, BrokenPipeError):
        raise SystemExit(2) from None

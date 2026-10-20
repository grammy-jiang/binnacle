"""Explicit wire faults for fixture/harness smoke only."""

import json
from typing import Any, BinaryIO

MODES = (
    "split",
    "coalesced",
    "missing-length",
    "malformed-length",
    "negative-length",
    "duplicate-length",
    "conflicting-length",
    "short-body",
    "long-body",
    "invalid-json",
    "oversize-header",
    "oversize-body",
    "non-object",
    "unknown-id",
    "null-id",
    "boolean-id",
    "list-id",
    "duplicate-id",
    "late-id",
)


def frame(value: Any) -> bytes:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def emit(stream: BinaryIO, mode: str, response: dict[str, Any]) -> bool:
    """Return True to close stdout deterministically after a malformed frame."""
    wire = frame(response)
    header, _, body = wire.partition(b"\r\n\r\n")
    terminal = True
    if mode == "split":
        for byte in wire:
            stream.write(bytes([byte]))
            stream.flush()
        return False
    if mode == "coalesced":
        wire = frame({"jsonrpc": "2.0", "method": "fixture/tick", "params": {}}) + wire
        terminal = False
    elif mode == "missing-length":
        wire = b"Content-Type: application/json\r\n\r\n" + body
    elif mode == "malformed-length":
        wire = b"Content-Length: nope\r\n\r\n" + body
    elif mode == "negative-length":
        wire = b"Content-Length: -1\r\n\r\n" + body
    elif mode in ("duplicate-length", "conflicting-length"):
        second = header if mode == "duplicate-length" else b"Content-Length: 1"
        wire = header + b"\r\n" + second + b"\r\n\r\n" + body
    elif mode == "short-body":
        wire = f"Content-Length: {len(body) + 5}\r\n\r\n".encode() + body
    elif mode == "long-body":
        wire = f"Content-Length: {len(body) - 1}\r\n\r\n".encode() + body
    elif mode == "invalid-json":
        wire = b"Content-Length: 1\r\n\r\n{"
    elif mode == "oversize-header":
        wire = b"X-Fill: " + b"x" * 2048 + b"\r\n" + wire
    elif mode == "oversize-body":
        wire = frame({**response, "result": "x" * 9000})
    elif mode == "non-object":
        wire = frame([1, 2])
    elif mode in ("unknown-id", "null-id", "boolean-id", "list-id"):
        bad_id = {
            "unknown-id": "unknown",
            "null-id": None,
            "boolean-id": True,
            "list-id": [1],
        }[mode]
        wire = frame({**response, "id": bad_id})
        terminal = False
    elif mode == "duplicate-id":
        wire += wire
        terminal = False
    else:
        raise ValueError(f"unhandled transport mode: {mode}")
    stream.write(wire)
    stream.flush()
    return terminal

"""Bounded incremental LSP stdio Content-Length framing, independent of MCP.

No process, filesystem, network, provider discovery or raw payload logging.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

_HEADER_NAME = re.compile(rb"[A-Za-z0-9-]+")
_LENGTH = re.compile(rb"[0-9]{1,9}")


class LspProtocolError(ValueError):
    """Stable, non-content protocol error: safe for higher-level status."""


def _reject_constant(_value: str) -> None:
    raise LspProtocolError("invalid_json_constant")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise LspProtocolError("invalid_json_number")
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LspProtocolError("duplicate_json_field")
        result[key] = value
    return result


def decode_json(body: bytes) -> dict:
    try:
        value = json.loads(
            body.decode("utf-8"),
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LspProtocolError("invalid_json_body") from exc
    if not isinstance(value, dict):
        raise LspProtocolError("json_rpc_not_object")
    return value


def encode_frame(value: dict, *, max_body: int = 1024 * 1024) -> bytes:
    try:
        data = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise LspProtocolError("invalid_outbound_json") from exc
    if len(data) > max_body:
        raise LspProtocolError("outbound_body_too_large")
    return f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data


class LspFrameDecoder:
    """Byte-fed decoder for split/coalesced LSP frames with strict limits."""

    def __init__(self, *, max_header: int = 1024, max_body: int = 1024 * 1024):
        if not (64 <= max_header <= 16384 and 1 <= max_body <= 8 * 1024 * 1024):
            raise ValueError("invalid_lsp_frame_limits")
        self.max_header = max_header
        self.max_body = max_body
        self._buffer = bytearray()
        self._body_length: int | None = None

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, fragment: bytes) -> list[dict]:
        if not isinstance(fragment, bytes):
            raise TypeError("frame_fragment_must_be_bytes")
        if len(fragment) > self.max_body + self.max_header + 4:
            raise LspProtocolError("frame_fragment_too_large")
        self._buffer.extend(fragment)
        decoded: list[dict] = []
        while True:
            if self._body_length is None:
                separator = self._buffer.find(b"\r\n\r\n")
                if separator < 0:
                    if len(self._buffer) > self.max_header + 3:
                        raise LspProtocolError("header_too_large")
                    break
                if separator > self.max_header:
                    raise LspProtocolError("header_too_large")
                length = self._header_length(bytes(self._buffer[:separator]))
                del self._buffer[: separator + 4]
                self._body_length = length
            if self._body_length is None:
                # Do not rely on assert: optimized Python removes assertions.
                raise LspProtocolError("missing_body_length")
            if len(self._buffer) < self._body_length:
                if len(self._buffer) > self.max_body:
                    raise LspProtocolError("body_buffer_too_large")
                break
            n = self._body_length
            body = bytes(self._buffer[:n])
            del self._buffer[:n]
            self._body_length = None
            decoded.append(decode_json(body))
        if len(self._buffer) > self.max_body + self.max_header + 4:
            raise LspProtocolError("frame_buffer_too_large")
        return decoded

    def finish(self) -> None:
        if self._body_length is not None or self._buffer:
            raise LspProtocolError("truncated_frame")

    def _header_length(self, header: bytes) -> int:
        lengths = []
        if not header:
            raise LspProtocolError("empty_header")
        for line in header.split(b"\r\n"):
            name, separator, value = line.partition(b":")
            if not separator or _HEADER_NAME.fullmatch(name) is None:
                raise LspProtocolError("invalid_header")
            if any(byte > 127 or (byte < 32 and byte != 9) for byte in value):
                raise LspProtocolError("invalid_header_value")
            if name.lower() == b"content-length":
                lengths.append(value.strip(b" \t"))
        if len(lengths) != 1:
            raise LspProtocolError("missing_or_duplicate_content_length")
        if _LENGTH.fullmatch(lengths[0]) is None:
            raise LspProtocolError("invalid_content_length")
        size = int(lengths[0])
        if size > self.max_body:
            raise LspProtocolError("body_too_large")
        return size

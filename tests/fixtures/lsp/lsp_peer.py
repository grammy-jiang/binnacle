"""Bounded test-only stdio peer, not the future production LSP client."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).with_name("fake_stdio_server.py")


def abort_spawned_peer(
    process: subprocess.Popen[bytes] | None,
    selector: selectors.BaseSelector | None,
    *,
    control_fd: int | None = None,
) -> None:
    """Rollback fixture-only startup. Never signal a PID learned from a trace."""
    if control_fd is not None:
        os.close(control_fd)
    try:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
    finally:
        try:
            if selector is not None:
                selector.close()
        finally:
            if process is not None:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()


class LspPeer:
    def __init__(self, *args: str):
        process = subprocess.Popen(
            [sys.executable, "-u", str(FIXTURE), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        selector = None
        try:
            selector = selectors.DefaultSelector()
            if process.stdout is None:
                raise ValueError("missing fake stdout pipe")
            selector.register(process.stdout, selectors.EVENT_READ)
        except BaseException:
            abort_spawned_peer(process, selector)
            raise
        self.process = process
        self.selector = selector
        self.buffer = bytearray()
        self._expected_body_length: int | None = None
        self.max_buffered = 0

    def __enter__(self) -> LspPeer:  # noqa: PYI034 - Python 3.10 lacks Self
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=3)
        finally:
            self.selector.close()
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                if pipe is not None:
                    pipe.close()

    def send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False).encode()
        assert self.process.stdin is not None
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.process.stdin.flush()

    def receive(self, timeout: float = 3) -> dict[str, Any]:
        """Keep partial header/body state after a bounded read timeout."""
        deadline = time.monotonic() + timeout
        while True:
            if self._expected_body_length is None and b"\r\n\r\n" in self.buffer:
                header, _, body = self.buffer.partition(b"\r\n\r\n")
                if len(header) > 1024:
                    raise ValueError("header too large")
                fields = [line.split(b":", 1) for line in header.split(b"\r\n")]
                lengths = [
                    parts[1].strip()
                    for parts in fields
                    if len(parts) == 2 and parts[0].lower() == b"content-length"
                ]
                if len(lengths) != 1:
                    raise ValueError("missing or duplicate Content-Length")
                if not lengths[0].isdigit():
                    raise ValueError("invalid Content-Length")
                length = int(lengths[0])
                if length > 8192:
                    raise ValueError("body too large")
                self._expected_body_length = length
                self.buffer = bytearray(body)
            length = self._expected_body_length
            if length is not None and len(self.buffer) >= length:
                body = bytes(self.buffer[:length])
                del self.buffer[:length]
                self._expected_body_length = None
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError("expected object")
                return value
            if length is None and len(self.buffer) > 1024:
                raise ValueError("header too large")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("fixture response deadline")
            assert self.process.stdout is not None
            chunk = os.read(self.process.stdout.fileno(), 1024)
            if not chunk:
                raise EOFError("truncated frame or closed stdout")
            self.buffer.extend(chunk)
            self.max_buffered = max(self.max_buffered, len(self.buffer))

    def request(self, method: str, request_id: int = 1, **params: Any) -> dict:
        self.send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        response = self.receive()
        assert "method" not in response, "server request requires dispatch"
        self.validate_response(response, request_id)
        return response

    @staticmethod
    def validate_response(response: dict[str, Any], expected_id: int) -> None:
        if "method" in response:
            raise ValueError("server request is not a response")
        response_id = response.get("id")
        if type(response_id) is not int or response_id != expected_id:
            raise ValueError("unexpected response ID")

    def finish(self) -> None:
        assert self.request("shutdown", 999) == {
            "jsonrpc": "2.0",
            "id": 999,
            "result": None,
        }
        self.send({"jsonrpc": "2.0", "method": "exit"})
        assert self.process.wait(timeout=3) == 0
        assert self.process.stderr is not None
        assert self.process.stderr.read() == b""

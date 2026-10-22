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


def reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


class LspPeer:
    def __init__(self, *args: str):
        self.control: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.selector: selectors.BaseSelector | None = None
        self.buffer = bytearray()
        self.pending_length: int | None = None
        self.max_buffered = 0
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", str(FIXTURE), *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.selector = selectors.DefaultSelector()
            assert self.process.stdout is not None
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
        except BaseException:
            self.release_resources()
            raise

    def __enter__(self) -> LspPeer:  # noqa: PYI034 - stdlib Python 3.10
        return self

    def release_resources(self) -> None:
        """Release partial acquisitions; signal only our owned Popen child.

        Closing pipes and the private control writer also releases cooperative
        readers if signaling fails. Always attempt reaping and all closes.
        """
        errors = []

        def attempt(action):
            try:
                action()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(error)

        control = getattr(self, "control", None)
        if control is not None:
            self.control = None
            attempt(lambda: os.close(control))
        if self.selector is not None:
            attempt(self.selector.close)
        if self.process is not None:
            process = self.process
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    # A failed kill must not bypass pipe closure or wait.
                    attempt(process.terminate)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    attempt(pipe.close)
            attempt(lambda: process.wait(timeout=3))
        if errors:
            raise OSError("fixture resource cleanup failed") from errors[-1]

    def __exit__(self, *exc: object) -> None:
        self.release_resources()

    def send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False).encode()
        process = self.process
        if process is None or process.stdin is None:
            raise RuntimeError("fixture peer is not started")
        process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        process.stdin.flush()

    def receive(self, timeout: float = 3) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            if self.pending_length is None and b"\r\n\r\n" in self.buffer:
                header, _, body = self.buffer.partition(b"\r\n\r\n")
                if len(header) > 1024:
                    raise ValueError("header too large")
                fields = [line.split(b":", 1) for line in header.split(b"\r\n")]
                if any(
                    len(parts) != 2
                    or not parts[0]
                    or not all(33 <= byte <= 126 and byte != 58 for byte in parts[0])
                    for parts in fields
                ):
                    raise ValueError("invalid header")
                lengths = [
                    parts[1].strip()
                    for parts in fields
                    if len(parts) == 2 and parts[0].lower() == b"content-length"
                ]
                if len(lengths) != 1:
                    raise ValueError("missing or duplicate Content-Length")
                if not lengths[0].isdigit():
                    raise ValueError("invalid Content-Length")
                frame_length = int(lengths[0])
                if frame_length > 8192:
                    raise ValueError("body too large")
                self.pending_length = frame_length
                self.buffer = bytearray(body)
            length = self.pending_length
            if length is not None and len(self.buffer) >= length:
                payload_bytes = bytes(self.buffer[:length])
                del self.buffer[:length]
                self.pending_length = None
                value = json.loads(
                    payload_bytes.decode("utf-8"), parse_constant=reject_constant
                )
                if not isinstance(value, dict):
                    raise ValueError("expected object")
                return value
            if self.pending_length is None and len(self.buffer) > 1024:
                raise ValueError("header too large")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("fixture response deadline")
            chunk = self.read_chunk(remaining)
            if chunk == b"":
                raise EOFError("truncated frame or closed stdout EOF")
            if chunk:
                self.buffer.extend(chunk)
                self.max_buffered = max(self.max_buffered, len(self.buffer))

    def read_chunk(self, timeout: float) -> bytes | None:
        selector = self.selector
        process = self.process
        if selector is None or process is None or process.stdout is None:
            raise RuntimeError("fixture peer is not started")
        if not selector.select(timeout):
            return None
        return os.read(process.stdout.fileno(), 1024)

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
        process = self.process
        if process is None:
            raise RuntimeError("fixture peer has no process")
        assert process.wait(timeout=3) == 0
        assert process.stderr is not None
        assert process.stderr.read() == b""

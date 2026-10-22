"""Bounded POSIX stdio peer for opt-in synthetic QA, never a runtime adapter."""

from __future__ import annotations

import json
import math
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

MAX_BODY = 1024 * 1024
MAX_HEADER = 8192


class ProbeError(Exception):
    """Stable failure code; never include provider output or local paths."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value):
    raise ProbeError("invalid_json_constant")


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ProbeError("invalid_json_number")
    return number


class Peer:
    """One outstanding request, bounded frames and total lifetime deadline."""

    def __init__(
        self, argv: list[str], root: Path, env: dict[str, str], timeout: float
    ):
        self.deadline = time.monotonic() + timeout
        self.buffer = bytearray()
        self.sequence = 0
        self.reverse_denied = 0
        self.notifications = 0
        self.cleanup = "not_started"
        self.process = subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
        )
        try:
            if self.process.stdin is None or self.process.stdout is None:
                raise ProbeError("pipe_unavailable")
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            self.close()
            raise

    def _ready(self, pipe, event):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("deadline")
        with selectors.DefaultSelector() as selector:
            selector.register(pipe, event)
            if not selector.select(remaining):
                raise ProbeError("deadline")

    def send(self, message):
        body = json.dumps(message, allow_nan=False).encode()
        if len(body) > MAX_BODY:
            raise ProbeError("outgoing_body_limit")
        data = memoryview(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        while data:
            self._ready(self.process.stdin, selectors.EVENT_WRITE)
            try:
                size = os.write(self.process.stdin.fileno(), data)
            except BlockingIOError:
                continue
            data = data[size:]

    def _fill(self):
        self._ready(self.process.stdout, selectors.EVENT_READ)
        try:
            chunk = os.read(self.process.stdout.fileno(), 4096)
        except BlockingIOError:
            return
        if not chunk:
            raise ProbeError("stdout_eof")
        self.buffer.extend(chunk)

    def receive(self):
        while b"\r\n\r\n" not in self.buffer:
            if len(self.buffer) > MAX_HEADER:
                raise ProbeError("header_limit")
            self._fill()
        header, _, _ = self.buffer.partition(b"\r\n\r\n")
        if len(header) > MAX_HEADER:
            raise ProbeError("header_limit")
        lengths = []
        for line in header.split(b"\r\n"):
            key, separator, value = line.partition(b":")
            if not separator or not key:
                raise ProbeError("invalid_header")
            if key.lower() == b"content-length":
                lengths.append(value.strip())
        if len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 8:
            raise ProbeError("invalid_length")
        size = int(lengths[0])
        if size > MAX_BODY:
            raise ProbeError("body_limit")
        del self.buffer[: len(header) + 4]
        while len(self.buffer) < size:
            self._fill()
        body = bytes(self.buffer[:size])
        del self.buffer[:size]
        try:
            value = json.loads(
                body,
                object_pairs_hook=_unique,
                parse_constant=_constant,
                parse_float=_finite,
            )
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ProbeError("invalid_json") from error
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise ProbeError("invalid_envelope")
        return value

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method, params, settings):
        self.sequence += 1
        self.send(
            {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}
        )
        for _ in range(2048):
            message = self.receive()
            if "method" in message:
                if "id" in message:
                    self.reverse(message, settings)
                else:
                    self.notifications += 1
                continue
            if type(message.get("id")) is not int or message["id"] != self.sequence:
                raise ProbeError("unexpected_response_id")
            if ("error" in message) == ("result" in message):
                raise ProbeError("invalid_response")
            if "error" in message:
                raise ProbeError("rpc_error")
            return message["result"]
        raise ProbeError("message_limit")

    def reverse(self, message, settings):
        if (
            type(message.get("id")) not in {str, int}
            or not isinstance(message.get("method"), str)
            or not isinstance(message.get("params", {}), dict)
        ):
            raise ProbeError("invalid_reverse_request")
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        method = message["method"]
        if method == "workspace/configuration":
            items = message.get("params", {}).get("items", [])
            if not isinstance(items, list) or len(items) > 64:
                raise ProbeError("configuration_limit")
            values = []
            for item in items:
                if not isinstance(item, dict) or not isinstance(
                    item.get("section", ""), str
                ):
                    raise ProbeError("invalid_configuration_item")
                value = settings
                for part in item.get("section", "").split("."):
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                values.append(value)
            reply["result"] = values
        elif method == "window/workDoneProgress/create":
            reply["result"] = None
        elif method == "workspace/applyEdit":
            self.reverse_denied += 1
            reply["result"] = {"applied": False}
        else:
            self.reverse_denied += 1
            reply["error"] = {
                "code": -32601,
                "message": "Not supported by synthetic QA",
            }
        self.send(reply)

    def await_diagnostics(self, uri, settings):
        """Bash publishes after its async configuration and document analysis."""
        for _ in range(2048):
            message = self.receive()
            if "method" not in message:
                raise ProbeError("unexpected_response_id")
            if "id" in message:
                self.reverse(message, settings)
            elif (
                message["method"] == "textDocument/publishDiagnostics"
                and message.get("params", {}).get("uri") == uri
            ):
                return
        raise ProbeError("message_limit")

    def close(self):
        """Reap leader and signal its owned session group, including after leader exit.

        This is cooperative POSIX cleanup, not containment of setsid escapes.
        No provider logs are retained. Cleanup has its own bounded budget.
        """
        failed = False
        try:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.process.pid, sig)
                except ProcessLookupError:
                    pass
                except OSError:
                    failed = True
                if sig == signal.SIGTERM:
                    try:
                        self.process.wait(timeout=0.3)
                    except subprocess.TimeoutExpired:
                        pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                failed = True
        finally:
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
        self.cleanup = (
            "cleanup_unverified" if failed else "group_signaled_leader_reaped"
        )

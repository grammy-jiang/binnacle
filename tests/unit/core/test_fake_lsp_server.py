"""Protocol smoke for the independent fake LSP fixture (stdio JSON-RPC)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "lsp" / "fake_stdio_server.py"
)


def _send(process: subprocess.Popen[bytes], request: dict) -> None:
    body = json.dumps(request, separators=(",", ":")).encode()
    assert process.stdin is not None
    process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    process.stdin.flush()


def _receive(process: subprocess.Popen[bytes]) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line.startswith(b"Content-Length:")
    length = int(line.split(b":", 1)[1].strip())
    assert process.stdout.readline() == b"\r\n"
    return json.loads(process.stdout.read(length))


def test_fake_lsp_initialize_definition_shutdown_and_exit():
    process = subprocess.Popen(
        [sys.executable, "-u", str(FIXTURE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"processId": None, "rootUri": None, "capabilities": {}},
            },
        )
        initialized = _receive(process)
        assert initialized["id"] == 1
        assert initialized["result"]["capabilities"]["definitionProvider"] is True

        _send(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///fixture.py"},
                    "position": {"line": 2, "character": 5},
                },
            },
        )
        definition = _receive(process)
        assert definition["id"] == 2
        assert definition["result"]["uri"] == "file:///fixture.py"
        assert definition["result"]["range"]["start"]["line"] == 1

        _send(process, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
        assert _receive(process) == {"jsonrpc": "2.0", "id": 3, "result": None}
        _send(process, {"jsonrpc": "2.0", "method": "exit"})
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        assert process.stderr.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()


def test_fake_lsp_unknown_request_is_explicit_error():
    process = subprocess.Popen(
        [sys.executable, "-u", str(FIXTURE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _send(process, {"jsonrpc": "2.0", "id": 5, "method": "unknown-method"})
        response = _receive(process)
        assert response["id"] == 5
        assert response["error"]["code"] == -32601
        _send(process, {"jsonrpc": "2.0", "method": "exit"})
        process.stdin.close()
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()

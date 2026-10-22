"""Synthetic P3.4 peer. Never starts real language servers or workspace code."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def send(value):
    body = json.dumps(value).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if mode == "hang-child":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # Explicit fixture-only readiness witness, *after* child creation and
        # SIGTERM disposition. An overloaded CI runner must not expire the
        # adversarial deadline before the process tree exists.
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text("ready\n", encoding="ascii")
        time.sleep(60)
        return
    if mode == "stderr":
        os.write(2, b"secret /private/example\n" * 100000)
    for line in sys.stdin.buffer:
        length = int(line.split(b":")[1])
        sys.stdin.buffer.readline()
        message = json.loads(sys.stdin.buffer.read(length))
        method = message.get("method")
        if method == "exit":
            return
        if method == "textDocument/didOpen":
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": message["params"]["textDocument"]["uri"],
                        "diagnostics": [],
                    },
                }
            )
        if "id" not in message or not method:
            continue
        result = None
        if method == "initialize":
            if mode == "reverse":
                for number, request in enumerate(
                    (
                        "workspace/applyEdit",
                        "workspace/executeClientCommand",
                        "client/registerCapability",
                    )
                ):
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": f"reverse-{number}",
                            "method": request,
                            "params": {},
                        }
                    )
            result = {
                "capabilities": {
                    "documentSymbolProvider": True,
                    "experimental": {"/private/secret": "file:///private/secret"},
                }
            }
        elif method == "textDocument/documentSymbol":
            result = [
                {
                    "name": "answer",
                    "range": {
                        "start": {"line": 0, "character": 2},
                        "end": {"line": 0, "character": 8},
                    },
                }
            ]
        send({"jsonrpc": "2.0", "id": message["id"], "result": result})


if __name__ == "__main__":
    main()

"""Client for the private local Binnacle job-manager protocol."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1


class JobManagerError(RuntimeError):
    """The local manager could not accept or complete an ownership operation."""


def _request(
    socket_path: Path, payload: dict[str, Any], *, timeout_s: float = 5.0
) -> dict[str, Any]:
    wire = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout_s)
            conn.connect(str(socket_path))
            conn.sendall(wire)
            reader = conn.makefile("rb")
            raw = reader.readline()
    except (OSError, TimeoutError) as exc:
        raise JobManagerError(
            f"job manager unavailable at {socket_path}: {exc}"
        ) from exc
    if not raw:
        raise JobManagerError("job manager closed the connection without a response")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JobManagerError("job manager returned malformed JSON") from exc
    if not isinstance(response, dict):
        raise JobManagerError("job manager returned a non-object response")
    if response.get("ok") is not True:
        raise JobManagerError(
            str(response.get("error") or "job manager request failed")
        )
    return response


def ping(socket_path: Path) -> dict[str, Any]:
    return _request(
        socket_path,
        {"version": PROTOCOL_VERSION, "op": "ping"},
    )


def start(
    socket_path: Path,
    *,
    command: str,
    workdir: Path,
    stdin: str | None,
    wait_seconds: float,
    call_id: str,
) -> dict[str, Any]:
    return _request(
        socket_path,
        {
            "version": PROTOCOL_VERSION,
            "op": "start",
            "command": command,
            "workdir": str(workdir),
            "stdin": stdin,
            "wait_seconds": wait_seconds,
            "call_id": call_id,
        },
        timeout_s=max(5.0, wait_seconds + 5.0),
    )


def stop(socket_path: Path, job_id: str, *, call_id: str = "-") -> dict[str, Any]:
    return _request(
        socket_path,
        {
            "version": PROTOCOL_VERSION,
            "op": "stop",
            "job_id": job_id,
            "call_id": call_id,
        },
        timeout_s=10.0,
    )

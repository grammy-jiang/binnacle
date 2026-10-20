"""Opt-in, lossless MCP payload capture in private local daily JSONL files.

Standard journals remain sanitized. The operator explicitly accepts that
request arguments, source text, outputs and exception messages may be sensitive.
"""

from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import stat
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastmcp.prompts.base import Prompt
from fastmcp.resources.base import Resource
from fastmcp.tools.base import Tool
from pydantic import BaseModel

from binnacle.config_telemetry import FullCaptureSettings

_LOG = logging.getLogger("binnacle.full_capture")


def _serialize(value: Any) -> Any:
    if isinstance(value, Tool):
        return value.to_mcp_tool().model_dump(mode="json", by_alias=True)
    if isinstance(value, Resource):
        return value.to_mcp_resource().model_dump(mode="json", by_alias=True)
    if isinstance(value, Prompt):
        return value.to_mcp_prompt().model_dump(mode="json", by_alias=True)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, bytes):
        return {"__bytes_base64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported full-capture value type: {type(value).__name__}")


def _secure_root(root: Path) -> Path:
    """Reject symlinked paths or directories readable by other users."""
    root = root.expanduser()
    if not root.is_absolute():
        raise ValueError("full capture directory must be absolute")
    for component in (root, *root.parents):
        if component.is_symlink():
            raise ValueError("full capture directory must not traverse a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise PermissionError("full capture directory must be owned and private")
    return root


class FullCaptureSink:
    """Append full, untruncated MCP records; no data is sent to the journal."""

    def __init__(self, settings: FullCaptureSettings) -> None:
        if not settings.enabled:
            raise ValueError("full capture sink requires enabled=true")
        self.root = _secure_root(settings.directory)
        self.fsync = settings.fsync
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        row = {
            "schema": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        # JSON serialization happens before opening the output file, so one
        # record is appended as a complete byte string without content clipping.
        payload = (
            json.dumps(
                row, ensure_ascii=False, separators=(",", ":"), default=_serialize
            )
            + "\n"
        ).encode("utf-8")
        day = datetime.fromisoformat(row["timestamp"]).date().isoformat()
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW
        with self._lock:
            root = _secure_root(self.root)
            fd = os.open(root / f"{day}.jsonl", flags, 0o600)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                ):
                    raise PermissionError("full capture output file is not private")
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    offset = 0
                    while offset < len(payload):
                        written = os.write(fd, payload[offset:])
                        if written <= 0:
                            raise OSError("full capture write made no progress")
                        offset += written
                    if self.fsync:
                        os.fsync(fd)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def required(self, event: str, **fields: Any) -> None:
        """Refuse a new operation when its initial record cannot be saved."""
        try:
            self.write(event, **fields)
        except Exception as exc:  # noqa: BLE001 - convert to a stable refusal
            _LOG.error(
                "event=full_capture_error stage=%s error_class=%s",
                event,
                type(exc).__name__,
            )
            raise RuntimeError(
                "full capture unavailable; request not executed"
            ) from None

    def best_effort(self, event: str, **fields: Any) -> None:
        """Never turn an already-executed tool into a retryable failure."""
        try:
            self.write(event, **fields)
        except Exception as exc:  # noqa: BLE001 - never alter an executed tool result
            _LOG.error(
                "event=full_capture_error stage=%s error_class=%s",
                event,
                type(exc).__name__,
            )

"""Assemble unchanged sanitized journals with optional private full capture."""

from functools import partial

from fastmcp import FastMCP

from binnacle.config import Settings
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.logging_middleware import (
    RequestLoggingMiddleware,
    ToolLoggingMiddleware,
)
from binnacle.observability.full_capture import FullCaptureSink
from binnacle.observability.log_safety import safe_request_payload


def attach_logging(root: FastMCP, identity: ClientIdentity, settings: Settings) -> None:
    """Capture raw MCP evidence only with explicit telemetry.full_capture.enabled."""
    capture = (
        FullCaptureSink(settings.telemetry.full_capture)
        if settings.telemetry.full_capture.enabled
        else None
    )
    root.add_middleware(
        RequestLoggingMiddleware(
            identity,
            capture=capture,
            include_payloads=True,
            max_payload_length=500,
            payload_serializer=partial(
                safe_request_payload, root=settings.roots.default_root
            ),
        )
    )
    root.add_middleware(
        ToolLoggingMiddleware(
            identity,
            capture=capture,
            tokenizer=settings.telemetry.tokenizer,
            path_root=settings.roots.default_root,
        )
    )

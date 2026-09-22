"""Request logging: what a quality review of the server needs from the journal.

Two middlewares; the field inventory and the review recipes are in
docs/logging.md.

- :class:`RequestLoggingMiddleware` extends fastmcp's LoggingMiddleware,
  appending ``request_id=``, ``session=``, ``client=`` and ``tool=`` to its
  request_start / request_success / request_error lines. Those lines are
  rich-wrapped in the journal; they are the format `binnacle stats` has
  parsed since 2026-08-29 and stay unchanged.
- :class:`ToolLoggingMiddleware` writes one single-line ``tool_call`` and
  one ``tool_result`` record per tools/call. Both carry the same ``call=``
  id, which the job store also stamps on ``job_start``. The result line
  has the duration, the outcome (error class and message; errors reach
  this middleware as exceptions, so the 2026-09-02 version never saw
  one), the size the model actually receives (text chars, structured JSON
  bytes, a chars/4 token estimate, and optionally a configured tokenizer
  count) and the tools' own outcome and truncation facts lifted from
  ``structured_content``. The call line has
  the tunnel's ``X-Request-Id`` (``wfr_<turn>/<call>``, measured
  2026-09-13), which ties a journal record to one ChatGPT turn.
"""

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.middleware.logging import LoggingMiddleware

from binnacle.callctx import (
    current_argument_names,
    current_call,
    current_call_started,
    current_client,
)
from binnacle.config import get_settings
from binnacle.identity import ClientIdentity
from binnacle.token_telemetry import TokenCounter

# Proposed settings (module constants until config.py is free to edit).
ARGS_MAX_CHARS = 500  # same clip as the request_start payload
ERROR_MAX_CHARS = 200
HEADER_MAX_CHARS = 80
#: Request headers copied into the tool_call line, header -> log key.
#: ``X-Request-Id`` is the OpenAI tunnel's ``wfr_<turn>/<call>``: the part
#: before the slash is one agent turn (the tunnel log's cmd_request_id).
CORRELATION_HEADERS: dict[str, str] = {"x-request-id": "turn"}
#: Headers logged as a short SHA-256 prefix: a grouping key, not the value.
HASHED_HEADERS: dict[str, str] = {"x-openai-session": "oai_session"}
#: structured_content keys lifted into the tool_result line when present
#: (every tool's own outcome and truncation facts; docs/tools/<name>.md).
RESULT_KEYS = (
    "job_id",
    "state",
    "exit_code",
    "signal",
    "background_job",
    "truncated",
    "count",
    "total_lines",
    "start_line",
    "end_line",
    "lines_clipped",
    "kind",
    "output_bytes",
    "log_bytes",
    "quiet",
    "waited_s",
    "runtime_s",
    "last_output_age_s",
    "fits_in_one_call",
    "lossy",
    "next_start_line",
    "mime_guess",
    "mode",
    "replacements",
    "match",
    "first_change_line",
    "action",
    "previous_bytes",
    "bytes",
)
#: List-valued keys logged as their length.
RESULT_LIST_KEYS = ("entries", "jobs", "processes")


def _request_id(context: MiddlewareContext[Any]) -> str:
    ctx = context.fastmcp_context
    if ctx is None:
        return "-"
    try:
        return str(ctx.request_id)
    except (AttributeError, ValueError, RuntimeError):
        return "-"


def _session_marker(context: MiddlewareContext[Any]) -> str:
    """Short session tag: request ids restart per session (ChatGPT's legacy
    era opens a session per call), so pairing needs (session, request_id)."""
    ctx = context.fastmcp_context
    if ctx is None:
        return "-"
    try:
        session = ctx.session_id or id(ctx.session)
    except (AttributeError, RuntimeError):
        return "-"
    return str(session)[-12:]


class RequestLoggingMiddleware(LoggingMiddleware):
    def __init__(self, identity: ClientIdentity, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._identity = identity

    def _extra_fields(self, context: MiddlewareContext[Any]) -> dict[str, str]:
        fields = {
            "request_id": _request_id(context),
            "session": _session_marker(context),
            "client": self._identity.resolve(context) or "-",
        }
        tool = getattr(context.message, "name", None)
        if context.method == "tools/call" and tool:
            fields["tool"] = str(tool)
        return fields

    def _create_before_message(
        self, context: MiddlewareContext[Any]
    ) -> dict[str, str | int | float]:
        message = super()._create_before_message(context)
        message.update(self._extra_fields(context))
        return message

    def _create_after_message(
        self, context: MiddlewareContext[Any], start_time: float
    ) -> dict[str, str | int | float]:
        message = super()._create_after_message(context, start_time)
        message.update(self._extra_fields(context))
        return message

    def _create_error_message(
        self, context: MiddlewareContext[Any], start_time: float, error: Exception
    ) -> dict[str, str | int | float]:
        message = super()._create_error_message(context, start_time, error)
        message.update(self._extra_fields(context))
        return message


# -- single-line tool records -------------------------------------------------


def _token(value: Any, limit: int) -> str:
    """One whitespace-free key=value token, clipped."""
    return "".join(str(value).split())[:limit] or "-"


def _text(value: Any, limit: int) -> str:
    """Free text on one line (whitespace collapsed), clipped; goes last."""
    return " ".join(str(value).split())[:limit]


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _token(value, 40)


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _args_json(arguments: Any) -> tuple[int, str]:
    """Compact JSON of the call arguments and its full length.

    Non-string values come first and strings follow shortest first, so the
    short facts (wait_seconds, tail_lines, start_line, path) stay visible
    when one long command or content value runs past the clip; JSON
    escaping keeps it on one line.
    """
    items = list(dict(arguments or {}).items())
    items.sort(
        key=lambda kv: (
            isinstance(kv[1], str),
            len(kv[1]) if isinstance(kv[1], str) else 0,
        )
    )
    text = _compact_json(dict(items))
    full = len(text)
    if full > ARGS_MAX_CHARS:
        text = text[:ARGS_MAX_CHARS] + "..."
    return full, text


def _header_fields() -> dict[str, str]:
    """Correlation headers of the live HTTP request; empty in-memory.

    ``get_http_headers`` never raises and already strips ``authorization``.
    """
    headers = get_http_headers()
    fields: dict[str, str] = {}
    for name, key in CORRELATION_HEADERS.items():
        value = headers.get(name)
        if value:
            fields[key] = _token(value, HEADER_MAX_CHARS)
    for name, key in HASHED_HEADERS.items():
        value = headers.get(name)
        if value:
            fields[key] = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return fields


def _result_fields(
    result: Any, token_counter: TokenCounter | None = None
) -> dict[str, str]:
    """Sizes of what the client receives, plus the tool's own outcome facts."""
    content_parts = [
        getattr(block, "text", "") or ""
        for block in (getattr(result, "content", None) or [])
    ]
    content_chars = sum(len(part) for part in content_parts)
    structured = getattr(result, "structured_content", None)
    structured_text = _compact_json(structured) if structured is not None else ""
    fields = {
        "content_chars": str(content_chars),
        "structured_bytes": str(len(structured_text.encode("utf-8"))),
        # chars / 4: an estimate retained for historical comparability.
        "est_tokens": str((content_chars + len(structured_text)) // 4),
    }
    if token_counter is not None:
        tokenizer_tokens = token_counter.count((*content_parts, structured_text))
        if tokenizer_tokens is not None:
            fields["tokenizer_tokens"] = str(tokenizer_tokens)
            fields["tokenizer_encoding"] = _token(token_counter.encoding, 40)
    if isinstance(structured, dict):
        for key in RESULT_KEYS:
            if key in structured:
                fields[key] = _scalar(structured[key])
        for key in RESULT_LIST_KEYS:
            value = structured.get(key)
            if isinstance(value, list):
                fields[key] = str(len(value))
    return fields


def _duration_ms(start: float) -> str:
    return f"{(time.perf_counter() - start) * 1000:.2f}"


class ToolLoggingMiddleware(Middleware):
    """One ``tool_call`` and one ``tool_result`` line per tools/call."""

    def __init__(self, identity: ClientIdentity) -> None:
        self._identity = identity
        self._logger = logging.getLogger("binnacle.results")
        tokenizer = get_settings().telemetry.tokenizer
        self._token_counter = TokenCounter(
            enabled=tokenizer.enabled,
            encoding=tokenizer.encoding,
            client_prefixes=tokenizer.client_prefixes,
        )
        self._token_counter.prepare()

    def _log(self, event: str, level: int, *parts: dict[str, str]) -> None:
        try:
            fields: dict[str, str] = {}
            for part in parts:
                fields.update(part)
            self._logger.log(
                level,
                "event=%s %s",
                event,
                " ".join(f"{k}={v}" for k, v in fields.items()),
            )
        except Exception:  # pragma: no cover - logging must never break a call
            self._logger.debug("event=tool_logging_failed", exc_info=True)

    def _who(self, context: MiddlewareContext[Any], call_id: str) -> dict[str, str]:
        return {
            "call": call_id,
            "tool": _token(getattr(context.message, "name", "?"), 64),
            "client": _token(self._identity.resolve(context) or "-", 64),
            "session": _session_marker(context),
            "request_id": _token(_request_id(context), 40),
        }

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        call_id = uuid.uuid4().hex[:12]
        who = self._who(context, call_id)
        who.update(_header_fields())
        arguments = getattr(context.message, "arguments", None) or {}
        args_chars, args_text = _args_json(arguments)
        self._log(
            "tool_call",
            logging.INFO,
            who,
            {"args_chars": str(args_chars), "args": args_text},
        )
        token = current_call.set(call_id)
        client_token = current_client.set(
            None if who["client"] == "-" else who["client"]
        )
        argument_names_token = current_argument_names.set(frozenset(arguments))
        start = time.perf_counter()
        started_token = current_call_started.set(start)
        try:
            result = await call_next(context)
        except BaseException as e:
            # Tool errors (ToolError, validation, a hidden tool) arrive here
            # as exceptions and become isError results only at the wire;
            # a cancelled request lands here too and is worth a record.
            error_fields = {
                "duration_ms": _duration_ms(start),
                "is_error": "True",
                "error_class": _token(
                    "ToolError" if isinstance(e, ToolError) else type(e).__name__, 64
                ),
            }
            error_code = getattr(e, "telemetry_code", None)
            if isinstance(error_code, str) and error_code:
                error_fields["error_code"] = _token(error_code, 64)
            # error= remains the final free-text field for historical parsers.
            error_fields["error"] = _text(e, ERROR_MAX_CHARS)
            self._log("tool_result", logging.WARNING, who, error_fields)
            raise
        finally:
            current_call_started.reset(started_token)
            current_argument_names.reset(argument_names_token)
            current_client.reset(client_token)
            current_call.reset(token)
        is_error = bool(getattr(result, "is_error", False))
        fields = {"duration_ms": _duration_ms(start), "is_error": str(is_error)}
        token_counter = (
            self._token_counter if self._token_counter.applies(who["client"]) else None
        )
        fields.update(_result_fields(result, token_counter))
        if is_error:
            text = "".join(
                getattr(block, "text", "") or ""
                for block in (getattr(result, "content", None) or [])
            )
            fields["error_class"] = "ToolResult"
            fields["error"] = _text(text, ERROR_MAX_CHARS)
        self._log(
            "tool_result", logging.WARNING if is_error else logging.INFO, who, fields
        )
        return result

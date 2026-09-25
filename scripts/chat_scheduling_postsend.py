"""Post-send robustness helpers for live scheduling benchmark trials."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_INTERRUPTION_TEXT = [
    "streaming interrupted",
    "request timed out",
    "request timeout",
    "no complete reply within",
    "connection interrupted",
    "connection lost",
    "network error",
    "something went wrong",
    "error generating a response",
]


def conversation_facts(path: Path) -> tuple[str, bool, int, str | None]:
    if not path.exists():
        return "", False, 1, None
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("mapping") or {}
    user_messages = 0
    assistants: list[dict[str, Any]] = []
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if not isinstance(message, dict):
            continue
        role = (message.get("author") or {}).get("role")
        if role == "user":
            user_messages += 1
        elif role == "assistant":
            assistants.append(message)
    current = mapping.get(data.get("current_node"), {})
    final = current.get("message") if isinstance(current, dict) else None
    if (
        not isinstance(final, dict)
        or (final.get("author") or {}).get("role") != "assistant"
    ):
        final = assistants[-1] if assistants else None
    if not isinstance(final, dict):
        return "", False, max(user_messages, 1), "missing_final_assistant"
    content = final.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else []
    reply = "\n".join(part for part in (parts or []) if isinstance(part, str))
    metadata = final.get("metadata") or {}
    complete = (
        bool(metadata.get("is_complete"))
        or final.get("status") == "finished_successfully"
    )
    low = reply.lower()
    interruption = next((item for item in _INTERRUPTION_TEXT if item in low), None)
    return reply, complete, max(user_messages, 1), interruption


def captured_send_reply(record: dict[str, Any]) -> tuple[str, bool]:
    chat = record.get("chat")
    if not isinstance(chat, dict):
        return "", False
    result = chat.get("send_result")
    if not isinstance(result, dict):
        return "", False
    reply = result.get("reply")
    if not isinstance(reply, str):
        return "", False
    return reply, record.get("submission_status") == "completed"


def transient_read_failure(text: str) -> bool:
    lowered = text.lower()
    return "http 429" in lowered or "too many requests" in lowered


def sleep_poll_backoff(attempt: int, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    delay = min(float(2 ** min(max(attempt - 1, 0), 3)), remaining)
    time.sleep(delay)


def cleanup_failure_is_fatal(submission_status: str) -> bool:
    return submission_status != "completed"

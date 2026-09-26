"""Post-send robustness helpers for live scheduling benchmark trials."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

FIRST_POLL_DELAY_S = 5.0
POLL_INTERVAL_S = 10.0
MAX_POLL_BACKOFF_S = 60.0
POLL_JITTER_S = 2.0
OBSERVATION_GRACE_S = 600.0

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


def _conversation_data(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _final_assistant_message(data: dict[str, Any]) -> dict[str, Any] | None:
    mapping = data.get("mapping") or {}
    assistants: list[dict[str, Any]] = []
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if not isinstance(message, dict):
            continue
        if (message.get("author") or {}).get("role") == "assistant":
            assistants.append(message)
    current = mapping.get(data.get("current_node"), {})
    final = current.get("message") if isinstance(current, dict) else None
    if (
        not isinstance(final, dict)
        or (final.get("author") or {}).get("role") != "assistant"
    ):
        ended = [message for message in assistants if message.get("end_turn") is True]
        final = ended[-1] if ended else (assistants[-1] if assistants else None)
    return final if isinstance(final, dict) else None


def conversation_facts(path: Path) -> tuple[str, bool, int, str | None]:
    data = _conversation_data(path)
    if data is None:
        return "", False, 1, None
    mapping = data.get("mapping") or {}
    user_messages = 0
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if (
            isinstance(message, dict)
            and (message.get("author") or {}).get("role") == "user"
        ):
            user_messages += 1
    final = _final_assistant_message(data)
    if final is None:
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


def final_assistant_message_epoch(path: Path) -> float | None:
    data = _conversation_data(path)
    final = _final_assistant_message(data) if data is not None else None
    metadata = final.get("metadata") if isinstance(final, dict) else {}
    if final is None or not (
        final.get("end_turn") is True
        or (isinstance(metadata, dict) and bool(metadata.get("is_complete")))
    ):
        return None
    for key in ("create_time", "update_time"):
        value = final.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def finalize_conversation_timing(
    timing_path: Path, conversation_path: Path
) -> dict[str, Any] | None:
    if not timing_path.exists():
        return None
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    sent = timing.get("sent_at_epoch_s")
    settled = final_assistant_message_epoch(conversation_path)
    if not isinstance(sent, (int, float)) or settled is None:
        return None
    wall_s = round(max(0.0, settled - float(sent)), 3)
    timing["settled_at_epoch_s"] = settled
    timing["wall_s"] = wall_s
    timing["settle_time_source"] = "conversation_final_assistant_timestamp"
    limit = timing.get("turn_limit_s")
    if isinstance(limit, (int, float)):
        timing["within_turn_limit"] = wall_s <= float(limit)
    tmp = timing_path.with_suffix(timing_path.suffix + ".tmp")
    tmp.write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    tmp.replace(timing_path)
    return timing


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
    return any(
        marker in lowered
        for marker in (
            "http 403",
            "forbidden",
            "cloudflare",
            "http 429",
            "too many requests",
            "request timeout",
            "request timed out",
            "timed out",
        )
    )


def _sleep_delay(delay: float, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(delay, remaining))


def sleep_poll_interval(deadline: float, *, first: bool = False) -> None:
    base = FIRST_POLL_DELAY_S if first else POLL_INTERVAL_S
    jitter = secrets.randbelow(int(POLL_JITTER_S * 1000) + 1) / 1000
    _sleep_delay(base + jitter, deadline)


def sleep_poll_backoff(attempt: int, deadline: float) -> None:
    base = min(
        POLL_INTERVAL_S * float(2 ** max(attempt - 1, 0)),
        MAX_POLL_BACKOFF_S,
    )
    jitter = secrets.randbelow(int(POLL_JITTER_S * 1000) + 1) / 1000
    delay = min(base + jitter, MAX_POLL_BACKOFF_S)
    _sleep_delay(delay, deadline)


def cleanup_failure_is_fatal(submission_status: str) -> bool:
    return submission_status != "completed"

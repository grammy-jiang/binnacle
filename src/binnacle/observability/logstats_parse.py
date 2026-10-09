"""Low-level journal field helpers shared by usage-statistics analyzers."""

from __future__ import annotations

import json
import re
from typing import Any

from binnacle.observability.log_safety import path_digest

_PLAIN_KV = re.compile(r"(\w+)=(\S+)")
# Keys whose value is free text (spaces allowed); each is the last key on
# its line, so the value runs to the end of the record.
_PLAIN_TAIL_KEYS = (" args=", " error=")


def plain_fields(body: str) -> dict[str, str]:
    """key=value fields of a single-line binnacle record.

    The free-text tail (``args=`` on tool_call, ``error=`` on tool_result)
    is split off first at the earliest such key, so its content cannot
    masquerade as further keys.
    """
    head, tail_key, tail = body, None, None
    cut = min(
        (i for i in (body.find(k) for k in _PLAIN_TAIL_KEYS) if i >= 0),
        default=-1,
    )
    if cut >= 0:
        key = next(k for k in _PLAIN_TAIL_KEYS if body.find(k) == cut)
        head, tail_key, tail = body[:cut], key.strip()[:-1], body[cut + len(key) :]
    fields = dict(_PLAIN_KV.findall(head))
    if tail_key is not None and tail is not None:
        fields[tail_key] = tail
    return fields


def _json_args(body: str) -> dict[str, Any]:
    raw = plain_fields(body).get("args")
    if not raw or raw.endswith("..."):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _base_turn(value: str | None) -> str:
    return (value or "-").split("/", 1)[0]


def _path_hash(value: str) -> str:
    return path_digest(value)


def _int(value: str | None) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0

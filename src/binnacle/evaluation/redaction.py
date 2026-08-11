"""Bounded defense-in-depth scanning for retained evaluation evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

MAX_EVIDENCE_BYTES = 1_048_576
_TEXT_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/x-ndjson",
        "text/plain",
        "text/markdown",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "authorization_code",
        "cookie",
        "credential_content",
        "gateway_assertion",
        "machine_id",
        "private_key",
        "refresh_token",
        "set_cookie",
    }
)
_SECRET_PATTERNS = (
    ("authorization-header", re.compile(r"(?im)^authorization\s*[:=]\s*\S+")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("cookie-header", re.compile(r"(?im)^(?:set-cookie|cookie)\s*:\s*\S+")),
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    (
        "token-field",
        re.compile(
            r'(?i)["\'](?:access_token|refresh_token|authorization_code|gateway_assertion)'
            r'["\']\s*:\s*["\'][^"\']+["\']'
        ),
    ),
    ("raw-machine-id", re.compile(r"(?i)machine[-_ ]?id\s*[:=]\s*[a-f0-9]{32}\b")),
)


class RedactionViolation(ValueError):
    """Evidence contains a forbidden secret class or cannot be safely inspected."""

    def __init__(self, categories: Sequence[str]) -> None:
        self.categories = tuple(sorted(set(categories)))
        super().__init__("evidence redaction failed: " + ", ".join(self.categories))


def validate_sanitized_evidence(
    data: bytes,
    *,
    media_type: str,
    human_reviewed: bool = False,
) -> None:
    """Reject oversized, unreviewed binary, malformed, or secret-bearing evidence."""

    if len(data) > MAX_EVIDENCE_BYTES:
        raise RedactionViolation(("unbounded-payload",))
    if media_type not in _TEXT_MEDIA_TYPES:
        if not human_reviewed:
            raise RedactionViolation(("binary-requires-human-review",))
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RedactionViolation(("invalid-utf8",)) from exc

    categories = [name for name, pattern in _SECRET_PATTERNS if pattern.search(text)]
    if media_type in {"application/json", "application/x-ndjson"}:
        try:
            json_values = (
                [json.loads(line) for line in text.splitlines() if line]
                if media_type == "application/x-ndjson"
                else [json.loads(text)]
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise RedactionViolation(("invalid-json",)) from exc
        for value in json_values:
            categories.extend(_sensitive_json_categories(value))
    if categories:
        raise RedactionViolation(categories)


def allowlisted_json_bytes(
    source: Mapping[str, Any],
    *,
    allowed_fields: frozenset[str],
) -> bytes:
    """Generate structured evidence from an explicit top-level allowlist."""

    value = {key: source[key] for key in sorted(allowed_fields) if key in source}
    data = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    validate_sanitized_evidence(data, media_type="application/json")
    return data


def _sensitive_json_categories(value: object, *, depth: int = 0) -> list[str]:
    if depth > 64:
        return ["excessive-json-depth"]
    categories: list[str] = []
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for raw_key, child in mapping.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in _SENSITIVE_KEYS and child not in (None, "", "[redacted]", "removed"):
                categories.append(f"sensitive-field-{key}")
            categories.extend(_sensitive_json_categories(child, depth=depth + 1))
    elif isinstance(value, list):
        for child in value:
            categories.extend(_sensitive_json_categories(child, depth=depth + 1))
    return categories


__all__ = [
    "MAX_EVIDENCE_BYTES",
    "RedactionViolation",
    "allowlisted_json_bytes",
    "validate_sanitized_evidence",
]

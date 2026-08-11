"""RFC 8785 JSON Canonicalization Scheme helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

import rfc8785


class CanonicalizationError(ValueError):
    pass


_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "authorization_code",
        "credential",
        "idempotency_key",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def _reject_authority_material(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("audit object keys must be strings")
            normalized = key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise CanonicalizationError("authority material is forbidden in audit events")
            _reject_authority_material(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_authority_material(item)
    elif isinstance(value, (bytes, bytearray)):
        raise CanonicalizationError("binary values are not valid audit JSON")


def canonicalize(value: object) -> bytes:
    _reject_authority_material(value)
    try:
        return rfc8785.dumps(cast(Any, value))
    except (TypeError, ValueError, rfc8785.CanonicalizationError) as exc:
        raise CanonicalizationError("audit value is not RFC 8785 canonicalizable") from exc


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

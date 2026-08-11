"""Evidence secret scanning and allowlist-first generation tests."""

from __future__ import annotations

import pytest

from binnacle.evaluation.redaction import (
    MAX_EVIDENCE_BYTES,
    RedactionViolation,
    allowlisted_json_bytes,
    validate_sanitized_evidence,
)


@pytest.mark.parametrize(
    ("data", "category"),
    [
        (b"Authorization: Bearer abcdefghijklmnop", "authorization-header"),
        (b"Cookie: session=private-value", "cookie-header"),
        (b"-----BEGIN PRIVATE KEY-----", "private-key"),
        (b'{"refresh_token":"private-value"}', "token-field"),
        (b"machine-id=0123456789abcdef0123456789abcdef", "raw-machine-id"),
    ],
)
def test_secret_classes_are_rejected_without_echoing_secret(
    data: bytes,
    category: str,
) -> None:
    with pytest.raises(RedactionViolation) as captured:
        validate_sanitized_evidence(data, media_type="text/plain")

    assert category in captured.value.categories
    assert "private-value" not in str(captured.value)


def test_allowlist_generation_excludes_unselected_fields() -> None:
    data = allowlisted_json_bytes(
        {
            "build_sha256": "a" * 64,
            "catalogue_sha256": "b" * 64,
            "unrelated_prompt": "must-not-be-retained",
        },
        allowed_fields=frozenset({"build_sha256", "catalogue_sha256"}),
    )

    assert b"build_sha256" in data
    assert b"must-not-be-retained" not in data


def test_binary_evidence_requires_explicit_human_review() -> None:
    with pytest.raises(RedactionViolation, match="binary-requires-human-review"):
        validate_sanitized_evidence(b"image", media_type="image/png")

    validate_sanitized_evidence(
        b"image",
        media_type="image/png",
        human_reviewed=True,
    )


def test_oversized_evidence_is_rejected_before_scanning() -> None:
    with pytest.raises(RedactionViolation, match="unbounded-payload"):
        validate_sanitized_evidence(
            b"x" * (MAX_EVIDENCE_BYTES + 1),
            media_type="text/plain",
        )


@pytest.mark.parametrize(
    ("data", "media_type", "category"),
    [
        (b"\xff", "text/plain", "invalid-utf8"),
        (b"{", "application/json", "invalid-json"),
        (b'{"cookie":"private"}\n{}\n', "application/x-ndjson", "sensitive-field-cookie"),
    ],
)
def test_malformed_and_nested_structured_evidence_is_rejected(
    data: bytes,
    media_type: str,
    category: str,
) -> None:
    with pytest.raises(RedactionViolation) as captured:
        validate_sanitized_evidence(data, media_type=media_type)

    assert category in captured.value.categories

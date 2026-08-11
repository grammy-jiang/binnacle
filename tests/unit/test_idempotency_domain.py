"""Raw-key validation and non-disclosing digest tests."""

from __future__ import annotations

import base64

import pytest
from tests.phase4_support import owner

from binnacle.domain.idempotency import (
    IdempotencyKeyError,
    IdempotencyKeyMode,
    owner_digest,
    validate_and_digest_key,
)


def test_lower_hex_and_base64url_keys_digest_deterministically() -> None:
    raw = bytes(range(32))
    hexadecimal = validate_and_digest_key(raw.hex(), IdempotencyKeyMode.CALLER_KEY)
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    base64_key = validate_and_digest_key(encoded, IdempotencyKeyMode.CALLER_KEY)
    assert hexadecimal.digest_sha256 == base64_key.digest_sha256
    assert raw.hex() not in hexadecimal.digest_sha256


def test_key_mode_is_domain_separated() -> None:
    raw = "ab" * 16
    caller = validate_and_digest_key(raw, IdempotencyKeyMode.CALLER_KEY)
    prepared = validate_and_digest_key(raw, IdempotencyKeyMode.PREPARED_EXECUTION_NONCE)
    assert caller.digest_sha256 != prepared.digest_sha256


@pytest.mark.parametrize(
    "raw",
    [
        "not a key",
        "550e8400-e29b-41d4-a716-446655440000",
        "x" * 22 + "=",
    ],
)
def test_invalid_keys_fail_closed(raw: str) -> None:
    with pytest.raises(IdempotencyKeyError):
        validate_and_digest_key(raw, IdempotencyKeyMode.CALLER_KEY)


def test_derived_member_keys_are_absent_until_parent_contract_exists() -> None:
    with pytest.raises(IdempotencyKeyError, match="parent contract"):
        validate_and_digest_key("ab" * 16, IdempotencyKeyMode.DERIVED_MEMBER_KEY)


def test_owner_digest_binds_identity_and_epoch_without_disclosure() -> None:
    first = owner_digest(owner())
    replacement = owner_digest(owner("controller-replacement"))
    assert first != replacement
    assert "controller-fixture" not in first
    assert len(first) == 64

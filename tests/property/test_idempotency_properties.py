"""Generated idempotency digest invariants."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key


@given(st.binary(min_size=16, max_size=128))
def test_valid_hex_keys_are_deterministic_and_never_retained_raw(raw: bytes) -> None:
    first = validate_and_digest_key(raw.hex(), IdempotencyKeyMode.CALLER_KEY)
    second = validate_and_digest_key(raw.hex(), IdempotencyKeyMode.CALLER_KEY)
    assert first == second
    assert len(first.digest_sha256) == 64
    assert raw.hex() != first.digest_sha256


@given(st.binary(min_size=16, max_size=128))
def test_key_modes_are_domain_separated(raw: bytes) -> None:
    caller = validate_and_digest_key(raw.hex(), IdempotencyKeyMode.CALLER_KEY)
    prepared = validate_and_digest_key(raw.hex(), IdempotencyKeyMode.PREPARED_EXECUTION_NONCE)
    assert caller.digest_sha256 != prepared.digest_sha256

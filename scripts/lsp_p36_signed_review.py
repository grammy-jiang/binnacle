"""Offline Ed25519 review-receipt verification for an external P3.6 trust anchor.

This checks an independently pinned key against exact stage/target/digest
claims; it cannot certify artifacts, sign evidence, or authorize READ/P4.
No signer key or trust registry is created, downloaded or read by this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from scripts.lsp_p36_evidence import Digest, Record, Text

DOMAIN = b"BINNACLE:P3.6:ED25519:REVIEW:V1\x00"
Stage = Literal["P3.3", "P3.4", "P3.5"]
Verdict = Literal["GO", "REWORK", "NO-GO"]
MAX_BYTES = 16 * 1024


class ReviewRefused(ValueError):
    """Fixed non-sensitive denial identifier."""


class SignedReviewReceipt(Record):
    """All signed fields are immutable and covered by the Ed25519 signature."""

    receipt_schema: Literal["binnacle.p36.review-ed25519/1"]
    stage: Stage
    reviewer: Text
    producer: Text
    target_sha256: Digest
    artifact_sha256: Digest
    evidence_sha256: Digest
    verdict: Verdict
    issued_at_utc: Annotated[
        str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    ]
    signature_b64: Annotated[str, Field(min_length=84, max_length=92)]


class VerifiedReview(Record):
    """A signature witness, not a complete P3.6 admission attestation."""

    stage: Stage
    reviewer: Text
    signed_claim_verdict: Verdict
    signed_payload_sha256: Digest
    reviewed_artifact_sha256: Digest
    signature_valid: Literal[True] = True
    externally_trusted_reviewer: Literal[False] = False
    attestations_verified: Literal[False] = False
    selection: Literal["REWORK"] = "REWORK"
    resource: Literal["REWORK"] = "REWORK"
    read: Literal["NO-GO"] = "NO-GO"
    public_release: Literal["NO-GO"] = "NO-GO"


def canonical_bytes(record: SignedReviewReceipt) -> bytes:
    """Domain-separated signing bytes, no signature self-reference."""
    raw = json.dumps(
        record.model_dump(mode="json", exclude={"signature_b64"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return DOMAIN + raw


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, entry in pairs:
        if name in value:
            raise ReviewRefused("duplicate_review_key")
        value[name] = entry
    return value


def verify_signed_review(
    receipt_json: bytes,
    *,
    public_key: bytes,
    pinned_public_key_sha256: str,
    expected_reviewer: str,
    expected_producer: str,
    expected_stage: Stage,
    expected_target_sha256: str,
    expected_evidence_sha256: str,
    reviewed_artifact: bytes,
    now: datetime | None = None,
    max_age_s: int = 86400,
) -> VerifiedReview:
    """Verify bytes, signature, role separation and exact artifact identity.

    The caller must acquire the key and its digest from an *independent*
    operator trust store outside user-supplied evidence and agent-writable
    roots. This function cannot prove that precondition and grants no GO.
    """
    if (
        len(receipt_json) > MAX_BYTES
        or len(reviewed_artifact) > 4 * 1024 * 1024
        or not 0 < len(receipt_json)
        or not 0 < len(reviewed_artifact)
    ):
        raise ReviewRefused("review_input_size_invalid")
    if (
        type(max_age_s) is not int
        or not 0 < max_age_s <= 30 * 86400
        or len(public_key) != 32
        or not hmac.compare_digest(
            hashlib.sha256(public_key).hexdigest(), pinned_public_key_sha256
        )
    ):
        raise ReviewRefused("operator_key_pin_unverified")
    try:
        unpacked = json.loads(receipt_json, object_pairs_hook=_no_duplicates)
        item = SignedReviewReceipt.model_validate(unpacked)
    except (UnicodeError, ValueError, TypeError, ValidationError) as exc:
        raise ReviewRefused("invalid_review_schema") from exc
    if (
        item.stage != expected_stage
        or item.reviewer != expected_reviewer
        or item.producer != expected_producer
        or item.reviewer == item.producer
        or item.target_sha256 != expected_target_sha256
        or item.evidence_sha256 != expected_evidence_sha256
        or not hmac.compare_digest(
            item.artifact_sha256, hashlib.sha256(reviewed_artifact).hexdigest()
        )
    ):
        raise ReviewRefused("review_scope_or_identity_mismatch")
    try:
        issued = datetime.strptime(item.issued_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ReviewRefused("invalid_review_timestamp") from exc
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ReviewRefused("invalid_review_clock")
    age = instant.astimezone(timezone.utc) - issued
    if not -timedelta(minutes=5) <= age <= timedelta(seconds=max_age_s):
        raise ReviewRefused("review_expired_or_future")
    try:
        signature = base64.b64decode(item.signature_b64, validate=True)
        if len(signature) != 64:
            raise ReviewRefused("review_signature_invalid")
        payload = canonical_bytes(item)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise ReviewRefused("review_signature_invalid") from exc
    return VerifiedReview(
        stage=item.stage,
        reviewer=item.reviewer,
        signed_claim_verdict=item.verdict,
        signed_payload_sha256=hashlib.sha256(payload).hexdigest(),
        reviewed_artifact_sha256=item.artifact_sha256,
    )

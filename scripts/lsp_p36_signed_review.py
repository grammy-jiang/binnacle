"""Offline Ed25519 review-receipt verification for P3.6.

``verify_signed_review`` (receipt v1) is a self-contained proof of signature
under a caller-supplied key. It authenticates nobody and grants no authority.
``verify_registry_review`` (receipt v2) additionally resolves the signer in an
operator-managed registry loaded by ``scripts.lsp_p36_trust_registry``. Both
only report a signed *claim*; neither certifies artifacts, signs evidence, or
authorizes READ/P4. No key is generated, enrolled or downloaded here.
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
from scripts.lsp_p36_trust_registry import (
    RegistryRefused,
    ReplayLedger,
    TrustRegistry,
    replay_key,
)

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


def _loads_strict(raw: bytes) -> object:
    return json.loads(raw, object_pairs_hook=_no_duplicates)


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


DOMAIN_V2 = b"BINNACLE:P3.6:ED25519:REVIEW:V2\x00"
Outcome = Literal["verified_approval", "verified_rework", "verified_no_go"]
_OUTCOMES: dict[str, Outcome] = {
    "GO": "verified_approval",
    "REWORK": "verified_rework",
    "NO-GO": "verified_no_go",
}


class RegistryReviewReceipt(Record):
    """Receipt v2: key id, registry and run scope are signed, never trusted."""

    receipt_schema: Literal["binnacle.p36.review-ed25519/2"]
    stage: Stage
    key_id: Digest
    registry_id: Text
    run_id: Text
    reviewer: Text
    producer: Text
    binnacle_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    target_sha256: Digest
    artifact_sha256: Digest
    evidence_sha256: Digest
    verdict: Verdict
    issued_at_utc: Annotated[
        str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    ]
    signature_b64: Annotated[str, Field(min_length=84, max_length=92)]


class TrustedReview(Record):
    """Registry-authenticated signed claim; still carries no authority."""

    stage: Stage
    reviewer: Text
    key_id: Digest
    registry_id: Text
    registry_serial: int
    registry_sha256: Digest
    registry_owner_is_current_user: bool
    run_id: Text
    outcome: Outcome
    signed_payload_sha256: Digest
    reviewed_artifact_sha256: Digest
    replay_key: Digest
    signature_valid: Literal[True] = True
    reviewer_authenticated_by_registry: Literal[True] = True
    externally_trusted_reviewer: Literal[False] = False
    authority_granted: Literal[False] = False
    os_confinement_accepted: Literal[False] = False
    attestations_verified: Literal[False] = False
    selection: Literal["REWORK"] = "REWORK"
    resource: Literal["REWORK"] = "REWORK"
    read: Literal["NO-GO"] = "NO-GO"
    public_release: Literal["NO-GO"] = "NO-GO"


def canonical_bytes_v2(record: RegistryReviewReceipt) -> bytes:
    raw = json.dumps(
        record.model_dump(mode="json", exclude={"signature_b64"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return DOMAIN_V2 + raw


def _refuse_mismatch(item: RegistryReviewReceipt, expected: dict[str, str]) -> None:
    if any(getattr(item, name) != value for name, value in expected.items()):
        raise ReviewRefused("review_scope_or_identity_mismatch")


def verify_registry_review(
    receipt_json: bytes,
    *,
    registry: TrustRegistry,
    ledger: ReplayLedger,
    expected_stage: Stage,
    expected_producer: str,
    expected_run_id: str,
    expected_binnacle_commit: str,
    expected_target_sha256: str,
    expected_evidence_sha256: str,
    reviewed_artifact: bytes,
    now: datetime | None = None,
    max_age_s: int = 86400,
    consume: bool = True,
) -> TrustedReview:
    """Verify a v2 receipt against an operator registry; grants no authority.

    The signer's public key, principal and stage roles come only from
    ``registry``. The receipt supplies a key id, never a key or a role.
    """
    if not isinstance(registry, TrustRegistry):
        raise ReviewRefused("trust_registry_missing")
    if (
        not 0 < len(receipt_json) <= MAX_BYTES
        or not 0 < len(reviewed_artifact) <= 4 * 1024 * 1024
    ):
        raise ReviewRefused("review_input_size_invalid")
    if type(max_age_s) is not int or not 0 < max_age_s <= 30 * 86400:
        raise ReviewRefused("review_age_policy_invalid")
    try:
        item = RegistryReviewReceipt.model_validate(_loads_strict(receipt_json))
    except (ValueError, TypeError, ValidationError) as exc:
        raise ReviewRefused("invalid_review_schema") from exc
    _refuse_mismatch(
        item,
        {
            "stage": expected_stage,
            "producer": expected_producer,
            "run_id": expected_run_id,
            "binnacle_commit": expected_binnacle_commit,
            "target_sha256": expected_target_sha256,
            "evidence_sha256": expected_evidence_sha256,
            "registry_id": registry.doc.registry_id,
            "artifact_sha256": hashlib.sha256(reviewed_artifact).hexdigest(),
        },
    )
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ReviewRefused("invalid_review_clock")
    instant = instant.astimezone(timezone.utc)
    issued = datetime.strptime(item.issued_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    if not -timedelta(minutes=5) <= instant - issued <= timedelta(seconds=max_age_s):
        raise ReviewRefused("review_expired_or_future")
    try:
        key = registry.resolve(item.key_id, item.stage, issued, instant)
    except RegistryRefused as exc:
        raise ReviewRefused(str(exc)) from exc
    if item.reviewer != key.principal:
        raise ReviewRefused("signer_identity_mismatch")
    if item.reviewer == item.producer or item.reviewer == expected_producer:
        raise ReviewRefused("self_review_refused")
    try:
        signature = base64.b64decode(item.signature_b64, validate=True)
        payload = canonical_bytes_v2(item)
        if len(signature) != 64:
            raise ValueError("signature length")
        Ed25519PublicKey.from_public_bytes(key.public_key()).verify(signature, payload)
    except (InvalidSignature, ValueError, binascii.Error, RegistryRefused) as exc:
        raise ReviewRefused("review_signature_invalid") from exc
    marker = replay_key(item.registry_id, item.run_id, item.stage)
    try:
        if ledger.seen(marker):
            raise ReviewRefused("review_replay_detected")
        if consume:
            ledger.record([marker])
    except RegistryRefused as exc:
        raise ReviewRefused(str(exc)) from exc
    return TrustedReview(
        stage=item.stage,
        reviewer=item.reviewer,
        key_id=item.key_id,
        registry_id=item.registry_id,
        registry_serial=registry.doc.serial,
        registry_sha256=registry.sha256,
        registry_owner_is_current_user=registry.owner_is_current_user,
        run_id=item.run_id,
        outcome=_OUTCOMES[item.verdict],
        signed_payload_sha256=hashlib.sha256(payload).hexdigest(),
        reviewed_artifact_sha256=item.artifact_sha256,
        replay_key=marker,
    )

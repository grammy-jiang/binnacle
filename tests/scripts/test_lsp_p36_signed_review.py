"""P3.6 review cryptography: key pins and signatures without admission authority."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.lsp_p36_signed_review import (
    ReviewRefused,
    SignedReviewReceipt,
    canonical_bytes,
    verify_signed_review,
)

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
ARTIFACT = b'{"synthetic_fixture_only":true}'
TARGET = hashlib.sha256(b"disposable-reviewed-target").hexdigest()
EVIDENCE = hashlib.sha256(b"disposable-review-payload").hexdigest()


@pytest.fixture
def signed():
    signer = Ed25519PrivateKey.generate()  # ephemeral test-only, never saved
    pub = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    item = SignedReviewReceipt(
        receipt_schema="binnacle.p36.review-ed25519/1",
        stage="P3.3",
        reviewer="independent-security-reviewer",
        producer="synthetic-ci-producer",
        target_sha256=TARGET,
        evidence_sha256=EVIDENCE,
        artifact_sha256=hashlib.sha256(ARTIFACT).hexdigest(),
        verdict="GO",
        issued_at_utc="2026-10-23T07:00:00Z",
        signature_b64=base64.b64encode(b"x" * 64).decode(),
    )
    sig = signer.sign(canonical_bytes(item))
    encoded = item.model_copy(update={"signature_b64": base64.b64encode(sig).decode()})
    return {
        "signer": signer,
        "pub": pub,
        "receipt": encoded,
        "args": {
            "public_key": pub,
            "pinned_public_key_sha256": hashlib.sha256(pub).hexdigest(),
            "expected_reviewer": item.reviewer,
            "expected_producer": item.producer,
            "expected_stage": item.stage,
            "expected_target_sha256": TARGET,
            "expected_evidence_sha256": EVIDENCE,
            "reviewed_artifact": ARTIFACT,
            "now": NOW,
        },
    }


def _encoded(item):
    return item.model_dump_json().encode("utf-8")


def test_exact_signature_checks_pass_but_never_authorize(signed):
    result = verify_signed_review(_encoded(signed["receipt"]), **signed["args"])
    assert result.signature_valid
    assert not result.externally_trusted_reviewer
    assert result.read == result.public_release == "NO-GO"
    assert result.reviewed_artifact_sha256 == hashlib.sha256(ARTIFACT).hexdigest()
    assert result.signed_claim_verdict == "GO"  # Signed claim only.
    assert result.selection == result.resource == "REWORK"
    assert not result.attestations_verified


@pytest.mark.parametrize(
    "field,replacement,reason",
    [
        ("reviewed_artifact", b"tampered", "scope_or_identity"),
        ("expected_target_sha256", "0" * 64, "scope_or_identity"),
        ("expected_evidence_sha256", "0" * 64, "scope_or_identity"),
        ("expected_reviewer", "some-other-reviewer", "scope_or_identity"),
        ("expected_producer", "different-producer", "scope_or_identity"),
        ("expected_stage", "P3.5", "scope_or_identity"),
        ("pinned_public_key_sha256", "0" * 64, "operator_key_pin"),
    ],
)
def test_external_scope_and_trust_anchor_are_not_receipt_controlled(
    signed, field, replacement, reason
):
    args = {**signed["args"], field: replacement}
    with pytest.raises(ReviewRefused, match=reason):
        verify_signed_review(_encoded(signed["receipt"]), **args)


@pytest.mark.parametrize(
    "modification",
    [
        {"verdict": "NO-GO"},
        {"stage": "P3.4"},
        {"producer": "independent-security-reviewer"},
        {"artifact_sha256": "0" * 64},
        {"issued_at_utc": "2026-10-24T07:00:00Z"},
    ],
)
def test_signed_payload_changes_without_resigning_are_rejected(signed, modification):
    changed = signed["receipt"].model_copy(update=modification)
    with pytest.raises(ReviewRefused):
        verify_signed_review(_encoded(changed), **signed["args"])


def test_external_different_signer_cannot_impersonate_pinned_key(signed):
    rogue = Ed25519PrivateKey.generate()
    signature = rogue.sign(canonical_bytes(signed["receipt"]))
    tampered = signed["receipt"].model_copy(
        update={"signature_b64": base64.b64encode(signature).decode()}
    )
    with pytest.raises(ReviewRefused, match="review_signature_invalid"):
        verify_signed_review(_encoded(tampered), **signed["args"])


def test_self_review_refuses_even_valid_signature(signed):
    change = signed["receipt"].model_copy(
        update={"producer": "independent-security-reviewer"}
    )
    signed_again = signed["signer"].sign(canonical_bytes(change))
    change = change.model_copy(
        update={"signature_b64": base64.b64encode(signed_again).decode()}
    )
    args = {**signed["args"], "expected_producer": change.producer}
    with pytest.raises(ReviewRefused, match="scope_or_identity_mismatch"):
        verify_signed_review(_encoded(change), **args)


@pytest.mark.parametrize("age", [timedelta(days=2), timedelta(minutes=-6)])
def test_stale_or_future_receipts_refused(signed, age):
    now = NOW + age
    with pytest.raises(ReviewRefused, match="review_expired_or_future"):
        verify_signed_review(
            _encoded(signed["receipt"]), **{**signed["args"], "now": now}
        )


@pytest.mark.parametrize("case", ["duplicate", "unknown", "missing", "invalid_b64"])
def test_strict_schema_refuses_untrusted_or_ambiguous_fields(signed, case):
    data = json.loads(_encoded(signed["receipt"]))
    if case == "duplicate":
        text = '{"receipt_schema":"x",' + _encoded(signed["receipt"])[1:].decode()
    elif case == "unknown":
        data["external-trust-attested"] = True
        text = json.dumps(data)
    elif case == "missing":
        data.pop("stage")
        text = json.dumps(data)
    else:
        data["signature_b64"] = "!" * 88
        text = json.dumps(data)
    with pytest.raises(ReviewRefused):
        verify_signed_review(text.encode(), **signed["args"])


def test_review_key_or_timestamp_does_not_leak_in_refusal(signed):
    # Neither raw user data nor signed report bytes should appear in errors.
    with pytest.raises(ReviewRefused) as exc:
        verify_signed_review(
            b'{"secret":"fixture-only-not-a-real-key"}',
            **signed["args"],
        )
    assert "fixture-only-not-a-real-key" not in str(exc.value)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("override", [0, -1, 86400 * 31, True])
def test_operator_age_policy_cannot_be_disabled(signed, override):
    with pytest.raises(ReviewRefused, match="operator_key_pin_unverified"):
        verify_signed_review(
            _encoded(signed["receipt"]),
            **{**signed["args"], "max_age_s": override},
        )

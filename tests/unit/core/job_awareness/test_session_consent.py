"""E2 S2 CA-1: ``lab-session-route-v1`` consent allowlist, schema and example."""

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

from binnacle.features.commands.job_awareness.models import (
    CONSENT_VERSIONS,
    JobRef,
    PrincipalClaims,
    RunGrantClaims,
    Scope,
    Success,
)
from binnacle.features.commands.job_awareness.receipt_schema import (
    decode_claims,
    encode_claims,
)
from tests.unit.core.job_awareness.test_grants import LabFixture

ROOT = Path(__file__).resolve().parents[4]
FOLDER = ROOT / "docs/job-awareness-implementation/p0/contract-schemas"


def claims_from_example(value: dict) -> RunGrantClaims:
    record = dict(value)
    record["principal"] = PrincipalClaims(**record["principal"])
    record["jobs"] = tuple(JobRef(**job) for job in record["jobs"])
    record["scopes"] = frozenset(Scope(scope) for scope in record["scopes"])
    return RunGrantClaims(**record)


def test_allowlist_is_exactly_two_versions():
    assert frozenset({"lab-user-run-v1", "lab-session-route-v1"}) == CONSENT_VERSIONS


def test_schema_enum_and_examples_agree_with_the_model():
    schema = json.loads((FOLDER / "contracts.schema.json").read_text())
    examples = json.loads((FOLDER / "examples.json").read_text())
    definition = schema["$defs"]["RunGrantClaims"]
    assert set(definition["properties"]["consent_version"]["enum"]) == CONSENT_VERSIONS
    validator = Draft202012Validator(
        {"$ref": "#/$defs/RunGrantClaims", "$defs": schema["$defs"]}
    )
    valid = [
        row["value"] for row in examples["valid"] if row["type"] == "RunGrantClaims"
    ]
    invalid = [
        row["value"] for row in examples["invalid"] if row["type"] == "RunGrantClaims"
    ]
    assert {row["consent_version"] for row in valid} == CONSENT_VERSIONS
    for value in valid:
        validator.validate(value)
        claims = claims_from_example(value)
        assert decode_claims(encode_claims(claims)) == claims
    assert invalid
    for value in invalid:
        with pytest.raises(ValidationError):
            validator.validate(value)
        with pytest.raises(ValueError):
            claims_from_example(value)


class ConsentGrantTests(LabFixture, unittest.TestCase):
    def test_issue_grant_records_the_session_route_consent(self):
        capability = self.ok(
            self.authority.issue_grant(
                self.person,
                (self.job,),
                frozenset({Scope.OBSERVE, Scope.READ}),
                ttl_ms=60000,
                consent_version="lab-session-route-v1",
            )
        )
        handle = self.ok(
            self.authority.verify(self.credential, capability, Scope.OBSERVE)
        )
        self.assertIsNotNone(handle)
        digest = hashlib.sha256(capability).hexdigest()
        record = self.ok(
            self.store.read_transaction(lambda tx: tx.grant_for_capability(digest))
        )
        self.assertEqual(record.claims.consent_version, "lab-session-route-v1")
        self.assertEqual(self.authority.epoch, record.claims.issuer_epoch)

    def test_unknown_consent_is_denied(self):
        for version in ("chat", "lab-session-route-v2", "", None):
            self.denied(
                self.authority.issue_grant(
                    self.person,
                    (self.job,),
                    frozenset({Scope.OBSERVE}),
                    consent_version=version,
                )
            )
        claims = self.ok(
            self.store.read_transaction(
                lambda tx: tx.grant_for_capability(
                    hashlib.sha256(self.capability).hexdigest()
                )
            )
        ).claims
        self.assertEqual(claims.consent_version, "lab-user-run-v1")
        with self.assertRaises(ValueError):
            replace(claims, consent_version="lab-session-route-v2")
        self.assertIsInstance(
            Success(replace(claims, consent_version="lab-session-route-v1")), Success
        )

"""Synthetic credentials only. No chat labels establish authority."""

import copy
import hashlib
import importlib
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    PrincipalClaims,
    ReceiptState,
    Scope,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
    VerifiedRunGrant,
)


class Unregistered(VerifiedRunGrant):
    @property
    def authority_handle(self):
        raise AssertionError("Untrusted handle attributes must not be read")


class Catalog:
    """Controller-owned append-only test catalog; leases pin immutable copies."""

    def __init__(self, authority, snapshot, data):
        self.authority = authority
        self.snapshot = snapshot
        self.data = data
        self.opens = self.pins = self.closed = 0
        self.before_open = lambda: None

    def open_verified(self, grant, snapshot):
        self.before_open()
        if (
            self.authority.check(grant, snapshot.job, frozenset({Scope.READ}))
            is not AuthorityDecision.AUTHORIZED
        ):
            return Failure(BoundaryError(ErrorCode.DENIED))
        self.opens += 1
        if snapshot != self.snapshot:
            return Failure(BoundaryError(ErrorCode.SOURCE_UNSEALED))
        if (
            len(self.data) != snapshot.byte_length
            or hashlib.sha256(self.data).hexdigest() != snapshot.sha256
        ):
            return Failure(BoundaryError(ErrorCode.OUTPUT_CHANGED))
        catalog = self

        class Lease:
            def __init__(self):
                self.snapshot, self.verified_bytes = snapshot, catalog.data

            def __enter__(self):
                catalog.pins += 1
                return self

            def __exit__(self, *args):
                catalog.pins -= 1
                catalog.closed += 1

        return Success(Lease())


class LabFixture:
    def setUp(self):
        self.mod = importlib.import_module(
            "binnacle.features.commands.job_awareness.grants"
        )
        self.temp = tempfile.TemporaryDirectory(prefix="ja-i12-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.wall, self.mono = 1000, 0
        self.clock = self.mod.TrustedClock(lambda: self.wall, lambda: self.mono)
        self.principal = PrincipalClaims("1" * 32, "2" * 32, "3" * 32, "4" * 32)
        self.job = JobRef("ja1_" + "5" * 32, "6" * 12, "g1_" + "7" * 32)
        self.data = b"x" * 16385
        self.snapshot = OutputSnapshot(
            self.job,
            hashlib.sha256(self.data).hexdigest(),
            len(self.data),
            TerminalOutcome(TerminalKind.EXIT_CODE, 1),
            1,
            800000,
            SourceKind.CONTROLLER_SEALED_SYNTHETIC,
            "8" * 32,
        )
        self.authority = self.mod.SyntheticAuthority(
            self.path, self.principal.issuer_id, self.clock
        )
        self.ok(self.authority.start())
        self.credential = self.ok(self.authority.register_principal(self.principal))
        self.person = self.ok(self.authority.verify_principal(self.credential))
        self.capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset(Scope), ttl_ms=900000
            )
        )
        self.handle = self.ok(
            self.authority.verify(self.credential, self.capability, Scope.READ)
        )
        self.store = self.authority.store
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_snapshot(self.snapshot, self.data)
            )
        )
        self.catalog = Catalog(self.authority, self.snapshot, self.data)

    def ok(self, result):
        self.assertIsInstance(result, Success, result)
        return result.value

    def denied(self, result):
        self.assertEqual(result, Failure(BoundaryError(ErrorCode.DENIED)))

    def counts(self):
        with sqlite3.connect(self.path) as db:
            return tuple(
                db.execute(statement).fetchone()[0]
                for statement in (
                    "SELECT count(*) FROM proofs",
                    "SELECT count(*) FROM receipts",
                    "SELECT count(*) FROM pages",
                )
            )

    def service(self, **kwargs):
        mod = importlib.import_module("binnacle.features.commands.job_awareness.proofs")
        return mod.SyntheticProofService(self.authority, self.catalog, **kwargs)

    def advance(self, milliseconds):
        self.wall += milliseconds
        self.mono += milliseconds * 1000000


class GrantTests(LabFixture, unittest.TestCase):
    def test_shared_principal_denied(self):
        """AUTH-01: shared bearer, chat labels, capability alone do not authenticate."""
        for credential in (
            b"binnacle-tunnel",
            b"X-OpenAI-Session",
            b"chat-id",
            self.capability,
            b"?" * 32,
        ):
            self.denied(self.authority.verify(credential, self.capability, Scope.READ))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_cross_subject_capability(self):
        """AUTH-02: independent credentials bind every principal component."""
        for field in ("tenant_id", "subject_id", "consumer_id"):
            credential = self.ok(
                self.authority.register_principal(
                    replace(self.principal, **{field: "9" * 32})
                )
            )
            self.denied(self.authority.verify(credential, self.capability, Scope.READ))
        self.denied(
            self.authority.register_principal(
                replace(self.principal, issuer_id="9" * 32)
            )
        )

    def test_disclosed_same_subject_transfer(self):
        """AUTH-03: same credential transfer is user/run scope, not chat-private."""
        other_chat_handle = self.ok(
            self.authority.verify(self.credential, self.capability, Scope.ACK)
        )
        self.assertIs(other_chat_handle, self.handle)
        self.assertIs(
            self.authority.check(other_chat_handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.AUTHORIZED,
        )

    def test_registered_identity_and_exact_selector(self):
        for handle in (Unregistered(), copy.copy(self.handle), object()):
            self.assertIs(
                self.authority.check(handle, self.job, frozenset({Scope.READ})),
                AuthorityDecision.DENIED,
            )
            self.denied(self.store.query(handle, self.snapshot))
        for scopes in (frozenset(), frozenset({"read"}), {Scope.READ}):
            self.assertIs(
                self.authority.check(self.handle, self.job, scopes),
                AuthorityDecision.DENIED,
            )
        for field, value in (
            ("incarnation", "g1_" + "a" * 32),
            ("job_id", "b" * 12),
            ("run_namespace", "ja1_" + "c" * 32),
        ):
            self.assertIs(
                self.authority.check(
                    self.handle,
                    replace(self.job, **{field: value}),
                    frozenset({Scope.READ}),
                ),
                AuthorityDecision.DENIED,
            )

    def test_ttl_and_clock(self):
        """AUTH-07: exact TTL, fresh read high-water, and latched regress denial."""
        self.advance(900000)
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.EXPIRED,
        )
        self.denied(self.authority.verify(self.credential, self.capability, Scope.READ))
        self.ok(self.authority.revoke(self.handle))
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.REVOKED,
        )

    def test_clock_regress_after_read_latches(self):
        self.advance(10)
        self.ok(self.store.query(self.handle, self.snapshot))
        self.wall -= 1
        self.assertEqual(
            self.store.query(self.handle, self.snapshot),
            Failure(BoundaryError(ErrorCode.CLOCK_UNSAFE)),
        )
        self.wall += 100
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.DENIED,
        )

    def test_monotonic_expiry_and_regress(self):
        self.mono = 900000 * 1000000
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.EXPIRED,
        )
        self.mono -= 1
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.DENIED,
        )

    def test_forward_jump_cannot_extend_monotonic_ttl(self):
        self.wall += 1000000
        capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset(Scope), ttl_ms=3
            )
        )
        handle = self.ok(self.authority.verify(self.credential, capability, Scope.READ))
        self.mono += 3000000
        self.assertIs(
            self.authority.check(handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.EXPIRED,
        )

    def test_query_is_read_only_and_default_ack_denies(self):
        before = self.path.read_bytes()
        self.assertIs(
            self.ok(self.store.query(self.handle, self.snapshot)).state,
            ReceiptState.UNCONFIRMED,
        )
        self.denied(self.store.acknowledge(self.handle, self.snapshot, ("0" * 64,)))
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_verifier_and_unstarted_controller(self):
        from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore

        store = ReceiptStore(self.path, clock=self.clock.now)
        self.denied(store.query(self.handle, self.snapshot))
        authority = self.mod.SyntheticAuthority(
            self.path, self.principal.issuer_id, self.clock
        )
        self.denied(authority.verify(self.credential, self.capability, Scope.READ))
        self.denied(authority.register_principal(self.principal))

    def test_no_authority_disclosure(self):
        service = self.service()
        for snapshot in (
            self.snapshot,
            replace(self.snapshot, seal_id="0" * 32),
            replace(self.snapshot, job=replace(self.job, job_id="0" * 12)),
        ):
            self.denied(service.issue(Unregistered(), snapshot, 0))
            self.denied(service.acknowledge(Unregistered(), snapshot, ("0" * 64,)))
        self.assertEqual(self.catalog.opens, 0)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_denial_queries_no_snapshot_or_receipt_tables(self):
        statements = []
        connect = self.store._connect

        def traced(create):
            db = connect(create)
            db.set_trace_callback(statements.append)
            return db

        with patch.object(self.store, "_connect", traced):
            self.denied(self.store.query(Unregistered(), self.snapshot))
        for statement in statements:
            self.assertFalse(
                any(
                    table in statement
                    for table in (
                        "FROM snapshots",
                        "FROM receipts",
                        "FROM pages",
                        "FROM proofs",
                    )
                )
            )

    def test_clock_source_failure_is_latched(self):
        with patch.object(
            self.clock, "_wall", side_effect=OSError("Clock unavailable")
        ):
            self.denied(
                self.authority.verify(self.credential, self.capability, Scope.READ)
            )
        self.denied(self.authority.verify(self.credential, self.capability, Scope.READ))

    def test_independent_credential_and_capability_digests(self):
        with sqlite3.connect(self.path) as db:
            capability_digest, credential_digest = db.execute(
                "SELECT capability_sha256,credential_sha256 FROM grants"
            ).fetchone()
        self.assertEqual(capability_digest, hashlib.sha256(self.capability).hexdigest())
        self.assertEqual(credential_digest, hashlib.sha256(self.credential).hexdigest())
        self.assertNotEqual(capability_digest, credential_digest)
        for secret in (self.capability, self.credential):
            self.assertNotIn(secret, self.path.read_bytes())

    def test_copied_principal_and_bad_grant_limits(self):
        self.denied(
            self.authority.issue_grant(
                copy.copy(self.person), (self.job,), frozenset(Scope)
            )
        )
        for ttl in (True, 0, 3600001):
            self.denied(
                self.authority.issue_grant(
                    self.person, (self.job,), frozenset(Scope), ttl_ms=ttl
                )
            )
        for scopes in (frozenset(), frozenset({"read"})):
            self.denied(self.authority.issue_grant(self.person, (self.job,), scopes))

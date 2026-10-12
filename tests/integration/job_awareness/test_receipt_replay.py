"""P0 duplicate-proof recovery preserves authority and durable receipt state."""

import hashlib
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    ByteRange,
    ReceiptState,
    Scope,
)
from binnacle.features.commands.job_awareness.receipt_store import ReceiptTransaction
from tests.unit.core.job_awareness.test_grants import Catalog, LabFixture


class ReplayTests(LabFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.proofs = self.service()

    def ack(self, *tokens):
        return self.proofs.acknowledge(self.handle, self.snapshot, tokens)

    def confirm(self, start=0):
        page = self.ok(self.proofs.issue(self.handle, self.snapshot, start))
        return page, self.ok(self.ack(page.proof))

    def read_ack_only(self, ttl_ms=900000):
        capability = self.ok(
            self.authority.issue_grant(
                self.person,
                (self.job,),
                frozenset({Scope.READ, Scope.ACK}),
                ttl_ms=ttl_ms,
            )
        )
        self.handle = self.ok(
            self.authority.verify(self.credential, capability, Scope.READ)
        )

    def test_p0_duplicate_valid_unexpired_proof_returns_current_receipt(self):
        """Q0-CONTRACT-01: identical replay succeeds without any durable write."""
        page, receipt = self.confirm()
        before = self.path.read_bytes()
        self.advance(1)
        self.assertEqual(self.ok(self.ack(page.proof)), receipt)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIs(receipt.state, ReceiptState.PARTIAL)
        self.assertEqual(receipt.commit_version, 1)
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.catalog.pins, 0)

    def test_read_ack_only_replay_does_not_add_observe_scope(self):
        self.read_ack_only()
        page, receipt = self.confirm()
        before = self.path.read_bytes()
        self.advance(1)
        self.denied(self.proofs.query(self.handle, self.snapshot))
        self.assertEqual(self.ok(self.ack(page.proof, page.proof)), receipt)
        self.assertEqual(self.path.read_bytes(), before)
        self.denied(self.proofs.query(self.handle, self.snapshot))
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.OBSERVE})),
            AuthorityDecision.DENIED,
        )

    def test_replay_returns_advanced_receipt_without_regression(self):
        self.read_ack_only()
        first, _ = self.confirm()
        last, current = self.confirm(16384)
        before = self.path.read_bytes()
        self.advance(1)
        for tokens in ((first.proof,), (last.proof,), (last.proof, first.proof)):
            with self.subTest(tokens=len(tokens)):
                self.assertEqual(self.ok(self.ack(*tokens)), current)
                self.assertEqual(self.path.read_bytes(), before)
        self.assertIs(current.state, ReceiptState.COMPLETE)
        self.assertEqual(current.commit_version, 2)

    def test_observe_replay_also_returns_advanced_receipt(self):
        first, _ = self.confirm()
        _, current = self.confirm(16384)
        before = self.path.read_bytes()
        self.advance(1)
        self.assertEqual(self.ok(self.ack(first.proof)), current)
        self.assertIs(current.state, ReceiptState.COMPLETE)
        self.assertEqual(current.commit_version, 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_mixed_consumed_and_fresh_proofs_confirm_only_new_coverage(self):
        self.read_ack_only()
        first, _ = self.confirm()
        last = self.ok(self.proofs.issue(self.handle, self.snapshot, 16384))
        result = self.ok(self.ack(first.proof, last.proof, first.proof))
        self.assertIs(result.state, ReceiptState.COMPLETE)
        self.assertEqual(result.commit_version, 2)
        self.assertEqual(self.counts(), (2, 1, 2))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(
                db.execute("SELECT sum(consumed) FROM proofs").fetchone()[0], 2
            )

    def test_fresh_token_for_confirmed_page_is_consumed_without_version_change(self):
        first, receipt = self.confirm()
        fresh = self.ok(self.proofs.issue(self.handle, self.snapshot, 0))
        self.assertNotEqual(first.proof, fresh.proof)
        self.assertEqual(self.ok(self.ack(first.proof, fresh.proof)), receipt)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(
                db.execute("SELECT sum(consumed) FROM proofs").fetchone()[0], 2
            )

    def test_foreign_consumer_and_new_grant_cannot_recover_receipt(self):
        page, _ = self.confirm()
        credential = self.ok(
            self.authority.register_principal(
                replace(self.principal, consumer_id="a" * 32)
            )
        )
        person = self.ok(self.authority.verify_principal(credential))
        for principal, secret in ((person, credential), (self.person, self.credential)):
            cap = self.ok(
                self.authority.issue_grant(principal, (self.job,), frozenset(Scope))
            )
            other = self.ok(self.authority.verify(secret, cap, Scope.READ))
            before = self.path.read_bytes()
            self.denied(self.proofs.acknowledge(other, self.snapshot, (page.proof,)))
            self.assertEqual(self.path.read_bytes(), before)
            self.assertIs(
                self.ok(self.proofs.query(other, self.snapshot)).state,
                ReceiptState.UNCONFIRMED,
            )

    def test_revoked_grant_replay_denies_without_disclosure(self):
        page, _ = self.confirm()
        self.ok(self.authority.revoke(self.handle))
        before = self.path.read_bytes()
        self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)

    def test_expired_grant_replay_denies(self):
        self.read_ack_only(ttl_ms=2)
        page, _ = self.confirm()
        before = self.path.read_bytes()
        self.advance(2)
        self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)

    def test_expired_proof_replay_denies_under_live_grant(self):
        page, _ = self.confirm()
        before = self.path.read_bytes()
        self.advance(300000)
        self.assertIs(
            self.authority.check(
                self.handle, self.job, frozenset({Scope.READ, Scope.ACK})
            ),
            AuthorityDecision.AUTHORIZED,
        )
        self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)

    def test_altered_or_unissued_token_denies_atomically_in_mixed_batch(self):
        page, _ = self.confirm()
        fresh = self.ok(self.proofs.issue(self.handle, self.snapshot, 16384))
        before = self.path.read_bytes()
        for index in (0, 32, 63):
            changed = (
                page.proof[:index]
                + ("0" if page.proof[index] != "0" else "1")
                + page.proof[index + 1 :]
            )
            with self.subTest(index=index):
                self.denied(self.ack(page.proof, fresh.proof, changed))
                self.assertEqual(self.path.read_bytes(), before)
        self.denied(self.ack("f" * 64))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.counts(), (2, 1, 1))

    def test_consumed_record_binding_still_checks_digest_range_and_expiry(self):
        page, _ = self.confirm()
        before = self.path.read_bytes()
        original = ReceiptTransaction.proof
        for change in (
            {"page_sha256": "f" * 64},
            {"range": ByteRange(16384, 16385)},
            {"range": ByteRange(0, 1)},
            {"expires_at_ms": page.expires_at_ms + 1},
        ):

            def tamper(tx, digest, change=change):
                record = original(tx, digest)
                return replace(record, **change) if record else record

            with (
                self.subTest(change=change),
                patch.object(ReceiptTransaction, "proof", tamper),
            ):
                self.denied(self.ack(page.proof))
                self.assertEqual(self.path.read_bytes(), before)

    def test_different_snapshot_and_stale_incarnation_replay_deny(self):
        page, _ = self.confirm()
        for snapshot in (
            replace(self.snapshot, seal_id="f" * 32),
            replace(self.snapshot, sha256="f" * 64),
            replace(self.snapshot, job=replace(self.job, incarnation="g1_" + "f" * 32)),
        ):
            before = self.path.read_bytes()
            self.denied(self.proofs.acknowledge(self.handle, snapshot, (page.proof,)))
            self.assertEqual(self.path.read_bytes(), before)
        self.catalog.data = b"y" * len(self.data)
        before = self.path.read_bytes()
        self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)

    def test_consumed_proof_requires_existing_confirmed_coverage(self):
        """A consumed flag alone must not create or return missing coverage."""
        self.read_ack_only()
        page, _ = self.confirm()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM pages")
        before = self.path.read_bytes()
        self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)

    def test_replay_expiring_during_receipt_lookup_denies(self):
        self.read_ack_only()
        page, _ = self.confirm()
        original = ReceiptTransaction.replay_receipt

        def expire(tx, *args):
            current = original(tx, *args)
            self.advance(300000)
            return current

        before = self.path.read_bytes()
        with patch.object(ReceiptTransaction, "replay_receipt", expire):
            self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.catalog.pins, 0)

    def test_replay_expiring_during_final_authorization_denies(self):
        page, _ = self.confirm()
        self.advance(299999)
        original = ReceiptTransaction.authorize
        calls = []

        def expire(tx, *args):
            claims = original(tx, *args)
            calls.append(None)
            if len(calls) == 2:
                self.advance(1)
            return claims

        before = self.path.read_bytes()
        with patch.object(ReceiptTransaction, "authorize", expire):
            self.denied(self.ack(page.proof))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.catalog.pins, 0)

    def test_empty_snapshot_replay_preserves_explicit_confirmation(self):
        self.read_ack_only()
        snapshot = replace(
            self.snapshot, sha256=hashlib.sha256(b"").hexdigest(), byte_length=0
        )
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_snapshot(snapshot, b"")
            )
        )
        self.snapshot = snapshot
        self.catalog = Catalog(self.authority, snapshot, b"")
        self.proofs = self.service()
        page, receipt = self.confirm()
        before = self.path.read_bytes()
        self.advance(1)
        self.assertEqual(self.ok(self.ack(page.proof)), receipt)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(receipt.empty_confirmed)
        self.assertIs(receipt.state, ReceiptState.COMPLETE)

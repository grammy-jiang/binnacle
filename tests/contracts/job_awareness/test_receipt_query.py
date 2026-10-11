"""Real SQLite implementation of the frozen read-only receipt port."""

import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace

from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    ReceiptState,
    Scope,
)
from binnacle.features.commands.job_awareness.ports import ReceiptQueryPort
from tests.integration.job_awareness import test_receipt_store as fixture_store
from tests.integration.job_awareness.test_receipt_store import Handle


class ReceiptQueryContract(fixture_store.StoreFixture, unittest.TestCase):
    def test_query_truth_and_no_side_effect(self):
        port: ReceiptQueryPort = self.store
        first = self.ok(port.query(self.handle, self.snap))
        self.assertEqual(first.state, ReceiptState.UNCONFIRMED)
        before = self.path.read_bytes()
        self.assertEqual(
            port.query(fixture_store.Handle(), self.snap),
            Failure(BoundaryError(ErrorCode.DENIED)),
        )
        self.assertEqual(self.path.read_bytes(), before)
        proof = self.proof()
        self.ok(self.confirm((proof,)))
        before = self.path.read_bytes()
        self.assertEqual(
            self.ok(port.query(self.handle, self.snap)).state, ReceiptState.PARTIAL
        )
        self.assertEqual(self.path.read_bytes(), before)

    def test_denial_only_default_and_scope(self):
        denied = self.mod.ReceiptStore(self.path, clock=lambda: 2)
        self.assertEqual(
            denied.query(self.handle, self.snap).error.code, ErrorCode.DENIED
        )
        original = self.claims
        self.claims = replace(
            original, grant_id="f" * 32, scopes=frozenset({Scope.READ, Scope.ACK})
        )
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_grant(self.claims, "e" * 64, "f" * 64)
            )
        )
        self.assertEqual(
            self.store.query(self.handle, self.snap).error.code, ErrorCode.DENIED
        )
        proof = self.proof()
        self.assertEqual(self.ok(self.confirm((proof,))).state, ReceiptState.PARTIAL)

    def test_query_cannot_mutate_and_reader_cannot_escape(self):
        escaped = []
        self.ok(self.store.read_transaction(lambda tx: escaped.append(tx)))
        with self.assertRaises(self.mod.StoreFailure):
            escaped[0].current_epoch("5" * 32)
        before = self.path.read_bytes()
        self.assertEqual(
            self.store.read_transaction(
                lambda tx: tx.revoke_grant(self.claims)
            ).error.code,
            ErrorCode.DENIED,
        )
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_schema_fails_without_migration(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA user_version=99")
        before = self.path.read_bytes()
        self.assertEqual(
            self.store.query(self.handle, self.snap).error.code,
            ErrorCode.STORAGE_UNAVAILABLE,
        )
        self.assertIsInstance(self.store.initialize(), Failure)
        self.assertEqual(before, self.path.read_bytes())

    def test_broken_resolver_and_clock_fail_closed(self):
        def broken(*args):
            raise RuntimeError("private canary")

        store = self.mod.ReceiptStore(self.path, clock=lambda: 2, resolve=broken)
        result = store.query(self.handle, self.snap)
        self.assertIsInstance(result, Failure)
        self.assertNotIn("canary", repr(result))
        store = self.mod.ReceiptStore(self.path, clock=broken)
        self.assertEqual(
            store.query(self.handle, self.snap).error.code, ErrorCode.CLOCK_UNSAFE
        )

    def test_authority_reader_capability_lookup(self):
        record = self.ok(
            self.store.read_transaction(lambda tx: tx.grant_for_capability("b" * 64))
        )
        self.assertEqual(record.claims, self.claims)
        self.assertIsNone(
            self.ok(
                self.store.read_transaction(
                    lambda tx: tx.grant_for_capability("0" * 64)
                )
            )
        )

    def test_issuance_is_not_ack(self):
        self.proof()
        self.assertEqual(self.query().state, ReceiptState.UNCONFIRMED)
        before = self.path.read_bytes()
        for _ in range(3):
            self.query()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(
            self.store.acknowledge(self.handle, self.snap, ("d" * 64,)),
            Failure(self.mod.BoundaryError(ErrorCode.DENIED)),
        )
        self.assertEqual(self.query().commit_version, 0)

    def test_two_consumers_and_replay(self):
        proof = self.proof()
        self.ok(self.confirm((proof,)))
        original = self.claims
        self.claims = replace(
            original,
            principal=replace(original.principal, consumer_id="f" * 32),
            grant_id="e" * 32,
        )
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_grant(self.claims, "e" * 64, "f" * 64)
            )
        )
        self.assertEqual(self.query().state, ReceiptState.UNCONFIRMED)
        self.assertIsInstance(self.confirm((proof,)), Failure)
        self.assertIsInstance(self.store.query(Handle(), self.snap), Failure)
        self.assertIsInstance(
            self.store.query(self.handle, replace(self.snap, sha256="f" * 64)), Failure
        )
        self.assertIsInstance(
            self.store.query(
                self.handle,
                replace(
                    self.snap, job=replace(self.snap.job, incarnation="g1_" + "f" * 32)
                ),
            ),
            Failure,
        )

    def test_revoke_and_epoch_no_resurrection(self):
        proof = self.proof()
        self.ok(
            self.store.controller_transaction(lambda tx: tx.revoke_grant(self.claims))
        )
        self.assertIsInstance(self.store.query(self.handle, self.snap), Failure)
        self.assertIsInstance(self.confirm((proof,)), Failure)
        self.assertIsInstance(
            self.store.controller_transaction(
                lambda tx: tx.register_grant(self.claims, "b" * 64, "c" * 64)
            ),
            Failure,
        )
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.rotate_epoch("5" * 32, "f" * 32)
            )
        )
        self.assertIsInstance(
            self.store.controller_transaction(
                lambda tx: tx.rotate_epoch("5" * 32, "9" * 32)
            ),
            Failure,
        )

    def test_scopes_expiry_and_generation_isolation(self):
        proof = self.proof()
        self.ok(self.confirm((proof,)))
        prior = self.claims
        self.claims = replace(prior, grant_id="f" * 32)
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_grant(self.claims, "e" * 64, "f" * 64)
            )
        )
        self.assertEqual(self.query().state, ReceiptState.UNCONFIRMED)
        self.now = self.claims.expires_at_ms
        self.assertEqual(
            self.store.query(self.handle, self.snap).error.code, ErrorCode.DENIED
        )

    def test_unsealed_mismatch_and_clock(self):
        other = replace(self.snap, seal_id="f" * 32)
        self.assertIsInstance(self.store.query(self.handle, other), Failure)
        self.assertIsInstance(
            self.store.controller_transaction(
                lambda tx: tx.register_snapshot(other, b"z" * len(self.data))
            ),
            Failure,
        )
        self.now = 0
        self.assertIsInstance(self.store.query(self.handle, self.snap), Failure)

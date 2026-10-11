"""Proof return is a service-side assertion, never comprehension or delivery."""

import hashlib
import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import ReceiptState, Scope
from tests.unit.core.job_awareness.test_grants import LabFixture


@contextmanager
def payload_hashes():
    """Count every SHA-256 input/update containing synthetic x payload bytes.

    Classify by content, never length: one-byte tails and empty payloads count.
    Tokens contain hex characters, not x; HMAC metadata is not snapshot payload.
    """
    original = hashlib.sha256
    sizes = []

    def record(data):
        if all(byte == ord("x") for byte in data):
            sizes.append(len(data))

    class Counted:
        def __init__(self, data=b"", **kwargs):
            record(data)
            self.hash = original(data, **kwargs)

        def update(self, data):
            record(data)
            self.hash.update(data)

        def __getattr__(self, name):
            return getattr(self.hash, name)

    with patch.object(hashlib, "sha256", Counted):
        yield sizes


class ProofTests(LabFixture, unittest.TestCase):
    def test_durable_issue_before_emit_and_exactly_once_ack(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertIs(
            self.ok(self.store.query(self.handle, self.snapshot)).state,
            ReceiptState.UNCONFIRMED,
        )
        self.assertEqual(len(page.proof), 64)
        self.assertEqual(page.expires_at_ms, self.wall + 300000)
        self.assertIs(
            self.ok(
                service.acknowledge(self.handle, self.snapshot, (page.proof,))
            ).state,
            ReceiptState.PARTIAL,
        )
        before = self.path.read_bytes()
        self.assertEqual(
            self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,))),
            self.ok(self.store.query(self.handle, self.snapshot)),
        )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(
            self.ok(self.store.query(self.handle, self.snapshot)).commit_version, 1
        )
        last = self.ok(service.issue(self.handle, self.snapshot, 16384))
        self.assertIs(
            self.ok(
                service.acknowledge(self.handle, self.snapshot, (last.proof,))
            ).state,
            ReceiptState.COMPLETE,
        )
        self.assertEqual(self.catalog.pins, 0)

    def test_binding_and_scope(self):
        """AUTH-04: malformed, foreign, and missing-scope proofs fail atomically."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        for proof in (
            "f" * 64,
            page.proof.upper(),
            "x" * 65,
            "x" * 100000,
            "../secret",
            "",
            None,
        ):
            self.denied(service.acknowledge(self.handle, self.snapshot, (proof,)))
        for scopes in (
            frozenset({Scope.READ}),
            frozenset({Scope.ACK}),
            frozenset({Scope.OBSERVE}),
        ):
            capability = self.ok(
                self.authority.issue_grant(self.person, (self.job,), scopes)
            )
            handle = self.ok(
                self.authority.verify(self.credential, capability, next(iter(scopes)))
            )
            self.denied(service.acknowledge(handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_forged_snapshot_and_tampered_bytes(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        for snapshot in (
            replace(self.snapshot, seal_id="f" * 32),
            replace(self.snapshot, sha256="f" * 64),
            replace(self.snapshot, job=replace(self.job, incarnation="g1_" + "f" * 32)),
        ):
            self.denied(service.acknowledge(self.handle, snapshot, (page.proof,)))
        self.catalog.data = b"y" * len(self.data)
        self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.denied(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_page_record_digest_cannot_be_forged(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        from binnacle.features.commands.job_awareness.receipt_store import (
            ReceiptTransaction,
        )

        original = ReceiptTransaction.proof
        for change in (
            {"page_sha256": "f" * 64},
            {"expires_at_ms": page.expires_at_ms + 1},
        ):

            def tamper(tx, digest, change=change):
                record = original(tx, digest)
                return replace(record, **change) if record else record

            with patch.object(ReceiptTransaction, "proof", tamper):
                self.denied(
                    service.acknowledge(self.handle, self.snapshot, (page.proof,))
                )
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_token_return_is_only_assertion(self):
        """AUTH-08: a malicious consumer can echo proof without decoding bytes."""
        service = self.service()
        tokens = tuple(
            self.ok(service.issue(self.handle, self.snapshot, start)).proof
            for start in (0, 16384)
        )
        receipt = self.ok(service.acknowledge(self.handle, self.snapshot, tokens[::-1]))
        self.assertIs(receipt.state, ReceiptState.COMPLETE)
        self.assertFalse(hasattr(receipt, "comprehension_proved"))

    def test_empty_requires_explicit_page_and_binary_integrity(self):
        from tests.unit.core.job_awareness.test_grants import Catalog

        service = self.service()
        self.denied(service.acknowledge(self.handle, self.snapshot, ()))
        for data in (b"", b"\x00\xff\xfe\r\n"):
            job = replace(self.job, incarnation=("g1_" + ("a" if data else "b") * 32))
            snapshot = replace(
                self.snapshot,
                job=job,
                byte_length=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            capability = self.ok(
                self.authority.issue_grant(self.person, (job,), frozenset(Scope))
            )
            handle = self.ok(
                self.authority.verify(self.credential, capability, Scope.READ)
            )
            self.ok(
                self.store.controller_transaction(
                    lambda tx, snapshot=snapshot, data=data: tx.register_snapshot(
                        snapshot, data
                    )
                )
            )
            self.catalog = Catalog(self.authority, snapshot, data)
            service = self.service()
            page = self.ok(service.issue(handle, snapshot, 0))
            result = self.ok(service.acknowledge(handle, snapshot, (page.proof,)))
            self.assertIs(result.state, ReceiptState.COMPLETE)
            self.assertEqual(result.empty_confirmed, not data)

    def test_timeout_rolls_back_and_closes_lease(self):
        from binnacle.features.commands.job_awareness.receipt_store import (
            ReceiptTransaction,
        )

        service = self.service(timeout_ms=5)
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        confirm = ReceiptTransaction.confirm

        def delayed(tx, *args):
            result = confirm(tx, *args)
            self.assertEqual(self.catalog.pins, 1)
            self.advance(5)
            return result

        with patch.object(ReceiptTransaction, "confirm", delayed):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.catalog.pins, 0)
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))

    def test_expired_proof_and_ttl_cap(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.advance(300000)
        self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.advance(400000)
        late = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(late.expires_at_ms, self.snapshot.retained_until_ms)

    def test_missing_snapshot_verifier(self):
        from binnacle.features.commands.job_awareness.proofs import (
            SyntheticProofService,
        )

        service = SyntheticProofService(self.authority, None)
        self.denied(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_fresh_proof_expiry_after_confirmation_rolls_back(self):
        from binnacle.features.commands.job_awareness.receipt_store import (
            ReceiptTransaction,
        )

        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.advance(299999)
        confirm = ReceiptTransaction.confirm

        def expire_after_mutation(tx, *args):
            result = confirm(tx, *args)
            self.advance(1)
            return result

        with patch.object(ReceiptTransaction, "confirm", expire_after_mutation):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_clock_regress_inside_ack_rolls_back(self):
        from binnacle.features.commands.job_awareness.receipt_store import (
            ReceiptTransaction,
        )

        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        confirm = ReceiptTransaction.confirm

        def regress(tx, *args):
            result = confirm(tx, *args)
            self.wall -= 1
            return result

        with patch.object(ReceiptTransaction, "confirm", regress):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.catalog.pins, 0)

    def test_grant_ttl_caps_proof_and_secrets_not_stored(self):
        capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset(Scope), ttl_ms=3
            )
        )
        handle = self.ok(self.authority.verify(self.credential, capability, Scope.READ))
        service = self.service()
        page = self.ok(service.issue(handle, self.snapshot, 0))
        self.assertEqual(page.expires_at_ms, self.wall + 3)
        self.assertNotIn(page.proof.encode("ascii"), self.path.read_bytes())
        self.advance(3)
        self.denied(service.acknowledge(handle, self.snapshot, (page.proof,)))

    def test_noncanonical_pages_and_duplicate_batch(self):
        service = self.service()
        for start in (-1, True, 1, self.snapshot.byte_length, 1048577):
            self.denied(service.issue(self.handle, self.snapshot, start))
        self.assertEqual(self.catalog.opens, 0)
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(
            self.ok(
                service.acknowledge(
                    self.handle, self.snapshot, (page.proof, page.proof)
                )
            ).commit_version,
            1,
        )
        before = self.path.read_bytes()
        self.assertEqual(
            self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,))),
            self.ok(self.store.query(self.handle, self.snapshot)),
        )
        self.assertEqual(self.path.read_bytes(), before)

    def test_verified_lease_hash_budget(self):
        """SEC-02: include page and implicit PageEnvelope validation hashing."""
        service = self.service()
        with payload_hashes() as sizes:
            page = self.ok(service.issue(self.handle, self.snapshot, 0))
            self.assertEqual(sizes, [16385, 16384, 16384])
            self.assertEqual(sum(sizes), 49153)
            sizes.clear()
            self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
            self.assertEqual(sizes, [16385, 16384])
            self.assertEqual(sum(sizes), 32769)
            sizes.clear()
            self.ok(service.issue(self.handle, self.snapshot, 16384))
            self.assertEqual(sizes, [16385, 1, 1])
            self.assertLessEqual(sum(sizes), 1048576)

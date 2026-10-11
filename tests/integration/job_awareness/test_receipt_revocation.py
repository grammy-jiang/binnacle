"""Real SQLite mutation ordering with independent synthetic worker processes."""

import multiprocessing
import unittest
from dataclasses import replace
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    ReceiptState,
    Scope,
    Success,
)
from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore
from tests.unit.core.job_awareness.test_grants import Catalog, LabFixture


class RevocationTests(LabFixture, unittest.TestCase):
    def test_replay_rechecks_revocation_after_lease_admission(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        original = self.store.controller_transaction
        revoked_bytes = []

        def revoke_then_begin(callback):
            self.ok(
                original(
                    lambda tx: tx.revoke_grant(
                        tx.authorize(self.handle, self.job, frozenset({Scope.READ}))
                    )
                )
            )
            revoked_bytes.append(self.path.read_bytes())
            return original(callback)

        with patch.object(self.store, "controller_transaction", revoke_then_begin):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.path.read_bytes(), revoked_bytes[0])
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.catalog.pins, 0)

    def test_precheck_cannot_authorize_ack(self):
        """AUTH-10: revoke after payload admission, before the ACK transaction."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.ACK})),
            AuthorityDecision.AUTHORIZED,
        )
        original = self.store.controller_transaction

        def revoke_then_begin(callback):
            self.ok(
                original(
                    lambda tx: tx.revoke_grant(
                        tx.authorize(self.handle, self.job, frozenset({Scope.READ}))
                    )
                )
            )
            return original(callback)

        with patch.object(self.store, "controller_transaction", revoke_then_begin):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.catalog.pins, 0)

    def test_revoke_ack_linearization(self):
        """AUTH-05: process barrier proves revoke-first and ACK-first order."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        context = multiprocessing.get_context("fork")
        parent, child = context.Pipe()

        def worker():
            parent.close()
            original = self.store.controller_transaction

            def barrier(callback):
                child.send("before-begin")
                if not child.poll(5):
                    raise AssertionError("Controller barrier timed out")
                child.recv()
                return original(callback)

            with patch.object(self.store, "controller_transaction", barrier):
                child.send(
                    service.acknowledge(self.handle, self.snapshot, (page.proof,))
                )
            child.close()

        process = context.Process(target=worker)
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(5))
            self.assertEqual(parent.recv(), "before-begin")
            self.ok(self.authority.revoke(self.handle))
            parent.send("revocation-committed")
            self.assertTrue(parent.poll(5))
            self.denied(parent.recv())
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        finally:
            if process.is_alive():
                process.kill()
                process.join(5)
            parent.close()
        self.assertEqual(self.counts(), (1, 0, 0))
        # Opposite order: commit in another worker, then revoke in the controller.
        cap = self.ok(
            self.authority.issue_grant(self.person, (self.job,), frozenset(Scope))
        )
        handle = self.ok(self.authority.verify(self.credential, cap, Scope.READ))
        page = self.ok(service.issue(handle, self.snapshot, 0))

        def ack_first():
            result = service.acknowledge(handle, self.snapshot, (page.proof,))
            if not isinstance(result, Success):
                raise AssertionError("ACK-first did not commit")  # noqa: TRY004 - behavioral test

        process = context.Process(target=ack_first)
        process.start()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        self.assertEqual(process.exitcode, 0)
        self.ok(self.authority.revoke(handle))
        self.assertEqual(self.counts(), (2, 1, 1))
        self.denied(service.query(handle, self.snapshot))

    def test_dual_restart_epoch(self):
        """AUTH-06: worker reopen preserves authority; controller restart retires it."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        reopened = ReceiptStore(
            self.path, clock=self.clock.now, resolve=self.authority.resolve
        )
        self.assertIs(
            self.ok(reopened.query(self.handle, self.snapshot)).state,
            ReceiptState.UNCONFIRMED,
        )
        old = self.ok(
            self.store.read_transaction(
                lambda tx: tx.authorize(self.handle, self.job, frozenset({Scope.READ}))
            )
        )
        restarted = self.mod.SyntheticAuthority(
            self.path,
            self.principal.issuer_id,
            self.mod.TrustedClock(lambda: self.wall, lambda: self.mono),
        )
        self.ok(restarted.start())
        self.assertIs(
            self.authority.check(self.handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.REVOKED,
        )
        self.denied(restarted.verify(self.credential, self.capability, Scope.READ))
        self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.denied(
            self.store.controller_transaction(
                lambda tx: tx.rotate_epoch(self.principal.issuer_id, old.issuer_epoch)
            )
        )
        credential = self.ok(restarted.register_principal(self.principal))
        person = self.ok(restarted.verify_principal(credential))
        capability = self.ok(
            restarted.issue_grant(person, (self.job,), frozenset(Scope))
        )
        handle = self.ok(restarted.verify(credential, capability, Scope.READ))
        self.assertIs(
            self.ok(restarted.store.query(handle, self.snapshot)).state,
            ReceiptState.UNCONFIRMED,
        )

    def test_generation_collision_and_rotation(self):
        claims = self.ok(
            self.store.read_transaction(
                lambda tx: tx.authorize(self.handle, self.job, frozenset({Scope.READ}))
            )
        )
        with patch(
            "binnacle.features.commands.job_awareness.grants.secrets.token_hex",
            return_value=claims.grant_id,
        ):
            self.denied(
                self.authority.issue_grant(self.person, (self.job,), frozenset(Scope))
            )
        with patch(
            "binnacle.features.commands.job_awareness.grants.secrets.token_hex",
            return_value=claims.issuer_epoch,
        ):
            cold = self.mod.SyntheticAuthority(
                self.path, self.principal.issuer_id, self.clock
            )
            self.denied(cold.start())
            self.denied(cold.register_principal(self.principal))
        self.ok(self.authority.revoke(self.handle))
        self.denied(self.authority.verify(self.credential, self.capability, Scope.READ))
        cap = self.ok(
            self.authority.issue_grant(self.person, (self.job,), frozenset(Scope))
        )
        handle = self.ok(self.authority.verify(self.credential, cap, Scope.READ))
        self.assertIs(
            self.authority.check(handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.AUTHORIZED,
        )

    def test_multiple_consumers_and_reused_job_id(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        other_principal = replace(self.principal, consumer_id="a" * 32)
        credential = self.ok(self.authority.register_principal(other_principal))
        person = self.ok(self.authority.verify_principal(credential))
        capability = self.ok(
            self.authority.issue_grant(person, (self.job,), frozenset(Scope))
        )
        other = self.ok(self.authority.verify(credential, capability, Scope.READ))
        self.denied(service.acknowledge(other, self.snapshot, (page.proof,)))
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertIs(
            self.ok(service.query(other, self.snapshot)).state, ReceiptState.UNCONFIRMED
        )
        new_job = replace(self.job, incarnation="g1_" + "b" * 32)
        snapshot = replace(self.snapshot, job=new_job)
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_snapshot(snapshot, self.data)
            )
        )
        self.catalog = Catalog(self.authority, snapshot, self.data)
        capability = self.ok(
            self.authority.issue_grant(person, (new_job,), frozenset(Scope))
        )
        new_handle = self.ok(self.authority.verify(credential, capability, Scope.READ))
        self.denied(self.service().acknowledge(new_handle, snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 1, 1))

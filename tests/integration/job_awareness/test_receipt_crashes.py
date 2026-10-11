"""Actual synthetic worker death; DELETE journal recovery, not power-loss proof."""

import hashlib
import multiprocessing
import os
import sqlite3
import sys
import types
import unittest
from contextlib import closing, contextmanager
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    Observation,
    ObservationState,
    ReceiptState,
    Scope,
    Success,
)
from binnacle.features.commands.job_awareness.receipt_store import (
    ReceiptStore,
    ReceiptTransaction,
)
from tests.integration.job_awareness.test_receipt_store import StoreFixture
from tests.unit.core.job_awareness.test_grants import LabFixture

REVIEWED_I02_SNAPSHOTS = (
    Path(__file__).resolve().parent / "fixtures" / "reviewed_i02_snapshots.py.txt"
)
REVIEWED_I02_SNAPSHOTS_SHA256 = (
    "e5f4b3e0900e4981864cae315e66c6a5c4c60519e793bb2909b563b72ce60440"
)


def observer_references():
    """Count references one local name adds, as getrefcount reports them.

    Python 3.14 stopped counting getrefcount's temporary argument reference, so
    the baseline is measured on a fresh object instead of assumed.
    """
    probe = bytes(4096)
    return sys.getrefcount(probe)


OBSERVER_REFERENCES = observer_references()


@lru_cache(maxsize=1)
def reviewed_snapshots():
    """Execute the vendored sealed I0-2 bytes; never read git history."""
    source = REVIEWED_I02_SNAPSHOTS.read_bytes()
    if hashlib.sha256(source).hexdigest() != REVIEWED_I02_SNAPSHOTS_SHA256:
        raise AssertionError("Reviewed I0-2 source mismatch")
    module = types.ModuleType("_reviewed_i02_snapshots")
    sys.modules[module.__name__] = module
    # The exact reviewed source digest is checked above before execution.
    exec(  # noqa: S102  # nosec B102
        compile(source, "<reviewed-I0-2-4e201ee>/snapshots.py", "exec"), module.__dict__
    )
    return module


def use_reviewed_store(lab):
    module = reviewed_snapshots()

    class Payload:
        def read(self, length):
            # Allocate a fresh buffer; the adapter keeps no payload references.
            return Success(b"x" * length)

    catalog = module.TrustedCatalog()
    lab.ok(
        catalog.register(
            Observation(
                lab.job, ObservationState.TERMINAL, lab.snapshot.terminal, lab.snapshot
            ),
            Payload(),
        )
    )
    lab.catalog = module.SnapshotStore(
        lab.authority, catalog, lab.clock.now, memory=module.SnapshotMemory()
    )
    return module


@contextmanager
def observe_retired_references(lab, workers):
    """Count references at the unpin/eviction boundary, before worker release."""
    module = reviewed_snapshots()
    original = module._Lease.__exit__
    observations = []

    def close(lease, *args):
        borrowed = lease.verified_bytes
        original(lease, *args)
        lab.catalog.memory.evict_unpinned()
        stats = lab.catalog.memory.stats()
        # Only this observer's local name (plus getrefcount's argument reference
        # on interpreters that take one) may own the bytes.
        retired = sys.getrefcount(borrowed) - OBSERVER_REFERENCES
        del borrowed
        permit = workers.reserve()
        observations.append(
            (
                retired,
                stats.cache_bytes,
                stats.inflight_bytes,
                stats.pins,
                permit is None,
            )
        )
        if permit is not None:
            permit.cancel_before_start()

    with patch.object(module._Lease, "__exit__", close):
        yield observations


class LeaseLifetimeTests(LabFixture, unittest.TestCase):
    def test_reviewed_lease_eviction_releases_all_borrows(self):
        """SEC-01: even a retained cancellation traceback cannot keep payloads."""
        from binnacle.features.commands.job_awareness.proofs import WorkerBudget

        module = use_reviewed_store(self)
        workers = WorkerBudget(1)
        service = self.service(workers=workers)
        with observe_retired_references(self, workers) as retired:
            page = self.ok(service.issue(self.handle, self.snapshot, 0))
            self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
            for error in (RuntimeError, KeyboardInterrupt):
                with patch.object(service, "_token", side_effect=error):
                    if error is KeyboardInterrupt:
                        with self.assertRaises(KeyboardInterrupt):
                            service.issue(self.handle, self.snapshot, 0)
                    else:
                        self.denied(service.issue(self.handle, self.snapshot, 0))
            with patch.object(
                module._Lease,
                "snapshot",
                property(lambda lease: replace(self.snapshot, seal_id="a" * 32)),
            ):
                self.denied(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(retired, [(0, 0, 0, 0, True)] * 5)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_reviewed_ack_cancellation_releases_traceback_borrows(self):
        from binnacle.features.commands.job_awareness.proofs import WorkerBudget

        use_reviewed_store(self)
        workers = WorkerBudget(1)
        service = self.service(workers=workers)
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        original = hashlib.sha256

        def interrupt_page_hash(data=b""):
            if isinstance(data, memoryview):
                raise KeyboardInterrupt
            return original(data)

        with (
            observe_retired_references(self, workers) as retired,
            patch.object(hashlib, "sha256", interrupt_page_hash),
            self.assertRaises(KeyboardInterrupt),
        ):
            service.acknowledge(self.handle, self.snapshot, (page.proof,))
        self.assertEqual(retired, [(0, 0, 0, 0, True)])
        self.assertEqual(self.counts(), (1, 0, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))


class CrashTests(LabFixture, unittest.TestCase):
    def child(self, callback):
        process = multiprocessing.get_context("fork").Process(target=callback)
        process.start()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
            self.fail("Synthetic child timeout")
        return process.exitcode

    def test_precommit_crash(self):
        """CRASH-01: kill after confirmation writes but before commit."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        original = ReceiptTransaction.confirm

        def die_before_commit(tx, *args):
            original(tx, *args)
            os._exit(73)

        def worker():
            with patch.object(ReceiptTransaction, "confirm", die_before_commit):
                service.acknowledge(self.handle, self.snapshot, (page.proof,))

        self.assertEqual(self.child(worker), 73)
        reopened = ReceiptStore(
            self.path, clock=self.clock.now, resolve=self.authority.resolve
        )
        self.assertIs(
            self.ok(reopened.query(self.handle, self.snapshot)).state,
            ReceiptState.UNCONFIRMED,
        )
        self.assertEqual(self.counts(), (1, 0, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))

    def test_postcommit_reply_loss(self):
        """CRASH-02: committed state survives; replay has no second effect."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))

        def worker():
            result = service.acknowledge(self.handle, self.snapshot, (page.proof,))
            os._exit(74 if isinstance(result, Success) else 75)

        self.assertEqual(self.child(worker), 74)
        self.assertEqual(
            self.ok(service.query(self.handle, self.snapshot)).commit_version, 1
        )
        before = self.path.read_bytes()
        self.advance(1)
        receipt = self.ok(
            service.acknowledge(self.handle, self.snapshot, (page.proof,))
        )
        self.assertEqual(receipt.commit_version, 1)
        self.assertIs(receipt.state, ReceiptState.PARTIAL)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_postcommit_reply_loss_read_ack_only(self):
        """CRASH-02: a worker restart recovers without an OBSERVE grant."""
        capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset({Scope.READ, Scope.ACK})
            )
        )
        handle = self.ok(self.authority.verify(self.credential, capability, Scope.READ))
        key = b"k" * 32
        service = self.service(proof_key=key)
        page = self.ok(service.issue(handle, self.snapshot, 0))

        def worker():
            result = service.acknowledge(handle, self.snapshot, (page.proof,))
            os._exit(74 if isinstance(result, Success) else 75)

        self.assertEqual(self.child(worker), 74)
        before = self.path.read_bytes()
        self.advance(1)
        restarted_worker = self.service(proof_key=key)
        self.denied(restarted_worker.query(handle, self.snapshot))
        receipt = self.ok(
            restarted_worker.acknowledge(handle, self.snapshot, (page.proof,))
        )
        self.assertIs(receipt.state, ReceiptState.PARTIAL)
        self.assertEqual(receipt.commit_version, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_two_process_duplicates(self):
        """CRASH-03: independent SQLite connections produce only one transition."""
        context = multiprocessing.get_context("fork")
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        admitted = context.Barrier(2)
        busy = Failure(BoundaryError(ErrorCode.BUSY))
        workers, readers = [], []

        def worker(writer):
            original = self.store.controller_transaction

            def begin(callback):
                # Both workers finish read admission before competing for a writer.
                admitted.wait(5)
                return original(callback)

            with patch.object(self.store, "controller_transaction", begin):
                result = service.acknowledge(self.handle, self.snapshot, (page.proof,))
            writer.send(result)
            if result == busy:
                if not writer.poll(5):
                    raise AssertionError("Retry barrier timeout")
                writer.recv()
                writer.send(
                    service.acknowledge(self.handle, self.snapshot, (page.proof,))
                )
            writer.close()

        try:
            for _ in range(2):
                reader, writer = context.Pipe()
                process = context.Process(target=worker, args=(writer,))
                process.start()
                writer.close()
                workers.append(process)
                readers.append(reader)
            results = []
            for reader in readers:
                self.assertTrue(reader.poll(5))
                results.append(reader.recv())
            # A 50 ms SQLite busy timeout is valid. Retry only BUSY, once, after
            # both first attempts release their connections. DENIED still fails.
            for index, result in enumerate(results):
                if result == busy:
                    readers[index].send("retry")
                    self.assertTrue(readers[index].poll(5))
                    results[index] = readers[index].recv()
            self.assertEqual(
                sum(isinstance(result, Success) for result in results), 2, results
            )
            self.assertEqual(results[0], results[1])
            for process in workers:
                process.join(5)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in workers:
                if process.is_alive():
                    process.kill()
                    process.join(5)
            for reader in readers:
                reader.close()
        self.assertEqual(
            self.ok(service.query(self.handle, self.snapshot)).commit_version, 1
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_issuance_rollback_and_reopen(self):
        service = self.service()
        original = ReceiptTransaction.issue_proof

        def failed(tx, *args):
            original(tx, *args)
            raise sqlite3.OperationalError("Synthetic write failure")

        with patch.object(ReceiptTransaction, "issue_proof", failed):
            self.denied(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(self.counts(), (0, 0, 0))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.ok(service.issue(self.handle, self.snapshot, 0))

    def test_callback_cancellation_rolls_back(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        original = ReceiptTransaction.confirm

        def cancelled(tx, *args):
            original(tx, *args)
            raise KeyboardInterrupt

        with (
            patch.object(ReceiptTransaction, "confirm", cancelled),
            self.assertRaises(KeyboardInterrupt),
        ):
            service.acknowledge(self.handle, self.snapshot, (page.proof,))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.catalog.pins, 0)
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))


class PortableBusyTests(StoreFixture, unittest.TestCase):
    def test_busy_classification_is_portable_across_python_versions(self):
        """Python 3.10 has no sqlite_errorcode; message-only errors stay BUSY."""
        for message, expected in (
            ("database is locked", ErrorCode.BUSY),
            ("database table is locked", ErrorCode.BUSY),
            ("disk full injected", ErrorCode.STORAGE_UNAVAILABLE),
            ("unable to open database file", ErrorCode.STORAGE_UNAVAILABLE),
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    hasattr(sqlite3.OperationalError(message), "sqlite_errorcode")
                )

                def fail(tx, message=message):
                    raise sqlite3.OperationalError(message)

                result = self.store.controller_transaction(fail)
                self.assertEqual(result.error.code, expected)

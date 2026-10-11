"""Bounded synthetic policy work and failure/worker-lifetime probes."""

import asyncio
import hashlib
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import replace
from threading import Event
from unittest.mock import patch

from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ByteRange,
    ErrorCode,
    Failure,
    ReceiptProofRecord,
    Scope,
    Success,
)
from binnacle.features.commands.job_awareness.receipt_schema import Limits
from binnacle.features.commands.job_awareness.receipt_store import (
    ReceiptStore,
    ReceiptTransaction,
)
from tests.integration.job_awareness.test_receipt_crashes import (
    observe_retired_references,
    use_reviewed_store,
)
from tests.unit.core.job_awareness.test_grants import LabFixture, Unregistered
from tests.unit.core.job_awareness.test_proofs import payload_hashes


class QuotaTests(LabFixture, unittest.TestCase):
    @contextmanager
    def no_sql_writes(self):
        statements = []
        original = self.store._connect

        def traced(create):
            db = original(create)
            db.set_trace_callback(statements.append)
            return db

        with patch.object(self.store, "_connect", traced):
            yield
        self.assertFalse(
            any(
                sql.startswith(("INSERT", "UPDATE", "DELETE", "BEGIN IMMEDIATE"))
                for sql in statements
            ),
            statements,
        )

    def enroll(self, length):
        self.data = b"x" * length
        self.job = replace(self.job, incarnation=f"g1_{length:032x}")
        self.snapshot = replace(
            self.snapshot,
            job=self.job,
            byte_length=length,
            sha256=hashlib.sha256(self.data).hexdigest(),
        )
        capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset(Scope), ttl_ms=900000
            )
        )
        self.handle = self.ok(
            self.authority.verify(self.credential, capability, Scope.READ)
        )
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.register_snapshot(self.snapshot, self.data)
            )
        )
        use_reviewed_store(self)

    def test_issue_aggregate_hash_boundary(self):
        """SEC-02: N + page + envelope validation, including exact cap and +1."""
        for length, accepted in ((1015808, True), (1015809, False), (1048576, False)):
            with self.subTest(length=length):
                self.enroll(length)
                service = self.service()
                before, counts = self.path.read_bytes(), self.counts()
                with payload_hashes() as sizes:
                    result = service.issue(self.handle, self.snapshot, 0)
                self.assertLessEqual(sum(sizes), 1048576, sizes)
                if accepted:
                    self.ok(result)
                    self.assertEqual(sizes, [1015808, 16384, 16384])
                    self.assertEqual(sum(sizes), 1048576)
                else:
                    self.quota(result)
                    self.assertEqual(sizes, [])
                    self.assertEqual(self.path.read_bytes(), before)
                    self.assertEqual(self.counts(), counts)
                    with self.no_sql_writes():
                        self.quota(service.issue(self.handle, self.snapshot, 0))
                self.assertEqual(self.catalog.memory.stats().pins, 0)

    def test_ack_aggregate_hash_boundary_and_retry(self):
        """SEC-02: sixteen distinct page hashes; quota denial consumes nothing."""
        for length, accepted in ((786432, True), (786433, False)):
            with self.subTest(length=length):
                self.enroll(length)
                service = self.service()
                tokens = tuple(
                    self.ok(service.issue(self.handle, self.snapshot, i * 16384)).proof
                    for i in range(16)
                )
                before, counts = self.path.read_bytes(), self.counts()
                with payload_hashes() as sizes:
                    result = service.acknowledge(self.handle, self.snapshot, tokens)
                self.assertLessEqual(sum(sizes), 1048576, sizes)
                if accepted:
                    self.ok(result)
                    self.assertEqual(sizes, [786432] + [16384] * 16)
                    self.assertEqual(sum(sizes), 1048576)
                else:
                    self.quota(result)
                    self.assertEqual(sizes, [])
                    self.assertEqual(self.path.read_bytes(), before)
                    self.assertEqual(self.counts(), counts)
                    with self.no_sql_writes():
                        self.quota(
                            service.acknowledge(self.handle, self.snapshot, tokens)
                        )
                    self.ok(service.acknowledge(self.handle, self.snapshot, tokens[:1]))
                    self.ok(service.acknowledge(self.handle, self.snapshot, tokens[:1]))
                    self.ok(service.acknowledge(self.handle, self.snapshot, tokens[1:]))
                self.assertEqual(self.catalog.memory.stats().pins, 0)

    def test_max_snapshot_ack_existing_proofs_denies_before_work(self):
        """A controller seeds valid legacy proofs that predate the stricter cap."""
        self.enroll(1048576)
        service = self.service()

        def legacy_proofs(tx):
            claims = tx.authorize(self.handle, self.job, frozenset({Scope.READ}))
            tokens = []
            for i in range(16):
                page = ByteRange(i * 16384, (i + 1) * 16384)
                record = ReceiptProofRecord(
                    "0" * 64,
                    claims.principal,
                    claims.issuer_epoch,
                    claims.grant_id,
                    self.job,
                    self.snapshot.sha256,
                    page,
                    hashlib.sha256(self.data[page.start : page.stop]).hexdigest(),
                    self.wall + 300000,
                    False,
                )
                token = service._token(
                    "a" * 32, service._binding(tx, claims, self.snapshot, record)
                )
                tx.issue_proof(
                    claims,
                    self.snapshot,
                    replace(
                        record,
                        proof_sha256=hashlib.sha256(token.encode("ascii")).hexdigest(),
                    ),
                )
                tokens.append(token)
            return tuple(tokens)

        tokens = self.ok(self.store.controller_transaction(legacy_proofs))
        before = self.path.read_bytes()
        for batch in (tokens, tokens[:1]):
            with payload_hashes() as sizes:
                result = service.acknowledge(self.handle, self.snapshot, batch)
            self.assertLessEqual(sum(sizes), 1048576, sizes)
            self.quota(result)
            self.assertEqual(sizes, [])
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.counts(), (16, 0, 0))
            with closing(sqlite3.connect(self.path)) as db, db:
                self.assertEqual(
                    db.execute("SELECT sum(consumed) FROM proofs").fetchone()[0], 0
                )
        self.assertEqual(self.catalog.memory.stats().cache_bytes, 0)

    def test_duplicate_ack_budget_counts_distinct_tokens(self):
        self.enroll(1015808)
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        with payload_hashes() as sizes:
            result = service.acknowledge(self.handle, self.snapshot, (page.proof,) * 16)
        self.ok(result)
        self.assertEqual(sizes, [1015808, 16384])
        self.assertEqual(sum(sizes), 1032192)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_hash_quota_preserves_authority_gate(self):
        self.enroll(1048576)
        service = self.service()
        capability = self.ok(
            self.authority.issue_grant(
                self.person, (self.job,), frozenset({Scope.READ})
            )
        )
        read_only = self.ok(
            self.authority.verify(self.credential, capability, Scope.READ)
        )
        with self.no_sql_writes(), payload_hashes() as sizes:
            self.denied(service.issue(Unregistered(), self.snapshot, 0))
            self.denied(service.acknowledge(Unregistered(), self.snapshot, ("f" * 64,)))
            self.denied(service.acknowledge(read_only, self.snapshot, ("f" * 64,)))
            self.quota(service.issue(read_only, self.snapshot, 0))
        self.assertEqual(sizes, [])
        self.assertEqual(self.counts(), (0, 0, 0))

    def limits(self, **kwargs):
        self.store = ReceiptStore(
            self.path,
            clock=self.clock.now,
            resolve=self.authority.resolve,
            limits=Limits(**kwargs),
        )
        self.authority.store = self.store

    def quota(self, result):
        self.assertEqual(result, Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED)))

    def test_growth_caps(self):
        """QUOTA-01: pending and retained consumed rows both have hard ceilings."""
        self.limits(outstanding=2, proofs_per_grant=3)
        service = self.service()
        first = self.ok(service.issue(self.handle, self.snapshot, 0))
        self.ok(service.issue(self.handle, self.snapshot, 0))
        self.quota(service.issue(self.handle, self.snapshot, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (first.proof,)))
        self.ok(service.issue(self.handle, self.snapshot, 0))
        self.quota(service.issue(self.handle, self.snapshot, 0))
        self.assertEqual(self.counts(), (3, 1, 1))

    def test_grant_cap_does_not_evict_revocation(self):
        self.limits(grants=2)
        self.ok(self.authority.issue_grant(self.person, (self.job,), frozenset(Scope)))
        self.ok(self.authority.revoke(self.handle))
        self.quota(
            self.authority.issue_grant(self.person, (self.job,), frozenset(Scope))
        )
        self.denied(self.authority.verify(self.credential, self.capability, Scope.READ))
        self.denied(
            self.authority.issue_grant(self.person, (self.job,) * 101, frozenset(Scope))
        )
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM grants").fetchone()[0], 2)

    def test_global_proof_and_page_caps_rollback(self):
        self.limits(proofs=2, pages=1)
        service = self.service()
        first = self.ok(service.issue(self.handle, self.snapshot, 0))
        last = self.ok(service.issue(self.handle, self.snapshot, 16384))
        self.quota(service.issue(self.handle, self.snapshot, 0))
        self.quota(
            service.acknowledge(self.handle, self.snapshot, (first.proof, last.proof))
        )
        self.assertEqual(self.counts(), (2, 0, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (first.proof,)))
        self.quota(service.acknowledge(self.handle, self.snapshot, (last.proof,)))
        self.assertEqual(self.counts(), (2, 1, 1))

    def test_batch_bounds_and_mixed_invalid_proof(self):
        service = self.service()
        tokens = tuple(
            self.ok(service.issue(self.handle, self.snapshot, 0)).proof
            for _ in range(16)
        )
        before = self.catalog.opens
        self.denied(
            service.acknowledge(self.handle, self.snapshot, (*tokens, tokens[0]))
        )
        self.assertEqual(self.catalog.opens, before)
        self.denied(
            service.acknowledge(self.handle, self.snapshot, (*tokens[:15], "f" * 64))
        )
        self.assertEqual(self.counts(), (16, 0, 0))
        result = self.ok(service.acknowledge(self.handle, self.snapshot, tokens))
        self.assertEqual(result.commit_version, 1)
        self.assertEqual(self.counts(), (16, 1, 1))

    def test_disk_busy_and_corruption(self):
        """QUOTA-02: real busy BEGIN and unknown schema deny without output loss."""
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        with (
            closing(sqlite3.connect(self.path, isolation_level=None)) as blocker,
            blocker,
        ):
            blocker.execute("BEGIN IMMEDIATE")
            self.assertEqual(
                service.acknowledge(self.handle, self.snapshot, (page.proof,)),
                Failure(BoundaryError(ErrorCode.BUSY)),
            )
            blocker.rollback()
        self.assertEqual(self.counts(), (1, 0, 0))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA user_version=99")
        self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.catalog.data, self.data)

    def test_failed_commit_rolls_back_consumption(self):
        service = self.service()
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        original = sqlite3.connect

        class FailedCommit(sqlite3.Connection):
            def commit(connection):
                if connection.execute("PRAGMA query_only").fetchone()[0] == 0:
                    raise sqlite3.OperationalError("Injected commit failure")
                return super().commit()

        def connect(*args, **kwargs):
            return original(*args, **kwargs, factory=FailedCommit)

        with patch(
            "binnacle.features.commands.job_awareness.receipt_schema.sqlite3.connect",
            connect,
        ):
            self.denied(service.acknowledge(self.handle, self.snapshot, (page.proof,)))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.ok(service.acknowledge(self.handle, self.snapshot, (page.proof,)))

    def test_journal_and_cleanup_bounds(self):
        """QUOTA-03: small disk-backed sample; no full-capacity pressure claim."""
        service = self.service()
        for _ in range(64):
            self.ok(service.issue(self.handle, self.snapshot, 0))
        self.quota(service.issue(self.handle, self.snapshot, 0))
        before = self.path.read_bytes()
        self.ok(service.query(self.handle, self.snapshot))
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("PRAGMA page_size").fetchone()[0], 4096)
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.assertLessEqual(
            sum(p.stat().st_size for p in self.path.parent.iterdir()), 134217728
        )
        self.advance(604800000 + 400000)
        self.assertEqual(
            self.ok(self.store.controller_transaction(lambda tx: tx.cleanup())), 64
        )
        self.assertEqual(
            self.ok(self.store.controller_transaction(lambda tx: tx.cleanup())), 0
        )

    def test_cancelled_awaiter_keeps_actual_worker_and_lease(self):
        from binnacle.features.commands.job_awareness.proofs import WorkerBudget

        use_reviewed_store(self)
        workers = WorkerBudget(1)
        service = self.service(workers=workers)
        page = self.ok(service.issue(self.handle, self.snapshot, 0))
        entered, release = Event(), Event()
        original = ReceiptTransaction.confirm

        def blocked(tx, *args):
            result = original(tx, *args)
            entered.set()
            if not release.wait(5):
                raise AssertionError("Worker barrier timeout")
            return result

        async def run():
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = asyncio.get_running_loop().run_in_executor(
                    pool, service.acknowledge, self.handle, self.snapshot, (page.proof,)
                )
                try:
                    # Test-only barrier: no event-loop responsiveness claim here.
                    # This also works with sandboxed thread-to-loop wakeups.
                    self.assertTrue(entered.wait(5))
                    future.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await future
                    self.catalog.memory.evict_unpinned()
                    self.assertEqual(self.catalog.memory.stats().pins, 1)
                    self.assertEqual(self.catalog.memory.stats().cache_bytes, 16385)
                    self.assertEqual(
                        service.issue(self.handle, self.snapshot, 0),
                        Failure(BoundaryError(ErrorCode.BUSY)),
                    )
                finally:
                    release.set()

        with (
            patch.object(ReceiptTransaction, "confirm", blocked),
            observe_retired_references(self, workers) as retired,
        ):
            asyncio.run(run())
        self.assertEqual(retired, [(0, 0, 0, 0, True)])
        self.assertEqual(
            self.ok(service.query(self.handle, self.snapshot)).commit_version, 1
        )

    def test_reserve_before_submission_and_nested_work(self):
        """A permit can move to a worker; a cancelled wrapper cannot release it."""
        from binnacle.features.commands.job_awareness.proofs import WorkerBudget

        workers = WorkerBudget(1)
        permit = workers.reserve()
        self.assertIsNotNone(permit)
        self.assertIsNone(workers.reserve())
        service = self.service(workers=workers)
        with ThreadPoolExecutor(max_workers=1) as pool:

            def run():
                with permit:
                    return service.query(self.handle, self.snapshot)

            self.assertIsInstance(pool.submit(run).result(timeout=5), Success)
        # Explicit release is only for a proven submission failure, before entry.
        failed_submission = workers.reserve()
        self.assertIsNotNone(failed_submission)
        failed_submission.cancel_before_start()
        with workers.hold() as admitted:
            self.assertTrue(admitted)
            with workers.hold() as nested:
                self.assertTrue(nested)

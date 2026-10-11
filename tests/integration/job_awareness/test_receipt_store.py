"""Synthetic controller transactions. These tests do not authenticate clients."""

import hashlib
import importlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from binnacle.features.commands.job_awareness.models import (
    ByteRange,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    PrincipalClaims,
    ReceiptProofRecord,
    ReceiptState,
    RunGrantClaims,
    Scope,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
    VerifiedRunGrant,
)


class Handle(VerifiedRunGrant):
    @property
    def authority_handle(self):
        return self


def fixtures(length=16385):
    job = JobRef("ja1_" + "1" * 32, "2" * 12, "g1_" + "3" * 32)
    data = b"x" * length
    snap = OutputSnapshot(
        job,
        hashlib.sha256(data).hexdigest(),
        length,
        TerminalOutcome(TerminalKind.EXIT_CODE, 1),
        1,
        10000,
        SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        "4" * 32,
    )
    claims = RunGrantClaims(
        PrincipalClaims("5" * 32, "6" * 32, "7" * 32, "8" * 32),
        "9" * 32,
        "a" * 32,
        job.run_namespace,
        (job,),
        frozenset(Scope),
        1,
        20000,
        1,
    )
    return claims, snap, data


class StoreFixture:
    """Shared synthetic ledger setup; no test methods to collect."""

    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec(
                "binnacle.features.commands.job_awareness.receipt_store"
            ),
            "store missing",
        )
        self.mod = importlib.import_module(
            "binnacle.features.commands.job_awareness.receipt_store"
        )
        self.temp = tempfile.TemporaryDirectory(prefix="ja-i11-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.now = 2
        self.claims, self.snap, self.data = fixtures()
        self.handle = Handle()

        # Test-owned identity resolver. No credential verifier is implemented here.
        def resolve(reader, handle):
            if handle is self.handle:
                return self.claims
            return None

        self.store = self.mod.ReceiptStore(
            self.path, clock=lambda: self.now, resolve=resolve
        )
        self.ok(self.store.initialize())
        self.ok(
            self.store.controller_transaction(
                lambda tx: (
                    tx.rotate_epoch(
                        self.claims.principal.issuer_id, self.claims.issuer_epoch
                    ),
                    tx.register_grant(self.claims, "b" * 64, "c" * 64),
                    tx.register_snapshot(self.snap, self.data),
                )
            )
        )

    def ok(self, result):
        self.assertIsInstance(result, Success, result)
        return result.value

    def query(self):
        return self.ok(self.store.query(self.handle, self.snap))

    def proof(self, start=0, token="d" * 64, claims=None, snap=None):
        c, s = claims or self.claims, snap or self.snap
        stop = min(start + 16384, s.byte_length)
        record = ReceiptProofRecord(
            token,
            c.principal,
            c.issuer_epoch,
            c.grant_id,
            s.job,
            s.sha256,
            ByteRange(start, stop),
            hashlib.sha256(self.data[start:stop]).hexdigest(),
            min(c.expires_at_ms, s.retained_until_ms, self.now + 300000),
            False,
        )
        self.ok(
            self.store.controller_transaction(lambda tx: tx.issue_proof(c, s, record))
        )
        return token

    def confirm(self, tokens):
        return self.store.controller_transaction(
            lambda tx: tx.confirm(self.claims, self.snap, tokens)
        )


class StoreTests(StoreFixture, unittest.TestCase):
    def test_duplicate_reply_and_restart(self):
        proof = self.proof()
        self.assertEqual(self.ok(self.confirm((proof,))).state, ReceiptState.PARTIAL)
        self.assertEqual(self.ok(self.confirm((proof, proof))).commit_version, 1)
        other = self.mod.ReceiptStore(
            self.path,
            clock=lambda: self.now,
            resolve=lambda reader, handle: self.claims,
        )
        self.assertEqual(self.ok(other.query(self.handle, self.snap)).commit_version, 1)
        end = self.proof(16384, "e" * 64)
        self.assertEqual(self.ok(self.confirm((end,))).state, ReceiptState.COMPLETE)
        self.now = 10000
        self.assertEqual(self.query().state, ReceiptState.OUTPUT_EXPIRED)
        self.assertIsInstance(self.confirm((proof,)), Failure)

    def test_batch_rollback(self):
        proof = self.proof()
        self.assertIsInstance(self.confirm((proof, "f" * 64)), Failure)
        self.assertEqual(self.query().commit_version, 0)

        def fail_after_write(tx):
            tx.confirm(self.claims, self.snap, (proof,))
            raise sqlite3.OperationalError("disk full injected")

        self.assertIsInstance(
            self.store.controller_transaction(fail_after_write), Failure
        )
        self.assertEqual(self.query().commit_version, 0)
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)

    def test_busy_and_explicit_retry(self):
        proof = self.proof()
        with sqlite3.connect(self.path, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            result = self.confirm((proof,))
            self.assertEqual(result.error.code, ErrorCode.BUSY)
            db.rollback()
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)

    def test_corrupt_unknown_and_missing_never_unconfirmed(self):
        self.path.write_bytes(b"corrupt")
        self.assertEqual(
            self.store.query(self.handle, self.snap).error.code,
            ErrorCode.STORAGE_UNAVAILABLE,
        )
        self.path.unlink()
        self.assertIsInstance(self.store.query(self.handle, self.snap), Failure)
        self.assertFalse(self.path.exists())

    def test_quota_and_physical_directory(self):
        (self.path.parent / "unexpected").write_bytes(b"x")
        self.assertEqual(
            self.store.controller_transaction(lambda tx: None).error.code,
            ErrorCode.QUOTA_EXCEEDED,
        )

    def test_process_crash_and_reply_loss(self):
        proof = self.proof()
        script = """
import os,sys
from pathlib import Path
from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore
from tests.integration.job_awareness.test_receipt_store import fixtures
c,s,_=fixtures()
store=ReceiptStore(Path(sys.argv[1]),clock=lambda:2)
def action(tx):
    tx.confirm(c,s,('d'*64,))
    if sys.argv[2]=='before': os._exit(17)
store.controller_transaction(action)
os._exit(18)
"""
        for phase, expected in [("before", 0), ("after", 1)]:
            child = subprocess.run(
                [sys.executable, "-c", script, str(self.path), phase],
                capture_output=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(
                child.returncode, 17 if phase == "before" else 18, child.stderr
            )
            self.assertEqual(self.query().commit_version, expected)
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)

    def test_reduced_quotas_are_transactional(self):
        from binnacle.features.commands.job_awareness.receipt_schema import Limits

        proof = self.proof()
        self.proof(16384, "e" * 64)
        bounded = self.mod.ReceiptStore(
            self.path, clock=lambda: self.now, limits=Limits(pages=1)
        )
        self.assertEqual(
            bounded.controller_transaction(
                lambda tx: tx.confirm(self.claims, self.snap, (proof, "e" * 64))
            ).error.code,
            ErrorCode.QUOTA_EXCEEDED,
        )
        self.assertEqual(self.query().commit_version, 0)
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)
        bounded = self.mod.ReceiptStore(
            self.path, clock=lambda: self.now, limits=Limits(grants=1)
        )
        other = replace(self.claims, grant_id="e" * 32)
        self.assertEqual(
            bounded.controller_transaction(
                lambda tx: tx.register_grant(other, "e" * 64, "f" * 64)
            ).error.code,
            ErrorCode.QUOTA_EXCEEDED,
        )

    def test_real_sqlite_full_rolls_back(self):
        before = self.query()

        def fill(tx):
            pages = tx._db.execute("PRAGMA page_count").fetchone()[0]
            tx._db.execute(f"PRAGMA max_page_count={pages}")
            jobs = tuple(replace(self.snap.job, job_id=f"{i:012x}") for i in range(100))
            for i in range(20):
                claim = replace(self.claims, grant_id=f"{i:032x}", jobs=jobs)
                tx.register_grant(claim, f"{i:064x}", "c" * 64)

        self.assertEqual(
            self.store.controller_transaction(fill).error.code,
            ErrorCode.STORAGE_UNAVAILABLE,
        )
        self.assertEqual(self.query(), before)
        self.assertIsNone(
            self.ok(
                self.store.read_transaction(
                    lambda tx: tx.grant("5" * 32, "9" * 32, "0" * 32)
                )
            )
        )

    def test_cleanup_is_explicit_bounded_and_keeps_revocations(self):
        for i in range(64):
            token = f"{i:064x}"
            self.proof(token=token)
            self.ok(self.confirm((token,)))
        self.ok(
            self.store.controller_transaction(lambda tx: tx.revoke_grant(self.claims))
        )
        self.now = 604830001
        self.assertEqual(
            self.ok(self.store.controller_transaction(lambda tx: tx.cleanup())), 64
        )
        self.assertTrue(
            self.ok(
                self.store.read_transaction(
                    lambda tx: tx.grant("5" * 32, "9" * 32, "a" * 32)
                )
            ).revoked
        )
        self.assertEqual(
            self.ok(self.store.controller_transaction(lambda tx: tx.cleanup())), 2
        )

    def test_returned_failure_and_exception_rollback(self):
        proof = self.proof()

        def reject(tx):
            tx.confirm(self.claims, self.snap, (proof,))
            return Failure(self.mod.BoundaryError(ErrorCode.DENIED))

        self.assertIsInstance(self.store.controller_transaction(reject), Failure)
        self.assertEqual(self.query().commit_version, 0)

        def broken(tx):
            tx.confirm(self.claims, self.snap, (proof,))
            raise RuntimeError("trusted callback failed")

        with self.assertRaises(RuntimeError):
            self.store.controller_transaction(broken)
        self.assertEqual(self.query().commit_version, 0)

    def test_empty_seal_and_wrong_page(self):
        c, s, data = fixtures(0)
        self.ok(
            self.store.controller_transaction(lambda tx: tx.register_snapshot(s, data))
        )
        self.assertEqual(
            self.ok(self.store.query(self.handle, s)).state, ReceiptState.UNCONFIRMED
        )
        token = self.proof(snap=s)
        self.assertEqual(
            self.ok(
                self.store.controller_transaction(lambda tx: tx.confirm(c, s, (token,)))
            ).state,
            ReceiptState.COMPLETE,
        )
        invalid = ReceiptProofRecord(
            "e" * 64,
            c.principal,
            c.issuer_epoch,
            c.grant_id,
            self.snap.job,
            self.snap.sha256,
            ByteRange(1, 100),
            "a" * 64,
            9999,
            False,
        )
        self.assertIsInstance(
            self.store.controller_transaction(
                lambda tx: tx.issue_proof(c, self.snap, invalid)
            ),
            Failure,
        )

    def test_independent_process_duplicate(self):
        proof = self.proof()
        script = """
import sys
from pathlib import Path
from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore
from tests.integration.job_awareness.test_receipt_store import fixtures
c,s,_=fixtures()
sys.stdin.read(1)
result=ReceiptStore(Path(sys.argv[1]),clock=lambda:2).controller_transaction(lambda tx:tx.confirm(c,s,('d'*64,)))
print(result)
"""
        children = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        try:
            for child in children:
                child.stdin.write(b"x")
                child.stdin.flush()
            for child in children:
                out, err = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, err)
                self.assertTrue(b"commit_version=1" in out or b"BUSY" in out, out)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)

    def test_busy_commit_rolls_back_consumption(self):
        proof = self.proof()
        with sqlite3.connect(self.path, isolation_level=None) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM clock").fetchone()
            self.assertEqual(self.confirm((proof,)).error.code, ErrorCode.BUSY)
            reader.rollback()
        self.assertEqual(self.query().commit_version, 0)
        record = self.ok(self.store.read_transaction(lambda tx: tx.proof(proof)))
        self.assertFalse(record.consumed)
        self.assertEqual(self.ok(self.confirm((proof,))).commit_version, 1)

    def test_proof_ttl_batch_and_duplicate_issuance(self):
        from binnacle.features.commands.job_awareness.receipt_schema import Limits

        proof = self.proof()
        self.proof()  # Identical unconsumed issuance is idempotent.
        record = self.ok(self.store.read_transaction(lambda tx: tx.proof(proof)))
        short = replace(record, proof_sha256="f" * 64, expires_at_ms=3)
        self.ok(
            self.store.controller_transaction(
                lambda tx: tx.issue_proof(self.claims, self.snap, short)
            )
        )
        self.now = 3
        self.assertIsInstance(self.confirm(("f" * 64,)), Failure)
        self.assertIsInstance(self.confirm((proof,) * 17), Failure)
        self.assertEqual(self.query().commit_version, 0)
        # Consumed rows still count against the total proof quota.
        self.ok(self.confirm((proof,)))
        bounded = self.mod.ReceiptStore(
            self.path, clock=lambda: self.now, limits=Limits(proofs_per_grant=2)
        )
        new = replace(record, proof_sha256="e" * 64)
        self.assertEqual(
            bounded.controller_transaction(
                lambda tx: tx.issue_proof(self.claims, self.snap, new)
            ).error.code,
            ErrorCode.QUOTA_EXCEEDED,
        )

    def test_sqlite_configuration_and_lock_admission(self):
        def inspect(tx):
            values = [
                tx._db.execute("PRAGMA " + name).fetchone()[0]
                for name in (
                    "journal_mode",
                    "synchronous",
                    "foreign_keys",
                    "page_size",
                    "max_page_count",
                    "cache_size",
                    "busy_timeout",
                )
            ]
            self.assertEqual(values, ["delete", 2, 1, 4096, 15360, -2048, 50])
            self.assertEqual(
                self.store.read_transaction(lambda inner: None).error.code,
                ErrorCode.BUSY,
            )

        self.ok(self.store.read_transaction(inspect))

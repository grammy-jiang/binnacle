"""Inert receipt transaction API for trusted controller callbacks.

The schema layer owns connections and rollback. This module owns receipt
operations. No credential verifier or accepting public ACK adapter exists here.
"""

import hashlib
import sqlite3
from collections.abc import Callable
from typing import TypeVar

from binnacle.features.commands.job_awareness.identifiers import (
    canonical_hex,
    require,
    snapshot_to_wire,
)
from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ConsumerReceipt,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    ReceiptProofRecord,
    ReceiptQueryResult,
    Result,
    RunGrantClaims,
    Scope,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.receipt_schema import (
    AuthorityReader,
    GrantRecord,
    Limits,
    ReceiptDatabase,
    Resolver,
    StoreFailure,
    abort,
    decode_proof,
    deny_resolver,
    encode,
    encode_claims,
    grant_key,
    snapshot_key,
)
from binnacle.features.commands.job_awareness.receipts import (
    canonical_page,
    project_receipt,
)

__all__ = [
    "AuthorityReader",
    "GrantRecord",
    "ReceiptStore",
    "ReceiptTransaction",
    "Resolver",
    "StoreFailure",
    "deny_resolver",
]

T = TypeVar("T")


class ReceiptTransaction(AuthorityReader):
    """Private storage API for trusted synthetic controller/I1-2 callbacks.

    Mutation methods do not authenticate credentials or prove reading. They
    must never be exposed directly as tools. SQL and connection are private.
    """

    def __init__(
        self,
        db: sqlite3.Connection,
        now_ms: int,
        limits: Limits,
        resolve: Resolver,
        writable: bool,
    ):
        super().__init__(db, now_ms)
        self._limits, self._resolve, self._writable = limits, resolve, writable

    def _write(self) -> None:
        self._check()
        if not self._writable:
            abort(ErrorCode.DENIED)

    def authorize(
        self, grant: VerifiedRunGrant, job: JobRef, scopes: frozenset[Scope]
    ) -> RunGrantClaims:
        self._check()
        try:
            claims = self._resolve(self, grant)
        except Exception:  # noqa: BLE001 - injected authority must fail closed
            raise StoreFailure(ErrorCode.DENIED) from None
        if type(claims) is not RunGrantClaims:
            raise StoreFailure(ErrorCode.DENIED)
        self.check_claims(claims, job, scopes)
        return claims

    def _room(self, table: str, limit: int, additional: int = 1) -> None:
        statements = {
            "epochs": "SELECT count(*) FROM epochs",
            "grants": "SELECT count(*) FROM grants",
            "snapshots": "SELECT count(*) FROM snapshots",
            "proofs": "SELECT count(*) FROM proofs",
            "receipts": "SELECT count(*) FROM receipts",
            "pages": "SELECT count(*) FROM pages",
        }
        if self._db.execute(statements[table]).fetchone()[0] + additional > limit:
            abort(ErrorCode.QUOTA_EXCEEDED)

    def rotate_epoch(self, issuer_id: str, epoch: str) -> None:
        self._write()
        canonical_hex(issuer_id, 32)
        canonical_hex(epoch, 32)
        if self._db.execute(
            "SELECT 1 FROM epochs WHERE issuer=? AND epoch=?", (issuer_id, epoch)
        ).fetchone():
            abort(ErrorCode.DENIED)
        self._room("epochs", self._limits.epochs)
        self._db.execute("UPDATE epochs SET active=0 WHERE issuer=?", (issuer_id,))
        self._db.execute("INSERT INTO epochs VALUES (?,?,1)", (issuer_id, epoch))

    def register_grant(
        self, claims: RunGrantClaims, capability_sha256: str, credential_sha256: str
    ) -> None:
        self._write()
        require(type(claims) is RunGrantClaims)
        canonical_hex(capability_sha256, 64)
        canonical_hex(credential_sha256, 64)
        if (
            self.current_epoch(claims.principal.issuer_id) != claims.issuer_epoch
            or not claims.issued_at_ms <= self.now_ms < claims.expires_at_ms
        ):
            abort(ErrorCode.DENIED)
        # Never upsert even identical claims: a generation cannot be reissued.
        self._room("grants", self._limits.grants)
        self._db.execute(
            "INSERT INTO grants VALUES (?,?,?,?,?,?,0,?)",
            (
                grant_key(claims),
                claims.principal.issuer_id,
                claims.issuer_epoch,
                encode_claims(claims),
                capability_sha256,
                credential_sha256,
                claims.expires_at_ms,
            ),
        )

    def revoke_grant(self, claims: RunGrantClaims) -> None:
        self._write()
        record = self.grant(
            claims.principal.issuer_id, claims.issuer_epoch, claims.grant_id
        )
        if record is None or record.claims != claims:
            abort(ErrorCode.DENIED)
        self._db.execute(
            "UPDATE grants SET revoked=1 WHERE key=?", (grant_key(claims),)
        )

    def register_snapshot(self, snapshot: OutputSnapshot, sealed_bytes: bytes) -> None:
        """Explicit trusted controller seal; never infer it from process exit."""
        self._write()
        require(type(snapshot) is OutputSnapshot and type(sealed_bytes) is bytes)
        if (
            len(sealed_bytes) != snapshot.byte_length
            or hashlib.sha256(sealed_bytes).hexdigest() != snapshot.sha256
            or not snapshot.sealed_at_ms <= self.now_ms < snapshot.retained_until_ms
        ):
            abort(ErrorCode.SOURCE_UNSEALED)
        metadata = encode(snapshot_to_wire(snapshot))
        if len(metadata.encode("ascii")) > 1024:
            abort(ErrorCode.QUOTA_EXCEEDED)
        existing = self._db.execute(
            "SELECT metadata FROM snapshots WHERE key=?", (snapshot_key(snapshot),)
        ).fetchone()
        if existing:
            if existing[0] != metadata:
                abort(ErrorCode.OUTPUT_CHANGED)
            return
        self._room("snapshots", self._limits.snapshots)
        self._db.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?)",
            (
                snapshot_key(snapshot),
                snapshot.job.run_namespace,
                metadata,
                snapshot.retained_until_ms,
            ),
        )

    def _snapshot(self, snapshot: OutputSnapshot, *, live: bool) -> None:
        row = self._db.execute(
            "SELECT metadata FROM snapshots WHERE key=?", (snapshot_key(snapshot),)
        ).fetchone()
        if row is None:
            abort(ErrorCode.SOURCE_UNSEALED)
        if row[0] != encode(snapshot_to_wire(snapshot)):
            abort(ErrorCode.OUTPUT_CHANGED)
        if live and self.now_ms >= snapshot.retained_until_ms:
            abort(ErrorCode.OUTPUT_EXPIRED)

    def receipt(
        self, claims: RunGrantClaims, snapshot: OutputSnapshot
    ) -> ConsumerReceipt:
        """Controller read after fresh admission; no receipt insert on absence."""
        self.check_claims(claims, snapshot.job, frozenset({Scope.OBSERVE}))
        self._snapshot(snapshot, live=False)
        return self._receipt(claims, snapshot)

    def replay_receipt(
        self,
        claims: RunGrantClaims,
        snapshot: OutputSnapshot,
        records: tuple[ReceiptProofRecord, ...],
    ) -> ConsumerReceipt:
        """Project consumed ACKs after same-transaction token/lease validation.

        Trusted I1-2 callback only. This does not authorize generic queries or
        mutate coverage. The caller must roll back an all-consumed replay.
        """
        self.check_claims(claims, snapshot.job, frozenset({Scope.READ, Scope.ACK}))
        self._snapshot(snapshot, live=True)
        require(type(records) is tuple and 1 <= len(records) <= 16)
        current = self._receipt(claims, snapshot)
        for record in records:
            if (
                type(record) is not ReceiptProofRecord
                or not record.consumed
                or record.principal != claims.principal
                or record.issuer_epoch != claims.issuer_epoch
                or record.grant_id != claims.grant_id
                or record.job != snapshot.job
                or record.snapshot_sha256 != snapshot.sha256
                or self.now_ms >= record.expires_at_ms
                or self.proof(record.proof_sha256) != record
                or record.range not in current.ranges
            ):
                abort(ErrorCode.DENIED)
        return current

    def _receipt(
        self, claims: RunGrantClaims, snapshot: OutputSnapshot
    ) -> ConsumerReceipt:
        key = (grant_key(claims), snapshot_key(snapshot))
        row = self._db.execute(
            "SELECT version FROM receipts WHERE grant_key=? AND snapshot_key=?", key
        ).fetchone()
        starts = tuple(
            r[0]
            for r in self._db.execute(
                "SELECT start FROM pages WHERE grant_key=? AND snapshot_key=? ORDER BY start LIMIT 65",
                key,
            )
        )
        return project_receipt(
            snapshot,
            starts,
            row[0] if row else 0,
            claims.authority_revision,
            self.now_ms,
        )

    def proof(self, digest: str) -> ReceiptProofRecord | None:
        self._check()
        canonical_hex(digest, 64)
        row = self._db.execute(
            "SELECT g.claims,s.metadata,p.start,p.stop,p.page_sha256,p.expires,p.consumed FROM proofs p JOIN grants g ON g.key=p.grant_key JOIN snapshots s ON s.key=p.snapshot_key WHERE digest=?",
            (digest,),
        ).fetchone()
        if row is None:
            return None
        return decode_proof(digest, row)

    def issue_proof(
        self,
        claims: RunGrantClaims,
        snapshot: OutputSnapshot,
        record: ReceiptProofRecord,
    ) -> None:
        """Persist trusted controller's digest only. No token generation or ACK."""
        self._write()
        self.check_claims(claims, snapshot.job, frozenset({Scope.READ}))
        self._snapshot(snapshot, live=True)
        require(type(record) is ReceiptProofRecord)
        if (
            record.principal != claims.principal
            or record.issuer_epoch != claims.issuer_epoch
            or record.grant_id != claims.grant_id
            or record.job != snapshot.job
            or record.snapshot_sha256 != snapshot.sha256
            or record.consumed
            or record.range != canonical_page(snapshot, record.range.start)
            or not self.now_ms
            < record.expires_at_ms
            <= min(
                self.now_ms + 300000, claims.expires_at_ms, snapshot.retained_until_ms
            )
        ):
            abort(ErrorCode.INVALID_PROOF)
        old = self.proof(record.proof_sha256)
        if old is not None:
            if old != record:
                abort(ErrorCode.INVALID_PROOF)
            return
        key = grant_key(claims)
        total, pending = self._db.execute(
            "SELECT count(*),coalesce(sum(consumed=0 AND expires>?),0) FROM proofs WHERE grant_key=?",
            (self.now_ms, key),
        ).fetchone()
        if (
            total >= self._limits.proofs_per_grant
            or pending >= self._limits.outstanding
        ):
            abort(ErrorCode.QUOTA_EXCEEDED)
        self._room("proofs", self._limits.proofs)
        self._db.execute(
            "INSERT INTO proofs VALUES (?,?,?,?,?,?,?,0)",
            (
                record.proof_sha256,
                key,
                snapshot_key(snapshot),
                record.range.start,
                record.range.stop,
                record.page_sha256,
                record.expires_at_ms,
            ),
        )

    def confirm(
        self, claims: RunGrantClaims, snapshot: OutputSnapshot, digests: tuple[str, ...]
    ) -> ConsumerReceipt:
        """Trusted transaction primitive, NOT an authenticated ACK endpoint.

        I1-2 must authorize the handle here, hold an I0 verified lease, validate
        tokens, and call this in that same callback. Public acknowledge denies.
        """
        self._write()
        self.check_claims(claims, snapshot.job, frozenset({Scope.READ, Scope.ACK}))
        self._snapshot(snapshot, live=True)
        require(type(digests) is tuple and 1 <= len(digests) <= 16)
        starts = set()
        for digest in digests:
            record = self.proof(digest)
            if (
                record is None
                or record.principal != claims.principal
                or record.issuer_epoch != claims.issuer_epoch
                or record.grant_id != claims.grant_id
                or record.job != snapshot.job
                or record.snapshot_sha256 != snapshot.sha256
                or self.now_ms >= record.expires_at_ms
                or record.range != canonical_page(snapshot, record.range.start)
            ):
                abort(ErrorCode.INVALID_PROOF)
            starts.add(record.range.start)
        key = (grant_key(claims), snapshot_key(snapshot))
        current = {
            row[0]
            for row in self._db.execute(
                "SELECT start FROM pages WHERE grant_key=? AND snapshot_key=?", key
            )
        }
        new = starts - current
        if new:
            if len(current | new) > 64:
                abort(ErrorCode.QUOTA_EXCEEDED)
            self._room("pages", self._limits.pages, len(new))
            exists = self._db.execute(
                "SELECT 1 FROM receipts WHERE grant_key=? AND snapshot_key=?", key
            ).fetchone()
            if not exists:
                self._room("receipts", self._limits.receipts)
                expiry = (
                    max(claims.expires_at_ms, snapshot.retained_until_ms) + 604800000
                )
                self._db.execute(
                    "INSERT INTO receipts VALUES (?,?,1,?)", (*key, expiry)
                )
            else:
                self._db.execute(
                    "UPDATE receipts SET version=version+1 WHERE grant_key=? AND snapshot_key=?",
                    key,
                )
            self._db.executemany(
                "INSERT INTO pages VALUES (?,?,?)",
                [(*key, start) for start in sorted(new)],
            )
        self._db.executemany(
            "UPDATE proofs SET consumed=1 WHERE digest=?",
            [(digest,) for digest in set(digests)],
        )
        # READ+ACK does not imply OBSERVE; projection itself needs no extra scope.
        version = self._db.execute(
            "SELECT version FROM receipts WHERE grant_key=? AND snapshot_key=?", key
        ).fetchone()[0]
        return project_receipt(
            snapshot,
            tuple(sorted(current | new)),
            version,
            claims.authority_revision,
            self.now_ms,
        )

    def cleanup(self) -> int:
        """Explicit controller only; <=64 total rows, no cascades/tombstone loss."""
        self._write()
        removed = 0
        # Keep proof history for seven days, not merely until token expiry.
        rows = self._db.execute(
            "SELECT digest FROM proofs WHERE expires<=? ORDER BY expires,digest LIMIT 64",
            (self.now_ms - 604800000,),
        ).fetchall()
        for row in rows:
            self._db.execute("DELETE FROM proofs WHERE digest=?", row)
            removed += 1
        rows = self._db.execute(
            "SELECT grant_key,snapshot_key FROM receipts WHERE expires<=? ORDER BY expires,grant_key,snapshot_key LIMIT ?",
            (self.now_ms, 64 - removed),
        ).fetchall()
        for key in rows:
            pages = self._db.execute(
                "SELECT start FROM pages WHERE grant_key=? AND snapshot_key=? ORDER BY start LIMIT ?",
                (*key, 64 - removed),
            ).fetchall()
            for page in pages:
                self._db.execute(
                    "DELETE FROM pages WHERE grant_key=? AND snapshot_key=? AND start=?",
                    (*key, page[0]),
                )
                removed += 1
            if removed == 64:
                break
            self._db.execute(
                "DELETE FROM receipts WHERE grant_key=? AND snapshot_key=?", key
            )
            removed += 1
        return removed


class ReceiptStore(ReceiptDatabase):
    """One SQLite transaction per operation; the v1 controller API facade."""

    def initialize(self) -> Result[None]:
        """Explicit controller-only schema creation/recovery; unknown version denies."""
        return self._run(lambda tx: None, ReceiptTransaction, write=True, create=True)

    def read_transaction(
        self, callback: Callable[[ReceiptTransaction], T]
    ) -> Result[T]:
        return self._run(callback, ReceiptTransaction, write=False)

    def controller_transaction(
        self, callback: Callable[[ReceiptTransaction], T]
    ) -> Result[T]:
        """Trusted synthetic controller seam. Never pass caller code or claims."""
        return self._run(callback, ReceiptTransaction, write=True)

    def query(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> ReceiptQueryResult:
        if type(snapshot) is not OutputSnapshot:
            return Failure(BoundaryError(ErrorCode.DENIED))

        def query_tx(tx: ReceiptTransaction) -> ConsumerReceipt:
            claims = tx.authorize(grant, snapshot.job, frozenset({Scope.OBSERVE}))
            return tx.receipt(claims, snapshot)

        return self.read_transaction(query_tx)

    def acknowledge(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot, proofs: tuple[str, ...]
    ) -> ReceiptQueryResult:
        """Unconditionally disabled until the full I1-2 ACK policy is supplied."""
        return Failure(BoundaryError(ErrorCode.DENIED))

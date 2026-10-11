"""Synthetic-only durable page issuance and service-side ACK assertions.

No public MCP endpoint exists. ReceiptStore.acknowledge remains denial-only.
Returning a proof can confirm a page assertion; it cannot prove that a model
read, understood, or even received output through an authenticated chat channel.
Only a controller-injected SnapshotReadPort supplies leases. Caller metadata
never seals output. The controller must enroll append-only seals in both its
catalog and ledger before use, and own an isolated restrictive ledger directory.
SnapshotReadPort owns whole-seal verification. Admission reserves aggregate
payload hashing, including page hashes and PageEnvelope validation, before
opening that lease. Some valid snapshots cannot fit the unchanged P0 work cap.
"""

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from threading import BoundedSemaphore, Lock, get_ident, local
from types import TracebackType
from typing import TypeVar

from binnacle.features.commands.job_awareness.grants import DENIED, SyntheticAuthority
from binnacle.features.commands.job_awareness.identifiers import (
    bounded_int,
    canonical_hex,
    snapshot_to_wire,
)
from binnacle.features.commands.job_awareness.models import (
    MAX_SNAPSHOT_BYTES,
    PAGE_BYTES,
    AuthorityDecision,
    BoundaryError,
    ConsumerReceipt,
    ErrorCode,
    Failure,
    OutputSnapshot,
    PageEnvelope,
    PageResult,
    ReceiptProofRecord,
    ReceiptQueryResult,
    Result,
    RunGrantClaims,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import SnapshotReadPort
from binnacle.features.commands.job_awareness.receipt_store import (
    ReceiptTransaction,
    StoreFailure,
)
from binnacle.features.commands.job_awareness.receipts import canonical_page

T = TypeVar("T")
# P0 snapshot_hash_bytes_per_explicit_operation, separate from the size ceiling.
MAX_HASH_BYTES = 1048576


class _ReceiptReplay(Exception):
    """Return a validated receipt only after rolling back incidental writes."""

    def __init__(self, receipt: ConsumerReceipt, expires_at_ms: int):
        self.receipt, self.expires_at_ms = receipt, expires_at_ms


class WorkerPermit:
    """Transfer a reserved slot to one worker. Cancellation is not completion."""

    def __init__(self, budget: "WorkerBudget"):
        self._budget = budget
        self._lock = Lock()
        self._owner: int | None = None
        self._released = False
        self._previous = False

    def cancel_before_start(self) -> bool:
        """Only for failed submission; cannot free an entered worker's slot."""
        with self._lock:
            if self._owner is not None or self._released:
                return False
            self._released = True
            self._budget._semaphore.release()
            return True

    def __enter__(self) -> "WorkerPermit":  # noqa: PYI034 - Python 3.10
        with self._lock:
            if self._owner is not None or self._released:
                raise RuntimeError("Permit already used")
            self._owner = get_ident()
            self._previous = getattr(self._budget._local, "held", False)
            self._budget._local.held = True
            return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            if self._owner != get_ident() or self._released:
                raise RuntimeError("Permit owner mismatch")
            self._budget._local.held = self._previous
            self._released = True
            self._budget._semaphore.release()


class WorkerBudget:
    """Nonblocking shared admission, held by the actual synchronous worker.

    An adapter calls reserve() before submission and enters that permit inside
    its worker, releasing only after that worker finishes. These synchronous entry
    points hold their own permit until transaction and lease cleanup. They must
    never run on an event-loop thread. Nested synchronous calls share admission.
    No executor, waiting queue, background thread, or retry is created here.
    """

    def __init__(self, limit: int = 2):
        self._semaphore = BoundedSemaphore(bounded_int(limit, 1, 2))
        self._local = local()

    def reserve(self) -> WorkerPermit | None:
        if not self._semaphore.acquire(blocking=False):
            return None
        return WorkerPermit(self)

    @contextmanager
    def hold(self) -> Iterator[bool]:
        if getattr(self._local, "held", False):
            yield True
            return
        permit = self.reserve()
        if permit is None:
            yield False
            return
        with permit:
            yield True


_WORKERS = WorkerBudget()


def _external(result: Result[T]) -> Result[T]:
    if isinstance(result, Failure) and result.error.code not in (
        ErrorCode.BUSY,
        ErrorCode.QUOTA_EXCEEDED,
    ):
        return DENIED
    return result


class SyntheticProofService:
    """Bounded PageIssuePort/ReceiptCommandPort/ReceiptQueryPort policy.

    Tokens are 64 lowercase hex bytes: 128 random nonce bits plus a 128-bit
    HMAC-SHA256 tag. The tag binds the full immutable grant, both credential
    digests, full sealed snapshot metadata, canonical page digest and expiry.
    SQLite stores SHA256(token), never the returned token or signing key.
    A controller can retain proof_key across ledger worker reconstruction; losing
    it safely invalidates proofs. Controller restart also retires the epoch.
    """

    def __init__(
        self,
        authority: SyntheticAuthority,
        snapshots: SnapshotReadPort | None,
        *,
        proof_key: bytes | None = None,
        workers: WorkerBudget | None = None,
        timeout_ms: int = 1000,
    ):
        self._authority, self._snapshots = authority, snapshots
        self._key = secrets.token_bytes(32) if proof_key is None else proof_key
        if type(self._key) is not bytes or len(self._key) != 32:
            raise ValueError("Invalid synthetic proof key")
        self._workers = workers or _WORKERS
        self._timeout_ms = bounded_int(timeout_ms, 1, 5000)

    def _fresh(
        self, claims: RunGrantClaims, snapshot: OutputSnapshot, deadline: int
    ) -> int:
        now = self._authority.clock.now()
        if now >= min(
            deadline, claims.expires_at_ms, snapshot.retained_until_ms
        ) or now < max(claims.issued_at_ms, snapshot.sealed_at_ms):
            raise StoreFailure(ErrorCode.DENIED)
        return now

    def _operate(
        self,
        grant: VerifiedRunGrant,
        snapshot: OutputSnapshot,
        scopes: frozenset[Scope],
        action: Callable[[ReceiptTransaction, RunGrantClaims, memoryview, int], T],
        hash_bytes: int,
    ) -> Result[T]:
        if type(snapshot) is not OutputSnapshot or self._snapshots is None:
            return DENIED
        with self._workers.hold() as admitted:
            if not admitted:
                return Failure(BoundaryError(ErrorCode.BUSY))
            try:
                deadline = self._authority.clock.now() + self._timeout_ms
                if (
                    self._authority.check(grant, snapshot.job, scopes)
                    is not AuthorityDecision.AUTHORIZED
                ):
                    return DENIED
                # Includes the port's full seal hash and every downstream
                # payload hash. Deny before source reads or a write transaction.
                if hash_bytes > MAX_HASH_BYTES:
                    return Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED))
                opened = self._snapshots.open_verified(grant, snapshot)
                if isinstance(opened, Failure):
                    return _external(opened)
                # Release the root view before unpinning, even when a traceback
                # retains callback frames. Page subviews have their own contexts.
                with opened.value as lease, memoryview(lease.verified_bytes) as data:
                    if (
                        type(data.obj) is not bytes
                        or len(data) > MAX_SNAPSHOT_BYTES
                        or lease.snapshot != snapshot
                        or len(data) != snapshot.byte_length
                    ):
                        return DENIED

                    def execute(tx: ReceiptTransaction) -> T:
                        # This is the admission that authorizes mutation. The
                        # earlier check merely avoids unauthorized payload reads.
                        claims = tx.authorize(grant, snapshot.job, scopes)
                        self._fresh(claims, snapshot, deadline)
                        try:
                            result = action(tx, claims, data, deadline)
                        except _ReceiptReplay as replay:
                            tx.authorize(grant, snapshot.job, scopes)
                            self._fresh(
                                claims, snapshot, min(deadline, replay.expires_at_ms)
                            )
                            raise
                        tx.authorize(grant, snapshot.job, scopes)
                        self._fresh(claims, snapshot, deadline)
                        return result

                    return _external(
                        self._authority.store.controller_transaction(execute)
                    )
            except _ReceiptReplay:
                raise
            except Exception:  # noqa: BLE001 - failed injected verifier/clock denies; BaseException unwinds
                return DENIED

    def _binding(
        self,
        tx: ReceiptTransaction,
        claims: RunGrantClaims,
        snapshot: OutputSnapshot,
        record: ReceiptProofRecord,
    ) -> bytes:
        grant = tx.grant(
            claims.principal.issuer_id, claims.issuer_epoch, claims.grant_id
        )
        if grant is None or grant.claims != claims:
            raise StoreFailure(ErrorCode.DENIED)
        full_claims = asdict(claims)
        full_claims["scopes"] = sorted(scope.value for scope in claims.scopes)
        value = {
            "version": "binnacle-ja-synthetic-proof-v1",
            "grant": full_claims,
            "capability_sha256": grant.capability_sha256,
            "credential_sha256": grant.credential_sha256,
            "snapshot": snapshot_to_wire(snapshot),
            "page": (record.range.start, record.range.stop, record.page_sha256),
            "expires_at_ms": record.expires_at_ms,
        }
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")

    def _token(self, nonce: str, binding: bytes) -> str:
        tag = hmac.digest(self._key, bytes.fromhex(nonce) + binding, "sha256")[:16]
        return nonce + tag.hex()

    def issue(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot, start: int
    ) -> PageResult:
        try:
            page = canonical_page(snapshot, start)
        except (ValueError, TypeError):
            return DENIED

        def issue_tx(
            tx: ReceiptTransaction,
            claims: RunGrantClaims,
            data: memoryview,
            deadline: int,
        ) -> PageEnvelope:
            now = self._fresh(claims, snapshot, deadline)
            # tx.issue_proof enforces its earlier admission-time TTL too.
            expires = min(
                now + 300000,
                tx.now_ms + 300000,
                claims.expires_at_ms,
                snapshot.retained_until_ms,
            )
            with data[page.start : page.stop] as payload:
                page_hash = hashlib.sha256(payload).hexdigest()
                record = ReceiptProofRecord(
                    "0" * 64,
                    claims.principal,
                    claims.issuer_epoch,
                    claims.grant_id,
                    snapshot.job,
                    snapshot.sha256,
                    page,
                    page_hash,
                    expires,
                    False,
                )
                token = self._token(
                    secrets.token_hex(16), self._binding(tx, claims, snapshot, record)
                )
                digest = hashlib.sha256(token.encode("ascii")).hexdigest()
                record = replace(record, proof_sha256=digest)
                # A randomness collision must not re-emit an existing/consumed token.
                if tx.proof(digest) is not None:
                    raise StoreFailure(ErrorCode.DENIED)
                tx.issue_proof(claims, snapshot, record)
                self._fresh(claims, snapshot, min(deadline, expires))
                return PageEnvelope(
                    snapshot,
                    page,
                    page_hash,
                    base64.b64encode(payload).decode("ascii"),
                    token,
                    expires,
                )

        return self._operate(
            grant,
            snapshot,
            frozenset({Scope.READ}),
            issue_tx,
            # One page digest here, another inside PageEnvelope.__post_init__.
            snapshot.byte_length + 2 * (page.stop - page.start),
        )

    def _validate_proof(
        self,
        tx: ReceiptTransaction,
        claims: RunGrantClaims,
        snapshot: OutputSnapshot,
        data: memoryview,
        token: str,
        deadline: int,
    ) -> ReceiptProofRecord:
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        record = tx.proof(digest)
        if (
            record is None
            or record.principal != claims.principal
            or record.issuer_epoch != claims.issuer_epoch
            or record.grant_id != claims.grant_id
            or record.job != snapshot.job
            or record.snapshot_sha256 != snapshot.sha256
            or record.range != canonical_page(snapshot, record.range.start)
        ):
            raise StoreFailure(ErrorCode.DENIED)
        self._fresh(claims, snapshot, min(deadline, record.expires_at_ms))
        with data[record.range.start : record.range.stop] as payload:
            page_hash = hashlib.sha256(payload).hexdigest()
        expected = self._token(token[:32], self._binding(tx, claims, snapshot, record))
        if not hmac.compare_digest(
            page_hash, record.page_sha256
        ) or not hmac.compare_digest(expected, token):
            raise StoreFailure(ErrorCode.DENIED)
        return record

    def acknowledge(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot, proofs: tuple[str, ...]
    ) -> ReceiptQueryResult:
        if (
            type(snapshot) is not OutputSnapshot
            or type(proofs) is not tuple
            or not 1 <= len(proofs) <= 16
        ):
            return DENIED
        try:
            for proof in proofs:
                canonical_hex(proof, 64)
        except ValueError:
            return DENIED
        tokens = tuple(dict.fromkeys(proofs))

        def ack_tx(
            tx: ReceiptTransaction,
            claims: RunGrantClaims,
            data: memoryview,
            deadline: int,
        ) -> ConsumerReceipt:
            records = tuple(
                self._validate_proof(tx, claims, snapshot, data, token, deadline)
                for token in tokens
            )
            consumed = tuple(record for record in records if record.consumed)
            if consumed:
                current = tx.replay_receipt(claims, snapshot, consumed)
                if len(consumed) == len(records):
                    expires = min(deadline, *(r.expires_at_ms for r in records))
                    self._fresh(claims, snapshot, expires)
                    raise _ReceiptReplay(current, expires)
            result = tx.confirm(
                claims, snapshot, tuple(record.proof_sha256 for record in records)
            )
            # A slow confirmation can expire tokens after initial admission.
            # Raising here rolls back pages, consumption and receipt together.
            self._fresh(
                claims, snapshot, min(deadline, *(r.expires_at_ms for r in records))
            )
            return result

        try:
            return self._operate(
                grant,
                snapshot,
                frozenset({Scope.READ, Scope.ACK}),
                ack_tx,
                # Include each distinct token's canonical page hash.
                snapshot.byte_length
                + len(tokens) * min(PAGE_BYTES, snapshot.byte_length),
            )
        except _ReceiptReplay as replay:
            return Success(replay.receipt)

    def query(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> ReceiptQueryResult:
        """Read-only ledger query; no lease, token, confirmation or cleanup."""
        with self._workers.hold() as admitted:
            if not admitted:
                return Failure(BoundaryError(ErrorCode.BUSY))
            return _external(self._authority.store.query(grant, snapshot))

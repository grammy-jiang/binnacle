"""Private SQLite schema, authority reads, and bounded transaction lifecycle."""

import json
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import NoReturn, TypeVar

from binnacle.features.commands.job_awareness.identifiers import (
    bounded_int,
    canonical_hex,
    snapshot_from_wire,
)
from binnacle.features.commands.job_awareness.models import (
    MAX_INTEGER,
    BoundaryError,
    ByteRange,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    PrincipalClaims,
    ReceiptProofRecord,
    Result,
    RunGrantClaims,
    Scope,
    Success,
    VerifiedRunGrant,
)

VERSION = 1
SCHEMA = (
    "CREATE TABLE clock (id INTEGER PRIMARY KEY CHECK(id=1), high_water INTEGER NOT NULL)",
    "CREATE TABLE epochs (issuer TEXT NOT NULL, epoch TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), PRIMARY KEY(issuer,epoch))",
    "CREATE UNIQUE INDEX one_epoch ON epochs(issuer) WHERE active=1",
    "CREATE TABLE grants (key TEXT PRIMARY KEY, issuer TEXT NOT NULL, epoch TEXT NOT NULL, claims TEXT NOT NULL, capability_sha256 TEXT NOT NULL UNIQUE, credential_sha256 TEXT NOT NULL, revoked INTEGER NOT NULL CHECK(revoked IN (0,1)), expires INTEGER NOT NULL, FOREIGN KEY(issuer,epoch) REFERENCES epochs(issuer,epoch))",
    "CREATE TABLE snapshots (key TEXT PRIMARY KEY, run TEXT NOT NULL, metadata TEXT NOT NULL, expires INTEGER NOT NULL)",
    "CREATE TABLE proofs (digest TEXT PRIMARY KEY, grant_key TEXT NOT NULL REFERENCES grants(key), snapshot_key TEXT NOT NULL REFERENCES snapshots(key), start INTEGER NOT NULL, stop INTEGER NOT NULL, page_sha256 TEXT NOT NULL, expires INTEGER NOT NULL, consumed INTEGER NOT NULL CHECK(consumed IN (0,1)))",
    "CREATE INDEX proof_grant ON proofs(grant_key,consumed,expires)",
    "CREATE TABLE receipts (grant_key TEXT NOT NULL REFERENCES grants(key), snapshot_key TEXT NOT NULL REFERENCES snapshots(key), version INTEGER NOT NULL CHECK(version>0), expires INTEGER NOT NULL, PRIMARY KEY(grant_key,snapshot_key))",
    "CREATE INDEX receipt_expiry ON receipts(expires,grant_key,snapshot_key)",
    "CREATE INDEX proof_expiry ON proofs(expires,digest)",
    "CREATE TABLE pages (grant_key TEXT NOT NULL, snapshot_key TEXT NOT NULL, start INTEGER NOT NULL, PRIMARY KEY(grant_key,snapshot_key,start), FOREIGN KEY(grant_key,snapshot_key) REFERENCES receipts(grant_key,snapshot_key))",
)


@dataclass(frozen=True)
class Limits:
    """P0 hard ceilings. Tests may reduce them, never raise them."""

    grants: int = 128
    epochs: int = 128  # Conservative bound: tombstones never evicted.
    snapshots: int = 100  # Conservative ledger-wide cap.
    proofs: int = 32768
    proofs_per_grant: int = 4096
    outstanding: int = 64
    receipts: int = 12800
    pages: int = 32768
    max_page_count: int = 15360

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= getattr(type(self), name):
                raise ValueError("Invalid private limits")


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def grant_key(claims: RunGrantClaims) -> str:
    # Generation binds an immutable full principal in the grants table.
    return encode((claims.principal.issuer_id, claims.issuer_epoch, claims.grant_id))


def encode_claims(claims: RunGrantClaims) -> str:
    value = asdict(claims)
    value["scopes"] = sorted(scope.value for scope in claims.scopes)
    return encode(value)


def decode_claims(value: str) -> RunGrantClaims:
    record = json.loads(value)
    record["principal"] = PrincipalClaims(**record["principal"])
    record["jobs"] = tuple(JobRef(**job) for job in record["jobs"])
    record["scopes"] = frozenset(Scope(scope) for scope in record["scopes"])
    return RunGrantClaims(**record)


def decode_proof(
    digest: str, row: tuple[str, str, int, int, str, int, int]
) -> ReceiptProofRecord:
    """Decode an issued proof joined to its immutable grant and snapshot."""
    claims, snapshot = decode_claims(row[0]), snapshot_from_wire(json.loads(row[1]))
    return ReceiptProofRecord(
        digest,
        claims.principal,
        claims.issuer_epoch,
        claims.grant_id,
        snapshot.job,
        snapshot.sha256,
        ByteRange(row[2], row[3]),
        row[4],
        row[5],
        bool(row[6]),
    )


class StoreFailure(Exception):
    """Fixed, nonreflecting transaction abort."""

    def __init__(self, code: ErrorCode):
        super().__init__(code.value)
        self.code = code


def abort(code: ErrorCode) -> NoReturn:
    raise StoreFailure(code)


def snapshot_key(snapshot: OutputSnapshot) -> str:
    return encode((snapshot.job.canonical_key, snapshot.sha256))


@dataclass(frozen=True)
class GrantRecord:
    claims: RunGrantClaims
    capability_sha256: str
    credential_sha256: str
    revoked: bool


class AuthorityReader:
    """Frozen I1-2 reader, valid only during its enclosing transaction.

    Never retains a connection after callback completion. Records are data,
    not authority tickets. Resolver must check registered object identity and
    independent principal credentials; it may not trust authority_handle alone.
    """

    def __init__(self, db: sqlite3.Connection, now_ms: int):
        self._db = db
        self.now_ms = now_ms
        self._active = True

    def _check(self) -> None:
        if not self._active:
            abort(ErrorCode.DENIED)

    def current_epoch(self, issuer_id: str) -> str | None:
        self._check()
        canonical_hex(issuer_id, 32)
        row = self._db.execute(
            "SELECT epoch FROM epochs WHERE issuer=? AND active=1", (issuer_id,)
        ).fetchone()
        return row[0] if row else None

    def grant(
        self, issuer_id: str, issuer_epoch: str, grant_id: str
    ) -> GrantRecord | None:
        self._check()
        for value in (issuer_id, issuer_epoch, grant_id):
            canonical_hex(value, 32)
        row = self._db.execute(
            "SELECT claims,capability_sha256,credential_sha256,revoked FROM grants WHERE key=?",
            (encode((issuer_id, issuer_epoch, grant_id)),),
        ).fetchone()
        return (
            GrantRecord(decode_claims(row[0]), row[1], row[2], bool(row[3]))
            if row
            else None
        )

    def grant_for_capability(self, capability_sha256: str) -> GrantRecord | None:
        """Indexed private digest lookup; returned claims are not authorization."""
        self._check()
        canonical_hex(capability_sha256, 64)
        row = self._db.execute(
            "SELECT claims,capability_sha256,credential_sha256,revoked FROM grants WHERE capability_sha256=?",
            (capability_sha256,),
        ).fetchone()
        return (
            GrantRecord(decode_claims(row[0]), row[1], row[2], bool(row[3]))
            if row
            else None
        )

    def check_claims(
        self, claims: RunGrantClaims, job: JobRef, required_scopes: frozenset[Scope]
    ) -> None:
        """Storage invariants only. Caller must first establish handle identity."""
        self._check()
        if (
            type(claims) is not RunGrantClaims
            or type(job) is not JobRef
            or type(required_scopes) is not frozenset
            or not required_scopes
            or any(type(scope) is not Scope for scope in required_scopes)
        ):
            abort(ErrorCode.DENIED)
        record = self.grant(
            claims.principal.issuer_id, claims.issuer_epoch, claims.grant_id
        )
        if (
            record is None
            or record.claims != claims
            or record.revoked
            or self.current_epoch(claims.principal.issuer_id) != claims.issuer_epoch
            or not claims.issued_at_ms <= self.now_ms < claims.expires_at_ms
            or not required_scopes <= claims.scopes
            or job not in claims.jobs
        ):
            abort(ErrorCode.DENIED)


Resolver = Callable[[AuthorityReader, VerifiedRunGrant], RunGrantClaims | None]


def deny_resolver(reader: AuthorityReader, grant: VerifiedRunGrant) -> None:
    return None


T = TypeVar("T")
TransactionT = TypeVar("TransactionT", bound=AuthorityReader)
_PROCESS_CONNECTION = Lock()


class ReceiptDatabase:
    """One SQLite transaction per operation; no connection or file at import.

    Path must be in an exclusive controller-owned local directory. DELETE with
    FULL sync avoids unbounded WAL readers/checkpoints. This does not establish
    hardware power-loss durability or an OS free-space reservation.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], int],
        resolve: Resolver = deny_resolver,
        limits: Limits | None = None,
    ):
        self.path, self._clock, self._resolve, self._limits = (
            Path(path),
            clock,
            resolve,
            limits or Limits(),
        )

    def _reserve(self) -> None:
        allowed = {self.path.name, self.path.name + "-journal"}
        used = 0
        for entry in self.path.parent.iterdir():
            if entry.name not in allowed or entry.is_symlink() or not entry.is_file():
                abort(ErrorCode.QUOTA_EXCEEDED)
            used += entry.stat().st_size
        maximum = self._limits.max_page_count * 4096
        main = self.path.stat().st_size
        if (
            main > maximum
            or used > 134217728
            or shutil.disk_usage(self.path.parent).free < maximum - main + 67108864
        ):
            abort(ErrorCode.QUOTA_EXCEEDED)

    def _connect(self, create: bool) -> sqlite3.Connection:
        if self.path.is_symlink():
            abort(ErrorCode.STORAGE_UNAVAILABLE)
        uri = self.path.absolute().as_uri() + "?mode=" + ("rwc" if create else "rw")
        db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0.05)
        try:
            db.execute("PRAGMA busy_timeout=50")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA cache_size=-2048")
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            if mode != "delete":
                abort(ErrorCode.STORAGE_UNAVAILABLE)
            if db.execute("PRAGMA page_size").fetchone()[0] != 4096:
                abort(ErrorCode.STORAGE_UNAVAILABLE)
            if db.execute("PRAGMA auto_vacuum").fetchone()[0] != 0:
                abort(ErrorCode.STORAGE_UNAVAILABLE)
            db.execute(f"PRAGMA max_page_count={self._limits.max_page_count}")
            return db
        except BaseException:
            db.close()
            raise

    def _run(
        self,
        callback: Callable[[TransactionT], T],
        transaction_type: Callable[
            [sqlite3.Connection, int, Limits, Resolver, bool], TransactionT
        ],
        *,
        write: bool,
        create: bool = False,
    ) -> Result[T]:
        if not _PROCESS_CONNECTION.acquire(blocking=False):
            return Failure(BoundaryError(ErrorCode.BUSY))
        db = None
        tx = None
        try:
            db = self._connect(create)
            if not write:
                db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            shape = {
                row[0]
                for row in db.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
                )
            }
            try:
                now = bounded_int(self._clock(), 0, MAX_INTEGER)
            except Exception:  # noqa: BLE001 - no safe time after clock failure
                raise StoreFailure(ErrorCode.CLOCK_UNSAFE) from None
            if create and version == 0 and not shape:
                self._reserve()
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute("PRAGMA user_version=1")
                db.execute("INSERT INTO clock VALUES (1,?)", (now,))
            elif version != VERSION or shape != set(SCHEMA):
                abort(ErrorCode.STORAGE_UNAVAILABLE)
            row = db.execute("SELECT high_water FROM clock WHERE id=1").fetchone()
            if row is None or now < row[0]:
                abort(ErrorCode.CLOCK_UNSAFE)
            if write:
                self._reserve()
                db.execute("UPDATE clock SET high_water=? WHERE id=1", (now,))
            tx = transaction_type(db, now, self._limits, self._resolve, write)
            value = callback(tx)
            # Returning a Failure must roll back too, not commit earlier writes.
            if isinstance(value, Failure):
                raise StoreFailure(value.error.code)
            db.commit()
            return Success(value)
        except StoreFailure as exc:
            return Failure(BoundaryError(exc.code))
        except sqlite3.IntegrityError:
            return Failure(BoundaryError(ErrorCode.DENIED))
        except sqlite3.Error as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 255
            return Failure(
                BoundaryError(
                    ErrorCode.BUSY if code in (5, 6) else ErrorCode.STORAGE_UNAVAILABLE
                )
            )
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return Failure(BoundaryError(ErrorCode.STORAGE_UNAVAILABLE))
        finally:
            if tx is not None:
                tx._active = False
            try:
                if db is not None:
                    try:
                        if db.in_transaction:
                            db.rollback()
                    finally:
                        db.close()
            finally:
                _PROCESS_CONNECTION.release()

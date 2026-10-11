"""E2 lab ledger schema, exclusive layout and in-memory binding table. LAB_ONLY.

CA-5: the lab ledger is a separate SQLite file with its own schema. The
ReceiptStore v1 schema and its exact-schema check are unchanged, and no
transaction spans the two stores. Every statement here is scoped by ``kd`` so
a row of one key is never read or written through another key's request.
Raw platform values never reach this module; only HMAC digests do.
"""

import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from binnacle.features.commands.job_awareness.models import (
    JobRef,
    OutputSnapshot,
    VerifiedPrincipal,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.session_route import KeyDigest

LAB_FILE = "ja-e2-lab.sqlite"
RECEIPT_FILE = "receipt.sqlite"
LAB_VERSION = 1
MIN_SQLITE = (3, 37, 0)
# Design §2.5 DDL (G3-01), stored without SQL comments so the exact-shape check
# compares statement text.
LAB_DDL = (
    """CREATE TABLE keys (
  kd     TEXT PRIMARY KEY CHECK (length(kd) = 98),
  epoch  TEXT NOT NULL CHECK (length(epoch) = 32),
  ns     TEXT NOT NULL UNIQUE CHECK (length(ns) = 36),
  state  TEXT NOT NULL CHECK (state IN ('ACTIVE','SUSPENDED'))
) STRICT""",
    """CREATE TABLE alloc (
  jobref          TEXT PRIMARY KEY CHECK (length(jobref) = 85),
  kd              TEXT NOT NULL REFERENCES keys(kd),
  slot            TEXT NOT NULL CHECK (length(slot) = 13),
  alloc_tag       TEXT NOT NULL UNIQUE CHECK (length(alloc_tag) = 32),
  snapshot_sha256 TEXT NULL CHECK (snapshot_sha256 IS NULL OR length(snapshot_sha256) = 64),
  grant_id        TEXT NULL CHECK (grant_id IS NULL OR length(grant_id) = 32),
  state           TEXT NOT NULL CHECK (state IN ('OWNED','GRANTED','LIVE','RETIRED','DENY_FOREVER')),
  created_ms      INTEGER NOT NULL,
  CHECK (state IN ('OWNED','DENY_FOREVER') OR (snapshot_sha256 IS NOT NULL AND grant_id IS NOT NULL))
) STRICT""",
    """CREATE TABLE emit (
  jobref         TEXT PRIMARY KEY REFERENCES alloc(jobref),
  kd             TEXT NOT NULL REFERENCES keys(kd),
  state          TEXT NOT NULL CHECK (state IN ('PENDING','RESERVED','EMITTED','ABORTED')),
  reservation_id TEXT NULL CHECK (reservation_id IS NULL OR length(reservation_id) = 32),
  reserved_ms    INTEGER NULL,
  final_ms       INTEGER NULL,
  version        INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
  CHECK ( (state = 'PENDING'  AND reservation_id IS NULL     AND reserved_ms IS NULL     AND final_ms IS NULL)
       OR (state = 'RESERVED' AND reservation_id IS NOT NULL AND reserved_ms IS NOT NULL AND final_ms IS NULL)
       OR (state IN ('EMITTED','ABORTED') AND final_ms IS NOT NULL) )
) STRICT""",
)
INSERT_EMIT = "INSERT INTO emit(jobref,kd,state) VALUES(:j,:kd,'PENDING')"
RESERVE = (
    "UPDATE emit SET state='RESERVED', reservation_id=:rid, reserved_ms=:now, "
    "version=version+1 WHERE jobref=:j AND kd=:kd AND state='PENDING' "
    "AND jobref IN (SELECT jobref FROM alloc WHERE kd=:kd AND state='LIVE')"
)
EMIT = (
    "UPDATE emit SET state='EMITTED', final_ms=:now, version=version+1 "
    "WHERE jobref=:j AND kd=:kd AND state='RESERVED' AND reservation_id=:rid"
)
RESET = (
    "UPDATE emit SET state='PENDING', reservation_id=NULL, reserved_ms=NULL, "
    "version=version+1 WHERE jobref=:j AND kd=:kd AND state='RESERVED' "
    "AND reservation_id=:rid"
)
ABORT = (
    "UPDATE emit SET state='ABORTED', final_ms=:now, version=version+1 "
    "WHERE jobref=:j AND kd=:kd AND state='RESERVED' AND reservation_id=:rid"
)
SWEEP_ALLOC = (
    "UPDATE alloc SET state='DENY_FOREVER' WHERE state!='RETIRED' "
    "AND kd IN (SELECT kd FROM keys WHERE epoch!=:epoch)"
)
SWEEP_EMIT = "UPDATE emit SET state='ABORTED',final_ms=:now WHERE state='RESERVED'"


class LabFailure(Exception):
    """Fixed, nonreflecting lab-ledger failure."""

    def __init__(self) -> None:
        super().__init__("lab ledger unavailable")


def _fail() -> LabFailure:
    return LabFailure()


def _exclusive_dir(path: Path, allowed: frozenset[str]) -> None:
    if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
        raise _fail()
    for entry in path.iterdir():
        if entry.name not in allowed or entry.is_symlink() or not entry.is_file():
            raise _fail()


def prepare_layout(phase_dir: Path) -> tuple[Path, Path]:
    """Create or check ``phase/{receipt,lab}/`` (0700, exclusive) (G3-05).

    Startup refuses any other entry, symlink or subdirectory in either one.
    """
    phase = Path(phase_dir)
    if phase.is_symlink():
        raise _fail()
    phase.mkdir(mode=0o700, exist_ok=True)
    if not phase.is_dir() or phase.stat().st_mode & 0o077:
        raise _fail()
    receipt, lab = phase / "receipt", phase / "lab"
    for directory, name in ((receipt, RECEIPT_FILE), (lab, LAB_FILE)):
        if not directory.is_symlink() and not directory.exists():
            directory.mkdir(mode=0o700)
        _exclusive_dir(directory, frozenset({name, name + "-journal"}))
    return receipt / RECEIPT_FILE, lab / LAB_FILE


class LabTx:
    """One open lab transaction. Statements are fixed and ``kd``-scoped."""

    def __init__(self, db: sqlite3.Connection, now_ms: int) -> None:
        self._db, self.now_ms = db, now_ms

    def _run(self, sql: str, params: Mapping[str, object]) -> int:
        return self._db.execute(sql, params).rowcount

    def _one(self, sql: str, params: Mapping[str, object]) -> None:
        if self._run(sql, params) != 1:
            raise _fail()

    def key_row(self, kd: str) -> tuple[str, str, str] | None:
        row = self._db.execute(
            "SELECT epoch,ns,state FROM keys WHERE kd=:kd", {"kd": kd}
        ).fetchone()
        return None if row is None else (row[0], row[1], row[2])

    def ensure_key(self, key: KeyDigest) -> str:
        """Insert or keep the key row; one stable namespace per key per phase."""
        row = self.key_row(key.kd)
        if row is not None:
            if row[0] != key.epoch:
                raise _fail()
            return row[1]
        ns = "ja1_" + secrets.token_hex(16)
        self._one(
            "INSERT INTO keys(kd,epoch,ns,state) VALUES(:kd,:epoch,:ns,'ACTIVE')",
            {"kd": key.kd, "epoch": key.epoch, "ns": ns},
        )
        return ns

    def counts(self, kd: str) -> tuple[int, int, int]:
        """(allocations of key, live allocations of key, allocations of phase)."""
        total, live = self._db.execute(
            "SELECT count(*), coalesce(sum(state NOT IN ('RETIRED','DENY_FOREVER')),0) "
            "FROM alloc WHERE kd=:kd",
            {"kd": kd},
        ).fetchone()
        phase = self._db.execute("SELECT count(*) FROM alloc").fetchone()[0]
        return int(total), int(live), int(phase)

    def insert_alloc(self, job: JobRef, kd: str, slot: str, alloc_tag: str) -> None:
        self._one(
            "INSERT INTO alloc(jobref,kd,slot,alloc_tag,state,created_ms) "
            "VALUES(:j,:kd,:slot,:tag,'OWNED',:now)",
            {
                "j": job.canonical_key,
                "kd": kd,
                "slot": slot,
                "tag": alloc_tag,
                "now": self.now_ms,
            },
        )

    def mark_granted(self, job: JobRef, kd: str, sha256: str, grant_id: str) -> None:
        params = {"j": job.canonical_key, "kd": kd, "sha": sha256, "g": grant_id}
        self._one(
            "UPDATE alloc SET state='GRANTED', snapshot_sha256=:sha, grant_id=:g "
            "WHERE jobref=:j AND kd=:kd AND state='OWNED'",
            params,
        )
        self.regrant_live(kd, grant_id)
        self._one(INSERT_EMIT, {"j": job.canonical_key, "kd": kd})

    def regrant_live(self, kd: str, grant_id: str) -> None:
        self._run(
            "UPDATE alloc SET grant_id=:g WHERE kd=:kd AND state='LIVE'",
            {"kd": kd, "g": grant_id},
        )

    def mark_live(self, job: JobRef, kd: str) -> None:
        self._one(
            "UPDATE alloc SET state='LIVE' WHERE jobref=:j AND kd=:kd "
            "AND state='GRANTED'",
            {"j": job.canonical_key, "kd": kd},
        )

    def deny(self, job: JobRef, kd: str) -> None:
        self._run(
            "UPDATE alloc SET state='DENY_FOREVER' WHERE jobref=:j AND kd=:kd "
            "AND state IN ('OWNED','GRANTED','LIVE')",
            {"j": job.canonical_key, "kd": kd},
        )

    def retire(self, job: JobRef, kd: str) -> None:
        self._one(
            "UPDATE alloc SET state='RETIRED' WHERE jobref=:j AND kd=:kd "
            "AND state='LIVE'",
            {"j": job.canonical_key, "kd": kd},
        )

    def suspend(self, kd: str) -> None:
        self._one("UPDATE keys SET state='SUSPENDED' WHERE kd=:kd", {"kd": kd})

    def serving(self, job: JobRef, kd: str) -> tuple[str, str, str] | None:
        """(alloc state, key epoch, key state); the row must belong to ``kd``."""
        row = self._db.execute(
            "SELECT a.state,k.epoch,k.state FROM alloc a JOIN keys k ON k.kd=a.kd "
            "WHERE a.jobref=:j AND a.kd=:kd",
            {"j": job.canonical_key, "kd": kd},
        ).fetchone()
        return None if row is None else (row[0], row[1], row[2])

    def pending_live(self, kd: str) -> frozenset[str]:
        rows = self._db.execute(
            "SELECT a.jobref FROM alloc a JOIN emit e ON e.jobref=a.jobref "
            "WHERE a.kd=:kd AND e.kd=:kd AND a.state='LIVE' AND e.state='PENDING'",
            {"kd": kd},
        ).fetchall()
        return frozenset(row[0] for row in rows)

    def emit_state(self, job: JobRef, kd: str) -> str | None:
        row = self._db.execute(
            "SELECT state FROM emit WHERE jobref=:j AND kd=:kd",
            {"j": job.canonical_key, "kd": kd},
        ).fetchone()
        return None if row is None else str(row[0])

    def transition(self, sql: str, job: JobRef, kd: str, rid: str) -> int:
        """One of RESERVE/EMIT/RESET/ABORT; the caller checks the rowcount."""
        if sql not in (RESERVE, EMIT, RESET, ABORT):
            raise _fail()
        params: dict[str, object] = {"j": job.canonical_key, "kd": kd, "rid": rid}
        if sql is not RESET:
            params["now"] = self.now_ms
        return self._run(sql, params)

    def sweep(self, epoch: str) -> None:
        """Cold start, before readiness: older epochs are DENY_FOREVER."""
        self._run(SWEEP_ALLOC, {"epoch": epoch})
        self._run(SWEEP_EMIT, {"now": self.now_ms})


class LabLedger:
    """``ja-e2-lab.sqlite`` with DELETE journal, FULL sync and FKs on.

    One connection and one ``BEGIN IMMEDIATE`` transaction per operation.
    ``fault`` is a test seam called inside each write before commit.
    """

    def __init__(
        self,
        path: Path,
        clock: Callable[[], int],
        *,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.path, self._clock, self._fault = Path(path), clock, fault
        self._lock = threading.Lock()

    def _exclusive(self) -> None:
        _exclusive_dir(
            self.path.parent, frozenset({self.path.name, self.path.name + "-journal"})
        )

    def _connect(self, create: bool) -> sqlite3.Connection:
        if self.path.is_symlink() or sqlite3.sqlite_version_info < MIN_SQLITE:
            raise _fail()
        self._exclusive()
        uri = self.path.absolute().as_uri() + "?mode=" + ("rwc" if create else "rw")
        db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0.05)
        try:
            db.execute("PRAGMA busy_timeout=50")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise _fail()
            return db
        except BaseException:
            db.close()
            raise

    @contextmanager
    def _transaction(
        self, op: str, *, write: bool, create: bool = False
    ) -> Iterator[LabTx]:
        if not self._lock.acquire(timeout=1.0):
            raise _fail()
        db: sqlite3.Connection | None = None
        try:
            db = self._connect(create)
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._check_shape(db, create)
            yield LabTx(db, int(self._clock()))
            if write and self._fault is not None:
                self._fault(op)
            db.commit()
        except LabFailure:
            raise
        except Exception:  # noqa: BLE001 - every ledger error is one fixed failure
            raise _fail() from None
        finally:
            try:
                if db is not None:
                    try:
                        if db.in_transaction:
                            db.rollback()
                    finally:
                        db.close()
            finally:
                self._lock.release()

    @staticmethod
    def _check_shape(db: sqlite3.Connection, create: bool) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        shape = {
            row[0]
            for row in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
        if create and version == 0 and not shape:
            for statement in LAB_DDL:
                db.execute(statement)
            db.execute(f"PRAGMA user_version={LAB_VERSION}")
        elif version != LAB_VERSION or shape != set(LAB_DDL):
            raise _fail()

    def initialize(self) -> None:
        """Create the exact schema, or verify it; unknown shape refuses."""
        with self._transaction("initialize", write=True, create=True):
            pass

    @contextmanager
    def write(self, op: str) -> Iterator[LabTx]:
        with self._transaction(op, write=True) as tx:
            yield tx

    @contextmanager
    def read(self) -> Iterator[LabTx]:
        with self._transaction("read", write=False) as tx:
            yield tx


@dataclass(eq=False)
class AllocationEntry:
    """In-memory published route for one LIVE allocation of one key.

    ``terminal`` is the controller's terminal point: only a terminal entry is
    hint-eligible. Memory only; a restart denies every allocation anyway.
    """

    job: JobRef
    slot: str
    snapshot: OutputSnapshot
    terminal: bool = True

    @property
    def handle(self) -> str:
        return "j_" + self.job.job_id


@dataclass(eq=False)
class KeyBinding:
    """Memory-only secrets for one key; lost on restart by design."""

    key: KeyDigest
    ns: str
    credential: bytes = field(repr=False)
    principal: VerifiedPrincipal = field(repr=False)
    capability: bytes | None = field(default=None, repr=False)
    grant: VerifiedRunGrant | None = field(default=None, repr=False)
    jobs: dict[JobRef, AllocationEntry] = field(default_factory=dict)
    suspended: bool = False


class SessionBindingTable:
    """kd -> KeyBinding. Owner scope: every lookup starts from the caller's kd."""

    def __init__(self) -> None:
        self._keys: dict[str, KeyBinding] = {}

    def get(self, kd: str) -> KeyBinding | None:
        return self._keys.get(kd)

    def add(self, binding: KeyBinding) -> None:
        if binding.key.kd in self._keys:
            raise _fail()
        self._keys[binding.key.kd] = binding

    def __len__(self) -> int:
        return len(self._keys)

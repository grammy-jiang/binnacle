"""E2 S2: lab ledger DDL, exact SQL, row counts and exclusive layout (§2.5/2.6)."""

import os
import sqlite3

import pytest

from binnacle.features.commands.job_awareness import session_binding as sb
from binnacle.features.commands.job_awareness.models import JobRef
from binnacle.features.commands.job_awareness.session_binding import (
    ABORT,
    EMIT,
    LAB_DDL,
    RESERVE,
    RESET,
    LabFailure,
    LabLedger,
    SessionBindingTable,
    prepare_layout,
)
from binnacle.features.commands.job_awareness.session_route import KeyDigest

KEY = KeyDigest("1" * 32, "2" * 32, "3" * 32)
OTHER = KeyDigest("1" * 32, "2" * 32, "4" * 32)
OLD = KeyDigest("9" * 32, "2" * 32, "3" * 32)
RID, RID2 = "a" * 32, "b" * 32


def job(index: int, ns: str = "ja1_" + "c" * 32) -> JobRef:
    return JobRef(ns, f"{index:012x}", "g1_" + f"{index:032x}")


@pytest.fixture
def ledger(tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir(mode=0o700)
    value = LabLedger(lab / sb.LAB_FILE, lambda: 1000)
    value.initialize()
    return value


def live(ledger: LabLedger, key: KeyDigest, index: int) -> JobRef:
    with ledger.write("t") as tx:
        ns = tx.ensure_key(key)
        item = job(index, ns)
        tx.insert_alloc(item, key.kd, "R3-SYN-JOB-01", f"{index:032x}")
        tx.mark_granted(item, key.kd, "e" * 64, "f" * 32)
        tx.mark_live(item, key.kd)
    return item


def emit_row(ledger: LabLedger, item: JobRef) -> tuple:
    db = sqlite3.connect(ledger.path)
    try:
        return db.execute(
            "SELECT kd,state,reservation_id,reserved_ms,final_ms,version FROM emit WHERE jobref=?",
            (item.canonical_key,),
        ).fetchone()
    finally:
        db.close()


def test_exact_strict_ddl_and_pragmas(ledger):
    db = sqlite3.connect(ledger.path)
    try:
        shape = {
            r[0]
            for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
        assert shape == set(LAB_DDL)
        assert all(s.endswith(") STRICT") for s in LAB_DDL)
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert db.execute("PRAGMA user_version").fetchone()[0] == sb.LAB_VERSION
    finally:
        db.close()
    ledger.initialize()  # idempotent on the exact shape


def test_strict_types_checks_and_foreign_keys(ledger):
    with ledger.write("t") as tx:
        ns = tx.ensure_key(KEY)
        assert tx.ensure_key(KEY) == ns  # one stable namespace per key
    bad = [
        (
            "INSERT INTO keys VALUES (?,?,?,?)",
            (KEY.kd[:-1], "1" * 32, "ja1_" + "0" * 32, "ACTIVE"),
        ),
        (
            "INSERT INTO keys VALUES (?,?,?,?)",
            (OTHER.kd, "1" * 32, "ja1_" + "0" * 32, "OTHER"),
        ),
        ("INSERT INTO keys VALUES (?,?,?,?)", (OTHER.kd, "1" * 32, ns, "ACTIVE")),
        (
            "INSERT INTO alloc VALUES (?,?,?,?,?,?,?,?)",
            (
                job(1).canonical_key,
                OTHER.kd,
                "R3-SYN-JOB-01",
                "0" * 32,
                None,
                None,
                "OWNED",
                1,
            ),
        ),
        (
            "INSERT INTO alloc VALUES (?,?,?,?,?,?,?,?)",
            (
                job(1).canonical_key,
                KEY.kd,
                "R3-SYN-JOB-01",
                "0" * 32,
                None,
                None,
                "LIVE",
                1,
            ),
        ),
        (
            "INSERT INTO alloc VALUES (?,?,?,?,?,?,?,?)",
            (
                job(1).canonical_key,
                KEY.kd,
                "R3-SYN-JOB-01",
                "0" * 32,
                None,
                None,
                "OWNED",
                "x",
            ),
        ),
        (
            "INSERT INTO emit(jobref,kd,state) VALUES (?,?,'PENDING')",
            (job(9).canonical_key, KEY.kd),
        ),
    ]
    db = sqlite3.connect(ledger.path)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        for sql, params in bad:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql, params)
    finally:
        db.close()


def test_emit_state_checks(ledger):
    item = live(ledger, KEY, 1)
    db = sqlite3.connect(ledger.path)
    try:
        for sql in (
            "UPDATE emit SET state='RESERVED' WHERE jobref=?",
            "UPDATE emit SET state='EMITTED' WHERE jobref=?",
            "UPDATE emit SET reservation_id='x' WHERE jobref=?",
            "UPDATE emit SET version=-1 WHERE jobref=?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql, (item.canonical_key,))
    finally:
        db.close()


def test_reserve_emit_reset_abort_row_counts(ledger):
    first, second = live(ledger, KEY, 1), live(ledger, KEY, 2)
    with ledger.write("t") as tx:
        assert tx.pending_live(KEY.kd) == {first.canonical_key, second.canonical_key}
        assert tx.transition(RESERVE, first, KEY.kd, RID) == 1
        assert tx.transition(RESERVE, first, KEY.kd, RID2) == 0  # only PENDING reserves
        assert tx.transition(RESERVE, second, OTHER.kd, RID) == 0  # kd-scoped
        assert tx.transition(EMIT, first, KEY.kd, RID2) == 0  # only the owning rid
        assert tx.transition(RESET, first, KEY.kd, RID2) == 0
        assert tx.transition(EMIT, first, KEY.kd, RID) == 1
        assert tx.transition(EMIT, first, KEY.kd, RID) == 0
        assert tx.transition(RESERVE, second, KEY.kd, RID2) == 1
        assert tx.transition(RESET, second, KEY.kd, RID2) == 1
        assert tx.transition(RESERVE, second, KEY.kd, RID) == 1
        assert tx.transition(ABORT, second, KEY.kd, RID) == 1
        assert tx.transition(RESERVE, second, KEY.kd, RID2) == 0  # ABORTED is final
        assert tx.emit_state(first, KEY.kd) == "EMITTED"
        assert tx.emit_state(first, OTHER.kd) is None
        assert tx.pending_live(KEY.kd) == frozenset()
        with pytest.raises(LabFailure):
            tx.transition("UPDATE emit SET state='EMITTED'", first, KEY.kd, RID)
    assert emit_row(ledger, first)[1:] == ("EMITTED", RID, 1000, 1000, 2)
    assert emit_row(ledger, second)[1:] == ("ABORTED", RID, 1000, 1000, 4)


def test_reserve_requires_live_allocation_of_the_same_key(ledger):
    item = live(ledger, KEY, 1)
    with ledger.write("t") as tx:
        tx.retire(item, KEY.kd)
        assert tx.transition(RESERVE, item, KEY.kd, RID) == 0
        assert tx.serving(item, KEY.kd) == ("RETIRED", KEY.epoch, "ACTIVE")
        assert tx.serving(item, OTHER.kd) is None


def test_inconsistent_emit_kd_is_never_reserved(ledger):
    """ADV-G4-02: an emit row whose kd differs from alloc.kd never reserves."""
    item = live(ledger, KEY, 1)
    with ledger.write("t") as tx:
        tx.ensure_key(OTHER)
    db = sqlite3.connect(ledger.path)
    try:
        db.execute(
            "UPDATE emit SET kd=? WHERE jobref=?", (OTHER.kd, item.canonical_key)
        )
        db.commit()
    finally:
        db.close()
    with ledger.write("t") as tx:
        assert tx.pending_live(KEY.kd) == frozenset()
        assert tx.pending_live(OTHER.kd) == frozenset()
        assert tx.transition(RESERVE, item, KEY.kd, RID) == 0
        assert tx.transition(RESERVE, item, OTHER.kd, RID) == 0


def test_cold_start_sweep(ledger):
    old_live = live(ledger, OLD, 1)
    with ledger.write("t") as tx:
        ns = tx.key_row(OLD.kd)[1]
        owned = job(2, ns)
        tx.insert_alloc(owned, OLD.kd, "R3-SYN-JOB-02", "2" * 32)
        retired = job(3, ns)
        tx.insert_alloc(retired, OLD.kd, "R3-SYN-JOB-03", "3" * 32)
        tx.mark_granted(retired, OLD.kd, "e" * 64, "f" * 32)
        tx.mark_live(retired, OLD.kd)
        tx.retire(retired, OLD.kd)
        assert tx.transition(RESERVE, old_live, OLD.kd, RID) == 1
    current = live(ledger, KEY, 4)
    with ledger.write("sweep") as tx:
        tx.sweep(KEY.epoch)
        states = {
            item: tx.serving(item, kd)[0]
            for item, kd in (
                (old_live, OLD.kd),
                (owned, OLD.kd),
                (retired, OLD.kd),
                (current, KEY.kd),
            )
        }
    assert states == {
        old_live: "DENY_FOREVER",
        owned: "DENY_FOREVER",
        retired: "RETIRED",
        current: "LIVE",
    }
    assert emit_row(ledger, old_live)[1] == "ABORTED"


def test_rowcount_mismatch_and_bad_key_epoch_fail(ledger):
    item = live(ledger, KEY, 1)
    for action in (
        lambda tx: tx.mark_live(item, KEY.kd),
        lambda tx: tx.retire(job(5), KEY.kd),
        lambda tx: tx.suspend(OTHER.kd),
        lambda tx: tx.mark_granted(item, KEY.kd, "e" * 64, "f" * 32),
        lambda tx: tx.insert_alloc(item, KEY.kd, "R3-SYN-JOB-01", "1" * 32),
    ):
        with pytest.raises(LabFailure), ledger.write("t") as tx:
            action(tx)
    assert emit_row(ledger, item)[1] == "PENDING"


def test_key_row_epoch_mismatch_fails(ledger):
    with ledger.write("t") as tx:
        tx.ensure_key(KEY)
    db = sqlite3.connect(ledger.path)
    try:
        db.execute("UPDATE keys SET epoch=? WHERE kd=?", ("8" * 32, KEY.kd))
        db.commit()
    finally:
        db.close()
    with pytest.raises(LabFailure), ledger.write("t") as tx:
        tx.ensure_key(KEY)


def test_counts_and_deny(ledger):
    first = live(ledger, KEY, 1)
    live(ledger, KEY, 2)
    live(ledger, OTHER, 3)
    with ledger.write("t") as tx:
        assert tx.counts(KEY.kd) == (2, 2, 3)
        tx.deny(first, KEY.kd)
        tx.deny(first, KEY.kd)  # idempotent
        assert tx.counts(KEY.kd) == (2, 1, 3)
        tx.suspend(KEY.kd)
        assert tx.key_row(KEY.kd)[2] == "SUSPENDED"


def test_fault_seam_rolls_back(tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir(mode=0o700)

    def fault(op: str) -> None:
        if op == "boom":
            raise RuntimeError("injected")

    ledger = LabLedger(lab / sb.LAB_FILE, lambda: 1000, fault=fault)
    ledger.initialize()
    with pytest.raises(LabFailure), ledger.write("boom") as tx:
        tx.ensure_key(KEY)
    with ledger.read() as tx:
        assert tx.key_row(KEY.kd) is None


def test_schema_drift_old_sqlite_and_symlink_refuse(tmp_path, monkeypatch):
    lab = tmp_path / "lab"
    lab.mkdir(mode=0o700)
    ledger = LabLedger(lab / sb.LAB_FILE, lambda: 1000)
    ledger.initialize()
    db = sqlite3.connect(ledger.path)
    db.execute("CREATE TABLE extra (x INTEGER)")
    db.commit()
    db.close()
    with pytest.raises(LabFailure):
        ledger.initialize()
    other = tmp_path / "lab2"
    other.mkdir(mode=0o700)
    monkeypatch.setattr(sb.sqlite3, "sqlite_version_info", (3, 36, 0))
    with pytest.raises(LabFailure):
        LabLedger(other / sb.LAB_FILE, lambda: 1000).initialize()
    monkeypatch.undo()
    linked = tmp_path / "lab3"
    linked.mkdir(mode=0o700)
    os.symlink(ledger.path, linked / sb.LAB_FILE)
    with pytest.raises(LabFailure):
        LabLedger(linked / sb.LAB_FILE, lambda: 1000).initialize()
    with pytest.raises(LabFailure), ledger.read():
        pass


def test_clock_failure_and_busy_lock(tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir(mode=0o700)

    def broken() -> int:
        raise RuntimeError("clock")

    ledger = LabLedger(lab / sb.LAB_FILE, broken)
    with pytest.raises(LabFailure):
        ledger.initialize()
    ok = LabLedger(lab / sb.LAB_FILE, lambda: 1000)
    ok.initialize()
    assert ok._lock.acquire()
    try:
        original = ok._lock

        class Busy:
            def acquire(self, timeout: float) -> bool:
                return False

        ok._lock = Busy()
        with pytest.raises(LabFailure), ok.read():
            pass
        ok._lock = original
    finally:
        original.release()


def test_prepare_layout_is_exclusive(tmp_path):
    phase = tmp_path / "phase-1"
    receipt, lab = prepare_layout(phase)
    assert receipt == phase / "receipt" / sb.RECEIPT_FILE
    assert lab == phase / "lab" / sb.LAB_FILE
    for path in (phase, phase / "receipt", phase / "lab"):
        assert path.stat().st_mode & 0o777 == 0o700
    (phase / "evidence.json").write_text("{}")  # the phase root may hold evidence
    assert prepare_layout(phase) == (receipt, lab)
    for directory, intruder in (
        ("receipt", "notes.txt"),
        ("lab", sb.RECEIPT_FILE),
        ("receipt", sb.LAB_FILE),
    ):
        path = phase / directory / intruder
        path.write_text("x")
        with pytest.raises(LabFailure):
            prepare_layout(phase)
        path.unlink()
    (phase / "lab" / "sub").mkdir()
    with pytest.raises(LabFailure):
        prepare_layout(phase)
    (phase / "lab" / "sub").rmdir()
    os.symlink(
        phase / "receipt" / "nowhere", phase / "lab" / (sb.LAB_FILE + "-journal")
    )
    with pytest.raises(LabFailure):
        prepare_layout(phase)
    os.unlink(phase / "lab" / (sb.LAB_FILE + "-journal"))
    (phase / "lab").chmod(0o750)
    with pytest.raises(LabFailure):
        prepare_layout(phase)
    (phase / "lab").chmod(0o700)
    assert prepare_layout(phase) == (receipt, lab)


def test_prepare_layout_refuses_symlinked_or_open_phase(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    os.symlink(real, tmp_path / "link")
    with pytest.raises(LabFailure):
        prepare_layout(tmp_path / "link")
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    with pytest.raises(LabFailure):
        prepare_layout(loose)
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    phase = tmp_path / "phase"
    phase.mkdir(mode=0o700)
    os.symlink(target, phase / "lab")
    with pytest.raises(LabFailure):
        prepare_layout(phase)


def test_binding_table_is_keyed_by_kd():
    table = SessionBindingTable()
    assert table.get(KEY.kd) is None and len(table) == 0

    class Principal:
        authority_handle = None

    binding = sb.KeyBinding(KEY, "ja1_" + "c" * 32, b"x" * 32, Principal())
    table.add(binding)
    assert table.get(KEY.kd) is binding and table.get(OTHER.kd) is None
    with pytest.raises(LabFailure):
        table.add(binding)
    assert "x" * 32 not in repr(binding)

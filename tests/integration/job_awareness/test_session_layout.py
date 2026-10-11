"""E2 S2: joint layout with the real ``ReceiptDatabase._reserve`` (G3-05).

``_reserve`` refuses a parent directory that holds anything except its own
file and ``-journal``. Each phase therefore uses exclusive ``receipt/`` and
``lab/`` directories. These tests run the real ReceiptStore v1, unchanged.
"""

import sqlite3

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    Success,
)
from binnacle.features.commands.job_awareness.receipt_schema import SCHEMA, VERSION
from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore
from binnacle.features.commands.job_awareness.session_binding import (
    LAB_FILE,
    RECEIPT_FILE,
)
from binnacle.features.commands.job_awareness.session_lab import LabError
from tests.unit.core.job_awareness.session_support import make_lab, scan_phase

QUOTA = Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED))


def entries(path):
    return sorted(p.name for p in path.iterdir())


def receipt_shape(path):
    db = sqlite3.connect(path)
    try:
        shape = {
            r[0]
            for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
        return shape, db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def test_joint_layout_writes_restart_and_exact_receipt_schema(tmp_path):
    phase = tmp_path / "phase-1"
    lab = make_lab(phase)
    handle = lab.start("A", "R3-SYN-JOB-01")
    assert isinstance(handle, str)
    assert entries(phase) == ["lab", "receipt"]
    assert entries(phase / "receipt") == [RECEIPT_FILE]
    assert entries(phase / "lab") == [LAB_FILE]
    assert receipt_shape(phase / "receipt" / RECEIPT_FILE) == (set(SCHEMA), VERSION)
    store = ReceiptStore(
        phase / "receipt" / RECEIPT_FILE, clock=lambda: lab.clock.wall_ms
    )
    assert store.initialize() == Success(None)  # exact-schema check passes
    restarted = make_lab(phase, clock=lab.clock)
    second = restarted.start("A", "R3-SYN-JOB-02")
    assert isinstance(second, str)
    assert (
        serving.read_page(restarted.lab, restarted.outcome("A"), handle, 0)
        is LabError.DENIED
    )
    assert isinstance(
        serving.read_page(restarted.lab, restarted.outcome("A"), second, 0), dict
    )
    assert entries(phase / "receipt") == [RECEIPT_FILE]
    assert entries(phase / "lab") == [LAB_FILE]
    assert receipt_shape(phase / "receipt" / RECEIPT_FILE) == (set(SCHEMA), VERSION)
    assert scan_phase(phase, lab.events + restarted.events) == []


def test_stray_file_in_receipt_dir_is_quota_exceeded_and_refuses_startup(tmp_path):
    phase = tmp_path / "phase-1"
    lab = make_lab(phase)
    assert isinstance(lab.start("A", "R3-SYN-JOB-01"), str)
    stray = phase / "receipt" / "notes.txt"
    stray.write_text("evidence does not belong here")
    # The real _reserve refuses every ReceiptStore write.
    assert lab.lab.authority.store.controller_transaction(lambda tx: None) == QUOTA
    assert lab.start("A", "R3-SYN-JOB-02") is LabError.DENIED
    assert lab.rows("SELECT state FROM alloc WHERE slot='R3-SYN-JOB-02'") == [
        ("DENY_FOREVER",)
    ]
    refused = make_lab(phase, clock=lab.clock, start=False)
    assert refused.lab.start() is False
    stray.unlink()
    assert make_lab(phase, clock=lab.clock).lab.ready


def test_lab_file_in_receipt_dir_is_refused(tmp_path):
    phase = tmp_path / "phase-1"
    lab = make_lab(phase)
    misplaced = phase / "receipt" / LAB_FILE
    misplaced.write_bytes(b"")
    assert lab.lab.authority.store.controller_transaction(lambda tx: None) == QUOTA
    assert make_lab(phase, clock=lab.clock, start=False).lab.start() is False


def test_flat_layout_negative_control(tmp_path):
    """Both files in one directory: the unchanged _reserve refuses writes."""
    flat = tmp_path / "flat"
    flat.mkdir(mode=0o700)
    store = ReceiptStore(flat / RECEIPT_FILE, clock=lambda: 1000)
    assert store.initialize() == Success(None)
    (flat / LAB_FILE).write_bytes(b"")
    assert store.controller_transaction(lambda tx: None) == QUOTA


def test_stray_entry_in_lab_dir_refuses_ledger_and_startup(tmp_path):
    phase = tmp_path / "phase-1"
    lab = make_lab(phase)
    assert isinstance(lab.start("A", "R3-SYN-JOB-01"), str)
    (phase / "lab" / "tap.jsonl").write_text("{}")
    assert lab.start("A", "R3-SYN-JOB-02") is LabError.DENIED
    assert (
        serving.read_page(lab.lab, lab.outcome("A"), "R3-SYN-JOB-01", 0)
        is LabError.DENIED
    )
    assert make_lab(phase, clock=lab.clock, start=False).lab.start() is False

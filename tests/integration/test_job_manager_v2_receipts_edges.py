"""Fail-closed edge cases of the v2 start-receipt store, driven directly.

Every test points ``jobs.JOBS_DIR`` at a private ``tmp_path`` store, so the
receipt directory is a disposable sibling and no Manager process is started.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from binnacle.features.commands import job_manager_v2_receipts as receipts
from binnacle.features.commands import jobs
from tests.integration.test_job_manager_v2 import _request

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY

_JOB_ID = "0123456789ab"


@pytest.fixture()
def store(tmp_path: Path, monkeypatch) -> Path:
    """An isolated, not-yet-created jobs store under tmp_path."""
    path = tmp_path / "store"
    monkeypatch.setattr(jobs, "JOBS_DIR", path)
    return path


def _payload(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    return _request(tmp_path / "allowed", **changes)


def _receipt_file(store: Path, payload: dict[str, Any]) -> Path:
    return store.parent / "v2-start-receipts" / receipts.receipt_key(payload["call_id"])


def _write_receipt(store: Path, payload: dict[str, Any], record: Any) -> Path:
    """Place a raw private receipt record, as a crashed owner could leave it."""
    folder = store.parent / "v2-start-receipts"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = _receipt_file(store, payload)
    path.write_bytes(
        record if isinstance(record, bytes) else json.dumps(record).encode()
    )
    path.chmod(0o600)
    return path


def _write_job_meta(
    store: Path, job_id: str, payload: dict[str, Any], **changes: Any
) -> None:
    """Persist a complete, already-exited job record carrying the v2 identity."""
    (store / job_id).mkdir(parents=True)
    meta = {
        "command": payload["command"],
        "workdir": payload["workdir"],
        "pid": 1,
        "started_at": 1.0,
        "ended_at": 2.0,
        "exit_code": 0,
        "call_id": payload["call_id"],
        "v2_request_fingerprint": receipts.payload_digest(payload),
    }
    meta.update(changes)
    jobs._write_meta(job_id, meta)


class _ZeroWriteOs:
    """Proxy of ``os`` whose ``write`` reports a zero-byte write."""

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    @staticmethod
    def write(_fd: int, _data: Any) -> int:
        return 0


def _stray_temps(store: Path) -> list[str]:
    folder = store.parent / "v2-start-receipts"
    return [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_lookup_without_any_reservation_refuses(store, tmp_path):
    """A missing receipt never authorizes a replay."""
    with pytest.raises(receipts.ReceiptFailure, match="missing or payload changed"):
        receipts.lookup(_payload(tmp_path))
    assert (store.parent / "v2-start-receipts").is_dir()


def test_accepted_without_reservation_refuses(store, tmp_path):
    with pytest.raises(receipts.ReceiptFailure, match="reservation disappeared"):
        receipts.accepted(_payload(tmp_path), _JOB_ID)
    assert list((store.parent / "v2-start-receipts").iterdir()) == []


def test_receipt_directory_with_group_access_is_refused(store, tmp_path):
    """A receipt directory readable by others is never trusted."""
    folder = store.parent / "v2-start-receipts"
    folder.mkdir(mode=0o700)
    folder.chmod(0o750)
    with pytest.raises(receipts.ReceiptFailure, match="not private or changed"):
        receipts.reserve(_payload(tmp_path))
    assert list(folder.iterdir()) == []


def test_receipt_record_readable_by_others_is_unsafe(store, tmp_path):
    payload = _payload(tmp_path)
    assert receipts.reserve(payload)[0] is True
    _receipt_file(store, payload).chmod(0o644)
    with pytest.raises(receipts.ReceiptFailure, match="record unsafe"):
        receipts.lookup(payload)


@pytest.mark.parametrize(
    "record",
    [
        ["not", "a", "mapping"],
        {"version": 1, "state": "pending"},
    ],
    ids=["non-dict", "wrong-version"],
)
def test_receipt_record_with_invalid_shape_is_refused(store, tmp_path, record):
    payload = _payload(tmp_path)
    _write_receipt(store, payload, record)
    with pytest.raises(receipts.ReceiptFailure, match="record invalid") as info:
        receipts.lookup(payload)
    assert not isinstance(info.value, receipts.ReceiptNotReady)


def test_receipt_record_with_unknown_state_is_refused(store, tmp_path):
    payload = _payload(tmp_path)
    fingerprint = receipts.payload_digest(payload)
    _write_receipt(
        store, payload, {"version": 2, "state": "done", "fingerprint": fingerprint}
    )
    with pytest.raises(receipts.ReceiptFailure, match="state unknown"):
        receipts.accepted(payload, _JOB_ID)


@pytest.mark.parametrize("job_id", [None, 12345, "short"])
def test_accepted_receipt_without_valid_job_id_refuses_lookup(store, tmp_path, job_id):
    payload = _payload(tmp_path)
    record = {
        "version": 2,
        "state": "accepted",
        "fingerprint": receipts.payload_digest(payload),
    }
    if job_id is not None:
        record["job_id"] = job_id
    _write_receipt(store, payload, record)
    with pytest.raises(receipts.ReceiptFailure, match="lacks a job ID"):
        receipts.lookup(payload)


def test_accepted_receipt_for_unknown_job_replays_unknown_state(store, tmp_path):
    """An acknowledged receipt whose job spool is gone still replays, never reruns."""
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    receipts.accepted(payload, _JOB_ID)
    reply = receipts.lookup(payload)
    assert reply["job_id"] == _JOB_ID
    assert reply["state"] == "unknown"
    assert reply["replayed"] is True


def test_oversized_receipt_record_is_refused_and_reservation_kept(store, tmp_path):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    with pytest.raises(receipts.ReceiptFailure, match="too large"):
        receipts.accepted(payload, "x" * (receipts._MAX_RECORD_BYTES + 1))
    record = json.loads(_receipt_file(store, payload).read_bytes())
    assert record["state"] == "pending"
    assert _stray_temps(store) == []


def test_accepted_with_other_job_id_after_acceptance_refuses(store, tmp_path):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    receipts.accepted(payload, _JOB_ID)
    receipts.accepted(payload, _JOB_ID)  # identical retry is a no-op
    with pytest.raises(receipts.ReceiptFailure, match="state changed during start"):
        receipts.accepted(payload, "ba9876543210")
    record = json.loads(_receipt_file(store, payload).read_bytes())
    assert record["job_id"] == _JOB_ID


def test_zero_byte_write_on_replace_removes_temp_and_keeps_pending(
    store, tmp_path, monkeypatch
):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    monkeypatch.setattr(receipts, "os", _ZeroWriteOs())
    with pytest.raises(OSError, match="zero-byte write"):
        receipts.accepted(payload, _JOB_ID)
    monkeypatch.setattr(receipts, "os", os)
    assert _stray_temps(store) == []
    record = json.loads(_receipt_file(store, payload).read_bytes())
    assert record["state"] == "pending"


def test_zero_byte_write_on_create_retains_reservation(store, tmp_path, monkeypatch):
    """A failed fresh reservation keeps its key: the call_id is never freed."""
    payload = _payload(tmp_path)
    monkeypatch.setattr(receipts, "os", _ZeroWriteOs())
    with pytest.raises(OSError, match="zero-byte write"):
        receipts.reserve(payload)
    monkeypatch.setattr(receipts, "os", os)
    assert _receipt_file(store, payload).read_bytes() == b""
    with pytest.raises(receipts.ReceiptNotReady):
        receipts.reserve(payload)


def test_reconciliation_skips_files_symlinks_and_unrelated_jobs(store, tmp_path):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    store.mkdir()
    (store / "stray-file").write_text("not a job\n")
    (store / "000000000000").mkdir()  # no metadata at all
    _write_job_meta(store, "111111111111", payload, call_id="another-call")
    _write_job_meta(store, _JOB_ID, payload)
    (store / "222222222222").symlink_to(store / _JOB_ID, target_is_directory=True)
    reply = receipts.lookup(payload)
    assert reply == {
        "version": 2,
        "ok": True,
        "workdir_fd_accepted": True,
        "job_id": _JOB_ID,
        "state": "exited",
        "replayed": True,
    }
    record = json.loads(_receipt_file(store, payload).read_bytes())
    assert record["state"] == "accepted"
    assert record["job_id"] == _JOB_ID


def test_pending_receipt_with_two_matching_jobs_stays_unknown(store, tmp_path):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    _write_job_meta(store, _JOB_ID, payload)
    _write_job_meta(store, "ba9876543210", payload)
    assert receipts.lookup(payload) == {
        "version": 2,
        "ok": False,
        "error": "v2_start_outcome_unknown",
    }
    assert json.loads(_receipt_file(store, payload).read_bytes())["state"] == "pending"


def test_reconciliation_refuses_receipt_changed_concurrently(
    store, tmp_path, monkeypatch
):
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    _write_job_meta(store, _JOB_ID, payload)
    original = jobs._read_meta

    def read_meta_and_rewrite_receipt(job_id: str):
        _write_receipt(
            store,
            payload,
            {"version": 2, "state": "pending", "fingerprint": "f" * 64},
        )
        return original(job_id)

    monkeypatch.setattr(jobs, "_read_meta", read_meta_and_rewrite_receipt)
    with pytest.raises(receipts.ReceiptFailure, match="changed during reconciliation"):
        receipts.lookup(payload)
    record = json.loads(_receipt_file(store, payload).read_bytes())
    assert record["fingerprint"] == "f" * 64


def test_reconciliation_keeps_receipt_accepted_concurrently(
    store, tmp_path, monkeypatch
):
    """A concurrent ack is not overwritten; the replay still reports the job."""
    payload = _payload(tmp_path)
    receipts.reserve(payload)
    _write_job_meta(store, _JOB_ID, payload)
    original = jobs._read_meta
    acked = {
        "version": 2,
        "state": "accepted",
        "fingerprint": receipts.payload_digest(payload),
        "job_id": _JOB_ID,
        "note": "concurrent-ack",
    }

    def read_meta_and_ack(job_id: str):
        _write_receipt(store, payload, acked)
        return original(job_id)

    monkeypatch.setattr(jobs, "_read_meta", read_meta_and_ack)
    reply = receipts.lookup(payload)
    assert reply["job_id"] == _JOB_ID
    assert reply["state"] == "exited"
    assert json.loads(_receipt_file(store, payload).read_bytes()) == acked

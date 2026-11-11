"""Edge cases of the Manager v2 start-admission fence, called in-process.

These tests call `job_manager_v2_drain` directly against a private
`tmp_path` job store. The kernel cgroup root is redirected to a fake tree
under `tmp_path`; no real cgroup, systemd unit or Manager socket is used.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.features.commands import job_manager_v2_drain as drain
from binnacle.features.commands import job_manager_v2_receipts as receipts
from binnacle.features.commands import jobs
from tests.integration.test_job_manager_v2 import _request

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY

_NONCE = "1234567890abcdef1234567890abcdef"
_OTHER = "ffffffffffffffffffffffffffffffff"
_JOB_A = "job-0123456789ab"
_JOB_B = "job-ba9876543210"


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Path:
    """Private job store; the receipts folder is its sibling."""
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    path = tmp_path / "jobs"
    path.mkdir(mode=0o700)
    monkeypatch.setattr(jobs, "JOBS_DIR", path)
    return path


@pytest.fixture
def cgroup_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect the module's `/sys/fs/cgroup` root to a fake tree."""
    fake = tmp_path / "cgroupfs"
    fake.mkdir()

    def fake_path(*parts: str) -> Path:
        if parts == ("/sys/fs/cgroup",):
            return fake
        return Path(*parts)

    monkeypatch.setattr(drain, "Path", fake_path)
    return fake


def _marker(store: Path) -> Path:
    return store.parent / "v2-start-receipts" / drain._MARKER


def _write_marker(store: Path, raw: bytes) -> Path:
    folder = store.parent / "v2-start-receipts"
    folder.mkdir(mode=0o700, exist_ok=True)
    marker = folder / drain._MARKER
    marker.write_bytes(raw)
    marker.chmod(0o600)
    return marker


def _owner(monkeypatch, current: str | None, subgroup: str = "manager") -> None:
    accounting = SimpleNamespace(owner_cgroup=lambda: (current, subgroup))
    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", accounting)


def _service(root: Path, owner_pids: str, root_pids: str = "") -> Path:
    """Build `<root>/svc/{cgroup.procs,manager/cgroup.procs}`."""
    unit = root / "svc"
    (unit / "manager").mkdir(parents=True)
    (unit / "manager" / "cgroup.procs").write_text(owner_pids)
    (unit / "cgroup.procs").write_text(root_pids)
    return unit


def _job_group(unit: Path, name: str, events: str) -> None:
    (unit / name).mkdir()
    (unit / name / "cgroup.events").write_text(events)


# --- marker parsing ----------------------------------------------------------


@pytest.mark.parametrize("raw", [b"not json", b"\xff\xfe\x00garbage"])
def test_corrupt_marker_blocks_starts(store: Path, raw: bytes) -> None:
    _write_marker(store, raw)
    with pytest.raises(drain.DrainRefused, match="maintenance marker corrupt"):
        drain.require_starts_allowed()


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"version": 2},
        {"version": 1, "nonce_hash": "a" * 64},
        {"version": 2, "nonce_hash": 7},
        {"version": 2, "nonce_hash": "abc"},
        {"version": 2, "nonce_hash": "a" * 64, "extra": True},
    ],
)
def test_wrong_marker_shape_blocks_starts(store: Path, body: object) -> None:
    _write_marker(store, json.dumps(body).encode())
    with pytest.raises(drain.DrainRefused, match="maintenance marker invalid"):
        drain.require_starts_allowed()


def test_well_formed_marker_blocks_starts_and_absence_allows(store: Path) -> None:
    drain.require_starts_allowed()  # no marker: no refusal
    _write_marker(store, json.dumps({"version": 2, "nonce_hash": "b" * 64}).encode())
    with pytest.raises(drain.DrainRefused, match="job_manager_starts_paused"):
        drain.require_starts_allowed()


# --- pause / resume nonce handling ------------------------------------------


def test_pause_with_different_nonce_is_refused_and_keeps_marker(
    store: Path, monkeypatch
) -> None:
    monkeypatch.setattr(drain, "_owner_cgroup_safety", lambda: (False, []))
    assert drain.pause(_NONCE)["starts_paused"] is True
    before = _marker(store).read_bytes()
    with pytest.raises(drain.DrainRefused, match="different nonce"):
        drain.pause(_OTHER)
    assert _marker(store).read_bytes() == before
    with pytest.raises(drain.DrainRefused, match="unknown maintenance nonce"):
        drain.resume(_OTHER)
    assert drain.resume(_NONCE) == {"version": 2, "ok": True, "starts_paused": False}
    assert not _marker(store).exists()


def test_partial_marker_write_is_refused_and_fails_closed(
    store: Path, monkeypatch
) -> None:
    real_write = os.write

    def short_write(fd: int, data: bytes) -> int:
        if bytes(data).startswith(b'{"version":2'):
            return real_write(fd, bytes(data)[:5])
        return real_write(fd, data)

    with monkeypatch.context() as patch:
        patch.setattr(drain.os, "write", short_write)
        with pytest.raises(drain.DrainRefused, match="partial maintenance marker"):
            drain.pause(_NONCE)
    # The truncated marker stays on disk: starts remain fenced (fail closed).
    assert _marker(store).read_bytes() == b'{"ver'
    with pytest.raises(drain.DrainRefused, match="maintenance marker corrupt"):
        drain.require_starts_allowed()
    with pytest.raises(drain.DrainRefused, match="maintenance marker corrupt"):
        drain.resume(_NONCE)


def test_verified_owner_with_no_work_is_safe_to_stop(store: Path, monkeypatch) -> None:
    monkeypatch.setattr(drain, "_owner_cgroup_safety", lambda: (True, []))
    result = drain.pause(_NONCE)
    assert result["safe_to_stop"] is True
    assert result["owner_cgroup_verified"] is True
    assert result["active_jobs"] == [] and result["pending_receipts"] == 0


# --- completed-job cgroup inventory -----------------------------------------


def test_completed_job_cgroups_are_inspected(
    store: Path, cgroup_root: Path, monkeypatch
) -> None:
    busy = cgroup_root / "busy"
    busy.mkdir()
    (busy / "cgroup.procs").write_text("4242\n")
    idle = cgroup_root / "idle"
    idle.mkdir()
    (idle / "cgroup.procs").write_text("\n")
    (cgroup_root / "noprocs").mkdir()  # exists, but cgroup.procs unreadable
    items = [
        {"job_id": "a" * 12, "state": "exited", "cgroup": "/busy"},
        {"job_id": "b" * 12, "state": "exited", "cgroup": "/idle"},
        {"job_id": "c" * 12, "state": "exited", "cgroup": "/noprocs"},
        {"job_id": "d" * 12, "state": "exited", "cgroup": "/gone"},
        {"job_id": "e" * 12, "state": "exited", "cgroup": "/x/../busy"},
        {"job_id": "f" * 12, "state": "exited", "cgroup": "busy"},
        {"job_id": "0" * 12, "state": "exited", "cgroup": None},
        {"job_id": "1" * 12, "state": "exited"},
    ]
    monkeypatch.setattr(jobs, "list_jobs", lambda: items)
    monkeypatch.setattr(drain, "_owner_cgroup_safety", lambda: (True, []))
    result = drain.pause(_NONCE)
    assert result["active_jobs"] == [
        {"job_id": "a" * 12, "state": "descendants_running"},
        {"job_id": "c" * 12, "state": "cgroup_unverified"},
    ]
    assert result["safe_to_stop"] is False


# --- pending receipt reconciliation -----------------------------------------


@pytest.mark.parametrize(
    ("metas", "expected"),
    [
        ([None, {"v2_receipt_key": "x"}], 1),  # no matching metadata
        (["match", {"v2_request_fingerprint": "y"}], 0),  # exactly one link
        (["match", "match"], 1),  # two links are still ambiguous
    ],
)
def test_pending_receipt_needs_exactly_one_matching_job(
    store: Path, tmp_path: Path, monkeypatch, metas: list, expected: int
) -> None:
    payload = _request(tmp_path, call_id="pending-edge")
    is_new, fingerprint = receipts.reserve(payload)
    assert is_new
    key = receipts.receipt_key("pending-edge")
    match = {"v2_receipt_key": key, "v2_request_fingerprint": fingerprint}
    table = {
        f"{index:012d}": (match if meta == "match" else meta)
        for index, meta in enumerate(metas)
    }
    items = [{"job_id": job_id, "state": "exited"} for job_id in table]
    monkeypatch.setattr(jobs, "list_jobs", lambda: items)
    monkeypatch.setattr(jobs, "_read_meta", table.get)
    monkeypatch.setattr(drain, "_owner_cgroup_safety", lambda: (True, []))
    # A non-receipt file in the folder is ignored by the scan.
    (store.parent / "v2-start-receipts" / "notes.txt").write_text("x")
    result = drain.pause(_NONCE)
    assert result["pending_receipts"] == expected
    assert result["safe_to_stop"] is (expected == 0)


# --- owner cgroup safety -----------------------------------------------------


def test_owner_cgroup_inside_a_job_cgroup_is_unverified(monkeypatch) -> None:
    monkeypatch.setenv("INVOCATION_ID", "inherited-from-parent-job")
    _owner(monkeypatch, f"/svc/{_JOB_A}")
    assert drain._owner_cgroup_safety() == (False, [])


@pytest.mark.parametrize("variable", ["INVOCATION_ID", "NOTIFY_SOCKET"])
def test_systemd_without_owner_subgroup_blocks_stop(monkeypatch, variable) -> None:
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setenv(variable, "set-by-systemd")
    _owner(monkeypatch, "/svc/other")
    assert drain._owner_cgroup_safety() == (
        False,
        [{"job_id": "-", "state": "owner_cgroup_unverified"}],
    )


def test_missing_owner_cgroup_api_is_unverified(monkeypatch) -> None:
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", SimpleNamespace())
    assert drain._owner_cgroup_safety() == (False, [])


def test_clean_owner_cgroup_reports_only_unsafe_subgroups(
    cgroup_root: Path, monkeypatch
) -> None:
    unit = _service(cgroup_root, f"{os.getpid()}\n")
    (unit / "memory.max").write_text("max\n")  # control file, not a group
    _job_group(unit, _JOB_A, "populated 1\nfrozen 0\n")
    _job_group(unit, _JOB_B, "populated 0\nfrozen 0\n")
    (unit / "stray").mkdir()
    _owner(monkeypatch, "/svc/manager")
    verified, blocked = drain._owner_cgroup_safety()
    assert verified is True
    assert sorted(blocked, key=lambda row: row["state"]) == [
        {"job_id": _JOB_A[4:], "state": "job_cgroup_populated"},
        {"job_id": "-", "state": "unexpected_owner_cgroup"},
    ]


def test_empty_owner_cgroup_is_verified_and_clean(
    cgroup_root: Path, monkeypatch
) -> None:
    unit = _service(cgroup_root, f"{os.getpid()}\n")
    _job_group(unit, _JOB_B, "populated 0\n")
    _owner(monkeypatch, "/svc/manager")
    assert drain._owner_cgroup_safety() == (True, [])


@pytest.mark.parametrize(
    ("owner_pids", "root_pids", "state"),
    [
        ("{pid}\n1\n", "", "owner_subgroup_has_other_processes"),
        ("", "", "owner_subgroup_has_other_processes"),
        ("{pid}\n", "77\n", "service_root_has_processes"),
    ],
)
def test_foreign_processes_block_owner_cgroup(
    cgroup_root: Path, monkeypatch, owner_pids: str, root_pids: str, state: str
) -> None:
    _service(cgroup_root, owner_pids.format(pid=os.getpid()), root_pids)
    _owner(monkeypatch, "/svc/manager")
    assert drain._owner_cgroup_safety() == (False, [{"job_id": "-", "state": state}])


def test_unreadable_owner_cgroup_scan_fails_closed(
    cgroup_root: Path, monkeypatch
) -> None:
    (cgroup_root / "svc" / "manager").mkdir(parents=True)  # no cgroup.procs
    _owner(monkeypatch, "/svc/manager")
    failed = (False, [{"job_id": "-", "state": "owner_cgroup_scan_failed"}])
    assert drain._owner_cgroup_safety() == failed


def test_malformed_job_events_scan_fails_closed(cgroup_root: Path, monkeypatch) -> None:
    unit = _service(cgroup_root, f"{os.getpid()}\n")
    _job_group(unit, _JOB_A, "populated \n")  # one token only: ValueError
    _owner(monkeypatch, "/svc/manager")
    assert drain._owner_cgroup_safety() == (
        False,
        [{"job_id": "-", "state": "owner_cgroup_scan_failed"}],
    )

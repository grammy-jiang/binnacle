"""SIGKILL the synthetic controller; independent guardian restores test writer."""

from __future__ import annotations

import bz2
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from binnacle.platform.darwin.log_maintenance_transaction import JournalSnapshot

NONCE = "a" * 32
RAW = "mcp.stderr.log.0"


@pytest.fixture
def fixture(tmp_path: Path):
    if sys.platform != "linux":
        pytest.skip("independent Linux /proc fixture worker qualification")
    base = tmp_path / ("issue30-fixture-e2e-" + NONCE)
    yield base
    if base.exists():
        (base / "guardian-worker.stop").touch(exist_ok=True)
        # The recovered test worker has its own bounded 20s timeout.


def _wait_outcome(root: Path) -> dict:
    path = root / "guardian-outcome.json"
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_bytes())
        time.sleep(0.03)
    pytest.fail("independent guardian did not recover before fixture deadline")


def _run_crash(root: Path, mode: str) -> tuple[dict, JournalSnapshot]:
    cmd = [
        sys.executable,
        "-m",
        "tests.issue30_e2e_controller_crash_fixture",
        str(root),
        mode,
    ]
    controller = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=14,
        check=False,
    )
    assert controller.returncode == -signal.SIGKILL, (
        controller.returncode,
        controller.stdout,
        controller.stderr,
    )
    result = _wait_outcome(root)
    state = inspect_unowned_transaction(root / ("txn-" + NONCE))
    assert state.needs_external_recovery
    assert state.producer_may_be_stopped
    assert not state.production_authorized
    return result, state


def _live_guardian_worker(outcome: dict, root: Path) -> None:
    assert outcome["state"] == "restarted"
    pid = outcome["pid"]
    assert type(pid) is int and pid > 0
    active = root / "private-logs/mcp.stderr.log"
    assert active.read_bytes() == b"e2e-fixture-generation guardian-active\n"
    assert active.stat().st_uid == os.getuid()
    try:
        os.kill(pid, 0)  # verify only the PID reported by our fixture guardian
    except ProcessLookupError:
        pytest.fail("recovery worker was not alive when guardian ACKed")


def test_sigkill_after_writer_closed_restores_independent_test_worker(
    fixture: Path,
) -> None:
    outcome, state = _run_crash(fixture, "after-stop")
    assert state.phase == "guardian_armed"
    raw = fixture / "private-logs" / RAW
    assert raw.read_bytes() == b"e2e-fixture-generation raw\n"
    assert not (fixture / "private-logs" / (RAW + ".bz2")).exists()
    _live_guardian_worker(outcome, fixture)


def test_sigkill_after_canonical_verified_keeps_both_inodes_and_restores(
    fixture: Path,
) -> None:
    outcome, state = _run_crash(fixture, "after-canonical")
    assert state.phase == "canonical_verified"
    raw = fixture / "private-logs" / RAW
    canonical = fixture / "private-logs" / (RAW + ".bz2")
    assert raw.exists() and canonical.exists()
    assert bz2.decompress(canonical.read_bytes()) == raw.read_bytes()
    _live_guardian_worker(outcome, fixture)


def test_sigkill_after_raw_unlink_never_claims_raw_pruned_journal_receipt(
    fixture: Path,
) -> None:
    outcome, state = _run_crash(fixture, "after-raw-unlink")
    assert state.phase == "canonical_verified"
    assert dict(state.receipts).get("raw_pruned") is None
    raw = fixture / "private-logs" / RAW
    canonical = fixture / "private-logs" / (RAW + ".bz2")
    assert not raw.exists()
    assert bz2.decompress(canonical.read_bytes()) == b"e2e-fixture-generation raw\n"
    _live_guardian_worker(outcome, fixture)


def test_sigkill_after_new_writer_restored_checks_liveness_not_just_receipt(
    fixture: Path,
) -> None:
    outcome, state = _run_crash(fixture, "after-restored")
    assert state.phase == "producer_restored"
    assert state.needs_external_recovery
    assert state.producer_may_be_stopped
    raw = fixture / "private-logs" / RAW
    canonical = fixture / "private-logs" / (RAW + ".bz2")
    assert not raw.exists()
    assert bz2.decompress(canonical.read_bytes()) == b"e2e-fixture-generation raw\n"
    assert outcome["state"] == "restarted"
    active = fixture / "private-logs/mcp.stderr.log"
    content = active.read_bytes()
    assert content.count(b"e2e-fixture-generation active\n") == 1
    assert content.count(b"e2e-fixture-generation guardian-active\n") == 1
    pid = outcome["pid"]
    assert isinstance(pid, int) and pid > 0
    os.kill(pid, 0)

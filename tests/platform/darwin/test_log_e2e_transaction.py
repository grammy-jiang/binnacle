"""Full disposable Binnacle log transaction: gate, real archive and recovery."""

from __future__ import annotations

import bz2
import sys
from pathlib import Path

import pytest

from binnacle.companions.darwin_log_j7_interlocks import J7Interlocks
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain, ToolAdmissionPaused
from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from tests.issue30_full_transaction_fixture import (
    FixtureProducer,
    RehearsalRefused,
    _guardian_outcome,
    run_complete_fixture_transaction,
    setup_fixture,
)
from tests.platform.darwin.test_job_manager_maintenance_fence import (
    _launch,
    _manager,
)

NONCE = "a" * 32
RAW = "mcp.stderr.log.0"


@pytest.fixture
def scenario(tmp_path: Path):
    # One explicit platform site; the synthetic subprocess guardian currently
    # uses Linux /proc to distinguish a dead writer from a zombie.
    if sys.platform != "linux":
        pytest.skip("independent /proc fixture guardian qualified on Linux only")
    base = tmp_path / ("issue30-fixture-e2e-" + NONCE)
    setup_fixture(base)
    manager, owner, _fence = _manager(base)
    gate = ToolAdmissionDrain()
    writer = FixtureProducer(base)
    writer.start_original()
    try:
        yield base, manager, owner, gate, writer
    finally:
        writer.close()
        (base / "guardian-worker.stop").touch(exist_ok=True)


def _run(scenario, **change):
    root, manager, _owner, gate, writer = scenario
    return run_complete_fixture_transaction(
        root, manager=manager, mcp=gate, writer=writer, **change
    )


def _journal(root: Path):
    # The synthetic guardian briefly locks the journal after a failed
    # controller releases it. Wait for its bounded completion witness before
    # testing unowned inspection; a concurrent observer is correctly refused.
    if (root / "guardian-disarm").exists():
        _guardian_outcome(root)
    return inspect_unowned_transaction(root / ("txn-" + NONCE))


def _barriers_released(root: Path) -> None:
    assert not (root / "watchdog/request.json").exists()
    assert not (root / "watchdog/ack.json").exists()
    assert not (root / "manager-pause/request.json").exists()
    with J7Interlocks(root / "j7-state") as locks:
        locks.verify()


def test_full_transaction_closes_actual_writer_publishes_and_prunes(
    scenario,
) -> None:
    root, _manager, owner, gate, writer = scenario
    raw = root / "private-logs" / RAW
    expected = raw.read_bytes()
    assert expected.endswith(b"e2e-fixture-generation raw\n")

    result = _run(scenario)
    assert result.archive.source == RAW
    assert result.archive.producer == "system/com.binnacle.mcp"
    assert not result.archive.resumed_publication
    compressed = root / "private-logs" / result.archive.canonical
    assert compressed.exists()
    assert not raw.exists()
    assert bz2.decompress(compressed.read_bytes()) == expected
    assert result.journal.phase == "complete"
    assert result.journal.revision == 11
    assert len(result.journal.receipts) == 11
    assert result.journal.needs_external_recovery is False
    assert not result.journal.producer_may_be_stopped
    assert not result.journal.production_authorized
    assert not result.production_authorized
    assert result.guardian_outcome == "not-needed"
    assert writer.original is not None and writer.original.poll() == 0
    assert writer.active is not None and writer.active.poll() is None
    assert (root / "private-logs/mcp.stderr.log").is_file()
    assert result.restored_pid == writer.active.pid
    assert not owner.spawned
    _barriers_released(root)
    snapshot = _journal(root)
    assert snapshot.phase == "complete"
    assert gate.snapshot().drained
    with pytest.raises(ToolAdmissionPaused):
        gate.admit()
    # A new native generation would have an independent admission gate.
    fresh_gate = ToolAdmissionDrain()
    fresh = fresh_gate.admit()
    fresh_gate.release(fresh)


@pytest.mark.parametrize(
    "failure",
    [
        "j7_locked",
        "watchdog_acked",
        "mcp_drained",
        "jobs_drained",
        "guardian_armed",
        "producer_stopped",
        "writer_fds_closed",
        "canonical_verified",
    ],
)
def test_fail_before_raw_unlink_preserves_source_and_releases_barriers(
    scenario,
    failure: str,
) -> None:
    root, _manager, _owner, _gate, writer = scenario
    raw = root / "private-logs" / RAW
    expected = raw.read_bytes()
    with pytest.raises(RehearsalRefused, match="synthetic failure"):
        _run(scenario, inject_failure=failure)
    assert raw.read_bytes() == expected
    _barriers_released(root)
    current = _journal(root)
    assert current.phase == failure
    assert current.needs_external_recovery
    assert not current.production_authorized
    if failure in {"producer_stopped", "writer_fds_closed", "canonical_verified"}:
        assert writer.active is not None and writer.active.poll() is None
    elif failure == "guardian_armed":
        assert writer.original is not None and writer.original.poll() is None
    else:
        assert writer.original is not None and writer.original.poll() is None


def test_abort_after_raw_unlink_restores_new_writer_and_keeps_canonical(
    scenario,
) -> None:
    root, _manager, _owner, _gate, writer = scenario
    raw = root / "private-logs" / RAW
    expected = raw.read_bytes()
    with pytest.raises(RehearsalRefused, match="raw_pruned"):
        _run(scenario, inject_failure="raw_pruned")
    assert not raw.exists()
    assert (
        bz2.decompress((root / "private-logs" / (RAW + ".bz2")).read_bytes())
        == expected
    )
    state = _journal(root)
    assert state.phase == "raw_pruned"
    assert state.producer_may_be_stopped
    assert state.needs_external_recovery
    assert writer.active is not None and writer.active.poll() is None
    _barriers_released(root)


def test_abort_before_service_restart_recovers_test_active_writer(
    scenario,
) -> None:
    root, _manager, _owner, _gate, writer = scenario
    with pytest.raises(RehearsalRefused, match="before_restore"):
        _run(scenario, inject_failure="before_restore")
    assert _journal(root).phase == "raw_pruned"
    assert writer.active is not None and writer.active.poll() is None
    _barriers_released(root)


def test_preexisting_tool_call_refuses_before_writer_is_stopped(
    scenario,
) -> None:
    root, _manager, _owner, gate, writer = scenario
    ticket = gate.admit()
    try:
        with pytest.raises(RehearsalRefused, match="MCP not fully drained"):
            _run(scenario)
        assert writer.original is not None and writer.original.poll() is None
        assert (root / "private-logs" / RAW).exists()
        _barriers_released(root)
    finally:
        gate.release(ticket)


def test_active_durable_job_prevents_writer_stop_and_preserves_raw(
    scenario,
) -> None:
    root, manager, owner, _gate, writer = scenario
    job_id = _launch(manager, root)
    assert isinstance(job_id, str)
    with pytest.raises(RehearsalRefused, match="Jobs admission not drained"):
        _run(scenario)
    assert writer.original is not None and writer.original.poll() is None
    assert owner.spawned == [job_id]
    assert (root / "private-logs" / RAW).exists()
    _barriers_released(root)


def test_refusal_after_guardian_ack_before_stop_does_not_spawn_duplicate(
    scenario,
) -> None:
    root, _manager, _owner, _gate, writer = scenario
    source = root / "private-logs" / RAW
    original = source.read_bytes()
    with pytest.raises(RehearsalRefused, match="guardian_armed"):
        _run(scenario, inject_failure="guardian_armed")
    assert writer.original is not None and writer.original.poll() is None
    assert writer.active is None
    assert source.read_bytes() == original
    assert (root / "guardian-disarm").exists()
    from tests.issue30_full_transaction_fixture import _guardian_outcome

    assert _guardian_outcome(root) == "already-restored"
    assert not (root / "private-logs" / (RAW + ".bz2")).exists()
    _barriers_released(root)

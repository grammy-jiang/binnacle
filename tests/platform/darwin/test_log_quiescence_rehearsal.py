"""End-to-end synthetic Issue #30 barriers, never a real service lifecycle."""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

import pytest

from binnacle.companions.darwin_log_j7_interlocks import (
    J7InterlockBusy,
    J7Interlocks,
)
from binnacle.companions.service_watchdog_maintenance import (
    WatchdogMaintenanceFence,
)
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain, ToolAdmissionPaused
from tests.issue30_rehearsal_support import (
    FixtureRehearsalResult,
    RehearsalRefused,
    rehearse_fixture_quiescence,
)
from tests.platform.darwin.test_job_manager_maintenance_fence import (
    _launch,
    _manager,
)

NONCE = "a" * 32


@pytest.fixture
def scenario(tmp_path: Path):
    base = tmp_path / "issue30-fixture-assembled"
    base.mkdir(mode=0o700)
    base.chmod(0o700)
    state = base / "j7-state"
    state.mkdir(mode=0o700)
    (state / "j7").mkdir(mode=0o700)
    wd = base / "watchdog"
    wd.mkdir(mode=0o700)
    (base / "manager-pause").mkdir(mode=0o700)
    mgr, owner, _old = _manager(base)
    mcp = ToolAdmissionDrain()
    return base, mgr, owner, mcp


def _run(scenario, **kwargs):
    base, mgr, _owner, mcp = scenario
    opts = {
        "root": base,
        "manager": mgr,
        "mcp": mcp,
        "nonce": NONCE,
        "watchdog_ack": lambda: WatchdogMaintenanceFence(base / "watchdog").poll(),
        "watchdog_pid": os.getpid(),
        "timeout_s": 0.02,
    }
    opts.update(kwargs)
    return rehearse_fixture_quiescence(**opts)


def _assert_released(base: Path) -> None:
    assert not (base / "watchdog/request.json").exists()
    assert not (base / "watchdog/ack.json").exists()
    assert not (base / "manager-pause/request.json").exists()
    with J7Interlocks(base / "j7-state") as unlocked:
        unlocked.verify()


def test_successful_end_to_end_fixture_never_grants_production_authority(
    scenario,
) -> None:
    root, _manager, owner, mcp = scenario
    result = _run(scenario)
    assert isinstance(result, FixtureRehearsalResult)
    assert result.nonce == NONCE
    assert result.manager_owner == owner.owner_instance_id
    assert result.manager_pid == os.getpid()
    assert result.watchdog_acknowledged
    assert result.mcp_drained
    assert result.manager_start_paused
    assert result.running_jobs == result.unknown_jobs == 0
    assert not result.production_authorized
    _assert_released(root)
    with pytest.raises(ToolAdmissionPaused):
        mcp.admit()


def test_watchdog_without_ack_never_proceeds_to_mcp_or_jobs(
    scenario,
) -> None:
    root, _manager, owner, mcp = scenario
    with pytest.raises(RehearsalRefused, match="Watchdog ACK"):
        _run(scenario, watchdog_ack=lambda: None)
    _assert_released(root)
    token = mcp.admit()  # MCP admission was never fenced
    mcp.release(token)
    assert not owner.spawned


def test_wrong_watchdog_pid_cannot_claim_a_matching_nonce(scenario) -> None:
    root, _manager, _owner, mcp = scenario
    with pytest.raises(RehearsalRefused, match="Watchdog ACK"):
        _run(scenario, watchdog_pid=os.getpid() + 1)
    _assert_released(root)
    assert mcp.snapshot().pause_nonce is None


def test_inflight_mcp_request_blocks_further_rehearsal(
    scenario,
) -> None:
    root, _manager, owner, mcp = scenario
    token = mcp.admit()
    try:
        with pytest.raises(RehearsalRefused, match="MCP call still in flight"):
            _run(scenario)
        _assert_released(root)
        assert mcp.snapshot().in_flight == 1
    finally:
        mcp.release(token)
    assert mcp.snapshot().drained
    assert not mcp.snapshot().shutdown_authorized
    assert not owner.spawned


def test_existing_durable_job_blocks_quiescence_without_killing_job(
    scenario,
) -> None:
    root, manager, owner, _mcp = scenario
    job = _launch(manager, root)
    assert isinstance(job, str)
    with pytest.raises(RehearsalRefused, match="Manager admission not quiet"):
        _run(scenario)
    _assert_released(root)
    assert owner.spawned == [job]
    assert manager.state(job) == "running"


def test_wrong_fixture_basename_refused_before_lock_creation(tmp_path: Path) -> None:
    root = tmp_path / "production-state"
    root.mkdir(mode=0o700)
    (root / "j7-state").mkdir(mode=0o700)
    (root / "j7-state/j7").mkdir(mode=0o700)
    (root / "watchdog").mkdir(mode=0o700)
    (root / "manager-pause").mkdir(mode=0o700)
    manager, _owner, _old = _manager(root)
    mcp = ToolAdmissionDrain()
    with pytest.raises(RehearsalRefused, match="isolation"):
        rehearse_fixture_quiescence(
            root,
            manager=manager,
            mcp=mcp,
            nonce=NONCE,
            watchdog_ack=lambda: None,
            watchdog_pid=os.getpid(),
        )
    assert not (root / "j7-state/mac-deploy-gate.lock").exists()
    assert mcp.snapshot().pause_nonce is None


def test_nonprivate_fixture_root_is_refused(scenario) -> None:
    root, _manager, _owner, mcp = scenario
    root.chmod(0o755)
    try:
        with pytest.raises(RehearsalRefused, match="isolation"):
            _run(scenario)
        assert mcp.snapshot().pause_nonce is None
    finally:
        root.chmod(0o700)


def test_existing_fixture_jobs_request_is_not_overwritten(
    scenario,
) -> None:
    root, _manager, _owner, _mcp = scenario
    path = root / "manager-pause/request.json"
    path.write_text('{"foreign":true}')
    path.chmod(0o600)
    with pytest.raises(RehearsalRefused, match="other fixture"):
        _run(scenario)
    assert path.read_text() == '{"foreign":true}'
    assert not (root / "watchdog/request.json").exists()


def test_j7_lock_held_by_other_writer_refuses_before_request(scenario) -> None:
    root, _manager, _owner, mcp = scenario
    lock = root / "j7-state/j7/jobs-service.lock"
    lock.write_bytes(b"other J7 activity")
    lock.chmod(0o600)
    with lock.open("r+b") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(J7InterlockBusy):
            _run(scenario)
        assert mcp.snapshot().pause_nonce is None
        assert not (root / "watchdog/request.json").exists()
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


@pytest.mark.parametrize("invalid", ["invalid", "G" * 32, True])
def test_invalid_fixture_nonce_refused_without_mutations(scenario, invalid) -> None:
    root, _manager, _owner, mcp = scenario
    with pytest.raises(RehearsalRefused, match="invalid fixture transaction"):
        _run(scenario, nonce=invalid)
    assert not (root / "j7-state/mac-deploy-gate.lock").exists()
    assert mcp.snapshot().pause_nonce is None


def test_failed_durable_census_never_claims_quiescence(scenario) -> None:
    root, _manager, owner, _mcp = scenario
    # A manager's own zero isn't enough; an unknown/unfinished historical
    # owner record remains unverified in the durable directory.
    history = root / "jobs" / "123456abcdef"
    history.mkdir()
    (history / "meta.json").write_text(
        json.dumps(
            {
                "command": "still unknown",
                "workdir": str(root),
                "pid": 1234,
                "started_at": time.time(),
            }
        )
    )
    with pytest.raises(
        RehearsalRefused, match="Manager admission not quiet|durable Jobs"
    ):
        _run(scenario)
    _assert_released(root)
    assert not owner.spawned


def test_read_only_absence_not_production_authorization(scenario) -> None:
    _root, _manager, owner, mcp = scenario
    result = _run(scenario)
    assert result.state == "quiescence_proved_in_fixture_only"
    assert result.production_authorized is False
    with pytest.raises(ValueError, match="not production"):
        FixtureRehearsalResult(
            NONCE,
            owner.owner_instance_id,
            os.getpid(),
            mcp.generation,
            "quiescence_proved_in_fixture_only",
            True,
            True,
            True,
            0,
            0,
            production_authorized=True,
        )

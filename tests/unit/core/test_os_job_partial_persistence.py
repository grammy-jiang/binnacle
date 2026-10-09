"""OS3 P2: failed native signals remain observable after durable leader exit.

The verified process lease may terminate the leader while leaving an EPERM
descendant alive. Persist that partial delivery before an idempotent stop can
mistake the reaper's "exited" metadata for complete group termination.
"""

from types import SimpleNamespace

import pytest

from binnacle.features.commands import job_owner, job_stop, job_store, jobs
from binnacle.features.commands.job_manager import JobManager
from binnacle.platform.contracts.process_contracts import JobSignalDeliveryError
from binnacle.platform.contracts.resource_contracts import NoResourceAccounting

JOB_ID = "abcdef123456"


@pytest.fixture()
def spool(tmp_path, monkeypatch):
    root = tmp_path / "private-spool"
    monkeypatch.setattr(jobs, "JOBS_DIR", root)
    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", NoResourceAccounting())
    directory = root / JOB_ID
    directory.mkdir(parents=True)
    job_store.write_meta(
        root,
        JOB_ID,
        {
            "command": "synthetic-worker",
            "workdir": str(tmp_path),
            "pid": 987654,
            "pgid": 987654,
            "starttime": 150,
            "started_at": 1.0,
            "schema_version": 2,
            "owner_instance_id": "owned-manager",
            "stop_requested": True,
            "call_id": "test-call",
        },
    )
    (directory / "out.log").write_bytes(b"prior output")
    return root


def test_partial_failure_persists_across_exit_reaper_and_idempotent_retry(
    spool, monkeypatch
):
    def partial_after_leader_exit(*args, **kwargs):
        jobs.record_exit(JOB_ID, SimpleNamespace(returncode=-15))
        raise JobSignalDeliveryError(
            "1 verified process target(s) could not receive terminate"
        )

    monkeypatch.setattr(job_stop, "stop_embedded", partial_after_leader_exit)
    with pytest.raises(JobSignalDeliveryError, match="could not receive terminate"):
        jobs.stop_job_embedded(JOB_ID)

    meta = job_store.read_meta(spool, JOB_ID)
    assert meta is not None
    assert meta["schema_version"] == 2
    assert (meta["exit_code"], meta["signal"]) == (None, 15)
    assert meta["stop_signal_partial"] is True
    assert meta["termination_reason"] == "stop_requested"
    assert (spool / JOB_ID / "out.log").read_bytes() == b"prior output"

    # Concurrent/delayed reaper record writes must retain the safety marker.
    jobs.record_exit(JOB_ID, SimpleNamespace(returncode=-15))
    assert job_store.read_meta(spool, JOB_ID)["stop_signal_partial"] is True

    monkeypatch.setattr(
        job_owner,
        "mark_stop_requested",
        lambda *args: pytest.fail("terminal partial stop must not dispatch again"),
    )
    with pytest.raises(JobSignalDeliveryError, match="previous verified"):
        job_owner.stop_job(JOB_ID)
    with pytest.raises(JobSignalDeliveryError, match="previous verified"):
        jobs.stop_job_embedded(JOB_ID)


def test_direct_manager_rpc_rejects_persisted_partial_before_marking(
    spool, monkeypatch
):
    meta = job_store.read_meta(spool, JOB_ID)
    assert meta is not None
    meta["stop_signal_partial"] = True
    meta["exit_code"] = None
    meta["signal"] = 15
    meta["ended_at"] = 2
    job_store.write_meta(spool, JOB_ID, meta)

    monkeypatch.setattr(
        job_owner,
        "mark_stop_requested",
        lambda job_id: pytest.fail("partial stop cannot become successful"),
    )
    monkeypatch.setattr(
        jobs,
        "stop_job_embedded",
        lambda job_id: pytest.fail("partial stop cannot send new signals"),
    )
    manager = JobManager(spool.parent / "test.sock", owner_instance_id="test-owner")
    result = manager._stop({"job_id": JOB_ID, "call_id": "retry-call"})
    assert result["ok"] is False
    assert "job stop partially failed: previous verified" in result["error"]


def test_old_metadata_without_partial_still_remains_compatible(spool):
    meta = job_store.read_meta(spool, JOB_ID)
    assert meta is not None
    assert "stop_signal_partial" not in meta
    assert job_stop.raise_if_partial_signal(meta) is None
    meta["exit_code"] = 0
    meta["ended_at"] = 2
    job_store.write_meta(spool, JOB_ID, meta)
    assert job_owner.stop_job(JOB_ID)["state"] == "exited"


def test_metadata_persistence_error_never_returns_false_success(spool, monkeypatch):
    def partial(*args, **kwargs):
        raise JobSignalDeliveryError("partial target")

    monkeypatch.setattr(job_stop, "stop_embedded", partial)
    monkeypatch.setattr(
        job_store,
        "write_meta",
        lambda *args: (_ for _ in ()).throw(OSError("read-only private spool")),
    )
    with pytest.raises(JobSignalDeliveryError, match="partial stop not persisted"):
        jobs.stop_job_embedded(JOB_ID)


def test_partial_marker_is_persisted_before_wait_or_concurrent_retry(
    spool, monkeypatch
):
    """No window in which leader exited but retry reads no failure marker."""
    lease = SimpleNamespace(
        signal=lambda intent: (_ for _ in ()).throw(
            JobSignalDeliveryError("unsignalable child")
        ),
        close=lambda: None,
    )
    fake_backend = SimpleNamespace(
        identity_from_record=lambda meta: object(),
        open_job_signals=lambda identity: lease,
        alive=lambda pid, starttime=None: True,
    )
    monkeypatch.setattr(jobs, "_PROCESS_BACKEND", fake_backend)

    def concurrently_finished(job_id, timeout):
        # The job's reaper can race with the RPC stop; the marker must
        # already be on disk when the owner observes the terminal state.
        jobs.record_exit(JOB_ID, SimpleNamespace(returncode=-15))
        assert job_store.read_meta(spool, JOB_ID)["stop_signal_partial"] is True
        with pytest.raises(JobSignalDeliveryError, match="previous verified"):
            job_owner.stop_job(JOB_ID)
        return {"state": "exited", "signal": 15}

    monkeypatch.setattr(jobs, "await_exit", concurrently_finished)
    with pytest.raises(JobSignalDeliveryError, match="unsignalable child"):
        jobs.stop_job_embedded(JOB_ID)
    assert job_store.read_meta(spool, JOB_ID)["stop_signal_partial"] is True

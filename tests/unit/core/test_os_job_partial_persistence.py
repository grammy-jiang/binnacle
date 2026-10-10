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


@pytest.mark.parametrize("failure_mode", ["oserror", "missing_record"])
def test_native_partial_callback_write_failure_stays_a_controlled_error(
    spool, monkeypatch, failure_mode
):
    """The callback itself must not leak an OSError or ignore a False write."""
    delivered = []

    def partial_signal(intent):
        delivered.append(intent)
        raise JobSignalDeliveryError("verified descendant was not signaled")

    lease = SimpleNamespace(
        signal=partial_signal, close=lambda: delivered.append("close")
    )
    backend = SimpleNamespace(
        identity_from_record=lambda meta: object(),
        open_job_signals=lambda identity: lease,
        alive=lambda pid, starttime=None: True,
    )
    monkeypatch.setattr(jobs, "_PROCESS_BACKEND", backend)
    monkeypatch.setattr(
        jobs,
        "await_exit",
        lambda *args: pytest.fail("callback error must be resolved before wait"),
    )
    if failure_mode == "oserror":
        monkeypatch.setattr(
            job_store,
            "write_meta",
            lambda *args: (_ for _ in ()).throw(OSError("spool read-only")),
        )
    else:
        monkeypatch.setattr(
            job_store, "mark_signal_delivery_partial", lambda *args: False
        )
    with pytest.raises(JobSignalDeliveryError, match="partial stop not persisted"):
        jobs.stop_job_embedded(JOB_ID)
    assert delivered == ["terminate", "close"]
    assert "stop_signal_partial" not in job_store.read_meta(spool, JOB_ID)


def test_native_partial_callback_write_recovers_on_outer_retry(spool, monkeypatch):
    """Transient disk failure gets a second chance before the error returns."""
    attempts = []
    original_write = job_store.write_meta

    def write_once_bad(root, job_id, meta):
        attempts.append(meta.get("stop_signal_partial"))
        if len(attempts) == 1:
            raise OSError("temporary read-only spool")
        return original_write(root, job_id, meta)

    monkeypatch.setattr(job_store, "write_meta", write_once_bad)
    signals = []

    def partial_signal(intent):
        signals.append(intent)
        raise JobSignalDeliveryError("unsignalable verified descendant")

    lease = SimpleNamespace(
        signal=partial_signal, close=lambda: signals.append("close")
    )
    monkeypatch.setattr(
        jobs,
        "_PROCESS_BACKEND",
        SimpleNamespace(
            identity_from_record=lambda meta: object(),
            open_job_signals=lambda identity: lease,
            alive=lambda pid, starttime=None: True,
        ),
    )
    monkeypatch.setattr(
        jobs,
        "await_exit",
        lambda *args: pytest.fail("do not return success before the marker"),
    )
    with pytest.raises(JobSignalDeliveryError, match="partial stop not persisted"):
        jobs.stop_job_embedded(JOB_ID)
    assert attempts == [True, True]
    assert signals == ["terminate", "close"]
    # A later reaper write cannot erase the previously durable partial marker.
    jobs.record_exit(JOB_ID, SimpleNamespace(returncode=-15))
    assert job_store.read_meta(spool, JOB_ID)["stop_signal_partial"] is True
    with pytest.raises(JobSignalDeliveryError, match="previous verified"):
        job_owner.stop_job(JOB_ID)


def test_manager_rpc_reports_callback_storage_outage_as_partial_stop(
    spool, monkeypatch
):
    """Manager RPC returns a controlled partial error rather than a raw OSError."""
    lease = SimpleNamespace(
        signal=lambda intent: (_ for _ in ()).throw(
            JobSignalDeliveryError("EPERM for verified descendant")
        ),
        close=lambda: None,
    )
    monkeypatch.setattr(
        jobs,
        "_PROCESS_BACKEND",
        SimpleNamespace(
            alive=lambda pid, starttime=None: True,
            identity_from_record=lambda meta: object(),
            open_job_signals=lambda identity: lease,
        ),
    )
    monkeypatch.setattr(job_owner, "mark_stop_requested", lambda job_id: None)
    monkeypatch.setattr(
        job_store,
        "write_meta",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")),
    )
    manager = JobManager(spool.parent / "partial-io.sock", owner_instance_id="owner")
    response = manager._stop({"job_id": JOB_ID, "call_id": "io-outage"})
    assert response["ok"] is False
    assert response["error"] == "job stop partially failed: partial stop not persisted"

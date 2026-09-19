"""Durable job-spool, pruning, and atomicity integration tests."""

import json
import os
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs as jobstore
from tests.integration.job_test_support import run, status, stop


@pytest.fixture(autouse=True, scope="module")
def _isolate_job_store(tmp_path_factory):
    original = jobstore.JOBS_DIR
    jobstore.JOBS_DIR = tmp_path_factory.mktemp("jobs-store")
    yield
    jobstore.JOBS_DIR = original


# -- pruning races (both seen in production, 2026-09-01/02) ----------------


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    """A per-test store: prune tests count directories exactly."""
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "store")


def _fake_finished_dir(name: str) -> None:
    d = jobstore.JOBS_DIR / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        '{"command": "x", "workdir": "/tmp", "pid": 1,'
        ' "started_at": 1.0, "ended_at": 2.0, "exit_code": 0}'
    )


def test_keep_newest_config_requires_at_least_one_slot():
    from pydantic import ValidationError

    from binnacle.config import JobsSettings

    with pytest.raises(ValidationError):
        JobsSettings(keep_newest=0)
    assert JobsSettings(keep_newest=1).keep_newest == 1


def test_start_job_lock_releases_after_popen_failure(fresh_store, monkeypatch):
    real_popen = jobstore.subprocess.Popen
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic popen failure")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(jobstore.subprocess, "Popen", fail_once)
    with pytest.raises(OSError, match="synthetic popen failure"):
        jobstore.start_job("true", Path("/tmp"), None)

    job_id, proc = jobstore.start_job("true", Path("/tmp"), None)
    proc.wait(timeout=5)
    jobstore.record_exit(job_id, proc)
    assert jobstore.job_state(job_id)["state"] == "exited"


def test_start_job_reserves_one_slot_at_cap(fresh_store, monkeypatch, caplog):
    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    with caplog.at_level("INFO", logger="binnacle.jobs"):
        p = run("printf new")
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert p["state"] == "exited"
    assert len(dirs) == 3
    assert (jobstore.JOBS_DIR / p["job_id"]).exists()
    assert sum(d.name.startswith("fake") for d in dirs) == 2
    prune = next(
        r.getMessage() for r in caplog.records if "event=jobs_pruned" in r.getMessage()
    )
    assert "keep_newest=3" in prune
    assert "reserve=1" in prune
    assert "effective_keep=2" in prune


def test_concurrent_starts_do_not_share_reserved_slot(fresh_store, monkeypatch):
    import threading

    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    barrier = threading.Barrier(3)
    results: list[dict] = []
    errors: list[BaseException] = []

    def go() -> None:
        try:
            barrier.wait()
            results.append(run("sleep 0.1"))
        except (AssertionError, ToolError, OSError, RuntimeError) as e:
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 2
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert len(dirs) == 3
    assert all((jobstore.JOBS_DIR / p["job_id"]).exists() for p in results)


def test_start_job_spares_old_running_job_outside_base_window(fresh_store, monkeypatch):
    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    old = run("sleep 30", background=True)
    assert old["state"] == "running"
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    new = run("printf new")
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert new["state"] == "exited"
    assert (jobstore.JOBS_DIR / old["job_id"]).exists()
    assert status(old["job_id"])["state"] == "running"
    # Three base slots plus the deliberately protected stale running job.
    assert len(dirs) == 4
    assert sum(d.name.startswith("fake") for d in dirs) == 2
    stop(old["job_id"])


def test_prune_spares_running_job(fresh_store):
    p = run("sleep 5", background=True)
    job_id = p["job_id"]
    for i in range(jobstore.KEEP_NEWEST + 5):
        _fake_finished_dir(f"fake{i:08x}0000")
    jobstore._prune()
    assert (jobstore.JOBS_DIR / job_id).exists()
    s = status(job_id)
    assert s["state"] == "running"
    fakes_left = sum(
        1 for d in jobstore.JOBS_DIR.iterdir() if d.name.startswith("fake")
    )
    assert fakes_left == jobstore.KEEP_NEWEST
    stop(job_id)


def test_prune_deletes_malformed_meta_dir(fresh_store):
    # A meta.json that parses but lacks fields (e.g. server killed
    # mid-write) must count as garbage, not crash the prune.
    for i in range(jobstore.KEEP_NEWEST):
        _fake_finished_dir(f"fake{i:08x}0000")
    bad = jobstore.JOBS_DIR / "badmeta000000"
    bad.mkdir()
    (bad / "meta.json").write_text("{}")
    import os

    os.utime(bad, (1_000_000_000, 1_000_000_000))  # oldest -> prune candidate
    jobstore._prune()
    assert not bad.exists()


def test_write_meta_replaces_complete_record_atomically(fresh_store, monkeypatch):
    job_id = "atomicmeta001"
    d = jobstore.JOBS_DIR / job_id
    d.mkdir(parents=True)
    old = {
        "command": "old",
        "workdir": "/tmp",
        "pid": 1,
        "started_at": 1.0,
    }
    new = dict(old, command="new", ended_at=2.0, exit_code=0)
    (d / "meta.json").write_text(json.dumps(old))

    real_replace = os.replace
    observed_before_replace: list[dict] = []

    def inspect_replace(src, dst):
        observed_before_replace.append(json.loads(Path(dst).read_text()))
        real_replace(src, dst)

    monkeypatch.setattr(jobstore.os, "replace", inspect_replace)
    jobstore._write_meta(job_id, new)

    assert observed_before_replace == [old]
    assert json.loads((d / "meta.json").read_text()) == new
    assert list(d.glob(".meta.*.tmp")) == []


def test_atomic_meta_write_survives_concurrent_readers(fresh_store):
    import threading

    job_id = "atomicmeta002"
    d = jobstore.JOBS_DIR / job_id
    d.mkdir(parents=True)
    base = {"command": "x", "workdir": "/tmp", "pid": 1, "started_at": 1.0}
    jobstore._write_meta(job_id, base)
    stop_readers = threading.Event()
    failures: list[str] = []

    def reader() -> None:
        while not stop_readers.is_set():
            state = jobstore._read_meta(job_id)
            if state is None:
                failures.append("invalid-or-missing-meta")
                return

    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in readers:
        t.start()
    try:
        for i in range(40):
            jobstore._write_meta(
                job_id,
                dict(
                    base,
                    command=("x" * 20_000) + str(i),
                    ended_at=float(i),
                    exit_code=0,
                ),
            )
    finally:
        stop_readers.set()
        for t in readers:
            t.join()

    assert failures == []
    assert jobstore._read_meta(job_id) is not None


def test_remove_job_dir_tolerates_vanished_dir(fresh_store):
    gone = jobstore.JOBS_DIR / "never-existed"
    assert jobstore._remove_job_dir(gone) is False  # no raise: the
    # deterministic form of the concurrent-prune race (jobs.py rmdir
    # traceback of 2026-09-02 10:25).


def test_reaper_tolerates_pruned_dir(caplog, fresh_store):
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        # Long enough that the job is still running after the 1 s
        # background warm-up, so the dir vanishes before the reaper fires.
        p = run("sleep 2", background=True)
        job_id = p["job_id"]
        assert status(job_id)["state"] == "running"
        assert jobstore._remove_job_dir(jobstore.JOBS_DIR / job_id)
        for _ in range(50):
            if any(
                f"event=job_exit_unrecorded job_id={job_id}" in r.getMessage()
                for r in caplog.records
            ):
                break
            time.sleep(0.1)
    assert any(
        f"event=job_exit_unrecorded job_id={job_id}" in r.getMessage()
        for r in caplog.records
    )

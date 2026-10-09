import builtins
import json
from pathlib import Path

import pytest

from binnacle.features.commands import jobs


def _job(tmp_path: Path, job_id: str = "rangejob0001", data: bytes = b"0123456789"):
    directory = tmp_path / job_id
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "command": "printf data",
                "workdir": "/tmp",
                "pid": 1,
                "started_at": 1.0,
            }
        )
    )
    (directory / "out.log").write_bytes(data)
    return job_id, directory


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    return tmp_path


def test_read_log_range_middle(store):
    job_id, _ = _job(store)

    assert jobs.read_log_range(job_id, 3, 4) == (b"3456", 10)


def test_read_log_range_to_eof(store):
    job_id, _ = _job(store)

    assert jobs.read_log_range(job_id, 7, 3) == (b"789", 10)


def test_read_log_range_larger_than_remainder(store):
    job_id, _ = _job(store)

    assert jobs.read_log_range(job_id, 7, 100) == (b"789", 10)


@pytest.mark.parametrize("start", [10, 11])
def test_read_log_range_at_or_beyond_eof(store, start):
    job_id, _ = _job(store)

    assert jobs.read_log_range(job_id, start, 4) == (b"", 10)


@pytest.mark.parametrize("missing", ["dir", "meta", "log"])
def test_read_log_range_missing_job_artifact_raises_job_gone(store, missing):
    job_id = "missing000001"
    directory = store / job_id
    if missing != "dir":
        directory.mkdir()
    if missing == "log":
        (directory / "meta.json").write_text("{}")

    with pytest.raises(jobs.JobGone):
        jobs.read_log_range(job_id, 0, 4)


def test_read_log_range_survives_log_unlink_after_open(store, monkeypatch):
    job_id, directory = _job(store, data=b"abcdefghij")
    log_path = directory / "out.log"
    real_open = builtins.open
    opened = 0

    def open_then_unlink(path, *args, **kwargs):
        nonlocal opened
        handle = real_open(path, *args, **kwargs)
        if Path(path) == log_path:
            opened += 1
            log_path.unlink()
        return handle

    monkeypatch.setattr(builtins, "open", open_then_unlink)

    assert jobs.read_log_range(job_id, 2, 5) == (b"cdefg", 10)
    assert opened == 1
    assert not log_path.exists()


@pytest.mark.parametrize(("start", "max_bytes"), [(-1, 4), (0, -1)])
def test_read_log_range_rejects_negative_bounds(store, start, max_bytes):
    job_id, _ = _job(store)

    with pytest.raises(ValueError):
        jobs.read_log_range(job_id, start, max_bytes)

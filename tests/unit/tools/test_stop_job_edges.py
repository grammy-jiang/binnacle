"""Error and rare terminal summaries for stop_job."""

import pytest
from fastmcp.exceptions import ToolError

from binnacle import job_owner
from binnacle.tools import stop_job


def test_stop_job_wraps_owner_failure(monkeypatch):
    monkeypatch.setattr(
        job_owner,
        "stop_job",
        lambda job_id: (_ for _ in ()).throw(RuntimeError("manager down")),
    )
    with pytest.raises(ToolError, match="Could not stop the job: manager down"):
        stop_job.stop_job_impl("job")


def test_stop_job_describes_exit_without_recorded_status(monkeypatch):
    monkeypatch.setattr(
        job_owner,
        "stop_job",
        lambda job_id: {"state": "exited", "exit_code": None, "signal": None},
    )
    result = stop_job.stop_job_impl("job")
    assert "ended without a recorded exit status" in str(result.content)

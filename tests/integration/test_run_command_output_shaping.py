import re

import pytest

from binnacle import jobs
from tests.integration.job_test_support import run

pytestmark = pytest.mark.usefixtures("_short_job_warmup")


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")


def _event_fields(caplog):
    line = next(
        record.getMessage()
        for record in caplog.records
        if "event=run_command_output_shaping" in record.getMessage()
    )
    return line, dict(re.findall(r"(\w+)=([^ ]+)", line))


def test_tail_only_emits_sparse_shaping_event(caplog):
    with caplog.at_level("INFO", logger="binnacle.run_command"):
        result = run("for i in $(seq 1 50); do echo line$i; done", tail_lines=5)
    line, fields = _event_fields(caplog)
    assert result["truncated"] is True
    assert fields["reason"] == "tail_lines"
    assert fields["tail_lines"] == "5"
    assert fields["dropped_lines"] == "45"
    assert fields["char_clipped"] == "false"
    assert "line50" not in line


def test_char_clip_emits_char_limit_event(caplog):
    with caplog.at_level("INFO", logger="binnacle.run_command"):
        result = run("for i in $(seq 1 6000); do printf '0123456789\\n'; done")
    _, fields = _event_fields(caplog)
    assert result["truncated"] is True
    assert fields["reason"] == "char_limit"
    assert fields["tail_lines"] == "-"
    assert fields["dropped_lines"] == "0"
    assert fields["char_clipped"] == "true"
    assert int(fields["omitted_chars"]) > 0


def test_unmodified_output_emits_no_shaping_event(caplog):
    with caplog.at_level("INFO", logger="binnacle.run_command"):
        result = run("printf small")
    assert result["truncated"] is False
    assert not any(
        "event=run_command_output_shaping" in record.getMessage()
        for record in caplog.records
    )

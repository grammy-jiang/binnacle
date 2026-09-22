"""Coverage of optional telemetry paths in materialized ripgrep execution."""

import subprocess

from binnacle import search_text_rg
from binnacle.search_text_telemetry import ExactSearchMetrics


def _result(stdout: str):
    return subprocess.CompletedProcess(["rg"], 0, stdout, "")


def test_run_rg_without_metrics_uses_plain_result_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        search_text_rg.subprocess,
        "run",
        lambda *args, **kwargs: _result('{"type":"match","data":{}}\n'),
    )
    events, no_match = search_text_rg.run_rg(
        tmp_path, "hit", True, 1, rg_bin="rg", timeout_s=1, metrics=None
    )
    assert [event["type"] for event in events] == ["match"]
    assert no_match is False


def test_run_rg_counts_bad_json_when_metrics_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        search_text_rg.subprocess,
        "run",
        lambda *args, **kwargs: _result('not-json\n{"type":"begin","data":{}}\n'),
    )
    metrics = ExactSearchMetrics("call", "dir", "1")
    events, _ = search_text_rg.run_rg(
        tmp_path, "hit", False, 0, rg_bin="rg", timeout_s=1, metrics=metrics
    )
    assert len(events) == 1
    assert metrics.rg_bad_json == 1
    assert metrics.rg_events == 1
    assert metrics.rg_begin_events == 1

"""Phase B exact-search metrics are cheap counters over existing work."""

from pathlib import Path

from binnacle.search_text_telemetry import ExactSearchMetrics
from binnacle.tools import search_text as st


def _event(kind: str, path: Path, line: int, text: str) -> dict:
    return {
        "type": kind,
        "data": {
            "path": {"text": str(path)},
            "line_number": line,
            "lines": {"text": text + "\n"},
        },
    }


def test_collect_metrics_count_glob_work_without_changing_result(tmp_path):
    keep = tmp_path / "keep.py"
    skip = tmp_path / "skip.txt"
    events = [
        _event("match", keep, 1, "hit"),
        _event("context", keep, 2, "ctx"),
        _event("match", skip, 1, "hit"),
    ]
    metrics = ExactSearchMetrics("call", "dir", "1")

    matches, line_map, total, truncated = st._collect(
        events, tmp_path, "*.py", 10, metrics
    )

    assert total == 1 and truncated is False
    assert [m["file"] for m in matches] == [str(keep)]
    assert set(line_map) == {str(keep)}
    assert metrics.collect_event_candidates == 3
    assert metrics.collect_glob_checks == 3
    assert metrics.collect_glob_rejected == 1
    assert metrics.accepted_matches == 1
    assert metrics.accepted_files == 1
    assert metrics.retained_matches == 1
    assert metrics.collect_ms >= 0


def test_run_rg_orjson_metrics_match_rg_event_types(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("before\nhit\nafter\n")
    metrics = ExactSearchMetrics("call", "dir", "1")

    events, no_match = st._run_rg(tmp_path, "hit", False, 1, metrics)

    assert no_match is False
    kinds = [event["type"] for event in events]
    assert metrics.rg_calls == 1
    assert metrics.rg_events == len(events)
    assert metrics.rg_match_events == kinds.count("match") == 1
    assert metrics.rg_context_events == kinds.count("context") == 2
    assert metrics.rg_begin_events == kinds.count("begin") == 1
    assert metrics.rg_bad_json == 0
    assert metrics.rg_stdout_chars > 0
    assert metrics.rg_subprocess_ms >= 0
    assert metrics.rg_parse_ms >= 0

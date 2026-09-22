"""Streaming reducer must match the existing materialized collector exactly."""

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as stg

from binnacle.search_text_collect import collect, matches_glob
from binnacle.search_text_stream_reduce import ExactStreamReducer

MAX_LINE = 80
MARK = "… [line truncated]"


def event(kind: str, path: Path, line: int, text: str) -> dict:
    return {
        "type": kind,
        "data": {
            "path": {"text": str(path)},
            "line_number": line,
            "lines": {"text": text + "\n"},
        },
    }


def reduce(events: list[dict], root: Path, glob: str | None, max_results: int):
    reducer = ExactStreamReducer(
        root,
        glob,
        max_results,
        max_line_chars=MAX_LINE,
        clip_mark=MARK,
        matches_glob=matches_glob,
    )
    for item in events:
        reducer.consume(item)
    return reducer


def test_reducer_matches_materialized_collect_and_caches_per_file(tmp_path):
    keep = tmp_path / "keep.py"
    skip = tmp_path / "skip.txt"
    events = [
        event("begin", keep, 0, ""),
        event("match", keep, 10, "needle"),
        event("context", keep, 11, "ctx"),
        event("match", keep, 12, "needle2"),
        event("match", skip, 1, "needle"),
        event("context", skip, 2, "ctx"),
    ]
    old = collect(
        events,
        tmp_path,
        "*.py",
        1,
        None,
        max_line_chars=MAX_LINE,
        clip_mark=MARK,
    )
    reducer = reduce(events, tmp_path, "*.py", 1)
    result = reducer.result()

    assert (result.matches, result.line_map, result.total, result.truncated) == old
    assert result.accepted_match_events == [events[1], events[3]]
    assert reducer.glob_cache_misses == 2
    assert reducer.glob_cache_hits == 3
    assert reducer.glob_rejected_files == 1
    assert reducer.glob_rejected_events == 2
    assert reducer.accepted_files == 1


def test_no_glob_does_not_build_glob_cache(tmp_path):
    events = [event("match", tmp_path / "a.py", 1, "hit")]
    reducer = reduce(events, tmp_path, None, 10)
    assert reducer.result().total == 1
    assert reducer.glob_cache == {}
    assert reducer.glob_cache_hits == reducer.glob_cache_misses == 0


@stg.composite
def event_stream(draw):
    paths = ["a.py", "b.py", "c.txt"]
    size = draw(stg.integers(min_value=0, max_value=30))
    result = []
    for index in range(size):
        kind = draw(stg.sampled_from(["match", "context", "begin", "end"]))
        path = draw(stg.sampled_from(paths))
        line = draw(stg.integers(min_value=1, max_value=40))
        text = draw(stg.text(min_size=0, max_size=120))
        result.append((kind, path, line, text))
    return result


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    items=event_stream(),
    glob=stg.sampled_from([None, "*.py", "*.txt"]),
    max_results=stg.integers(min_value=1, max_value=10),
)
def test_stream_reducer_property_equivalent_to_materialized(
    tmp_path, items, glob, max_results
):
    events = [
        event(kind, tmp_path / path, line, text) for kind, path, line, text in items
    ]
    old = collect(
        events,
        tmp_path,
        glob,
        max_results,
        None,
        max_line_chars=MAX_LINE,
        clip_mark=MARK,
    )
    result = reduce(events, tmp_path, glob, max_results).result()
    assert (result.matches, result.line_map, result.total, result.truncated) == old

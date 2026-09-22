"""Accepted streaming match events are equivalent adaptive input after glob filtering."""

from pathlib import Path

from binnacle.search_text_adaptive import build_adaptive_result
from binnacle.search_text_collect import matches_glob
from binnacle.search_text_stream_reduce import ExactStreamReducer
from binnacle.tools import search_text as st


def match(path: Path, line: int, text: str) -> dict:
    return {
        "type": "match",
        "data": {
            "path": {"text": str(path)},
            "line_number": line,
            "lines": {"text": text + "\n"},
        },
    }


def test_adaptive_bridge_preserves_payload(tmp_path):
    events = []
    for index in range(6):
        py = tmp_path / f"f{index}.py"
        txt = tmp_path / f"f{index}.txt"
        for line in range(1, 8):
            events.append(match(py, line, f"alpha beta {index} {line}"))
            events.append(match(txt, line, f"alpha rejected {index} {line}"))

    old = build_adaptive_result(
        events,
        root=tmp_path,
        pattern="alpha|beta",
        glob="*.py",
        fixed_strings=False,
        max_match_entries=100,
        settings=st.SEARCH_SETTINGS,
        matches_glob=matches_glob,
        result_max_bytes=65_536,
    )

    reducer = ExactStreamReducer(
        tmp_path,
        "*.py",
        100,
        max_line_chars=st.SEARCH_MAX_LINE_CHARS,
        clip_mark=st.LINE_CLIP_MARK,
        matches_glob=matches_glob,
    )
    for item in events:
        reducer.consume(item)
    accepted = reducer.result().accepted_match_events
    new = build_adaptive_result(
        accepted,
        root=tmp_path,
        pattern="alpha|beta",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=st.SEARCH_SETTINGS,
        matches_glob=matches_glob,
        result_max_bytes=65_536,
    )

    assert old is not None and new is not None
    assert new.payload == old.payload
    assert len(accepted) == 42

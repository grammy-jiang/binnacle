"""r6 W3 SR1: adaptive verify totals, one EMFILE policy, stable truncation."""

import errno
import random
from pathlib import Path

import pytest

from binnacle.errors import CodedToolError
from binnacle.features.search import search_text_verify as verify
from binnacle.features.search.search_text_collect import SmallestMatches
from binnacle.features.search.search_text_stream_reduce import ExactStreamReducer


def _event(file: str, line: int) -> dict:
    return {
        "type": "match",
        "data": {
            "path": {"text": file},
            "line_number": line,
            "lines": {"text": f"hit {line}\n"},
        },
    }


def _reduce(events: list[dict], cap: int):
    reducer = ExactStreamReducer(
        Path("/r"),
        None,
        cap,
        max_line_chars=100,
        clip_mark="…",
        matches_glob=lambda *_: True,
    )
    for event in events:
        reducer.consume(event)
    return reducer.result()


@pytest.mark.parametrize("seed", range(5))
def test_truncation_is_stable_across_arrival_orders(seed: int) -> None:
    events = [_event(f"/r/f{i % 40:02d}", i // 40 + 1) for i in range(400)]
    expected = _reduce(events, 25)
    random.Random(seed).shuffle(events)
    result = _reduce(events, 25)
    assert result.matches == expected.matches
    assert [m["file"] for m in result.matches] == sorted(
        m["file"] for m in result.matches
    )
    assert result.total == 400
    assert result.truncated is True


def test_not_truncated_when_total_equals_cap() -> None:
    result = _reduce([_event("/r/a", n) for n in (3, 1, 2)], 3)
    assert [m["line"] for m in result.matches] == [1, 2, 3]
    assert result.truncated is False


def test_smallest_matches_bounds_memory() -> None:
    kept = SmallestMatches(4)
    for n in range(100, 0, -1):
        kept.add("/r/a", n, "x")
    assert len(kept._rows) < 8
    assert [m["line"] for m in kept.result(10, "…")] == [1, 2, 3, 4]


def _adaptive(tmp_path: Path) -> tuple[dict, Path]:
    good = tmp_path / "good.txt"
    good.write_text("x\n")
    (tmp_path / "bad.txt").symlink_to(good)
    entries = [
        {"file": str(good), "line": 1, "text": "x", "count": 2},
        {"file": str(tmp_path / "bad.txt"), "line": 1, "text": "x", "count": 5},
        {"file": str(tmp_path / "bad.txt"), "count": 5},
    ]
    note = "Adaptive discovery for 7 matches across 2 files."
    return {"entries": entries, "count": 7, "note": note}, tmp_path


def test_verify_adaptive_subtracts_dropped_matches(tmp_path: Path) -> None:
    payload, base = _adaptive(tmp_path)
    out = verify.verify_adaptive(payload, base)
    assert [e["file"] for e in out["entries"]] == [str(tmp_path / "good.txt")]
    assert out["count"] == 2
    assert "for 2 matches" in out["note"]
    assert verify.candidate_files(out) == 1


def test_verify_adaptive_unchanged_when_all_pass(tmp_path: Path) -> None:
    good = tmp_path / "g.txt"
    good.write_text("x\n")
    payload = {"entries": [{"file": str(good), "count": 1}], "count": 1}
    assert verify.verify_adaptive(payload, tmp_path) is payload


@pytest.mark.parametrize("code", [errno.EMFILE, errno.ENFILE])
def test_descriptor_shortage_is_coded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x\n")

    def boom(self, parts):
        raise OSError(code, "shortage")

    monkeypatch.setattr(verify.DirectoryChain, "directory", boom)
    with pytest.raises(CodedToolError) as info:
        verify.checked_files([str(f)], tmp_path)
    assert info.value.telemetry_code == "too_many_open_files"

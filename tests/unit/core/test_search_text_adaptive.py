from __future__ import annotations

from pathlib import Path
from typing import Any

from binnacle.config import SearchTextSettings
from binnacle.search_text_adaptive import build_adaptive_result


def event(path: str, line: int, text: str) -> dict[str, Any]:
    return {
        "type": "match",
        "data": {
            "path": {"text": path},
            "line_number": line,
            "lines": {"text": text + "\n"},
        },
    }


def settings(**overrides: Any) -> SearchTextSettings:
    values = {
        "adaptive_discovery_enabled": True,
        "adaptive_detailed_files": 30,
        "adaptive_total_files": 200,
        "adaptive_representative_matches": 2,
        "adaptive_snippet_chars": 180,
    }
    values.update(overrides)
    return SearchTextSettings(**values)


def allow_all(_path: str, _root: Path, _glob: str | None) -> bool:
    return True


def test_adaptive_result_uses_detailed_front_and_count_only_tail(tmp_path: Path):
    events = [
        event(str(tmp_path / f"f{i:03d}.py"), 1, f"alpha beta {i}") for i in range(205)
    ]

    result = build_adaptive_result(
        events,
        root=tmp_path,
        pattern="alpha|beta",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=settings(),
        matches_glob=allow_all,
        result_max_bytes=65_536,
    )

    assert result is not None
    assert result.matching_files == 205
    assert result.candidate_files == 200
    assert result.detailed_files == 30
    assert result.representative_entries == 30
    assert result.tail_entries == 170
    assert result.payload["count"] == 205
    assert result.payload["truncated"] is True
    assert all("line" in entry for entry in result.payload["entries"][:30])
    assert all("line" not in entry for entry in result.payload["entries"][30:])
    assert result.result_bytes <= 65_536


def test_adaptive_result_representatives_cover_branches_and_clip(tmp_path: Path):
    target = str(tmp_path / "target.py")
    events = [
        event(target, 1, "alpha " + "x" * 500),
        event(target, 2, "alpha again"),
        event(target, 3, "beta gamma " + "y" * 500),
    ]

    result = build_adaptive_result(
        events,
        root=tmp_path,
        pattern="alpha|beta|gamma",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=settings(
            adaptive_detailed_files=1,
            adaptive_total_files=1,
            adaptive_representative_matches=2,
            adaptive_snippet_chars=80,
        ),
        matches_glob=allow_all,
        result_max_bytes=65_536,
    )

    assert result is not None
    entries = result.payload["entries"]
    assert [entry["line"] for entry in entries] == [1, 3]
    assert all(entry["count"] == 3 for entry in entries)
    assert all(len(entry["text"]) <= 81 for entry in entries)
    assert "beta gamma" in entries[1]["text"]


def test_max_match_entries_caps_only_detailed_match_entries(tmp_path: Path):
    events: list[dict[str, Any]] = []
    for file_index in range(12):
        path = str(tmp_path / f"f{file_index:02d}.py")
        events.extend(
            [
                event(path, 1, "alpha"),
                event(path, 2, "beta"),
                event(path, 3, "gamma"),
            ]
        )

    result = build_adaptive_result(
        events,
        root=tmp_path,
        pattern="alpha|beta|gamma",
        glob=None,
        fixed_strings=False,
        max_match_entries=3,
        settings=settings(
            adaptive_detailed_files=10,
            adaptive_total_files=12,
            adaptive_representative_matches=2,
        ),
        matches_glob=allow_all,
        result_max_bytes=65_536,
    )

    assert result is not None
    assert result.representative_entries == 3
    assert result.detailed_files == 2
    assert result.candidate_files == 12
    assert result.tail_entries == 10
    assert sum("line" in entry for entry in result.payload["entries"]) == 3


def test_adaptive_result_final_budget_is_authoritative(tmp_path: Path):
    events = []
    for index in range(200):
        path = str(tmp_path / (f"directory-{index:03d}-" + "p" * 30) / ("f" + "q" * 40))
        events.append(event(path, 1, "alpha " + "z" * 300))

    result = build_adaptive_result(
        events,
        root=tmp_path,
        pattern="alpha",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=settings(),
        matches_glob=allow_all,
        result_max_bytes=4_096,
    )

    assert result is not None
    assert result.budget_trimmed is True
    assert 0 < result.candidate_files < 200
    assert result.result_bytes <= 4_096
    assert "response budget reached" in result.payload["note"]


def test_unportable_branch_regex_falls_back_without_failure(tmp_path: Path):
    dense = str(tmp_path / "dense.py")
    sparse = str(tmp_path / "sparse.py")
    events = [event(dense, i, "name") for i in range(1, 8)]
    events.append(event(sparse, 1, "name"))

    result = build_adaptive_result(
        events,
        root=tmp_path,
        pattern=r"(?<name>name)",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=settings(
            adaptive_detailed_files=1,
            adaptive_total_files=2,
            adaptive_representative_matches=1,
        ),
        matches_glob=allow_all,
        result_max_bytes=65_536,
    )

    assert result is not None
    assert result.payload["entries"][0]["file"] == dense


def test_alternative_parser_handles_escapes_classes_and_groups():
    from binnacle import search_text_adaptive as adaptive

    assert adaptive._split_top_level_alternatives(r"alpha\|beta|[a|b]|(x|y)|gamma") == [
        r"alpha\|beta",
        r"[a|b]",
        r"(x|y)",
        "gamma",
    ]


def test_collect_files_ignores_nonmatches_bad_paths_and_bad_lines(tmp_path: Path):
    from binnacle import search_text_adaptive as adaptive

    events = [
        {"type": "context", "data": {}},
        {"type": "match", "data": {"path": {}, "line_number": 1, "lines": {}}},
        {
            "type": "match",
            "data": {
                "path": {"text": str(tmp_path / "skip.py")},
                "line_number": 1,
                "lines": {"text": "alpha\n"},
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": str(tmp_path / "bad.py")},
                "line_number": "not-an-int",
                "lines": {"text": "alpha\n"},
            },
        },
    ]

    files = adaptive._collect_files(
        events,
        tmp_path,
        None,
        lambda path, _root, _glob: not path.endswith("skip.py"),
    )

    assert files == {}


def test_empty_events_cannot_build_adaptive_result(tmp_path: Path):
    result = build_adaptive_result(
        [],
        root=tmp_path,
        pattern="alpha",
        glob=None,
        fixed_strings=False,
        max_match_entries=100,
        settings=settings(),
        matches_glob=allow_all,
        result_max_bytes=65_536,
    )

    assert result is None


def test_impossibly_small_adaptive_budget_returns_none():
    from binnacle import search_text_adaptive as adaptive

    payload = {
        "path": "/tmp/x",
        "pattern": "alpha",
        "entries": [{"file": "/tmp/x/a.py", "line": 1, "text": "alpha", "count": 1}],
        "count": 1,
        "truncated": True,
        "note": "adaptive",
    }

    assert adaptive._fit_budget(payload, max_bytes=8, matching_files=1) is None


def test_representative_matches_empty_input():
    from binnacle import search_text_adaptive as adaptive

    assert (
        adaptive._representative_matches(
            [],
            [],
            limit=2,
            snippet_chars=180,
        )
        == []
    )


def test_fixed_string_pipe_is_one_ranking_branch():
    from binnacle import search_text_adaptive as adaptive

    branches = adaptive._compile_branches("alpha|beta", True)

    assert len(branches) == 1
    assert branches[0].search("literal alpha|beta value")
    assert not branches[0].search("alpha only")

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


def test_permission_only_failure_has_no_pattern_hint() -> None:
    from binnacle.features.files.rg_env import rejection_message

    text = rejection_message("rg: /x/secret: Permission denied (os error 13)")
    assert "Fix the pattern" not in text
    assert "permissions" in text


def test_pattern_failure_keeps_pattern_hint() -> None:
    from binnacle.features.files.rg_env import rejection_message

    assert "Fix the pattern" in rejection_message("regex parse error: unclosed group")
    mixed = "rg: a: Permission denied (os error 13)\nregex parse error"
    assert "Fix the pattern" in rejection_message(mixed)


def test_python_order_equals_rg_sort_path_bytes(tmp_path: Path) -> None:
    import json
    import subprocess

    from binnacle.features.search.search_text_stream import RgJsonStream

    names = [
        "a.txt", "a/x.txt", "a/B.txt", "B.txt", "b.txt", "Z/y.txt", "z/y.txt",
        "é.txt", "e.txt", "日本/語.txt", "ä/ö.txt", "a-b/c.txt", "a b.txt",
        "dir/sub/deep.txt", "dir/sub.txt", "dir.txt", "_u.txt", "~t.txt",
    ]  # fmt: skip
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("needle\nneedle\n")
    out = subprocess.run(
        ["rg", "--no-config", "--json", "--sort", "path", "needle", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    events = [json.loads(line) for line in out.splitlines()]
    matches = [e for e in events if e["type"] == "match"]
    expected = [(e["data"]["path"]["text"], e["data"]["line_number"]) for e in matches]
    # A case-insensitive file system (macOS APFS) merges B.txt/b.txt and Z/z,
    # so count the files that exist, not the names written.
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(expected) == 2 * len(files)
    for seed in range(4):
        shuffled = list(matches)
        random.Random(seed).shuffle(shuffled)
        for cap in (len(expected), 7):
            result = _reduce(shuffled, cap)
            got = [(m["file"], m["line"]) for m in result.matches]
            assert got == expected[:cap]
    command = RgJsonStream(tmp_path, "n", False, 0, rg_bin="rg", timeout_s=5)._command()
    assert "--sort" not in command


def test_unreadable_child_is_not_a_pattern_error(tmp_path: Path) -> None:
    import os

    from binnacle.features.search.search_text_rg import run_rg

    (tmp_path / "ok.txt").write_text("needle\n")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "f.txt").write_text("needle\n")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):  # root: permissions not enforced
            return
        with pytest.raises(CodedToolError) as info:
            run_rg(tmp_path, "needle", False, 0, rg_bin="rg", timeout_s=20)
        assert "Fix the pattern" not in str(info.value)
    finally:
        locked.chmod(0o700)

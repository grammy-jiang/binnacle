"""R6 W3 PX1B-F4: search_text reports unsendable filenames without leaking them."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

import orjson
import pytest

from binnacle.config import RootsSettings, SearchTextSettings
from binnacle.features.search.tools import search_text as st


def _event(path: bytes, *, numbered: int = 1, context: bool = False) -> bytes:
    data = {
        "type": "context" if context else "match",
        "data": {
            "path": {"bytes": base64.b64encode(path).decode("ascii")},
            "lines": {"text": "needle\n"},
            "line_number": numbered,
            "absolute_offset": 0,
            "submatches": [],
        },
    }
    return json.dumps(data).encode("utf-8") + b"\n"


def _valid(path: Path) -> bytes:
    record = {
        "type": "match",
        "data": {
            "path": {"text": str(path)},
            "lines": {"text": "needle\n"},
            "line_number": 1,
            "absolute_offset": 0,
            "submatches": [],
        },
    }
    return json.dumps(record).encode("utf-8") + b"\n"


def _rg(tmp_path: Path, stdout: bytes, *, stderr: bytes = b"", rc: int = 0) -> Path:
    cmd = tmp_path / "rg-test"
    cmd.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        f"sys.stderr.buffer.write({stderr!r})\n"
        f"raise SystemExit({rc})\n"
    )
    cmd.chmod(cmd.stat().st_mode | stat.S_IXUSR)
    return cmd


def _search(
    root: Path,
    rg: Path,
    *,
    mode: str,
    names_only: bool = False,
    glob: str | None = None,
    adaptive: bool = False,
):
    return st.search_text_impl(
        "needle",
        str(root),
        glob,
        True,
        0,
        names_only,
        100,
        False,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=SearchTextSettings(
            exact_execution=mode,
            adaptive_discovery_enabled=adaptive,
            result_max_bytes=4096 if adaptive else 24_000,
        ),
        rg_bin=str(rg),
    )


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
@pytest.mark.parametrize("names_only", [False, True])
def test_search_reports_distinct_omitted_names_with_safe_note(
    tmp_path: Path, mode: str, names_only: bool
):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "good.txt"
    good.write_text("needle\n")
    bad1 = os.fsencode(root) + b"/secret-\xff.txt"
    bad2 = os.fsencode(root) + b"/private-\xfe.md"
    stdout = (
        _event(bad1)
        + _event(bad1, numbered=2)
        + _event(bad2)
        + _event(bad2, context=True)
        + _valid(good)
    )
    result = _search(
        root,
        _rg(tmp_path, stdout),
        mode=mode,
        names_only=names_only,
        glob="*.txt",
    )
    payload = result.structured_content
    assert payload["count"] == 1
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["file"] == str(good)
    note = "Skipped 2 non-UTF-8 filenames from search results before glob filtering."
    assert note in payload["note"]
    assert note in result.content[0].text
    assert payload["note"].count(note) == 1
    for text in (json.dumps(payload, ensure_ascii=False), result.content[0].text):
        text.encode("utf-8", errors="strict")
        assert "secret-" not in text and "private-" not in text
        assert "udcff" not in text and "udcfe" not in text
    assert not payload["truncated"]


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
def test_omission_and_permission_notes_coexist(tmp_path: Path, mode: str):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "ok.txt"
    good.write_text("needle\n")
    bad = os.fsencode(root) + b"/secret-\xff.txt"
    stderr = b"rg: ./denied: Permission denied (os error 13)\n"
    result = _search(
        root,
        _rg(tmp_path, _event(bad) + _valid(good), stderr=stderr, rc=2),
        mode=mode,
    )
    payload = result.structured_content
    assert payload["count"] == 1
    assert payload["note"].count("Skipped 1 non-UTF-8 filename") == 1
    assert payload["note"].count("Skipped 1 unreadable path") == 1
    assert result.content[0].text.count("Skipped 1 non-UTF-8 filename") == 1


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
def test_only_bad_names_get_a_count_not_false_no_match(tmp_path: Path, mode: str):
    root = tmp_path / "root"
    root.mkdir()
    bad = os.fsencode(root) + b"/redacted-\xff.txt"
    result = _search(root, _rg(tmp_path, _event(bad)), mode=mode)
    payload = result.structured_content
    assert payload["count"] == 0 and payload["entries"] == []
    assert "Skipped 1 non-UTF-8 filename" in payload["note"]
    assert "Skipped 1 non-UTF-8 filename" in getattr(result.content[0], "text", "")


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
def test_valid_utf8_search_remains_unchanged(tmp_path: Path, mode: str):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "ok.txt"
    good.write_text("needle\n")
    result = _search(root, _rg(tmp_path, _valid(good)), mode=mode)
    payload = result.structured_content
    assert payload["count"] == 1
    assert "note" not in payload


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
def test_adaptive_keeps_omission_note_and_verified_count(tmp_path: Path, mode: str):
    root = tmp_path / "root"
    root.mkdir()
    stdout = b""
    for index in range(45):
        path = root / f"valid-{index:02}.txt"
        path.write_text("needle\n")
        stdout += _valid(path)
    stdout += _event(os.fsencode(root) + b"/secret-\xff.txt")
    result = _search(
        root,
        _rg(tmp_path, stdout),
        mode=mode,
        adaptive=True,
    )
    payload = result.structured_content
    assert "Adaptive" in payload.get("note", "")
    assert "Skipped 1 non-UTF-8 filename" in payload["note"]
    assert "Skipped 1 non-UTF-8 filename" in getattr(result.content[0], "text", "")
    assert payload["count"] == 45


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
def test_omission_counter_is_scoped_to_one_tool_call(tmp_path: Path, mode: str):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "ok.txt"
    good.write_text("needle\n")
    bad = os.fsencode(root) + b"/unprintable-\xff"
    first = _search(root, _rg(tmp_path, _event(bad)), mode=mode)
    assert "Skipped 1 non-UTF-8 filename" in first.structured_content["note"]
    second = _search(root, _rg(tmp_path, _valid(good)), mode=mode)
    assert second.structured_content["count"] == 1
    assert "note" not in second.structured_content


def test_bounded_omission_identity_memory_and_honest_lower_bound(
    tmp_path: Path, monkeypatch
):
    from binnacle.features.files import rg_env as omissions

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(omissions, "MAX_NAME_IDENTITIES", 2)
    stdout = b"".join(
        _event(os.fsencode(root) + f"/redacted-{n}-".encode() + b"\xff")
        for n in range(4)
    )
    report = _search(root, _rg(tmp_path, stdout), mode="streaming")
    assert report.structured_content["count"] == 0
    assert "Skipped at least 2 non-UTF-8 filenames" in report.structured_content["note"]
    assert "Skipped at least 2 non-UTF-8 filenames" in report.content[0].text


@pytest.mark.parametrize("mode", ["materialized", "streaming"])
@pytest.mark.parametrize("names_only", [False, True])
def test_post_note_result_never_exceeds_structured_budget(
    tmp_path: Path, mode: str, names_only: bool
):
    root = tmp_path / "root"
    root.mkdir()
    stdout = b""
    for index in range(55):
        path = root / f"safe-{index:02}.txt"
        path.write_text("needle\n")
        stdout += _valid(path)
    stdout += _event(os.fsencode(root) + b"/bad-\xff.txt")
    result = st.search_text_impl(
        "needle",
        str(root),
        None,
        True,
        0,
        names_only,
        100,
        False,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=SearchTextSettings(
            exact_execution=mode,
            result_max_bytes=4096,
            adaptive_discovery_enabled=False,
        ),
        rg_bin=str(_rg(tmp_path, stdout)),
    )
    payload = result.structured_content
    assert isinstance(payload, dict)
    assert len(orjson.dumps(payload)) <= 4096
    assert payload["count"] == 55
    assert payload["truncated"] is True
    assert "Skipped 1 non-UTF-8 filename" in payload["note"]
    assert "Skipped 1 non-UTF-8 filename" in getattr(result.content[0], "text", "")
    assert 0 <= len(payload["entries"]) < 55


def test_final_budget_includes_both_permission_and_utf8_notes():
    from fastmcp.tools.base import ToolResult

    from binnacle.features.files import rg_env

    def produce(*, settings):
        rg_env.observe_rg_event(
            {"type": "match", "data": {"path": {"bytes": "c2VjcmV0L/8="}}}
        )
        rg_env.record_unreadable(["/tmp/private-in-test-root"])
        return ToolResult(
            content="Original summary",
            structured_content={
                "path": "/tmp/only-test",
                "pattern": "needle",
                "count": 1,
                "truncated": False,
                "entries": [{"file": "/tmp/only-test", "line": 1, "text": "x" * 3880}],
            },
        )

    limited = rg_env.noting_search_with_budget(produce)(
        settings=SearchTextSettings(result_max_bytes=4096)
    )
    payload = limited.structured_content
    assert isinstance(payload, dict)
    assert len(orjson.dumps(payload)) <= 4096
    assert payload["truncated"] is True
    assert payload["count"] == 1
    assert payload["note"].count("Skipped 1 non-UTF-8 filename") == 1
    assert payload["note"].count("Skipped 1 unreadable path") == 1
    assert (
        getattr(limited.content[0], "text", "").count("Skipped 1 non-UTF-8 filename")
        == 1
    )

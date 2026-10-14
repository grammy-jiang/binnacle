"""rg stderr is parsed whole and bytes are never decoded strictly (r6 W3 PX1b).

R-PX1-1: Linux stream search decided "permission-only" from the last 64 KiB
of rg's stderr, so an early non-permission error was accepted and the note
under-counted. Now glob, the streaming search and the materialized search
scan ALL of it with one bounded parser (rg_env.DeniedScan): every permission
line is counted, only the first few names are kept, any other line keeps
rg's failure.

R-PX1-3: Linux glob decoded rg output strictly as UTF-8 (UnicodeDecodeError on
a legitimate name). Now rg output is decoded with surrogateescape, as the
search path decodes names; a name that is not UTF-8 is omitted from a result
(a JSON result is UTF-8); a count-only note reports omitted filenames
without exposing them. Permission-denied paths still use escaped display.

A fake rg (a Python script under tmp_path, non-secret) prints the exact bytes,
so every case runs on both OSes; none is skipped. A real non-UTF-8 name
cannot exist on APFS: the Pi runs the real-name probe (PX1B-REPORT.json).
"""

import json
import os
import stat
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ListFilesSettings, RootsSettings, SearchTextSettings
from binnacle.features.files import list_files_glob, rg_env
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search.search_text_rg import run_rg
from binnacle.features.search.search_text_stream import RgJsonStream, managed_rg_stream
from binnacle.features.search.tools import search_text as st

DENIED = "rg: ./d{n}: IO error for operation on ./d{n}: Permission denied (os error 13)"
MODES = pytest.mark.parametrize("mode", ["streaming", "materialized"])


def fake_rg(tmp_path: Path, *, stdout: bytes, stderr: bytes, code: int) -> Path:
    """A fake rg printing exactly these bytes, whatever its arguments."""
    path = tmp_path / "fake-rg"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        f"sys.stderr.buffer.write({stderr!r})\n"
        f"raise SystemExit({code})\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "root"
    base.mkdir()
    (base / "m.txt").write_text("needle\n")
    return base


def denied_lines(count: int) -> bytes:
    return "".join(DENIED.format(n=n) + "\n" for n in range(count)).encode()


def match_event(file: Path) -> bytes:
    return (
        b'{"type":"match","data":{"path":{"text":"%s"},"lines":{"text":"needle\\n"},'
        b'"line_number":1,"absolute_offset":0,"submatches":[]}}\n' % str(file).encode()
    )


def glob(root: Path, rg: Path):
    return lf.list_files_impl(
        str(root),
        "*.txt",
        100,
        False,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=ListFilesSettings(),
        rg_bin=str(rg),
    )


def search(root: Path, rg: Path, mode: str):
    return st.search_text_impl(
        "needle",
        str(root),
        None,
        True,
        0,
        False,
        100,
        True,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=SearchTextSettings(exact_execution=mode),
        rg_bin=str(rg),
    )


def code_of(call) -> str | None:
    with pytest.raises(ToolError) as exc:
        call()
    return getattr(exc.value, "telemetry_code", None)


# R-PX1-1: the whole stderr decides, for glob and both search runners.


def test_an_early_io_error_in_a_big_stderr_fails_glob(tmp_path, root):
    stderr = b"rg: ./d: Input/output error (os error 5)\n" + denied_lines(1500)
    assert len(stderr) > 65_536
    rg = fake_rg(tmp_path, stdout=b"m.txt\n", stderr=stderr, code=2)
    assert code_of(lambda: glob(root, rg)) == "rg_failed"


@MODES
def test_an_early_io_error_in_a_big_stderr_fails_search(tmp_path, root, mode):
    stderr = b"rg: ./d: Input/output error (os error 5)\n" + denied_lines(1500)
    rg = fake_rg(tmp_path, stdout=match_event(root / "m.txt"), stderr=stderr, code=2)
    assert code_of(lambda: search(root, rg, mode)) == "rg_rejected"


def expected_note(root: Path, count: int) -> str:
    names = sorted(str(root / f"d{n}") for n in range(count))
    return (
        f"Skipped {count} unreadable paths (permission denied): "
        f"{', '.join(names[:5])} and {count - 5} more. Results exclude their contents."
    )


def test_1500_permission_lines_are_all_counted_by_glob(tmp_path, root):
    rg = fake_rg(tmp_path, stdout=b"m.txt\n", stderr=denied_lines(1500), code=2)
    payload = glob(root, rg).structured_content
    assert payload["count"] == 1
    assert payload["note"] == expected_note(root, 1500)


@MODES
def test_1500_permission_lines_are_all_counted_by_search(tmp_path, root, mode):
    rg = fake_rg(
        tmp_path, stdout=match_event(root / "m.txt"), stderr=denied_lines(1500), code=2
    )
    payload = search(root, rg, mode).structured_content
    assert payload["count"] == 1
    assert payload["note"] == expected_note(root, 1500)


def test_glob_and_both_search_runners_agree_on_any_stderr(tmp_path, root):
    late = denied_lines(1200) + b"rg: ./z: Input/output error (os error 5)\n"
    for stderr in (denied_lines(1200), late):
        token = rg_env.UNREADABLE.set([])
        try:
            spooled = tmp_path / "stderr"
            spooled.write_bytes(stderr)
            with spooled.open("rb") as handle:
                answers = {
                    rg_env.accept_denied(stderr.decode(), root),
                    rg_env.accept_denied(stderr, root),
                    rg_env.accept_denied(handle, root),
                }
        finally:
            rg_env.UNREADABLE.reset(token)
        assert answers == {stderr is not late}


def test_the_scan_keeps_bounded_memory(root):
    scan = rg_env.scan_denied(denied_lines(5000), root)
    assert scan is not None and scan.count == 5000
    assert scan.names == sorted(str(root / f"d{n}") for n in range(5000))[:5]


def test_a_stderr_over_the_cap_fails_closed(monkeypatch, root):
    monkeypatch.setattr(rg_env, "STDERR_SCAN_CAP", 1000)
    assert rg_env.scan_denied(denied_lines(100), root) is None
    assert rg_env.scan_denied(denied_lines(5), root) is not None


@MODES
def test_the_streaming_runner_scans_the_spooled_file(tmp_path, root, mode):
    # The runner itself, outside the tool: no collector, so rg's failure stands.
    rg = fake_rg(tmp_path, stdout=b"", stderr=denied_lines(3), code=2)
    if mode == "streaming":
        stream = RgJsonStream(root, "x", False, 0, rg_bin=str(rg), timeout_s=5)
        with pytest.raises(ToolError) as exc, managed_rg_stream(stream):
            list(stream)
    else:
        with pytest.raises(ToolError) as exc:
            run_rg(root, "x", False, 0, rg_bin=str(rg), timeout_s=5)
    assert exc.value.telemetry_code == "rg_rejected"


# R-PX1-3: bytes that are not UTF-8.

BAD = b"bad\xff"


def test_a_non_utf8_permission_line_is_counted_and_escaped(tmp_path, root):
    stderr = b"rg: ./" + BAD + b": Permission denied (os error 13)\n"
    rg = fake_rg(tmp_path, stdout=b"m.txt\n", stderr=stderr, code=2)
    payload = glob(root, rg).structured_content
    assert payload["note"] == (
        f"Skipped 1 unreadable path (permission denied): {root}/bad\\xff. "
        "Results exclude their contents."
    )


@MODES
def test_a_non_utf8_permission_line_in_search(tmp_path, root, mode):
    stderr = b"rg: ./" + BAD + b": Permission denied (os error 13)\n"
    rg = fake_rg(tmp_path, stdout=match_event(root / "m.txt"), stderr=stderr, code=2)
    note = search(root, rg, mode).structured_content["note"]
    assert note.endswith(f"{root}/bad\\xff. Results exclude their contents.")


def test_a_non_utf8_name_from_glob_is_omitted_not_a_crash(tmp_path, root, monkeypatch):
    # APFS cannot store a non-UTF-8 name, so make the bad name EXIST for the
    # metadata step on every host: lstat of exactly that name answers with a
    # regular file's stat. Without that, the name is dropped by the ENOENT
    # omission and the UTF-8 filter in glob_mode is never what removes it
    # (R-PX1b-F2: the mutant without `shown(line) == line` survived).
    bad = os.fsdecode(BAD + b".txt")
    real = os.lstat

    def lstat(path, *, dir_fd=None):
        return real("m.txt" if path == bad else path, dir_fd=dir_fd)

    monkeypatch.setattr(list_files_glob.os, "lstat", lstat)
    rg = fake_rg(tmp_path, stdout=BAD + b".txt\nm.txt\n", stderr=b"", code=0)
    payload = glob(root, rg).structured_content
    assert [e["path"] for e in payload["entries"]] == [str(root / "m.txt")]
    assert payload["count"] == 1
    assert payload["note"] == (
        "Skipped 1 non-UTF-8 filename from the recursive listing; "
        "it cannot be represented in the result."
    )


def test_multiple_non_utf8_glob_names_are_counted_without_disclosure(tmp_path, root):
    rg = fake_rg(
        tmp_path,
        # The second invalid name does not match *.txt, but still belongs
        # to the raw recursive listing and must count toward omission.
        stdout=BAD + b".txt\nother\xfe.md\nm.txt\n",
        stderr=b"",
        code=0,
    )
    result = glob(root, rg)
    payload = result.structured_content
    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert [e["path"] for e in payload["entries"]] == [str(root / "m.txt")]
    assert payload["note"] == (
        "Skipped 2 non-UTF-8 filenames from the recursive listing; "
        "they cannot be represented in the result."
    )
    assert payload["note"] in result.content[0].text
    assert "bad" not in payload["note"] and "other" not in payload["note"]


def test_non_utf8_glob_note_coexists_with_denied_path_note(tmp_path, root):
    rg = fake_rg(
        tmp_path,
        stdout=BAD + b".txt\nm.txt\n",
        stderr=denied_lines(1),
        code=2,
    )
    result = glob(root, rg)
    note = result.structured_content["note"]
    assert note.startswith(
        "Skipped 1 non-UTF-8 filename from the recursive listing; "
        "it cannot be represented in the result. "
    )
    assert "Skipped 1 unreadable path (permission denied)" in note
    assert result.structured_content["count"] == 1
    assert note.endswith("Results exclude their contents.")


def test_glob_non_utf8_only_retains_empty_note_without_leaking_name(tmp_path, root):
    rg = fake_rg(tmp_path, stdout=BAD + b".txt\n", stderr=b"", code=0)
    result = glob(root, rg)
    payload = result.structured_content
    assert payload["count"] == 0
    assert payload["entries"] == []
    assert payload["truncated"] is False
    assert payload["note"].startswith("No files match")
    assert payload["note"].endswith(
        "Skipped 1 non-UTF-8 filename from the recursive listing; "
        "it cannot be represented in the result."
    )
    # Proof must cover all outgoing JSON and all text blocks, not the
    # directionally useless comparison of the note against repr(BAD).
    serialized = json.dumps(payload, ensure_ascii=False)
    serialized.encode("utf-8", errors="strict")
    messages = [serialized, *(block.text for block in result.content)]
    for message in messages:
        assert os.fsdecode(BAD) not in message
        assert r"bad\xff" not in message
        assert r"bad\udcff" not in message


def test_non_utf8_glob_note_keeps_existing_truncation_note(tmp_path, root):
    (root / "n.txt").write_text("n")
    (root / "o.txt").write_text("o")
    rg = fake_rg(
        tmp_path,
        stdout=BAD + b".txt\nm.txt\nn.txt\no.txt\n",
        stderr=b"",
        code=0,
    )
    result = lf.list_files_impl(
        str(root),
        "*.txt",
        1,
        False,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=ListFilesSettings(),
        rg_bin=str(rg),
    )
    payload = result.structured_content
    assert payload["count"] == 1
    assert len(payload["entries"]) == 1
    assert payload["truncated"] is True
    assert payload["note"].startswith("Showing first 1 of 3 matches;")
    assert payload["note"].endswith(
        "Skipped 1 non-UTF-8 filename from the recursive listing; "
        "it cannot be represented in the result."
    )


def test_truncated_permission_and_two_non_utf8_notes_compose_once(tmp_path, root):
    (root / "n.txt").write_text("n")
    (root / "o.txt").write_text("o")
    rg = fake_rg(
        tmp_path,
        stdout=BAD + b".txt\nother\xfe.md\nm.txt\nn.txt\no.txt\n",
        stderr=denied_lines(1),
        code=2,
    )
    result = lf.list_files_impl(
        str(root),
        "*.txt",
        1,
        False,
        roots=RootsSettings(default_root=root, extra_roots=()),
        settings=ListFilesSettings(),
        rg_bin=str(rg),
    )
    payload = result.structured_content
    assert payload["truncated"] is True
    assert payload["count"] == len(payload["entries"]) == 1
    omission = (
        "Skipped 2 non-UTF-8 filenames from the recursive listing; "
        "they cannot be represented in the result."
    )
    permission = "Skipped 1 unreadable path (permission denied)"
    assert payload["note"].startswith("Showing first 1 of 3 matches;")
    for text in (payload["note"], result.content[0].text):
        assert text.count(omission) == 1
        assert text.count(permission) == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    serialized.encode("utf-8", errors="strict")
    assert os.fsdecode(BAD) not in serialized
    assert r"bad\xff" not in serialized


def test_valid_utf8_glob_does_not_claim_omissions(tmp_path, root):
    rg = fake_rg(tmp_path, stdout=b"m.txt\n", stderr=b"", code=0)
    result = glob(root, rg)
    assert result.structured_content["count"] == 1
    assert "note" not in result.structured_content


@MODES
def test_a_non_utf8_file_from_search_is_omitted_not_a_crash(tmp_path, root, mode):
    encoded = b'{"type":"match","data":{"path":{"bytes":"YmFk/w=="},' + (
        b'"lines":{"text":"needle\\n"},"line_number":1,"absolute_offset":0,'
        b'"submatches":[]}}\n'
    )
    rg = fake_rg(
        tmp_path, stdout=encoded + match_event(root / "m.txt"), stderr=b"", code=0
    )
    payload = search(root, rg, mode).structured_content
    assert payload["count"] == 1
    assert [e["file"] for e in payload["entries"]] == [str(root / "m.txt")]


def test_a_non_utf8_rg_failure_is_escaped_in_the_message(tmp_path, root):
    rg = fake_rg(tmp_path, stdout=b"", stderr=b"rg: " + BAD + b": boom\n", code=2)
    with pytest.raises(ToolError) as exc:
        glob(root, rg)
    assert "rg: bad\\xff: boom" in str(exc.value)
    assert os.fsencode(str(exc.value)).decode("utf-8")  # sendable as JSON

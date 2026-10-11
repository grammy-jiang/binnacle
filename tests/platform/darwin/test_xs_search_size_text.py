"""R4 Xs (SD-50): the search_text size disclosure lives in the result text.

The search_text description equals the Linux bytes on Darwin (pinned in
test_durable_tool_wiring.py for both owners). The 16 MiB size disclosure is
part of the result summary only when the Search adapter reports a file
skipped for size. The adapter is a stand-in, so this runs on every host.
"""

from contextlib import contextmanager
from pathlib import Path, PurePath
from types import SimpleNamespace

from binnacle.config import SearchTextSettings
from binnacle.features.search.search_text_collect import (
    SEARCH_BYTE_BUDGET,
    search_opened,
)

SIZE_TEXT = (
    "larger than the Darwin per-file size limit of 16 MiB (16,777,216 bytes), "
    "further bounded by the remaining aggregate 16 MiB input budget."
)


class _Search:
    def __init__(self, stats):
        self.stats = stats

    def search(self, grant, request):
        assert request.max_bytes == SEARCH_BYTE_BUDGET
        match = {
            "path": {"text": "a.txt"},
            "lines": {"text": "needle\n"},
            "line_number": 1,
            "submatches": [],
        }
        events = [
            {"type": "match", "data": match},
            {"type": "summary", "data": {"stats": self.stats}},
        ]
        return SimpleNamespace(events=events, truncated=False)


class _Access:
    def __init__(self, root: Path, stats):
        self.root = root
        self.search = _Search(stats)

    @contextmanager
    def operation(self, path, tool):
        yield object(), PurePath("."), self.root


def _summary(tmp_path, stats) -> str:
    result = search_opened(
        _Access(tmp_path, stats),
        "needle",
        str(tmp_path),
        None,
        False,
        0,
        False,
        10,
        False,
        SearchTextSettings(),
    )
    return result.content[0].text


def test_size_disclosure_appears_when_a_file_is_skipped_for_size(tmp_path):
    text = _summary(tmp_path, {"files_searched": 1, "skipped_oversize": 2})
    assert text.startswith(f"Found 1 matches for 'needle' under {tmp_path}.")
    assert text.endswith(f" 2 file(s) skipped: {SIZE_TEXT}")


def test_size_disclosure_is_absent_without_a_size_skip(tmp_path):
    for stats in (
        {"files_searched": 1},
        {"files_searched": 1, "skipped_oversize": 0},
        {"files_searched": 1, "skipped_io_error": 1, "skipped_changed": 1},
    ):
        text = _summary(tmp_path, stats)
        assert "MiB" not in text and "per-file size limit" not in text, stats

"""Single-pass exact-search reducer for streamed ripgrep events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from binnacle.search_text_collect import clip

MatchGlob = Callable[[str, Path, str | None], bool]


@dataclass
class ExactScanResult:
    matches: list[dict]
    line_map: dict[str, dict[int, str]]
    total: int
    truncated: bool
    adaptive_events: list[dict]
    adaptive_glob: str | None


@dataclass
class StreamScanResult:
    matches: list[dict]
    line_map: dict[str, dict[int, str]]
    total: int
    truncated: bool
    accepted_match_events: list[dict]


class ExactStreamReducer:
    """Consume rg match/context events once while preserving current ordering."""

    def __init__(
        self,
        root: Path,
        glob: str | None,
        max_results: int,
        *,
        max_line_chars: int,
        clip_mark: str,
        matches_glob: MatchGlob,
    ) -> None:
        self.root = root
        self.glob = glob
        self.max_results = max_results
        self.max_line_chars = max_line_chars
        self.clip_mark = clip_mark
        self.matches_glob = matches_glob
        self.matches: list[dict] = []
        self.line_map: dict[str, dict[int, str]] = {}
        self.accepted_match_events: list[dict] = []
        self.total = 0
        self.truncated = False
        self.event_candidates = 0
        self.glob_cache: dict[str, bool] = {}
        self.glob_cache_hits = 0
        self.glob_cache_misses = 0
        self.glob_rejected_events = 0
        self._glob_rejected_files: set[str] = set()
        self._accepted_files: set[str] = set()

    @property
    def accepted_files(self) -> int:
        return len(self._accepted_files)

    @property
    def glob_rejected_files(self) -> int:
        return len(self._glob_rejected_files)

    def _accept_file(self, file: str) -> bool:
        if self.glob is None:
            return True
        cached = self.glob_cache.get(file)
        if cached is not None:
            self.glob_cache_hits += 1
            return cached
        accepted = self.matches_glob(file, self.root, self.glob)
        self.glob_cache[file] = accepted
        self.glob_cache_misses += 1
        return accepted

    def consume(self, event: dict) -> None:
        kind = event.get("type")
        if kind not in ("match", "context"):
            return
        self.event_candidates += 1
        data = event["data"]
        file = data["path"]["text"]
        if not self._accept_file(file):
            self.glob_rejected_events += 1
            self._glob_rejected_files.add(file)
            return

        self._accepted_files.add(file)
        line_no = data["line_number"]
        text = data["lines"].get("text", "").rstrip("\n")
        self.line_map.setdefault(file, {})[line_no] = text
        if kind != "match":
            return

        self.total += 1
        self.accepted_match_events.append(event)
        if len(self.matches) < self.max_results:
            self.matches.append(
                {
                    "file": file,
                    "line": line_no,
                    "text": clip(text, self.max_line_chars, self.clip_mark),
                }
            )
        else:
            self.truncated = True

    def result(self) -> StreamScanResult:
        return StreamScanResult(
            matches=self.matches,
            line_map=self.line_map,
            total=self.total,
            truncated=self.truncated,
            accepted_match_events=self.accepted_match_events,
        )
